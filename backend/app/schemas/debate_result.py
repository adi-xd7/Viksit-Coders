"""Debate orchestration result schema coordinating Thor and Loki."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.loki_result import LokiResult
from backend.app.schemas.thor_result import ThorResult
from backend.app.schemas.claim import Claim
from backend.app.schemas.debate import CrossExamination, Concession


class DebateResult(BaseModel):
    """Deliverable produced by the Multi-Agent Debate Orchestrator."""
    case_id: str = Field(description="Unique case identifier")
    as_of_date: str = Field(description="Simulated clock cutoff in YYYY-MM-DD")
    run_number: int = Field(default=1, description="Trial run number (1 for initial debate, 2 for sufficiency rerun)")
    status: Literal["success", "partial", "error"] = Field(
        default="success",
        description="Overall debate orchestration status"
    )
    failed_stage: Optional[str] = Field(
        default=None,
        description="Name of the stage that failed if an error occurred"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Diagnostic error message if an agent or stage failed"
    )
    loki_round1: Optional[LokiResult] = Field(
        default=None,
        description="Loki's initial analysis & Round 1 low-exposure claims"
    )
    thor_round1: Optional[ThorResult] = Field(
        default=None,
        description="Thor's independent Round 1 investigation & high-exposure claims"
    )
    loki_round2: Optional[LokiResult] = Field(
        default=None,
        description="Loki's Round 2 cross-examination attacks against Thor and justified concessions"
    )
    thor_round2: Optional[ThorResult] = Field(
        default=None,
        description="Thor's Round 2 cross-examination attacks against Loki and formal concessions"
    )
    case_file: CaseFile = Field(
        description="The final coordinated CaseFile containing all claims, attacks, and concessions"
    )
    stages_executed: list[str] = Field(
        default_factory=list,
        description="Ordered audit log of orchestration stages completed"
    )

    @property
    def claims(self) -> list[Claim]:
        """All submitted claims across Thor and Loki."""
        return self.case_file.claims

    @property
    def attacks(self) -> list[CrossExamination]:
        """All cross-examination attacks launched across Thor and Loki."""
        return self.case_file.attacks

    @property
    def concessions(self) -> list[Concession]:
        """All concessions made across Thor and Loki."""
        return self.case_file.concessions

    @property
    def uncertainties(self) -> list[str]:
        """Aggregated uncertainties reported by both agents."""
        unc: list[str] = []
        for r in [self.loki_round1, self.thor_round1, self.loki_round2, self.thor_round2]:
            if r and hasattr(r, "uncertainties"):
                unc.extend(r.uncertainties)
        return unc
