"""LLM request economy: call counts per stage, the case call cap, combined memory
baseline, Heimdall seeds shared through the query cache, code-derived cross-exam
searches, Odin's merged call and its fallback, delta-only second runs, and the
same-case response cache (resume replays finished steps without API calls).

The model is scripted (tests/fake_llm.py): isolated tests only, never the demo."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from conftest import SYNTH_PACK, header, write_pack
from fake_llm import C, ScriptedBackend, default_handlers
from ragnarok.agents import schemas as S
from ragnarok.config import Settings
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.llm.client import LLMError, LLMOutputError
from ragnarok.models import AgentName, LogEventType, Verdict
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store
from ragnarok.trial.machine import Stage, Trial
from ragnarok.trial.runner import case_status
from test_phase4 import AS_OF, QUESTION, Q_XTR, TWO_RUNS, odin_insufficient_once


@pytest.fixture()
def settings(tmp_path):
    return Settings(_env_file=None, cases_dir=tmp_path / "cases", gemini_api_key="test-key", max_evidence_per_query=2)


@pytest.fixture()
def world(tmp_path, settings, embedder):
    store = Store(tmp_path / "t.db")
    ingest_pack(SYNTH_PACK, store, settings)
    extra = write_pack(tmp_path / "extra", "extra_pack", {"XTR-0001.txt": header(
        "XTR-0001", "Customs ledger of cereal arrivals by origin", date="2030-06-30", source="Beta Customs",
        stype="customs_data", tier=1) + f"Customs ledger of cereal arrivals by origin\n\n[P1] {Q_XTR}\n"})
    ingest_pack(extra, store, settings)
    svc = RetrievalService(store, settings, embedder)
    yield store, svc
    store.close()


def trial(world, settings, overrides=None, case_id=None):
    store, svc = world
    b = ScriptedBackend(overrides)
    return Trial(QUESTION, AS_OF, store, settings, backend=b, service=svc, case_id=case_id), b


def events(store, case_id, type_=None, agent=None):
    return [e for e in store.events(case_id) if (type_ is None or e.type == type_) and (agent is None or e.agent.value == agent)]


def by_stage(t: Trial) -> dict[str, int]:
    return dict(Counter(f"run {r['run']} {r['stage']}" for r in t.ledger.records if not r["cached"]))


# --------------------------------------------------------- call counts ---


def test_two_run_case_fits_the_free_tier_budget(world, settings):
    t, b = trial(world, settings, TWO_RUNS)
    r = t.run()
    assert r.stage == Stage.DONE and r.runs_completed == 2
    assert by_stage(t) == {"run 1 HEIMDALL": 2, "run 1 THOR_LOKI": 4, "run 1 CROSS_EXAMINATION": 4, "run 1 ODIN": 1,
                           "run 2 HEIMDALL_RESEARCH": 2, "run 2 THOR_LOKI": 4, "run 2 CROSS_EXAMINATION": 4, "run 2 ODIN": 1}
    assert t.ledger.calls_used == len(b.calls) == 22 <= 25
    # no planning call for cross-examination, the send-back follow-up or Odin; no separate memory baseline
    labels = [rec["label"] for rec in t.ledger.records]
    assert not [x for x in labels if "cross-exam research" in x or "defense research" in x or "follow-up" in x
                or "odin research" in x or "baseline without memory" in x]
    calls = json.loads((r.case_dir / "llm_calls.json").read_text(encoding="utf-8"))
    assert calls["summary"]["calls_used"] == 22 and calls["summary"]["by_agent"] == {"heimdall": 4, "loki": 8, "odin": 2,
                                                                                     "thor": 8}
    usage = [e for e in events(world[0], t.case_id, LogEventType.LLM_USAGE)]
    assert len(usage) == 1 and usage[0].payload["calls_used"] == 22
    st = case_status(settings, t.case_id)
    assert st["calls_used"] == 22 and st["calls_limit"] == settings.max_llm_calls_per_case


def test_one_planning_turn_holds_up_to_the_configured_requests(world, settings):
    asked = {}

    def thor_research(user, n):
        asked["user"] = user
        reqs = [S.ToolRequest(tool="search", purpose=f"s{i}", query=f"grain loadings question {i}") for i in range(12)]
        return S.ResearchTurn.of(reqs, done=True)
    t, b = trial(world, settings.model_copy(update={"max_requests_per_round": 8}), {("thor", "ResearchTurn"): thor_research})
    t.run()
    q = [e for e in events(world[0], t.case_id, LogEventType.QUERY, "thor") if e.run_number == 1 and "query_norm" in e.payload
         and e.payload["query"].startswith("grain loadings question")]
    assert len(q) == 8 and "Request up to 8 tool calls" in asked["user"] and "only planning turn" in asked["user"]
    assert [c["schema"] for c in b.calls if c["agent"] == "thor"].count("ResearchTurn") == 1


def test_second_planning_turn_only_when_the_own_search_is_missing(world, settings):
    def loki_no_search(user, n):  # first turn: reads only; the extra turn must contain the required search
        if n >= 1:
            return S.ResearchTurn.of([S.ToolRequest(tool="search", purpose="own", query="millers bought grain from Gamma")])
        return S.ResearchTurn.of([S.ToolRequest(tool="read_doc", purpose="stocks", doc_id="SYN-0003")], done=True)
    t, b = trial(world, settings, {("loki", "ResearchTurn"): loki_no_search})
    r = t.run()
    assert [c["schema"] for c in b.calls if c["agent"] == "loki"].count("ResearchTurn") == 2
    assert r.submissions["loki"].claims and r.stage == Stage.DONE


def test_case_call_cap_finishes_gracefully(world, settings):
    s = settings.model_copy(update={"max_llm_calls_per_case": 14})  # run 1 needs 11; run 2 is cut off
    t, b = trial(world, s, TWO_RUNS)
    r = t.run()
    assert len(b.calls) == 14 and t.ledger.calls_used == 14
    lim = [e for e in events(world[0], t.case_id, LogEventType.LIMIT_HIT) if "LLM calls for the case" in e.summary]
    assert lim and r.stage == Stage.DONE and r.runs_completed == 1
    assert json.loads((r.case_dir / "briefing.json").read_text(encoding="utf-8"))["status"] == "incomplete"
    s1 = settings.model_copy(update={"max_llm_calls_per_case": 3})  # cannot even finish run 1: honest failure
    t1, b1 = trial(world, s1)
    r1 = t1.run()
    assert len(b1.calls) == 3 and r1.stage == Stage.FAILED and not (r1.case_dir / "briefing.json").exists()


# ------------------------------------------------- seeds (Heimdall -> advocates) ---


def test_heimdall_seed_searches_are_shared_through_the_query_cache(world, settings):
    t, b = trial(world, settings)
    r = t.run()
    store = world[0]
    plan = next(e for e in events(store, t.case_id, LogEventType.RESEARCH_PLAN, "heimdall") if e.payload.get("seed"))
    assert "Beta" in plan.payload["countries"] and plan.payload["sectors"] == ["grain"]  # names in the question
    seeds = r.heimdall.seeds
    assert len(seeds) >= 2 and {sd["query_seq"] for sd in seeds} <= {e.seq for e in events(store, t.case_id, LogEventType.QUERY,
                                                                                           "heimdall")}
    for a in ("thor", "loki"):
        got = [e for e in events(store, t.case_id, LogEventType.RETRIEVED, a) if e.payload.get("seed")]
        assert len(got) == len(seeds) and all(e.payload["reused"] and e.payload["from_agent"] == "heimdall" for e in got)
        # the seed results reached the advocate's first planning prompt, with the case file's trade rows
        first = next(c["user"] for c in b.calls if c["agent"] == a)
        assert "Heimdall's seed searches" in first and "SYN-0012#R1" in first
        # and the advocate still made its own, non-reused search
        own = [e for e in events(store, t.case_id, LogEventType.QUERY, a) if "query_norm" in e.payload and not e.payload["reused"]]
        assert own
    # no advocate prompt contains the other advocate's claims before cross-examination
    thor_brief = next(c["user"] for c in b.calls if c["agent"] == "thor" and c["schema"] == "AdvocateBrief")
    assert "Beta millers substituted grain from Gamma" not in thor_brief


def test_advocate_must_still_search_itself_even_with_seeds(world, settings):
    def thor_reads_only(user, n):
        return S.ResearchTurn.of([S.ToolRequest(tool="read_doc", purpose="x", doc_id="SYN-0001")], done=True)
    t, b = trial(world, settings, {("thor", "ResearchTurn"): thor_reads_only})
    r = t.run()
    assert r.submissions["thor"].failed and "did not make a search of its own" in r.submissions["thor"].failed
    assert any("thor failed" in n or "unchallenged" in n for n in r.notes)


# ------------------------------------------------------ cross-examination ---


def test_cross_exam_searches_are_derived_in_code_and_rules_still_hold(world, settings):
    t, b = trial(world, settings)
    r = t.run()
    store = world[0]
    cx = r.cross_exam
    assert {a.attacker for a in cx.attacks} == {AgentName.THOR, AgentName.LOKI}  # >= 1 attack each way
    for a in cx.attacks:
        assert a.target_claim_id and len(a.objection) >= 20 and (a.counter_evidence or a.evidence_gap)
    plans = [e for e in events(store, t.case_id, LogEventType.RESEARCH_PLAN) if e.payload.get("cross_exam")]
    assert {(e.agent.value, e.payload["cross_exam"]) for e in plans} >= {("thor", "attack"), ("loki", "attack")}
    # the derived searches went through the normal logged, as_of-gated search tool of that advocate
    for e in plans:
        for sr in [x for x in e.payload.get("searches", e.payload.get("requests", [])) if x.get("query")]:
            assert any(q.payload.get("query") == sr["query"] and q.agent == e.agent
                       for q in events(store, t.case_id, LogEventType.QUERY))
    # defend with NEW evidence or concede (scripted: Thor defends, Loki concedes)
    assert cx.defenses and all(d.new_evidence for d in cx.defenses) and cx.concessions
    assert not [c for c in b.calls if c["schema"] == "ResearchTurn" and ("Cross-examination" in c["user"]
                                                                           or "Respond to every attack" in c["user"])]


def test_attack_with_no_valid_part_gets_one_repair(world, settings):
    def bad_then_good(user, n):
        if "<repair_request>" not in user:
            return S.AttackSet(attacks=[S.AttackDraft(target_claim_id="T1-1", objection="I disagree.", why_it_matters="x")])
        return default_handlers()[("loki", "AttackSet")](user.split("<repair_request>")[0], n)
    t, b = trial(world, settings, {("loki", "AttackSet"): bad_then_good})
    r = t.run()
    assert [c["schema"] for c in b.calls if c["agent"] == "loki"].count("AttackSet") == 2
    assert [a for a in r.cross_exam.attacks if a.attacker == AgentName.LOKI]


# ------------------------------------------------------------------- Odin ---


def test_odin_merged_call_falls_back_to_two_steps(world, settings):
    def odin_broken(user, n):
        raise LLMOutputError("merged output invalid after one repair attempt")
    overrides = {("odin", "OdinVerdict"): odin_broken}
    t, b = trial(world, settings, overrides)
    r = t.run()
    schemas = [c["schema"] for c in b.calls if c["agent"] == "odin"]
    assert schemas == ["OdinVerdict", "OdinRulings", "OdinAssessment"]
    assert any(e.payload.get("fallback") == "two_step" for e in events(world[0], t.case_id, LogEventType.ERROR, "odin"))
    claims = {c.claim_id for s in r.submissions.values() for c in s.claims}
    assert {x.claim_id for x in r.odin.rulings} == claims and r.stage == Stage.DONE


def test_odin_api_outage_is_not_retried_as_a_fallback(world, settings):
    def odin_down(user, n):
        raise LLMError("rate limited after 7 attempt(s): quota")
    t, b = trial(world, settings, {("odin", "OdinVerdict"): odin_down})
    r = t.run()
    assert [c["schema"] for c in b.calls if c["agent"] == "odin"] == ["OdinVerdict"] and r.stage == Stage.FAILED


def test_odin_sees_code_validated_citations_and_no_planning_turn(world, settings):
    s = settings.model_copy(update={"max_evidence_per_query": 12})  # Thor's estimate claim survives
    store, svc = world
    t, b = trial((store, RetrievalService(store, s, index=svc.index)), s)
    t.run()
    odin = [c for c in b.calls if c["agent"] == "odin"]
    assert [c["schema"] for c in odin] == ["OdinVerdict"]
    assert "PRE-CHECK: valid citations:" in odin[0]["user"] and "replay from source rows: OK" in odin[0]["user"]
    assert "validated and every calculation replayed in code" in odin[0]["user"]


# ------------------------------------------------------------- delta run ---


def test_run2_is_delta_only(world, settings):
    t, b = trial(world, settings, TWO_RUNS)
    r = t.run()
    run1, run2 = r.runs
    odin2 = [c["user"] for c in b.calls if c["agent"] == "odin"][1]
    assert "Rule on every claim (IDs: T2-1, L2-1)" in odin2 and "<standing_rulings>" in odin2
    rul2 = {x.claim_id: x for x in run2.odin.rulings}
    assert set(rul2) == {c.claim_id for c in run2.ruled_claims}  # every active claim has a ruling
    carried = {c.claim_id for c in run2.ruled_claims if c.run_number == 1}
    assert carried and all(rul2[c].run_number == 1 for c in carried)  # earlier rulings stand, unchanged
    ruled2 = {e.refs[0] for e in events(world[0], t.case_id, LogEventType.RULING) if e.run_number == 2}
    assert ruled2 == {"T2-1", "L2-1"}
    # cross-examination in run 2 only targets the new or revised claims
    assert {a.target_claim_id for a in r.cross_exam.attacks if a.run_number == 2} <= {"T2-1", "L2-1"}
    assert rul2["L1-1"].verdict == Verdict.CONCEDED
    eff = next(e for e in events(world[0], t.case_id, LogEventType.NEW_EVIDENCE) if e.payload.get("phase") == "effect")
    assert "T2-1" in eff.payload["claims_citing_new_evidence"]


def test_run2_revision_without_new_evidence_is_dropped(world, settings):
    def thor_resummary(user, n):  # "revises" T1-1 citing only its run-1 evidence
        return S.AdvocateRevision(claims=[S.RevisedClaimDraft(
            text="Alpha grain loadings fell sharply, as said before.", country="Beta", sector="grain", claim_type="fact",
            citations=[C("SYN-0001", "P1", "loadings of grain fell sharply")], revises_claim_id="T1-1")])
    t, b = trial(world, settings, TWO_RUNS | {("thor", "AdvocateRevision"): thor_resummary})
    r = t.run()
    assert "T1-1" not in r.superseded and not [c for c in r.runs[1].ruled_claims if c.claim_id.startswith("T2-")]
    assert any("cites no evidence first retrieved in this run" in e.summary
               for e in events(world[0], t.case_id, LogEventType.ERROR, "thor"))


def test_second_run_still_needs_genuinely_new_evidence(world, settings):
    def findings_old(user, n):
        return S.ResearchFindings(findings=[S.FindingDraft(missing_item=1, status="partial", summary="old",
                                                           citations=[C("SYN-0001", "P1", "loadings of grain fell sharply")])])
    t, b = trial(world, settings, TWO_RUNS | {("heimdall", "ResearchFindings"): findings_old})
    r = t.run()
    assert r.runs_completed == 1 and not [c for c in b.calls if c["schema"] == "AdvocateRevision"]


# ------------------------------------------------------------- resume ---


def test_resumed_complete_case_replays_without_api_calls(world, settings):
    t1, b1 = trial(world, settings, TWO_RUNS)
    r1 = t1.run()
    t2, b2 = trial(world, settings, TWO_RUNS, case_id=t1.case_id)
    r2 = t2.run()
    assert t2.attempt == 2 and b2.calls == [] and t2.ledger.calls_used == 0
    assert len(t2.ledger.records) == len(b1.calls)  # every step replayed from the case's cache
    hits = [e for e in events(world[0], t1.case_id, LogEventType.LLM_CACHE_HIT) if e.seq > t2.start_seq]
    assert len(hits) == len(b1.calls)
    assert r2.history == r1.history and r2.briefing_status == r1.briefing_status
    assert [(x.claim_id, x.verdict) for x in r2.odin.rulings] == [(x.claim_id, x.verdict) for x in r1.odin.rulings]
    replayed = [e for e in events(world[0], t1.case_id, LogEventType.MEMORY_WRITE) if e.payload.get("replayed")]
    assert replayed  # lessons from attempt 1 are not reinforced twice


def test_case_failing_midway_resumes_with_only_the_missing_calls(world, settings):
    def odin_down(user, n):
        raise LLMError("rate limited after 7 attempt(s): daily quota")
    t1, b1 = trial(world, settings, {("odin", "OdinVerdict"): odin_down})
    r1 = t1.run()
    assert r1.stage == Stage.FAILED
    t2, b2 = trial(world, settings, case_id=t1.case_id)  # quota back: same case resumed
    r2 = t2.run()
    assert r2.stage == Stage.DONE and [c["agent"] for c in b2.calls] == ["odin"]  # only the unfinished step
    assert t2.ledger.calls_used == 1 and len(t2.ledger.records) == len(b1.calls)
    st = case_status(settings, t1.case_id)
    assert st["status"] in ("complete", "partial") and st["attempt"] == 2


def test_response_cache_is_never_shared_across_cases(world, settings):
    t1, b1 = trial(world, settings)
    t1.run()
    t2, b2 = trial(world, settings)  # a new case with the same question: everything is asked again
    t2.run()
    assert t2.attempt == 1 and len(b2.calls) == len(b1.calls) and t2.ledger.calls_used == len(b1.calls)
    assert not events(world[0], t2.case_id, LogEventType.LLM_CACHE_HIT)
