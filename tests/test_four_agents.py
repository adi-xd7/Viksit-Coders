"""Full Four-Agent Integration Test for RAGNAROK Courtroom System.

Validates end-to-end execution across Heimdall, Thor, Loki, Odin,
and the LangGraph state machine from query to validated briefing.
"""

from __future__ import annotations

import os
import pytest
from typing import Dict, List

from backend.agents.cross_exam import CrossExaminationOrchestrator
from backend.agents.heimdall import HeimdallAgent
from backend.agents.loki import LokiAgent
from backend.agents.odin import OdinJudge
from backend.agents.thor import ThorAgent
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    EventVerificationStatus,
    Verdict,
)
from backend.trial import TrialGraphBuilder, run_trial


@pytest.fixture
def four_agents_setup(tmp_path):
    output_dir = str(tmp_path / "cases")
    db_path = str(tmp_path / "logbook.db")
    logbook = LogBook(db_path=db_path, jsonl_path=str(tmp_path / "audit.jsonl"))
    memory_store = MemoryStore()
    import json
    llm = LLMClient()

    def mock_odin(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "THOR-C1-MID-WHE",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Sufficiently proven by corridor transit records.",
                },
                {
                    "claim_id": "LOKI-C1-MID-WHE",
                    "verdict": "contested",
                    "basis": "inference",
                    "rationale": "Contested regarding substitute rail capacity.",
                },
            ]
        })

    llm.set_mock_handler(mock_odin)

    heimdall = HeimdallAgent(llm_client=llm, logbook=logbook, memory_store=memory_store, use_fastembed=False)
    thor = ThorAgent(llm_client=llm, logbook=logbook, memory_store=memory_store)
    loki = LokiAgent(llm_client=llm, logbook=logbook, memory_store=memory_store)
    cross_exam = CrossExaminationOrchestrator(thor_agent=thor, loki_agent=loki)
    odin = OdinJudge(llm_client=llm, logbook=logbook, memory_store=memory_store)

    builder = TrialGraphBuilder(
        heimdall=heimdall,
        thor=thor,
        loki=loki,
        cross_exam=cross_exam,
        odin=odin,
        llm_client=llm,
        logbook=logbook,
        memory_store=memory_store,
        output_dir=output_dir,
    )

    return {
        "builder": builder,
        "logbook": logbook,
        "memory_store": memory_store,
        "llm": llm,
        "output_dir": output_dir,
    }


@pytest.mark.asyncio
async def test_four_agent_end_to_end_trial(four_agents_setup):
    """Test full four-agent trial workflow from raw question to validated briefing."""
    builder = four_agents_setup["builder"]

    state = await run_trial(
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement? Give a low and high range for wheat and maize imports.",
        as_of="2027-01-25",
        max_runs=2,
        builder=builder,
    )

    # 1. Verify Heimdall verification
    assert state.get("case_file") is not None
    assert state["case_file"].verification_status == EventVerificationStatus.REAL

    # 2. Verify Thor and Loki claims generated
    assert len(state.get("thor_claims", [])) >= 1
    assert len(state.get("loki_claims", [])) >= 1
    assert any(c.posture == "high" for c in state["thor_claims"])
    assert any(c.posture == "limited" for c in state["loki_claims"])

    # 3. Verify Cross-examination attacks and defenses
    assert len(state.get("attacks", [])) >= 1
    assert len(state.get("defenses", [])) >= 1

    # 4. Verify Odin rulings
    rulings = state.get("rulings", [])
    assert len(rulings) >= 2
    # Ensure every ruled claim has a valid verdict
    for r in rulings:
        assert r.verdict in (Verdict.ESTABLISHED, Verdict.CONTESTED, Verdict.CONCEDED, Verdict.REJECTED)

    # 5. Verify exposure ranges computed deterministically
    ranges = state.get("exposure_ranges", [])
    assert len(ranges) >= 1

    # 6. Verify briefing generated
    briefing = state.get("briefing")
    assert briefing is not None
    assert len(briefing.executive_summary) > 0
    assert state.get("persisted_briefing_path") is not None
    assert os.path.exists(state["persisted_briefing_path"])


@pytest.mark.asyncio
async def test_four_agent_not_real_event_early_exit(four_agents_setup):
    """Test that a fabricated event terminates early without running advocate hearings."""
    builder = four_agents_setup["builder"]

    state = await run_trial(
        question="Reported fabricated hoax event in Midgard wheat",
        as_of="2027-01-25",
        max_runs=1,
        builder=builder,
    )

    assert state.get("overall_status") in ("event_not_real", "ready_for_briefing")
    assert state["case_file"].verification_status == EventVerificationStatus.NOT_REAL
    # Advocates should not have produced claims for a confirmed hoax
    assert len(state.get("thor_claims", [])) == 0
    assert len(state.get("loki_claims", [])) == 0
