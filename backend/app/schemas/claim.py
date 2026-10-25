"""Claim and Exposure schemas for adversarial courtroom agents."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.evidence import EvidenceReference


class ExposureEstimate(BaseModel):
    """Deterministic exposure bound with explicit country, sector, metric, and unit."""
    country: str = Field(description="Target nation, e.g. 'Midgard', 'Tolan'")
    sector: str = Field(description="Target commodity or sector, e.g. 'Wheat', 'Maize'")
    metric: str = Field(description="Metric name, e.g. 'net_value_loss_pct', 'volume_shortfall_tonnes'")
    min_estimate: float = Field(description="Lower bound of estimate")
    max_estimate: float = Field(description="Upper bound of estimate")
    unit: str = Field(default="%", description="Measurement unit ('%', 'USD M', 'tonnes')")
    period: str = Field(default="2026-Q4", description="Applicable time period")
    assumptions: list[str] = Field(default_factory=list, description="Explicit modeling assumptions")

    def format_range(self) -> str:
        return f"{self.country} {self.sector} ({self.metric}): {self.min_estimate:.1f} - {self.max_estimate:.1f} {self.unit} [{self.period}]"


class Claim(BaseModel):
    """An adversarial argument backed by document citations and numerical bounds."""
    claim_id: str = Field(description="Unique claim identifier, e.g. 'LOKI-C01'")
    agent: Literal["loki", "thor", "heimdall", "odin"] = Field(description="Originating agent")
    stance: Literal["limited_exposure", "high_exposure", "neutral"] = Field(description="Advocacy stance")
    claim_type: Literal["sourced_fact", "inference"] = Field(description="Fact vs reasoning classification")
    statement: str = Field(description="Core assertion in clear plain language")
    reasoning: str = Field(description="Analytical justification linking evidence to claim")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Calibrated confidence score (0.0 to 1.0)")
    estimates: list[ExposureEstimate] = Field(default_factory=list, description="Quantitative exposure estimates")
    citations: list[EvidenceReference] = Field(default_factory=list, description="Runemark document citations")
    is_unsupported: bool = Field(default=False, description="Flagged true if evidence is missing or thin")
