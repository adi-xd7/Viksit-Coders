"""Phase 5: API endpoints and the briefing's build-time citation / provenance checks.
The model is scripted (tests/fake_llm.py); no network."""

from __future__ import annotations

import io
import shutil
import threading
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from conftest import SYNTH_PACK, header
from fake_llm import ScriptedBackend
from ragnarok.api import create_app
from ragnarok.briefing.build import build_briefing
from ragnarok.config import Settings
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.llm.client import LLMError
from ragnarok.models import Citation
from ragnarok.retrieval.service import RetrievalService
from ragnarok.retrieval.text import normalise_quote
from ragnarok.store.db import Store
from ragnarok.trial.runner import run_case

AS_OF = "2030-07-31"
QUESTION = "How exposed is Beta to the Alpha lock closure for grain imports?"


@pytest.fixture()
def settings(tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    return Settings(_env_file=None, gemini_api_key="test-key", db_path=tmp_path / "t.db", cases_dir=tmp_path / "cases",
                    packs_dir=packs, max_upload_bytes=200_000)


@pytest.fixture()
def service(settings, embedder):
    store = Store(settings.db_path)
    ingest_pack(SYNTH_PACK, store, settings)
    svc = RetrievalService(store, settings, embedder)
    yield svc
    store.close()


def client(settings, service, overrides=None, factory="scripted"):
    backend_factory = (lambda: ScriptedBackend(overrides)) if factory == "scripted" else factory
    app = create_app(settings, backend_factory=backend_factory, service=service)
    return TestClient(app), app


def run_via_api(c, app, question=QUESTION, as_of=AS_OF) -> dict:
    r = c.post("/cases", json={"question": question, "as_of": as_of})
    assert r.status_code == 202, r.text
    cid = r.json()["case_id"]
    app.state.runner.join(cid, 300)
    return c.get(f"/cases/{cid}").json()


def broken(user, n):
    raise LLMError("simulated outage")


# ------------------------------------------------------------- cases ---


def test_case_lifecycle_and_results(settings, service):
    c, app = client(settings, service)
    st = run_via_api(c, app)
    assert st["status"] == "complete" and st["stage"] == "DONE" and st["briefing_status"] == "complete"
    res = st["results"]
    assert res["briefing"]["case_id"] == st["case_id"] and "## Exposure" in res["briefing_markdown"]
    assert res["rulings"]["rulings"] and res["claims"]["claims"] and res["runs"] == ["run-1"]
    assert c.get("/api/health").json()["provider"] == "gemini"


def test_events_stream_is_the_real_audit_log(settings, service):
    c, app = client(settings, service)
    cid = run_via_api(c, app)["case_id"]
    body = c.get(f"/cases/{cid}/events?follow=false").text
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and len(ids) > 20
    for t in ("RUN_START", "QUERY", "CLAIM", "ATTACK", "RULING", "BRIEFING", "RUN_END"):
        assert f"event: {t}\n" in body, t
    with Store(settings.db_path) as s:
        assert len(s.events(cid)) == len(ids)  # exactly the stored events, nothing synthetic
    tail = c.get(f"/cases/{cid}/events", params={"after": ids[-3], "follow": True}).text  # finished case: stream ends
    assert tail.count("id: ") == 2 and "event: end" in tail


def test_partial_and_failed_cases_are_reported_as_such(settings, service):
    c, app = client(settings, service, {("loki", "AdvocateBrief"): broken})
    st = run_via_api(c, app)
    assert st["status"] == "partial" and any("unchallenged" in n for n in st["notes"])
    c2, app2 = client(settings, service, {("thor", "AdvocateBrief"): broken, ("loki", "AdvocateBrief"): broken})
    st2 = run_via_api(c2, app2)
    assert st2["status"] == "failed" and "No briefing was produced" in st2["limitations"]
    assert st2["results"]["briefing"] is None


def test_request_validation(settings, service):
    c, _ = client(settings, service)
    assert c.post("/cases", json={"question": "Hi", "as_of": AS_OF}).status_code == 422
    assert c.post("/cases", json={"question": QUESTION, "as_of": "yesterday"}).status_code == 422
    assert c.post("/cases", json={"question": QUESTION, "as_of": AS_OF, "agent": "odin"}).status_code == 422
    assert c.get("/cases/case-does-not-exist").status_code == 404
    assert c.get("/cases/..%2F..%2Fetc").status_code in (400, 404)
    assert c.get("/docs/SYN-0001").status_code == 400  # no as_of: every evidence path is date-gated


def test_no_api_key_means_no_case(settings, service):
    s = settings.model_copy(update={"gemini_api_key": settings.anthropic_api_key})  # empty key
    app = create_app(s, service=service)
    r = TestClient(app).post("/cases", json={"question": QUESTION, "as_of": AS_OF})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]


def test_one_case_at_a_time(settings, service):
    gate = threading.Event()

    def slow(user, n):
        gate.wait(30)
        raise LLMError("released")
    c, app = client(settings, service, {("heimdall", "ResearchTurn"): slow})
    first = c.post("/cases", json={"question": QUESTION, "as_of": AS_OF})
    assert first.status_code == 202
    got = c.get(f"/cases/{first.json()["case_id"]}")
    assert got.status_code == 200 and got.json()["status"] == "running", got.text
    assert c.post("/cases", json={"question": QUESTION, "as_of": AS_OF}).status_code == 409
    gate.set()
    app.state.runner.join(first.json()["case_id"], 60)
    assert c.get(f"/cases/{first.json()['case_id']}").json()["status"] == "failed"


# ----------------------------------------------- briefing traceability ---


def test_every_briefing_citation_resolves_via_docs_or_trade(settings, service):
    c, app = client(settings, service)
    st = run_via_api(c, app)
    cid, b = st["case_id"], st["results"]["briefing"]
    cits = [x for k in ("established", "contested", "conceded", "rejected") for f in b[k] for x in f["citations"]]
    cits += b["event_citations"]
    assert cits
    for x in cits:
        if x["row_id"]:
            table, row = x["row_id"].split("#")
            r = c.get(f"/trade/{table}/{row}", params={"case_id": cid})
            assert r.status_code == 200, x
            texts = [r.json()["rows"][0]["raw_text"]]
        else:
            r = c.get(f"/docs/{x['doc_id']}/{x['paragraph_ref']}", params={"case_id": cid})
            assert r.status_code == 200, x
            texts = [p["text"] for p in r.json()["paragraphs"]]
            assert r.json()["pub_date"] == x["pub_date"]
        assert any(normalise_quote(x["quote"]) in normalise_quote(t) for t in texts), x
    for row in b["exposure_table"]:
        for who in ("thor", "loki", "odin"):
            for ref in (row[who] or {}).get("trade_row_refs", []):
                table, r_ = ref.split("#")
                assert c.get(f"/trade/{table}/{r_}", params={"case_id": cid}).status_code == 200
    md = st["results"]["briefing_markdown"]
    assert "## Assumptions and uncertainty" in md and "Metric (unit, period, denominator)" in md and "## Sources" in md


def test_briefing_drops_invalid_citations_and_unjustified_estimates(settings, service):
    r = run_case(QUESTION, date.fromisoformat(AS_OF), settings, service=service, backend=ScriptedBackend())
    claims = [c for s in r.submissions.values() for c in s.claims]
    bad = claims[0].model_copy(update={"citations": claims[0].citations + [
        Citation(doc_id="SYN-0001", paragraph_ref="P1", pub_date=claims[0].citations[0].pub_date, quote="words that are not there")]})
    est_claim = next(c for c in claims if c.exposure)
    est_bad = est_claim.model_copy(update={"exposure": est_claim.exposure.model_copy(update={"high": 999.0})})
    tampered = [bad if c.claim_id == bad.claim_id else est_bad if c.claim_id == est_bad.claim_id else c for c in claims]
    b, md, dropped = build_briefing(service.store, r.heimdall.case_file, tampered, r.odin, {}, [], [],
                                    calc=service.calculator(date.fromisoformat(AS_OF)))
    assert any(d["where"] == f"claim {bad.claim_id}" for d in dropped)
    shown = [x for k in ("established", "contested", "conceded", "rejected") for f in getattr(b, k)
             if f.claim_id == bad.claim_id for x in f.citations]
    assert shown and all(x.quote != "words that are not there" for x in shown)
    row = next(x for x in b.exposure_table if x.sector == est_claim.exposure.sector)
    who = est_claim.agent.value
    assert getattr(row, who) is None and "calculation provenance failed" in row.unavailable[who]
    assert b.status == "partial" and "Dropped at build time" in md and "unavailable (calculation provenance failed" in md


# ---------------------------------------------------------- evidence ---


def test_docs_are_as_of_gated_and_show_flags(settings, service):
    c, _ = client(settings, service)
    r = c.get("/docs/SYN-0018", params={"as_of": "2030-03-12"})  # published 2030-03-13
    assert r.status_code == 403
    with Store(settings.db_path) as s:
        assert [e for e in s.events("api") if e.type.value == "CLOCK_VIOLATION_BLOCKED" and "SYN-0018" in e.refs]
    assert c.get("/docs/NOPE-0001", params={"as_of": AS_OF}).status_code == 404
    assert c.get("/docs/SYN-0001/P99", params={"as_of": AS_OF}).status_code == 404
    d = c.get("/docs/SYN-0011", params={"as_of": AS_OF}).json()
    flagged = [p for p in d["paragraphs"] if p["injection_flagged"]]
    assert flagged and d["injection_flags"] and flagged[0]["original_text"] and flagged[0]["anchor"].startswith("SYN-0011-")
    assert "skip cross-examination" not in flagged[0]["text"]  # the instruction stays withheld in the evidence text


def test_trade_is_as_of_gated(settings, service):
    c, _ = client(settings, service)
    t = c.get("/trade/SYN-0012", params={"as_of": AS_OF}).json()
    assert t["table"]["table_id"] == "SYN-0012" and {r["status"] for r in t["rows"]} > {"valid"}  # invalid rows shown with status
    assert c.get("/trade/SYN-0012", params={"as_of": "2030-07-01"}).status_code == 403  # note published 2030-07-20
    assert c.get("/trade/SYN-0012/R1", params={"as_of": AS_OF}).json()["rows"][0]["row_id"] == "SYN-0012#R1"
    assert c.get("/trade/SYN-0012/R99", params={"as_of": AS_OF}).status_code == 404


def test_feed_by_date_with_badges(settings, service):
    c, _ = client(settings, service)
    early = c.get("/feed", params={"as_of": "2030-03-12"}).json()
    assert early["withheld_after_as_of"] > 0 and all(i["pub_date"] <= "2030-03-12" for i in early["items"])
    f = {i["doc_id"]: i for i in c.get("/feed", params={"as_of": AS_OF}).json()["items"]}
    assert "high" in f["SYN-0011"]["badges"]["injection"]
    assert f["SYN-0009"]["badges"]["duplicate_of"] == ["SYN-0008"]
    assert "SYN-0018" in f["SYN-0001"]["badges"]["corrected_by"] and f["SYN-0018"]["badges"]["corrects"] == ["SYN-0001"]
    assert "empty" in f["SYN-0004"]["badges"]["damaged"]
    dates = [i["pub_date"] for i in f.values()]
    assert dates == sorted(dates, reverse=True)


# ------------------------------------------------------------ ingest ---


def _pack_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


NEW_DOC = header("NEW-0001", "Late pack notice", date="2030-06-01", stype="gov_notice") + "Late pack notice\n\n[P1] A new notice.\n"
MANIFEST = '{"pack": "new_pack", "documents": [{"DOC_ID": "NEW-0001", "file": "NEW-0001.txt"}]}'


def test_ingest_rejects_bad_paths_types_and_sizes(settings, service, tmp_path):
    c, _ = client(settings, service)
    outside = tmp_path / "outside"
    shutil.copytree(SYNTH_PACK, outside)
    assert c.post("/ingest", data={"pack_dir": str(outside)}).status_code == 400  # not inside PACKS_DIR
    assert c.post("/ingest", data={"pack_dir": "../outside"}).status_code == 400  # traversal
    assert c.post("/ingest", data={"pack_dir": "missing"}).status_code == 404
    assert c.post("/ingest").status_code == 400
    up = lambda name, data: c.post("/ingest", files={"file": (name, data, "application/zip")})  # noqa: E731
    assert up("pack.exe", b"x").status_code == 415
    assert up("pack.zip", b"not a zip").status_code == 400
    assert up("pack.zip", _pack_zip({"../evil.txt": "x", "manifest.json": MANIFEST})).status_code == 400
    assert up("pack.zip", _pack_zip({"/abs/evil.txt": "x", "manifest.json": MANIFEST})).status_code == 400
    assert up("pack.zip", _pack_zip({"run.exe": "x", "manifest.json": MANIFEST})).status_code == 415
    assert up("pack.zip", _pack_zip({"docs/big.txt": "x" * 300_000, "manifest.json": MANIFEST})).status_code == 413
    assert up("pack.zip", _pack_zip({"docs/a.txt": "x"})).status_code == 400  # no manifest


def test_ingest_approved_dir_and_upload(settings, service):
    c, _ = client(settings, service)
    shutil.copytree(SYNTH_PACK, settings.packs_dir / "synth_copy")
    r = c.post("/ingest", data={"pack_dir": "synth_copy"})
    assert r.status_code == 200 and r.json()["documents"] > 10
    z = _pack_zip({"manifest.json": MANIFEST, "docs/NEW-0001.txt": NEW_DOC})
    r2 = c.post("/ingest", files={"file": ("late_pack.zip", z, "application/zip")})
    assert r2.status_code == 200 and r2.json()["documents"] == 1, r2.text
    d = c.get("/docs/NEW-0001/P1", params={"as_of": AS_OF})
    assert d.status_code == 200 and d.json()["paragraphs"][0]["text"] == "A new notice."
    assert list((settings.packs_dir / "uploads").iterdir())  # stored under the approved packs dir
