"""Schemas for the Multi-Trial Sufficiency Feedback Loop (Part 6B)."""

from typing import Literal, Optional, Any
from pydantic import BaseModel, Field

from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.loki_result import LokiResult
from backend.app.schemas.thor_result import ThorResult
from backend.app.schemas.heimdall_result import HeimdallVerificationResult
from backend.app.schemas.odin_result import OdinResult

LoopStopReason = Literal[
    "evidence_sufficient",
    "max_retries_exhausted",
    "no_actionable_gaps",
    "no_new_evidence",
    "validation_failure",
    "heimdall_gate_rejected",
    "agent_failure",
]


class TargetedRetrievalTask(BaseModel):
    """A targeted retrieval task formulated from an identified evidence gap or dispute."""
    task_id: str = Field(description="Unique task identifier, e.g. 'TASK-R02-01'")
    target_gap: str = Field(description="The specific evidentiary gap or dispute being addressed")
    target_claim_id: Optional[str] = Field(default=None, description="The claim ID associated with the gap, if any")
    query: str = Field(description="Targeted search query executed against the corpus")
    filters: dict[str, Any] = Field(default_factory=dict, description="Metadata filters applied to the query")
    retrieved_doc_ids: list[str] = Field(default_factory=list, description="IDs of documents retrieved by this task")
    admissible_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Admissible citations discovered by this task"
    )
    inadmissible_citations: list[str] = Field(
        default_factory=list,
        description="Notes on inadmissible citations (clock violations, retractions) rejected"
    )
    resolved: bool = Field(default=False, description="True if task yielded new admissible evidence")
    notes: Optional[str] = Field(default=None, description="Diagnostic notes or commentary")


class TrialRecord(BaseModel):
    """Audit record capturing the full execution deliverables of a single debate trial."""
    trial_number: int = Field(description="1-indexed trial number (1 = initial trial, 2+ = retries)")
    status: Literal["success", "partial", "error"] = Field(description="Trial execution status")
    failed_stage: Optional[str] = Field(default=None, description="Stage that failed if an error occurred")
    error_message: Optional[str] = Field(default=None, description="Error message if trial failed")
    heimdall_verification: Optional[HeimdallVerificationResult] = Field(
        default=None,
        description="Heimdall verification result for this trial"
    )
    loki_round1: Optional[LokiResult] = Field(default=None, description="Loki Round 1 output")
    thor_round1: Optional[ThorResult] = Field(default=None, description="Thor Round 1 output")
    loki_round2: Optional[LokiResult] = Field(default=None, description="Loki Round 2 output")
    thor_round2: Optional[ThorResult] = Field(default=None, description="Thor Round 2 output")
    odin_adjudication: Optional[OdinResult] = Field(default=None, description="Odin judicial ruling for this trial")
    is_evidence_sufficient: bool = Field(default=False, description="Odin's evidence sufficiency determination")
    evidence_gaps_identified: list[str] = Field(
        default_factory=list,
        description="Evidence gaps identified by Odin in this trial"
    )
    unresolved_disputes: list[str] = Field(
        default_factory=list,
        description="Unresolved contradictory claims preserved in this trial"
    )
    targeted_tasks_generated: list[TargetedRetrievalTask] = Field(
        default_factory=list,
        description="Targeted retrieval tasks generated from gaps in this trial"
    )
    new_evidence_discovered: list[EvidenceReference] = Field(
        default_factory=list,
        description="New admissible evidence discovered prior to the next trial"
    )
    gap_resolution_summary: Optional[str] = Field(
        default=None,
        description="Summary of whether this trial resolved, reduced, or failed to improve gaps"
    )
