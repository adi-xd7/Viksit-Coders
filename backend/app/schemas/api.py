"""API request and response schemas for RAGNAROK PS3 FastAPI server layer."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check status response."""
    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        default="healthy",
        description="Overall service health status"
    )
    service: str = Field(
        default="ragnarok-ps3-courtroom",
        description="Service name"
    )
    version: str = Field(
        default="1.0.0",
        description="API and engine version"
    )
    timestamp: str = Field(description="ISO UTC timestamp")
    corpus_available: bool = Field(
        default=False,
        description="True if Runemark dev_pack_E5 corpus directory is accessible"
    )
    storage_type: str = Field(
        default="in_memory",
        description="Case persistence backend type"
    )


class CaseCreateRequest(BaseModel):
    """Payload for registering a new disruption case."""
    case_id: str = Field(
        description="Unique case identifier, e.g. 'CASE-E5'",
        min_length=1,
    )
    question: str = Field(
        description="User disruption question",
        min_length=1,
    )
    as_of_date: str = Field(
        description="Simulated clock cutoff in YYYY-MM-DD format",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    event_id: Optional[str] = Field(
        default=None,
        description="Optional event identifier, e.g. 'E5'",
    )
    is_verified: bool = Field(
        default=True,
        description="Initial verification flag before Heimdall analysis",
    )


class DebateRunRequest(BaseModel):
    """Configuration options for running an adversarial debate trial."""
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=5,
        description="Maximum additional retry trials for sufficiency feedback loop (default: 2)",
    )


class CaseSummaryResponse(BaseModel):
    """Brief summary of a registered case and its analysis status."""
    case_id: str = Field(description="Case identifier")
    question: str = Field(description="Target disruption inquiry")
    as_of_date: str = Field(description="Cutoff date in YYYY-MM-DD")
    event_id: Optional[str] = Field(default=None, description="Event ID if specified")
    has_debate_result: bool = Field(default=False, description="True if debate has been executed")
    has_briefing: bool = Field(default=False, description="True if executive briefing is available")
    debate_status: Optional[str] = Field(default=None, description="Debate status ('success', 'error', 'partial')")
    is_evidence_sufficient: Optional[bool] = Field(
        default=None,
        description="Odin's final evidence sufficiency determination"
    )


class ErrorResponse(BaseModel):
    """Structured error deliverable."""
    detail: str = Field(description="Human-readable error diagnostic")
    error_code: Optional[str] = Field(default=None, description="Machine-readable error classification code")
    case_id: Optional[str] = Field(default=None, description="Associated case ID if applicable")
