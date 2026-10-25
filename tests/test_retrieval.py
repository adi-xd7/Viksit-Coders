"""Hybrid search, filters, as_of gate on every path, duplicates, query cache, audit
events and hot ingest. Runs on the synthetic pack with the real local embedding model."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import SYNTH_PACK, header, write_pack
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.models import LogEventType, RowStatus
from ragnarok.retrieval.cli import main as search_cli
from ragnarok.retrieval.index import passes
from ragnarok.retrieval.service import RetrievalService
from ragnarok.retrieval.types import SearchFilters, TradeQuery
from ragnarok.store.db import Store

LATE = date(2030, 12, 31)


@pytest.fixture()
def svc(tmp_path, test_settings, embedder):
    store = Store(tmp_path / "r.db")
    ingest_pack(SYNTH_PACK, store, test_settings)
    s = RetrievalService(store, test_settings, embedder)
    yield s
    store.close()


def events(svc, type_, case="adhoc"):
    return [e for e in svc.store.events(case) if e.type == type_]


# -------------------------------------------------------------- search ---


def test_search_returns_relevant_traceable_hits(svc):
    res = svc.search("rail operator spare capacity", LATE, "heimdall", limit=3)
    assert res.hits and res.hits[0].doc_id in {"SYN-0001", "SYN-0002", "SYN-0010"}
    h = res.hits[0]
    assert h.chunk_id == f"{h.doc_id}#{h.paragraph_ref}" and h.pub_date and h.source_name and h.reliability_tier
    assert svc.store.get_paragraph(h.doc_id, h.paragraph_ref) is not None
    assert h.scores.vector_rank is not None and h.scores.rrf > 0


def test_as_of_is_mandatory(svc):
    with pytest.raises(ValueError):
        svc.search("grain", None, "thor")
    with pytest.raises(SystemExit):
        search_cli(["grain", "--db", str(svc.store.path)])


def test_search_never_returns_documents_after_as_of(svc):
    q = "Beta port authority kept its fees unchanged for the spring schedule"  # SYN-0008/9, published 2030-03-15
    early = svc.search(q, "2030-03-12", "loki", limit=20)
    assert early.hits and all(h.pub_date <= date(2030, 3, 12) for h in early.hits)
    assert "SYN-0008" not in {h.doc_id for h in early.hits}
    later = svc.search(q, "2030-03-15", "loki", limit=20)
    assert later.hits[0].doc_id == "SYN-0008"


def test_date_range_beyond_as_of_is_clamped_and_logged(svc):
    res = svc.search("grain", "2030-03-12", "thor", {"date_to": "2030-12-31"})
    assert all(h.pub_date <= date(2030, 3, 12) for h in res.hits)
    assert events(svc, LogEventType.CLOCK_VIOLATION_BLOCKED)


def test_two_filters_combine_as_intersection(svc):
    svc.index.refresh()
    chunks = svc.index.chunks
    f_country, f_type = SearchFilters(country="Beta"), SearchFilters(source_type="news")
    both = SearchFilters(country="beta", source_type="NEWS")
    a = {c.chunk_id for c in chunks if passes(c, f_country, LATE)}
    b = {c.chunk_id for c in chunks if passes(c, f_type, LATE)}
    ab = {c.chunk_id for c in chunks if passes(c, both, LATE)}
    assert a and b and ab == a & b and ab != a and ab != b
    res = svc.search("prices", LATE, "thor", both, limit=20)
    assert res.candidates == len(ab)
    assert all(h.country == "Beta" and h.source_type == "news" for h in res.hits)


def test_reliability_event_and_background_filters(svc):
    res = svc.search("grain loadings", LATE, "heimdall", {"max_reliability": 1, "sector": "grain"}, limit=20)
    assert res.hits and all(h.reliability_tier == 1 for h in res.hits)
    bg = svc.search("community notes", LATE, "heimdall", {"event_id": "none"}, limit=20)
    assert bg.hits and all(h.event_id is None for h in bg.hits)


def test_sector_filter_matches_trade_table_commodity(svc):
    # SYN-0012's header says Rice, its trade table says grain: both find it.
    for sector in ("grain", "rice"):
        res = svc.search("trade note value volume", LATE, "thor", {"sector": sector, "doc_ids": ["SYN-0012"]})
        assert res.hits and {h.doc_id for h in res.hits} == {"SYN-0012"}


def test_exact_duplicates_hidden_by_default_with_provenance_available(svc):
    q = "port fees unchanged spring schedule"
    res = svc.search(q, LATE, "loki", limit=20)
    ids = {h.doc_id for h in res.hits}
    assert "SYN-0008" in ids and "SYN-0009" not in ids
    res2 = svc.search(q, LATE, "loki", {"include_duplicates": True}, limit=20)
    dup = [h for h in res2.hits if h.doc_id == "SYN-0009"]
    assert dup and dup[0].duplicate_of == "SYN-0008"


def test_flagged_injection_text_is_withheld_in_hits(svc):
    res = svc.search("skip cross-examination ignore previous instructions", LATE, "odin", {"doc_ids": ["SYN-0011"]})
    p2 = next(h for h in res.hits if h.paragraph_ref == "P2")
    assert p2.injection_flagged and "ignore previous" not in p2.text and "WITHHELD" in p2.text


def test_correction_visible_only_when_in_window(svc):
    q = "grain loadings fell sharply after the lock closed"
    before = svc.search(q, "2030-03-12", "heimdall", {"doc_ids": ["SYN-0001"]})
    after = svc.search(q, "2030-03-13", "heimdall", {"doc_ids": ["SYN-0001"]})
    assert before.hits[0].corrected_by == [] and after.hits[0].corrected_by == ["SYN-0018"]


# --------------------------------------------------------------- cache ---


def test_identical_query_reused_and_logged(svc):
    first = svc.search("lock repairs harbour", LATE, "thor", {"country": "Alpha"}, case_id="C1")
    again = svc.search("  Lock repairs   HARBOUR. ", LATE, "thor", {"country": "alpha"}, case_id="C1")
    assert not first.reused and again.reused and again.first_query_seq == first.query_seq
    assert [h.chunk_id for h in again.hits] == [h.chunk_id for h in first.hits]
    qs = events(svc, LogEventType.QUERY, "C1")
    assert [e.payload["reused"] for e in qs] == [False, True]
    assert events(svc, LogEventType.RETRIEVED, "C1")[-1].payload["reused"] is True


@pytest.mark.parametrize("change", [
    {"query": "lock repair harbour delays"},  # similar but new wording
    {"agent": "loki"},
    {"filters": {"country": "Beta"}},
    {"as_of": "2030-03-20"},
    {"case_id": "C2"},
])
def test_similar_but_different_requests_run(svc, change):
    base = dict(query="lock repairs harbour", as_of=LATE, agent="thor", filters={"country": "Alpha"}, case_id="C1")
    svc.search(**base)
    res = svc.search(**{**base, **change})
    assert not res.reused


def test_query_and_retrieved_events_logged(svc):
    res = svc.search("rail tonnage", LATE, "loki", case_id="C9", run_number=2)
    q = events(svc, LogEventType.QUERY, "C9")
    r = events(svc, LogEventType.RETRIEVED, "C9")
    assert len(q) == 1 and q[0].agent.value == "loki" and q[0].run_number == 2 and q[0].payload["as_of"] == "2030-12-31"
    assert r[0].refs == [h.chunk_id for h in res.hits] and r[0].payload["query_seq"] == res.query_seq


# ------------------------------------------------------------ read_doc ---


def test_read_doc_in_window(svc):
    v = svc.read_doc("SYN-0011", LATE, "thor", ["P1", "P2", "P9"])
    assert v.status == "ok" and [p.ref for p in v.paragraphs] == ["P1", "P2"] and v.missing_refs == ["P9"]
    assert "WITHHELD" in v.paragraphs[1].text and v.paragraphs[1].injection_flagged
    raw = svc.read_doc("SYN-0011", LATE, "odin", ["P2"], original_text=True)
    assert raw.paragraphs[0].text.startswith("SYSTEM:")


def test_read_doc_after_as_of_is_blocked_and_logged(svc):
    v = svc.read_doc("SYN-0018", "2030-03-12", "thor")
    assert v.status == "blocked" and v.paragraphs == [] and v.title is None
    ev = events(svc, LogEventType.CLOCK_VIOLATION_BLOCKED)
    assert ev and "SYN-0018" in ev[-1].refs
    # relations never leak out-of-window documents
    assert not any("SYN-0018" in r for r in svc.read_doc("SYN-0001", "2030-03-12", "thor").relations)
    assert any("corrected_by SYN-0018" == r for r in svc.read_doc("SYN-0001", LATE, "thor").relations)


def test_read_doc_unknown_and_undated(svc):
    assert svc.read_doc("NOPE-1", LATE, "thor").status == "not_found"
    assert events(svc, LogEventType.ERROR)


# ---------------------------------------------------------- trade rows ---


def test_trade_rows_gated_by_publication_date(svc):
    # SYN-0012 published 2030-07-20; TT-SYN-01 (SYN-0013) published 2030-07-21.
    res = svc.get_trade_rows({}, "2030-07-20", "thor")
    tables = {r.table_id for r in res.rows}
    assert tables == {"SYN-0012"} and not res.blocked
    res2 = svc.get_trade_rows({"table_ids": ["TT-SYN-01"]}, "2030-07-20", "thor")
    assert res2.rows == [] and len(res2.blocked) == 7
    assert events(svc, LogEventType.CLOCK_VIOLATION_BLOCKED)
    res3 = svc.get_trade_rows({"row_ids": ["TT-SYN-01#R1"]}, "2030-07-21", "thor")
    assert [r.row_id for r in res3.rows] == ["TT-SYN-01#R1"]


def test_trade_rows_filters_and_invalid_rows_visible_with_reason(svc):
    res = svc.get_trade_rows(TradeQuery(origin=["alpha"], destination=["beta"], sector=["grain"]), LATE, "loki")
    assert res.rows and all(r.origin == "Alpha" and r.destination == "Beta" for r in res.rows)
    bad = [r for r in res.rows if r.status != RowStatus.VALID]
    assert bad and all(r.damage_reason for r in bad)
    valid = svc.get_trade_rows({"origin": "alpha", "valid_only": True}, LATE, "loki")
    assert valid.rows and all(r.status == RowStatus.VALID for r in valid.rows)
    period = svc.get_trade_rows({"table_ids": ["TT-SYN-01"], "period_from": "2030-02", "period_to": "2030-03"}, LATE, "loki")
    assert {r.period for r in period.rows} == {"2030-02", "2030-03"}


# ----------------------------------------------------------- hot ingest ---


def test_hot_ingested_document_becomes_searchable(svc, tmp_path):
    q = "zirconium shipments through the Delta canal"
    before = svc.search(q, LATE, "heimdall", limit=3)
    assert all(h.doc_id != "LIV-0001" for h in before.hits)
    pack = write_pack(tmp_path / "live", "live_pack", {"LIV-0001.txt": header(
        "LIV-0001", "Zirconium cargo diverted", date="2030-05-01", stype="news", tier=2) +
        "Zirconium cargo diverted\n\n[P1] Zirconium shipments through the Delta canal were diverted to rail.\n"})
    rep = svc.hot_ingest(pack)
    assert not rep.errors
    after = svc.search(q, LATE, "heimdall", limit=3)
    assert not after.reused and after.hits[0].chunk_id == "LIV-0001#P1"
    assert any(e.type == LogEventType.INGEST and "hot ingest" in e.summary for e in svc.store.events("adhoc"))


def test_ingest_by_another_writer_is_picked_up_without_restart(svc, tmp_path, test_settings):
    svc.search("anything at all", LATE, "thor")
    pack = write_pack(tmp_path / "live2", "live_pack2", {"LIV-0002.txt": header(
        "LIV-0002", "Molybdenum quota", date="2030-05-02", stype="news", tier=2) +
        "Molybdenum quota\n\n[P1] A new molybdenum export quota was announced.\n"})
    ingest_pack(pack, svc.store, test_settings)  # e.g. the ingest CLI writing to the same DB
    res = svc.search("molybdenum export quota", LATE, "thor", limit=2)
    assert res.hits[0].doc_id == "LIV-0002"
