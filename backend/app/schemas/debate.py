"""Debate interaction schemas: Cross-examination attacks and concessions."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.claim import ExposureEstimate


class CrossExamination(BaseModel):
    """An adversarial challenge attacking an opponent's claim."""
    challenge_id: str = Field(description="Unique challenge identifier, e.g. 'LOKI-X01'")
    challenger: Literal["loki", "thor"] = Field(description="Agent launching the challenge")
    target_claim_id: str = Field(description="ID of the contested claim, e.g. 'THOR-C02'")
    challenge_type: Literal[
        "unreliable_source",
        "clock_violation",
        "contradiction",
        "omitted_substitution",
        "unsupported_inference",
        "prompt_injection_trap",
        "no_counter_evidence"
    ] = Field(description="Specific categorization of the flaw")
    objection: str = Field(description="Summary of the objection")
    reasoning: str = Field(description="Detailed critique of opponent's logic or sources")
    counter_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="Documents proving the opponent's claim is flawed or incomplete"
    )


class Concession(BaseModel):
    """Formal acknowledgement or revision of an argument under adversarial challenge."""
    concession_id: str = Field(description="Unique concession identifier, e.g. 'LOKI-CON01'")
    agent: Literal["loki", "thor"] = Field(description="Agent making the concession")
    target_challenge_id: Optional[str] = Field(default=None, description="Challenge being responded to")
    target_claim_id: str = Field(description="Claim being conceded or defended")
    action: Literal["concede", "defend", "adjust_range"] = Field(description="Action taken")
    reason: str = Field(description="Document-grounded rationale for conceding or defending")
    adjusted_estimates: list[ExposureEstimate] = Field(
        default_factory=list,
        description="Revised numerical range if adjusted"
    )
    defence_citations: list[EvidenceReference] = Field(
        default_factory=list,
        description="New supporting evidence if defending"
    )
