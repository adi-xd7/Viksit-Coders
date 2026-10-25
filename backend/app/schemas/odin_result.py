"""Odin judicial adjudication result schemas."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.claim import ExposureEstimate
from backend.app.schemas.debate import Concession


class ClaimRuling(BaseModel):
    """Judicial evaluation and ruling on a material claim."""
    claim_id: str = Field(description="Traceable identifier of the evaluated claim, e.g. 'THOR-C01'")
    claim_statement: str = Field(description="The factual proposition or assertion evaluated")
    proponent: Literal["loki", "thor", "heimdall", "odin", "unknown"] = Field(
        default="unknown",
        description="Originating advocate or agent"
    )
    claim_type: Literal["sourced_fact", "inference"] = Field(
        default="sourced_fact",
        description="Distinction between sourced facts (directly stated) and inferences (derived by reasoning)"
    )
    ruling: Literal["established", "contested", "conceded"] = Field(
        description="Final judicial determination: established, contested, or conceded"
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score based on evidence quality and adversarial survival"
    )
    reasoning: str = Field(description="Concise evidence-grounded rationale for the ruling")
    supporting_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Admissible supporting citations verifying the claim"
    )
    contradicting_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Admissible counter-citations undermining or contradicting the claim"
    )
    loki_position: Optional[str] = Field(
        default=None,
        description="Loki's stance, attack, or concession regarding this claim"
    )
    thor_position: Optional[str] = Field(
        default=None,
        description="Thor's stance, attack, or concession regarding this claim"
    )
    concessions: list[Concession] = Field(
        default_factory=list,
        description="Formal concessions relevant to this claim"
    )
    is_conceded: bool = Field(default=False, description="True if formally conceded by an agent")
    conceded_by: Optional[Literal["loki", "thor"]] = Field(
        default=None,
        description="Agent that formally made the concession"
    )
    evidence_gaps: list[str] = Field(
        default_factory=list,
        description="Unresolved evidentiary gaps, limitations, or missing documentation"
    )
    discrepancy_notes: Optional[str] = Field(
        default=None,
        description="Notes on contradictions, retractions, clock violations, or adversarial traps"
    )
    adjudicated_range: Optional[ExposureEstimate] = Field(
        default=None,
        description="Validated or qualified quantitative exposure range, if applicable"
    )


class OdinResult(BaseModel):
    """The structured deliverable produced by Odin's final judicial adjudication engine."""
    agent: Literal["odin"] = "odin"
    case_id: str = Field(description="Unique case identifier")
    as_of_date: str = Field(description="Simulated clock cutoff in YYYY-MM-DD")
    run_number: int = Field(default=1, description="Trial run number (1 for initial run, 2 for sufficiency rerun)")
    adjudication_status: Literal["completed", "insufficient_evidence", "error"] = Field(
        default="completed",
        description="Overall status of judicial adjudication"
    )
    claim_rulings: list[ClaimRuling] = Field(
        default_factory=list,
        description="Itemized judicial rulings for every material claim"
    )
    established_claims: list[str] = Field(
        default_factory=list,
        description="IDs of claims ruled established"
    )
    contested_claims: list[str] = Field(
        default_factory=list,
        description="IDs of claims ruled contested"
    )
    conceded_claims: list[str] = Field(
        default_factory=list,
        description="IDs of claims ruled conceded"
    )
    unresolved_disputes: list[str] = Field(
        default_factory=list,
        description="Key factual or commercial disputes that remain unresolved by evidence"
    )
    evidence_limitations: list[str] = Field(
        default_factory=list,
        description="Identified evidence gaps, missing documentation, or reliability limitations"
    )
    evidence_examined: list[str] = Field(
        default_factory=list,
        description="All Runemark document IDs examined during adjudication"
    )
    is_evidence_sufficient: bool = Field(
        default=True,
        description="True if the evidentiary record is sufficient to substantiate the case findings"
    )
    summary: str = Field(description="Plain-language judicial summary of rulings and findings")
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if judicial adjudication failed"
    )
