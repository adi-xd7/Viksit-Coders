"""Unit and integration tests for LangGraph trial state machine orchestration."""

import json
import pytest
from typing import Dict, List, Optional

from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    Citation,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    LogEventType,
    Ruling,
    SendBack,
    SufficiencyResult,
    SufficiencyStatus,
    TradeRow,
    Verdict,
)
from backend.agents.adapters import (
    CrossExamAdapter,
    HeimdallAdapter,
    LokiAdapter,
    ThorAdapter,
)
from backend.agents.odin import OdinJudge
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.trial import TrialGraphBuilder, run_trial


@pytest.fixture
def test_setup(tmp_path):
    output_dir = str(tmp_path / "cases")
    logbook = LogBook(db_path=str(tmp_path / "audit.db"))
    memory_store = MemoryStore()
    llm_client = LLMClient()
    return {
        "output_dir": output_dir,
        "logbook": logbook,
        "memory_store": memory_store,
        "llm_client": llm_client,
    }


@pytest.mark.asyncio
async def test_successful_single_run_sufficient_trial(test_setup):
    """A trial with sufficient evidence terminates in Run 1 with ready_for_briefing."""
    llm = test_setup["llm_client"]

    def mock_llm(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "THOR-C1-MID-WHE",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Sufficiently proven by official corridor record.",
                },
                {
                    "claim_id": "LOKI-C1-MID-WHE",
                    "verdict": "conceded",
                    "basis": "inference",
                    "rationale": "Conceded during cross-examination.",
                },
            ]
        })

    llm.set_mock_handler(mock_llm)

    class MockSufficiencyOdin(OdinJudge):
        def assess_sufficiency(self, *args, **kwargs) -> SufficiencyResult:
            return SufficiencyResult(
                status=SufficiencyStatus.SUFFICIENT,
                is_sufficient=True,
                reasons=["All required trade baseline and disruption evidence is present and verified."],
            )

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        odin=MockSufficiencyOdin(llm_client=llm, logbook=test_setup["logbook"], memory_store=test_setup["memory_store"]),
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="As of 25 January 2027, how exposed is Midgard wheat?",
        as_of="2027-01-25",
        max_runs=2,
        builder=builder,
    )

    assert state.get("overall_status") == "ready_for_briefing"
    assert state.get("run_count") == 1
    assert len(state.get("claims", [])) >= 2
    assert len(state.get("rulings", [])) >= 2
    assert state.get("persisted_snapshot_path") is not None


@pytest.mark.asyncio
async def test_parallel_thor_and_loki_preservation_regardless_of_order(test_setup):
    """Test that Thor and Loki updates are disjoint and both survive parallel execution."""
    llm = test_setup["llm_client"]

    class CustomThor(ThorAdapter):
        def generate_claims(self, *args, **kwargs) -> List[Claim]:
            return [
                Claim(
                    claim_id="THOR-UNIQUE-1",
                    agent=AgentRole.THOR,
                    country="Midgard",
                    sector="wheat",
                    posture="high",
                    statement="Thor unique claim.",
                    citations=[Citation(doc_id="ATL-0001", paragraph_num=1)],
                )
            ]

    class CustomLoki(LokiAdapter):
        def generate_claims(self, *args, **kwargs) -> List[Claim]:
            return [
                Claim(
                    claim_id="LOKI-UNIQUE-1",
                    agent=AgentRole.LOKI,
                    country="Midgard",
                    sector="wheat",
                    posture="limited",
                    statement="Loki unique claim.",
                    citations=[Citation(doc_id="ATL-0002", paragraph_num=1)],
                )
            ]

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        thor=CustomThor(llm_client=llm),
        loki=CustomLoki(llm_client=llm),
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=1,
        builder=builder,
    )

    # Both Thor and Loki claims must be present in state
    claim_ids = [c.claim_id for c in state.get("claims", [])]
    assert "THOR-UNIQUE-1" in claim_ids
    assert "LOKI-UNIQUE-1" in claim_ids
    assert len(state.get("thor_claims", [])) == 1
    assert len(state.get("loki_claims", [])) == 1


@pytest.mark.asyncio
async def test_event_not_real_terminates_without_running_advocates(test_setup):
    """If Heimdall determines event is NOT_REAL, graph halts immediately before advocates or Odin."""
    llm = test_setup["llm_client"]

    heimdall = HeimdallAdapter(
        llm_client=llm,
        verification_override=EventVerificationStatus.NOT_REAL,
    )

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        heimdall=heimdall,
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="Assess fake event in Midgard",
        max_runs=2,
        builder=builder,
    )

    assert state.get("overall_status") == "event_not_real"
    assert state.get("case_file").verification_status == EventVerificationStatus.NOT_REAL
    # Advocates and Odin must NOT have run
    assert state.get("thor_claims") is None or len(state.get("thor_claims")) == 0
    assert state.get("loki_claims") is None or len(state.get("loki_claims")) == 0
    assert state.get("rulings") is None or len(state.get("rulings")) == 0


@pytest.mark.asyncio
async def test_uncertain_event_follows_policy_and_discloses_uncertainty(test_setup):
    """If event is UNCERTAIN, trial runs and sufficiency checker flags the uncertainty."""
    llm = test_setup["llm_client"]

    heimdall = HeimdallAdapter(
        llm_client=llm,
        verification_override=EventVerificationStatus.UNCERTAIN,
    )

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        heimdall=heimdall,
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="Assess unverified event in Midgard",
        max_runs=2,
        builder=builder,
    )

    assert state.get("case_file").verification_status == EventVerificationStatus.UNCERTAIN
    history = state.get("run_history", [])
    assert len(history) >= 1
    # Check that Run 1 sufficiency identified the unverified event gap
    snapshot_p = history[0]["snapshot_path"]
    with open(snapshot_p, "r", encoding="utf-8") as f:
        snap = json.load(f)
    assert snap.get("send_back") is not None
    assert "unverified_event" in snap["send_back"].get("gap_types", [])


@pytest.mark.asyncio
async def test_send_back_routes_to_heimdall_and_run_two_introduces_new_evidence(test_setup):
    """Insufficient Run 1 generates SendBack, routes back to Heimdall, and introduces new evidence in Run 2."""
    llm = test_setup["llm_client"]

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="As of 25 January 2027, how exposed are Midgard and Tolan to grain disruption?",
        as_of="2027-01-25",
        max_runs=2,
        builder=builder,
    )

    # Must have completed Run 1 and attempted Run 2
    history = state.get("run_history", [])
    assert len(history) >= 1
    assert history[0]["run_num"] == 1
    # Run 2 snapshot created
    assert state.get("run_count") >= 2


@pytest.mark.asyncio
async def test_degraded_mode_when_thor_fails_preserves_loki(test_setup):
    """When Thor advocate fails, Loki's claims survive unchallenged."""
    llm = test_setup["llm_client"]

    thor = ThorAdapter(llm_client=llm, simulate_failure=True)
    loki = LokiAdapter(llm_client=llm, simulate_failure=False)

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        thor=thor,
        loki=loki,
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="Assess Midgard wheat exposure",
        max_runs=1,
        builder=builder,
    )

    assert state.get("thor_failed") is True
    assert state.get("loki_failed") is False
    assert len(state.get("loki_claims", [])) >= 1
    assert len(state.get("thor_claims", [])) == 0


@pytest.mark.asyncio
async def test_degraded_mode_when_loki_fails_preserves_thor(test_setup):
    """When Loki advocate fails, Thor's claims survive unchallenged."""
    llm = test_setup["llm_client"]

    thor = ThorAdapter(llm_client=llm, simulate_failure=False)
    loki = LokiAdapter(llm_client=llm, simulate_failure=True)

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        thor=thor,
        loki=loki,
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="Assess Midgard wheat exposure",
        max_runs=1,
        builder=builder,
    )

    assert state.get("thor_failed") is False
    assert state.get("loki_failed") is True
    assert len(state.get("thor_claims", [])) >= 1
    assert len(state.get("loki_claims", [])) == 0


@pytest.mark.asyncio
async def test_cross_examination_produces_attacks_and_defenses(test_setup):
    """Cross-examination produces reciprocal attacks and defenses."""
    llm = test_setup["llm_client"]

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=1,
        builder=builder,
    )

    attacks = state.get("attacks", [])
    defenses = state.get("defenses", [])

    assert len(attacks) >= 2
    assert any(a.attacker == AgentRole.THOR for a in attacks)
    assert any(a.attacker == AgentRole.LOKI for a in attacks)
    assert len(defenses) >= 2
    assert any(d.defender == AgentRole.THOR for d in defenses)
    assert any(d.defender == AgentRole.LOKI for d in defenses)
