"""Unit and regression tests for trial execution limits, novelty rules, and persistence."""

import json
import os
import subprocess
import sys
import pytest

from backend.models import (
    AgentRole,
    Citation,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    SendBack,
    SufficiencyStatus,
    TradeRow,
)
from backend.agents.adapters import (
    HeimdallAdapter,
    LokiAdapter,
    ThorAdapter,
)
from backend.agents.odin import OdinJudge
from backend.llm import (
    BudgetExceededError,
    LLMClient,
    MAX_TOKENS_PER_CASE,
    MAX_TOOL_CALLS_PER_AGENT,
    ToolCallLimitExceededError,
)
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.trial import TrialGraphBuilder, persist_run_snapshot, run_trial


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
async def test_maximum_run_limit_terminates_gracefully(test_setup):
    """When max_runs=2 is reached without reaching sufficiency, trial terminates with limits_exhausted."""
    llm = test_setup["llm_client"]

    # Provide a Heimdall that always returns new evidence so it doesn't fail on novelty,
    # and let the sufficiency checker terminate when max_runs is hit.
    class ContinualResearchHeimdall(HeimdallAdapter):
        def retrieve_evidence(self, case_file, send_back=None, previous_evidence_ids=None, previous_evidence_hashes=None):
            docs, trade, _, hashes = super().retrieve_evidence(case_file, send_back, previous_evidence_ids, previous_evidence_hashes)
            run_n = send_back.iteration if send_back else 1
            new_id = f"NOVEL-DOC-RUN-{run_n}"
            docs[new_id] = Document(
                meta=DocMeta(DOC_ID=new_id, PUB_DATE="2027-01-20", RELIABILITY=2),
                paragraphs={1: f"Novel findings from run {run_n}"},
            )
            hashes[new_id] = f"hash-{run_n}"
            return docs, trade, [new_id], hashes

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        heimdall=ContinualResearchHeimdall(llm_client=llm),
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=2,
        builder=builder,
    )

    assert state.get("run_count") == 2
    assert state.get("overall_status") in ("terminated_limits_exhausted", "incomplete")
    assert state.get("sufficiency_result").status == SufficiencyStatus.LIMITS_EXHAUSTED


@pytest.mark.asyncio
async def test_evidence_novelty_rule_no_new_evidence_terminates_truthfully(test_setup):
    """If Heimdall re-search produces 0 qualifying new evidence, graph terminates truthfully without looping."""
    llm = test_setup["llm_client"]

    class StaleHeimdall(HeimdallAdapter):
        def retrieve_evidence(self, case_file, send_back=None, previous_evidence_ids=None, previous_evidence_hashes=None):
            docs, trade, new_ids, hashes = super().retrieve_evidence(case_file, send_back, previous_evidence_ids, previous_evidence_hashes)
            if send_back:
                # Re-search found only previously known evidence
                return docs, trade, [], hashes
            return docs, trade, new_ids, hashes

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        heimdall=StaleHeimdall(llm_client=llm),
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=3,
        builder=builder,
    )

    # Must terminate with incomplete status rather than looping to max_runs (3)
    assert state.get("overall_status") == "incomplete"
    assert "no qualifying new admissible evidence" in state.get("incomplete_reason", "").lower()
    assert state.get("new_evidence_count") == 0


@pytest.mark.asyncio
async def test_case_budget_exhaustion_terminates_safely(test_setup):
    """Token budget exhaustion terminates safely with incomplete status and preserves valid rulings."""
    llm = test_setup["llm_client"]
    # Pre-exhaust token budget
    llm.total_tokens_used = MAX_TOKENS_PER_CASE

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=2,
        builder=builder,
    )

    # Adjudication handled budget gracefully
    rulings = state.get("rulings", [])
    assert len(rulings) > 0
    # Eligible claims marked contested due to token_budget_exceeded
    assert any(r.disqualified_reason == "token_budget_exceeded" for r in rulings)


@pytest.mark.asyncio
async def test_tool_call_quota_exhaustion_terminates_safely(test_setup):
    """Tool-call quota exhaustion is handled safely without unbounded loops."""
    llm = test_setup["llm_client"]
    # Pre-exhaust Thor's tool calls
    llm.tool_call_counts[AgentRole.THOR.value] = MAX_TOOL_CALLS_PER_AGENT

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

    assert state.get("thor_failed") is True
    assert "ToolCallLimitExceededError" in str(state.get("errors", []))


@pytest.mark.asyncio
async def test_case_token_budget_does_not_reset_across_runs(test_setup):
    """Token budget must accumulate across send-back runs rather than resetting."""
    llm = test_setup["llm_client"]

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=test_setup["logbook"],
        memory_store=test_setup["memory_store"],
        output_dir=test_setup["output_dir"],
    )

    state = await run_trial(
        question="How exposed is Midgard?",
        max_runs=2,
        builder=builder,
    )

    history = state.get("run_history", [])
    if len(history) >= 2:
        assert history[1]["token_usage"] >= history[0]["token_usage"]


def test_snapshot_persistence_secret_redaction_and_failure(tmp_path):
    """Verify secrets are scrubbed in run snapshots and persistence errors raise RuntimeError."""
    test_state = {
        "case_id": "CASE-SNAP-SEC",
        "run_count": 1,
        "as_of": "2027-01-25",
        "evidence_ids": ["DOC-1"],
        "token_usage": 500,
        "overall_status": "in_progress",
        "errors": ["Leaked: api_key=sk-ant-secret1234567890abcdef1234567890"],
    }

    out_dir = str(tmp_path / "valid_cases")
    snap_path = persist_run_snapshot(test_state, output_dir=out_dir)
    assert os.path.exists(snap_path)

    with open(snap_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "sk-ant-" not in str(data)
    assert "[REDACTED" in str(data)

    # Persistence failure test: point to unwritable directory path
    invalid_file_as_dir = str(tmp_path / "plain_file.txt")
    with open(invalid_file_as_dir, "w") as f:
        f.write("I am a file, not a directory")

    with pytest.raises(RuntimeError, match="Failed to persist run snapshot"):
        persist_run_snapshot(test_state, output_dir=invalid_file_as_dir)


def test_cli_terminal_entry_point():
    """Verify python -m backend.trial executes and prints readable report."""
    cmd = [
        sys.executable,
        "-m",
        "backend.trial",
        "As of 25 January 2027, assess wheat exposure for Midgard",
        "--as-of",
        "2027-01-25",
        "--max-runs",
        "1",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd())
    assert res.returncode == 0
    assert "TRIAL OF THE NINE REALMS" in res.stdout
    assert "Event Verification:" in res.stdout
    assert "Runs Executed:" in res.stdout
    assert "FINAL TRIAL STATUS" in res.stdout
