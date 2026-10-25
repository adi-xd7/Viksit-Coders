"""Executive briefing schema for the RAGNAROK PS3 Supply Chain Disruption Analyzer."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

from backend.app.schemas.odin_result import ClaimRuling


class TimelineEvent(BaseModel):
    """A chronologically positioned factual disruption event."""
    event_date: str = Field(description="Date in YYYY-MM-DD")
    description: str = Field(description="Description of the factual event")
    supporting_doc_id: Optional[str] = Field(default=None, description="Document ID corroborating the date/event")
    source_name: Optional[str] = Field(default=None, description="Publisher or reporting agency")
    reliability_tier: Optional[int] = Field(default=None, ge=1, le=4, description="Reliability tier (1-4)")


class ExposureComparisonRow(BaseModel):
    """Comparative exposure evaluation row contrasting Thor, Loki, and Odin's ruling."""
    country: str = Field(description="Affected country, e.g. 'Midgard', 'Tolan'")
    sector: str = Field(description="Affected commodity or sector, e.g. 'Wheat', 'Maize'")
    metric: str = Field(description="Impact metric name, e.g. 'net_value_loss_pct'")
    unit: str = Field(default="%", description="Measurement unit ('%', 'USD M', 'tonnes')")
    period: str = Field(default="2026-Q4", description="Disruption impact time horizon")
    thor_range: Optional[str] = Field(default=None, description="Thor's high-exposure assertion range")
    loki_range: Optional[str] = Field(default=None, description="Loki's low-exposure assertion range")
    odin_adjudicated_range: Optional[str] = Field(
        default=None,
        description="Odin's authoritative adjudicated range or 'Contested'"
    )
    odin_status: Literal["established", "contested", "conceded", "unsupported"] = Field(
        default="established",
        description="Odin's ruling status on this exposure metric"
    )
    baseline_or_denominator: Optional[str] = Field(
        default=None,
        description="Baseline volume or trade value denominator used for calculation"
    )
    calculation_methodology: Optional[str] = Field(
        default=None,
        description="Specific calculation methodology or formulas applied"
    )
    key_assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions grounding the range"
    )


class ConcessionSummary(BaseModel):
    """Summary of a formal courtroom concession made during adversarial debate."""
    concession_id: str = Field(description="Unique concession identifier, e.g. 'THOR-CON01'")
    advocate: Literal["loki", "thor"] = Field(description="Advocate that made the concession")
    target_claim_id: str = Field(description="Target claim ID being conceded or revised")
    action: Literal["concede", "defend", "adjust_range"] = Field(description="Concession action taken")
    reason: str = Field(description="Evidence-grounded rationale for the concession")
    adjusted_range_str: Optional[str] = Field(
        default=None,
        description="Adjusted numerical bounds if action is adjust_range"
    )


class CitedSourceProvenance(BaseModel):
    """Itemized bibliographic reference providing full provenance for factual statements."""
    doc_id: str = Field(description="Runemark document ID, e.g. 'ORV-0016'")
    paragraph: Optional[str] = Field(default=None, description="Specific paragraph, e.g. 'P2'")
    source_name: Optional[str] = Field(default=None, description="Name of the outlet or agency")
    reliability_tier: Optional[int] = Field(default=None, ge=1, le=4, description="Credibility tier (1-4)")
    publication_date: Optional[str] = Field(default=None, description="Publication date in YYYY-MM-DD")
    pub_time: Optional[str] = Field(default=None, description="Publication time in HH:MM")
    quote_or_datapoint: str = Field(description="Exact excerpt or quantitative datum cited")
    is_off_runemark: bool = Field(default=False, description="Flag for off-Runemark sources")


class ExecutiveBriefing(BaseModel):
    """Structured, human-readable, evidence-grounded executive briefing deliverable."""
    case_id: str = Field(description="Unique case identifier")
    as_of_date: str = Field(description="Simulated clock cutoff in YYYY-MM-DD")
    event_id: Optional[str] = Field(default=None, description="Event ID, e.g. 'E5'")
    question: str = Field(description="Target decision-maker disruption question")
    title: str = Field(description="Concise briefing title")
    status: Literal["completed", "insufficient_evidence", "insufficient_input", "error"] = Field(
        default="completed",
        description="Overall briefing completion status"
    )
    generated_at: str = Field(description="Generation timestamp in ISO format")

    # Executive Summary & Foundations
    executive_summary: str = Field(description="Nontechnical executive summary synthesising key findings")
    event_verified: bool = Field(description="Whether the core disruption event was verified by Heimdall")
    verification_summary: str = Field(description="Heimdall's foundational verification summary")
    confirmed_disruption_facts: list[str] = Field(
        default_factory=list,
        description="Bulleted core factual statements verified by evidence"
    )

    # Disruption Context & Scope
    timeline: list[TimelineEvent] = Field(
        default_factory=list,
        description="Chronological sequence of verified disruption milestones"
    )
    affected_regions: list[str] = Field(
        default_factory=list,
        description="Countries and territories impacted by the disruption"
    )
    affected_sectors: list[str] = Field(
        default_factory=list,
        description="Commodities and industrial sectors impacted"
    )
    affected_trade_routes: list[str] = Field(
        default_factory=list,
        description="Maritime, canal, or rail trade corridors affected"
    )
    key_stakeholders: list[str] = Field(
        default_factory=list,
        description="Governments, authorities, and major commercial entities involved"
    )

    # Quantitative Exposure Comparison
    exposure_table: list[ExposureComparisonRow] = Field(
        default_factory=list,
        description="Comparative exposure table contrasting Thor, Loki, and Odin's ruling"
    )
    quantitative_summary: str = Field(
        description="Narrative detailing exposure bounds, baselines, and methodology"
    )

    # Adjudicated Claims & Disputes
    established_claims: list[ClaimRuling] = Field(
        default_factory=list,
        description="Material claims ruled established by Odin"
    )
    contested_claims: list[ClaimRuling] = Field(
        default_factory=list,
        description="Claims ruled contested due to unresolved disputes or thin evidence"
    )
    concessions: list[ConcessionSummary] = Field(
        default_factory=list,
        description="Formal concessions made during adversarial debate"
    )
    unresolved_disputes: list[str] = Field(
        default_factory=list,
        description="Explicit disputes that could not be reconciled by available evidence"
    )

    # Evidentiary Confidence & Limitations
    overall_confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score across established findings"
    )
    confidence_assessment: Literal["high", "moderate", "low", "unsubstantiated"] = Field(
        default="moderate",
        description="Qualitative confidence assessment"
    )
    is_evidence_sufficient: bool = Field(
        default=True,
        description="Whether the evidentiary record was ruled sufficient by Odin"
    )
    evidence_limitations: list[str] = Field(
        default_factory=list,
        description="Evidentiary limitations, missing baseline documents, or gaps"
    )
    key_uncertainties: list[str] = Field(
        default_factory=list,
        description="Material commercial and operational uncertainties identified"
    )

    # Forward Outlook & Recommendations
    next_quarter_outlook: str = Field(
        description="Forward-looking operational outlook based strictly on substantiated findings"
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Evidence-backed strategic and operational recommended actions"
    )
    recommendations_qualified: bool = Field(
        default=True,
        description="Flag indicating recommendations are qualified by data limitations"
    )

    # Bibliography & Trial Audit Trace
    cited_sources: list[CitedSourceProvenance] = Field(
        default_factory=list,
        description="Traceable citations for all material factual statements"
    )
    total_trials: int = Field(default=1, description="Total debate trials executed")
    retries_attempted: int = Field(default=0, description="Additional retries attempted")
    max_retries: int = Field(default=2, description="Configured maximum retries")
    loop_stop_reason: Optional[str] = Field(
        default=None,
        description="Explicit feedback-loop stop reason"
    )
    trial_progression_summary: list[str] = Field(
        default_factory=list,
        description="Audit trace of trial-by-trial developments and gap resolutions"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Diagnostic error message if briefing generation or input had an error"
    )
