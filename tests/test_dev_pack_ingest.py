"""The organiser dev pack ingests end to end. Assertions are generic properties
derived from the manifest and files, never hard-coded document IDs or values."""

from __future__ import annotations

import json
from datetime import date

import pytest

from ragnarok.config import Settings, get_settings
from ragnarok.ingest.cli import summarise
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.models import DamageKind, LogEventType, RowStatus
from ragnarok.store.db import Store

PACK = get_settings().packs_dir / "dev_pack_E5"
pytestmark = pytest.mark.skipif(not PACK.is_dir(), reason="dev pack not downloaded")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    store = Store(tmp_path_factory.mktemp("dev") / "dev.db")
    rep = ingest_pack(PACK, store, Settings(_env_file=None))
    yield store, rep
    store.close()


def _manifest() -> dict:
    return json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))


def test_no_crash_no_errors_every_doc_stored(result):
    store, rep = result
    m = _manifest()
    assert rep.errors == [] and rep.skipped == []
    ids = {d.meta.doc_id for d in rep.documents}
    listed = {e.get("DOC_ID") or e.get("doc_id") for e in m["documents"]}
    assert ids == listed and len(ids) == m["count"]
    assert store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == m["count"]


def test_formats_match_files_and_empty_files_flagged(result):
    _, rep = result
    by_file = {d.meta.file_name: d for d in rep.documents}
    for name, d in by_file.items():
        size = (PACK / "docs" / name).stat().st_size
        if size == 0:
            assert DamageKind.EMPTY in {f.kind for f in d.damage_flags}
            assert d.meta.title and d.meta.pub_date  # metadata recovered from the manifest
        else:
            assert d.meta.format is not None and d.meta.format.value == name.rsplit(".", 1)[1].lower()
            assert d.paragraphs, name


def test_readable_docs_have_sequential_refs_and_full_metadata(result):
    _, rep = result
    for d in rep.documents:
        if not d.paragraphs:
            continue
        refs = [p.ref for p in d.paragraphs]
        assert refs == [f"P{i}" for i in range(1, len(refs) + 1)], d.meta.doc_id
        assert d.meta.reliability_tier in (1, 2, 3, 4) and d.meta.pub_date and d.meta.source_type != "unknown"
        assert not any(f.kind == DamageKind.BAD_ENCODING for f in d.damage_flags)


def test_trade_notes_yield_tables_with_valid_rows(result):
    _, rep = result
    notes = [d.meta.doc_id for d in rep.documents if d.meta.source_type == "trade_note"]
    tables = {t.source_doc_id: t for t in rep.tables}
    assert notes and set(notes) <= set(tables)
    for did in notes:
        t = tables[did]
        assert t.origin != "unknown" and t.destination != "unknown"
        assert all(r.period and (r.status != RowStatus.VALID or r.value is not None) for r in t.rows)
        title = next(d for d in rep.documents if d.meta.doc_id == did).meta.title.lower()
        assert t.sector in title  # commodity read from content agrees with the title


def test_injection_detected_and_logged(result):
    store, rep = result
    assert any(f.severity == "high" for d in rep.documents for f in d.injection_flags)
    evs = store.events(f"ingest:{rep.pack_id}")
    assert any(e.type == LogEventType.TRAP_INJECTION for e in evs)
    for d in rep.documents:
        for f in d.injection_flags:
            if f.paragraph_ref and f.severity == "high":
                assert d.paragraph(f.paragraph_ref).evidence_text  # agents get a marked version


def test_post_as_of_docs_are_stored_and_reported(result):
    _, rep = result
    as_of = date.fromisoformat(_manifest()["as_of"])
    late = {d.meta.doc_id for d in rep.documents if d.meta.pub_date and d.meta.pub_date > as_of}
    s = summarise(rep)
    assert {x.split()[0] for x in s["published_after_pack_as_of"]} == late


def test_duplicates_found_but_never_deleted(result):
    _, rep = result
    s = summarise(rep)
    assert s["exact_duplicates"]
    by_id = {d.meta.doc_id: d for d in rep.documents}
    for dup, canon in s["exact_duplicates"].items():
        assert by_id[dup].paragraphs and by_id[canon].paragraphs
        assert by_id[dup].content_sha256 == by_id[canon].content_sha256
