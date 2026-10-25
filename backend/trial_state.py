"""Trial state definition for LangGraph trial orchestration.

Compatible with LangGraph 1.2+ typed state and Pydantic v2 domain models.
Preserves complete case history, evidence hashes, disjoint advocate updates,
Odin rulings, and resource budget states across trial runs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
from typing_extensions import TypedDict

from backend.models import (
    Attack,
    CaseFile,
    Citation,
    Claim,
    Concession,
    Defense,
    Document,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    SendBack,
    SufficiencyResult,
    TradeRow,
)


class TrialState(TypedDict, total=False):
    """LangGraph state schema for the Trial of the Nine Realms courtroom graph."""

    # Case identifiers and query parameters
    case_id: str
    question: str
    as_of: str
    case_file: Optional[CaseFile]
    event_verification: Optional[EventVerificationStatus]

    # Run and round counters
    run_count: int
    max_runs: int
    round_count: int
    max_rounds: int
    current_node: str

    # Evidence stores and provenance tracking
    doc_store: Dict[str, Document]
    trade_store: Dict[str, List[TradeRow]]
    evidence_ids: List[str]
    evidence_hashes: Dict[str, str]
    previous_evidence_ids: List[str]
    previous_evidence_hashes: Dict[str, str]
    new_evidence_count: int

    # Disjoint parallel advocate updates (prevents merge overwrites)
    thor_claims: List[Claim]
    loki_claims: List[Claim]
    claims: List[Claim]

    # Cross-examination records
    attacks: List[Attack]
    defenses: List[Defense]
    concessions: List[Concession]

    # Judicial adjudication and sufficiency
    rulings: List[Ruling]
    exposure_ranges: List[ExposureRange]
    sufficiency_result: Optional[SufficiencyResult]
    send_back: Optional[SendBack]

    # Historical runs and resource accounting
    run_history: List[Dict[str, Any]]
    token_usage: int
    tool_call_counts: Dict[str, int]

    # Overall execution status and diagnostics
    overall_status: str  # "ready_for_briefing", "incomplete", "insufficient", "terminated_limits_exhausted", "event_not_real", "error"
    incomplete_reason: Optional[str]
    errors: List[str]
    thor_failed: bool
    loki_failed: bool
    persisted_snapshot_path: Optional[str]
    briefing: Optional[Any]  # Briefing
    persisted_briefing_path: Optional[str]
