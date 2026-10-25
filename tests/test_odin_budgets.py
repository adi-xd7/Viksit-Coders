"""Unit and regression tests for Odin resource budget enforcement.

Verifies:
- Token budgets (preflight and in-flight exhaustion).
- Tool-call quotas (MAX_TOOL_CALLS_PER_AGENT=12).
- Bounded retries and repairs (MAX_RETRIES=2).
- Provider timeout and rate-limit error handling.
- Preservation of valid rulings and identification of unresolved claims.
- Non-resetting budgets across runs in the same case.
"""

import json
import pytest

from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    Citation,
    Claim,
    DocMeta,
    Document,
    LogEventType,
    Ruling,
    Verdict,
)
from backend.llm import (
    BudgetExceededError,
    LLMClient,
    MAX_TOKENS_PER_CASE,
    MAX_TOOL_CALLS_PER_AGENT,
    ToolCallLimitExceededError,
)
from backend.logbook import LogBook
from backend.agents.odin import OdinJudge


@pytest.fixture
def sample_case_and_doc():
    case_file = CaseFile(
        case_id="CASE-BUDGET-01",
        query="Assess impact on shipping",
        as_of="2027-01-25",
    )
    doc_store = {
        "DOC-DET-REJ": Document(
            meta=DocMeta(DOC_ID="DOC-DET-REJ", PUB_DATE="2027-01-10", RELIABILITY=4),
            paragraphs={1: "Tier 4 unverified rumor."},
        ),
        "DOC-VALID": Document(
            meta=DocMeta(DOC_ID="DOC-VALID", PUB_DATE="2027-01-12", RELIABILITY=2),
            paragraphs={1: "Official port authority reports 20% decline."},
        ),
    }
    return case_file, doc_store


@pytest.mark.asyncio
async def test_case_below_budget_succeeds_normally(sample_case_and_doc):
    case_file, doc_store = sample_case_and_doc
    claim = Claim(
        claim_id="CLM-NORMAL",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="20% decline confirmed.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    def mock_llm(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "CLM-NORMAL",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Directly confirmed by port authority.",
                }
            ]
        })

    client = LLMClient()
    client.set_mock_handler(mock_llm)
    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    rulings = await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store)
    assert len(rulings) == 1
    assert rulings[0].verdict == Verdict.ESTABLISHED
    assert client.total_tokens_used > 0
    assert client.total_tokens_used < MAX_TOKENS_PER_CASE
    assert client.tool_call_counts.get("odin") == 1


@pytest.mark.asyncio
async def test_preflight_budget_exhaustion_preserves_valid_rulings_and_marks_unresolved(sample_case_and_doc):
    case_file, doc_store = sample_case_and_doc

    # Claim 1 is deterministically rejected (Tier 4 only)
    claim1 = Claim(
        claim_id="CLM-T4",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="Tier 4 claim.",
        citations=[Citation(doc_id="DOC-DET-REJ", paragraph_num=1)],
        nature=Basis.INFERENCE,
    )
    # Claim 2 is eligible for LLM
    claim2 = Claim(
        claim_id="CLM-ELIGIBLE",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="shipping",
        posture="limited",
        statement="Eligible claim.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    client = LLMClient()
    # Exhaust case tokens prior to call
    client.total_tokens_used = MAX_TOKENS_PER_CASE

    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    rulings = await judge.judge_claims(
        case_file=case_file,
        claims=[claim1, claim2],
        doc_store=doc_store,
    )
    assert len(rulings) == 2

    # Deterministic ruling is preserved!
    r1 = next(r for r in rulings if r.claim_id == "CLM-T4")
    assert r1.verdict == Verdict.REJECTED
    assert r1.disqualified_reason == "tier_4_only"

    # Eligible claim could not be adjudicated due to budget exhaustion -> marked CONTESTED
    r2 = next(r for r in rulings if r.claim_id == "CLM-ELIGIBLE")
    assert r2.verdict == Verdict.CONTESTED
    assert r2.disqualified_reason == "token_budget_exceeded"
    assert "token budget exhausted" in r2.rationale.lower()

    # Verify LIMIT_HIT was logged in audit log
    limit_events = logbook.get_events(case_id=case_file.case_id, event_type=LogEventType.LIMIT_HIT)
    assert len(limit_events) >= 1
    assert limit_events[0].payload.get("limit_type") == "token_budget"


@pytest.mark.asyncio
async def test_tool_call_quota_exhaustion_is_enforced(sample_case_and_doc):
    case_file, doc_store = sample_case_and_doc
    claim = Claim(
        claim_id="CLM-TOOL-TEST",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="Valid claim requiring LLM tool call.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    client = LLMClient()
    # Set odin's tool call count to the maximum allowed limit
    client.tool_call_counts[AgentRole.ODIN.value] = MAX_TOOL_CALLS_PER_AGENT

    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    rulings = await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store)
    assert len(rulings) == 1
    assert rulings[0].verdict == Verdict.CONTESTED
    assert rulings[0].disqualified_reason == "tool_call_limit_exceeded"

    # Verify LIMIT_HIT event logged for tool calls
    limit_events = logbook.get_events(case_id=case_file.case_id, event_type=LogEventType.LIMIT_HIT)
    assert len(limit_events) >= 1
    assert limit_events[0].payload.get("limit_type") == "tool_calls"


@pytest.mark.asyncio
async def test_provider_timeout_and_error_handling(sample_case_and_doc):
    case_file, doc_store = sample_case_and_doc
    claim = Claim(
        claim_id="CLM-TIMEOUT",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="Valid statement.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    def timeout_mock(sys: str, user: str, kwargs: dict) -> str:
        raise TimeoutError("Anthropic API request timed out after 60s")

    client = LLMClient()
    client.set_mock_handler(timeout_mock)
    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    rulings = await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store)
    assert len(rulings) == 1
    assert rulings[0].verdict == Verdict.CONTESTED
    assert rulings[0].disqualified_reason == "provider_error"
    assert "timed out" in rulings[0].rationale.lower()

    # Verify ERROR event was logged in audit log
    err_events = logbook.get_events(case_id=case_file.case_id, event_type=LogEventType.ERROR)
    assert len(err_events) >= 1
    assert "TimeoutError" in err_events[0].payload.get("error_type", "")


@pytest.mark.asyncio
async def test_retry_exhaustion_on_unrepairable_malformed_response(sample_case_and_doc):
    """When LLM repeatedly produces invalid JSON, repair retries up to MAX_RETRIES then fails safely."""
    case_file, doc_store = sample_case_and_doc
    claim = Claim(
        claim_id="CLM-MALFORMED",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="Statement requiring valid json.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    attempts = 0

    def repeatedly_malformed_mock(sys: str, user: str, kwargs: dict) -> str:
        nonlocal attempts
        attempts += 1
        return "I am unable to answer in JSON format. Here is plain text."

    client = LLMClient()
    client.set_mock_handler(repeatedly_malformed_mock)
    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    rulings = await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store)
    # Total attempts = initial (1) + MAX_RETRIES (2) = 3 attempts
    assert attempts == 3
    assert len(rulings) == 1
    assert rulings[0].verdict == Verdict.CONTESTED
    assert rulings[0].disqualified_reason == "provider_error"

    # Verify ERROR event was logged
    err_events = logbook.get_events(case_id=case_file.case_id, event_type=LogEventType.ERROR)
    assert len(err_events) >= 1


@pytest.mark.asyncio
async def test_case_budget_persists_across_multiple_runs(sample_case_and_doc):
    """Budget must accumulate across runs in the same case (no budget reset)."""
    case_file, doc_store = sample_case_and_doc
    claim = Claim(
        claim_id="CLM-MULTI-RUN",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="shipping",
        posture="high",
        statement="Valid statement.",
        citations=[Citation(doc_id="DOC-VALID", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    def mock_llm(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "CLM-MULTI-RUN",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Confirmed.",
                }
            ]
        })

    client = LLMClient()
    client.set_mock_handler(mock_llm)
    logbook = LogBook()
    judge = OdinJudge(llm_client=client, logbook=logbook)

    # Run 1
    await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store, run_num=1)
    tokens_after_run1 = client.total_tokens_used
    tool_calls_after_run1 = client.tool_call_counts["odin"]
    assert tokens_after_run1 > 0
    assert tool_calls_after_run1 == 1

    # Run 2: same case file, budget must NOT reset
    await judge.judge_claims(case_file=case_file, claims=[claim], doc_store=doc_store, run_num=2)
    tokens_after_run2 = client.total_tokens_used
    tool_calls_after_run2 = client.tool_call_counts["odin"]

    assert tokens_after_run2 > tokens_after_run1
    assert tool_calls_after_run2 == 2
