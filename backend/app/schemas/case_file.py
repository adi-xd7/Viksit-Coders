"""Shared CaseFile schema coordinating the multi-agent courtroom trial."""

from typing import Optional
from pydantic import BaseModel, Field
from backend.app.schemas.claim import Claim
from backend.app.schemas.debate import CrossExamination, Concession


class CaseFile(BaseModel):
    """The central shared artifact across Heimdall, Thor, Loki, and Odin."""
    case_id: str = Field(description="Unique case identifier, e.g. 'CASE-E5'")
    question: str = Field(description="The target disruption question")
    as_of_date: str = Field(description="Simulated clock cutoff in YYYY-MM-DD")
    is_verified: bool = Field(default=True, description="True if Heimdall verified the event is real")
    event_id: Optional[str] = Field(default=None, description="Event ID, e.g. 'E5'")
    round_number: int = Field(default=1, description="Current trial round (1 or 2)")
    run_number: int = Field(default=1, description="Current trial run (1 or 2)")
    claims: list[Claim] = Field(default_factory=list, description="All submitted claims from Thor and Loki")
    attacks: list[CrossExamination] = Field(default_factory=list, description="All cross-examination attacks")
    concessions: list[Concession] = Field(default_factory=list, description="All concessions made by agents")
    judicial_rulings: list[dict] = Field(default_factory=list, description="Rulings issued by Odin")
