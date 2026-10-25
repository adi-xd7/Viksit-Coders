"""Heimdall pre-debate verification result schemas."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.evidence import EvidenceReference


class PremiseVerification(BaseModel):
    """Verification analysis for a specific material factual premise."""
    premise_id: str = Field(description="Unique premise identifier, e.g. 'HEIM-P01'")
    premise: str = Field(description="The factual proposition being tested")
    status: Literal["verified", "contradicted", "unverified", "inadmissible"] = Field(
        description="Evidentiary classification of the premise"
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Calibrated confidence score")
    reasoning: str = Field(description="Analytical explanation of evidentiary findings")
    citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Admissible supporting evidence citations"
    )
    contradicting_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Admissible evidence contradicting the premise"
    )
    discrepancy_notes: Optional[str] = Field(
        default=None,
        description="Explanation of material discrepancies or fake decoy retractions"
    )


class HeimdallVerificationResult(BaseModel):
    """The structured deliverable produced by Heimdall's pre-debate verification gate."""
    agent: Literal["heimdall"] = "heimdall"
    case_id: str = Field(description="Unique case identifier")
    as_of_date: str = Field(description="Simulated clock cutoff in YYYY-MM-DD")
    event_id: Optional[str] = Field(default=None, description="Event ID, e.g. 'E5'")
    is_event_real: bool = Field(description="True if the core disruption event is verified and active")
    verification_status: Literal["verified", "contradicted", "unverified", "error"] = Field(
        description="Overall gate determination"
    )
    premises: list[PremiseVerification] = Field(
        default_factory=list,
        description="Itemized verification for each foundational premise"
    )
    unverified_premises: list[str] = Field(
        default_factory=list,
        description="List of premise IDs or summaries that could not be verified"
    )
    contradicted_premises: list[str] = Field(
        default_factory=list,
        description="List of premise IDs or summaries that were contradicted"
    )
    evidence_examined: list[str] = Field(
        default_factory=list,
        description="Document IDs examined during verification"
    )
    summary: str = Field(description="Plain-language executive summary of verification findings")
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if verification execution failed"
    )
