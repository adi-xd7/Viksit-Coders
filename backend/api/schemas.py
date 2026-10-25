"""Public API request and response schemas for Odin Courtroom."""

from __future__ import annotations

import datetime
import re
from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from backend.models import Briefing, EventVerificationStatus, Ruling


class CreateCaseRequest(BaseModel):
    """Input payload to create a new supply-chain disruption case."""
    query: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Target question or disruption topic under investigation",
    )
    as_of: str = Field(
        ...,
        description="Cutoff as-of date (YYYY-MM-DD)",
    )
    case_id: Optional[str] = Field(
        None,
        max_length=64,
        description="Optional custom case ID (alphanumeric, dashes, underscores)",
    )
    target_country_sector_pairs: Optional[List[Tuple[str, str]]] = Field(
        default_factory=list,
        description="Optional pre-identified target country-sector pairs (e.g. [['Midgard', 'wheat']])",
    )

    @field_validator("as_of")
    @classmethod
    def validate_as_of_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"as_of date '{v}' must be in YYYY-MM-DD format.")
        try:
            datetime.date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"as_of date '{v}' is not a valid calendar date: {e}")
        return v

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^[A-Za-z0-9_\-]+$", v):
                raise ValueError(f"case_id '{v}' contains invalid characters. Must be alphanumeric with dashes/underscores.")
            if len(v) > 64:
                raise ValueError("case_id exceeds maximum length of 64 characters.")
        return v


class CaseResponse(BaseModel):
    """Safe public representation of an investigation case."""
    case_id: str
    query: str
    as_of: str
    verification_status: str
    verification_reason: Optional[str] = None
    target_country_sector_pairs: List[Tuple[str, str]] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


class CaseListResponse(BaseModel):
    """Paginated list of investigation cases."""
    items: List[CaseResponse]
    total: int
    limit: int
    offset: int


class StartTrialRequest(BaseModel):
    """Parameters to initiate a trial run."""
    max_runs: Optional[int] = Field(default=3, ge=1, le=5, description="Maximum send-back research runs")
    max_rounds: Optional[int] = Field(default=2, ge=1, le=4, description="Maximum cross-examination rounds")
    background: Optional[bool] = Field(default=False, description="Whether to execute as a background task")


class TrialStatusResponse(BaseModel):
    """Sanitized trial status projection without sensitive internal paths or prompts."""
    case_id: str
    trial_id: str
    status: str  # pending, running, completed, failed, awaiting_research, limits_exhausted, incomplete, event_not_real
    current_node: Optional[str] = None
    run_count: int = 1
    max_runs: int = 3
    start_time: str
    end_time: Optional[str] = None
    is_awaiting_research: bool = False
    is_completed: bool = False
    error_message: Optional[str] = None


class RulingsResponse(BaseModel):
    """Final Odin rulings for a completed trial."""
    case_id: str
    trial_id: str
    rulings_count: int
    rulings: List[Ruling]


class HealthResponse(BaseModel):
    """API process and database dependency health report."""
    status: str = "ok"  # ok or degraded
    version: str = "1.0.0"
    process: str = "healthy"
    database: str = "healthy"  # healthy or unhealthy
    timestamp: str


class ErrorResponse(BaseModel):
    """Standardized sanitized error envelope."""
    error: str
    message: str
    details: Optional[Any] = None
