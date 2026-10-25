"""Loki's structured result output schema."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.claim import Claim
from backend.app.schemas.debate import CrossExamination, Concession


class LokiResult(BaseModel):
    """The structured deliverable returned by Loki for each round and run."""
    agent: Literal["loki"] = "loki"
    case_id: str
    as_of_date: str
    round_number: int
    run_number: int
    claims: list[Claim] = Field(default_factory=list, description="Loki's low-exposure claims")
    attacks: list[CrossExamination] = Field(default_factory=list, description="Loki's challenges against Thor")
    concessions: list[Concession] = Field(default_factory=list, description="Loki's formal concessions")
    uncertainties: list[str] = Field(default_factory=list, description="Explicitly documented data gaps")
    memory_used: list[str] = Field(default_factory=list, description="Provenance IDs of private memory utilized")
    search_log: list[dict] = Field(default_factory=list, description="Audit log of search queries and results")
    status: Literal["success", "partial", "error"] = "success"
    error_message: Optional[str] = None
