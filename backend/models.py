"""Shared Pydantic models for Trial of the Nine Realms.

Defines the contract between Heimdall, Thor, Loki, and Odin.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    ESTABLISHED = "established"
    CONTESTED = "contested"
    CONCEDED = "conceded"
    REJECTED = "rejected"


class Basis(str, Enum):
    SOURCED_FACT = "sourced_fact"
    INFERENCE = "inference"


class AgentRole(str, Enum):
    HEIMDALL = "heimdall"
    THOR = "thor"
    LOKI = "loki"
    ODIN = "odin"


class EventVerificationStatus(str, Enum):
    REAL = "real"
    UNCERTAIN = "uncertain"
    NOT_REAL = "not_real"


class Citation(BaseModel):
    doc_id: str
    paragraph_num: Optional[int] = None
    trade_row_ref: Optional[str] = None  # e.g., "TAB-001#5"
    quoted_text: Optional[str] = None
    pub_date: Optional[str] = None  # Optional cited publication date (YYYY-MM-DD)

    def display_str(self, pub_date: Optional[str] = None) -> str:
        eff_date = pub_date or self.pub_date
        date_part = f", {eff_date}" if eff_date else ""
        if self.paragraph_num is not None:
            return f"[{self.doc_id} P{self.paragraph_num}{date_part}]"
        if self.trade_row_ref:
            return f"[{self.trade_row_ref}{date_part}]"
        return f"[{self.doc_id}{date_part}]"


class DocMeta(BaseModel):
    DOC_ID: str
    PUB_DATE: str
    RELIABILITY: int = Field(ge=1, le=4)
    COUNTRY: Optional[str] = "general"
    SECTOR: Optional[str] = "general"
    SOURCE_NAME: Optional[str] = None
    SOURCE_TYPE: Optional[str] = None
    EVENT_ID: Optional[str] = None
    FORMAT: Optional[str] = "TXT"
    TITLE: Optional[str] = None
    file: Optional[str] = None


class Document(BaseModel):
    meta: DocMeta
    paragraphs: Dict[int, str] = Field(default_factory=dict)
    raw_text: str = ""
    is_damaged: bool = False
    is_retracted: bool = False
    superseded_by: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    injection_detected: bool = False
    injection_details: Optional[str] = None


class TradeRow(BaseModel):
    table_id: str
    row_num: int
    country_pair: str
    sector: str
    month: str
    value: Optional[float] = None
    volume: Optional[float] = None
    unit: str = "tons"
    is_damaged: bool = False
    damage_reason: Optional[str] = None


class CaseFile(BaseModel):
    case_id: str
    query: str
    as_of: str  # YYYY-MM-DD
    target_pairs: List[Tuple[str, str]] = Field(default_factory=list)  # (country, sector)
    verification_status: EventVerificationStatus = EventVerificationStatus.UNCERTAIN
    verification_reason: Optional[str] = None
    active_event_id: Optional[str] = None


class Claim(BaseModel):
    claim_id: str
    agent: AgentRole
    country: str
    sector: str
    posture: str  # "high" or "limited"
    statement: str
    estimate_low: Optional[float] = None
    estimate_high: Optional[float] = None
    unit: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list)
    nature: Basis = Basis.SOURCED_FACT


class Attack(BaseModel):
    attack_id: str
    attacker: AgentRole
    target_claim_id: str
    argument: str
    counter_citations: List[Citation] = Field(default_factory=list)


class Defense(BaseModel):
    defense_id: str
    attack_id: str
    defender: AgentRole
    argument: str
    new_citations: List[Citation] = Field(default_factory=list)
    is_concession: bool = False


class Concession(BaseModel):
    concession_id: str
    agent: AgentRole
    claim_id: str
    rationale: str


class Ruling(BaseModel):
    claim_id: str
    verdict: Verdict
    basis: Basis
    rationale: str
    disqualified_reason: Optional[str] = None
    admissible_citations: List[Citation] = Field(default_factory=list)
    inadmissible_citations: List[Citation] = Field(default_factory=list)


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    LIMITS_EXHAUSTED = "limits_exhausted"


class SendBack(BaseModel):
    missing: List[str] = Field(default_factory=list)
    gap_types: List[str] = Field(default_factory=list)
    iteration: int = 1


class ExposureRange(BaseModel):
    country: str
    sector: str
    thor_range: Optional[Tuple[float, float]] = None
    loki_range: Optional[Tuple[float, float]] = None
    odin_range: Optional[Tuple[float, float]] = None
    status: str = "resolved"  # "resolved" or "unresolved"
    rationale: str = ""
    established_claim_ids: List[str] = Field(default_factory=list)
    contested_claim_ids: List[str] = Field(default_factory=list)
    conceded_claim_ids: List[str] = Field(default_factory=list)
    rejected_claim_ids: List[str] = Field(default_factory=list)
    trade_row_refs: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


class SufficiencyResult(BaseModel):
    status: SufficiencyStatus
    is_sufficient: bool
    reasons: List[str] = Field(default_factory=list)
    send_back: Optional[SendBack] = None
    unresolved_gaps: List[str] = Field(default_factory=list)
    disclosed_uncertainties: List[str] = Field(default_factory=list)


class Briefing(BaseModel):
    case_id: str
    as_of: str
    event_verification: Dict[str, Any]
    executive_summary: str = ""
    established_findings: List[Dict[str, Any]] = Field(default_factory=list)
    contested_findings: List[Dict[str, Any]] = Field(default_factory=list)
    conceded_claims: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_claims: List[Dict[str, Any]] = Field(default_factory=list)
    exposure_table: List[ExposureRange] = Field(default_factory=list)
    next_quarter_outlook: str = ""
    assumptions: List[str] = Field(default_factory=list)
    verification_summary: Dict[str, Any] = Field(default_factory=dict)
    traps_and_data_quality: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    markdown_content: str = ""


class LogEventType(str, Enum):
    QUERY = "QUERY"
    RETRIEVED = "RETRIEVED"
    CLAIM = "CLAIM"
    ATTACK = "ATTACK"
    DEFENSE = "DEFENSE"
    CONCESSION = "CONCESSION"
    RULING = "RULING"
    SENDBACK = "SENDBACK"
    MEMORY_READ = "MEMORY_READ"
    MEMORY_WRITE = "MEMORY_WRITE"
    TRAP_INJECTION = "TRAP_INJECTION"
    LIMIT_HIT = "LIMIT_HIT"
    ERROR = "ERROR"


class LogEvent(BaseModel):
    event_id: str
    case_id: str
    run_num: int = 1
    round_num: int = 1
    agent: AgentRole
    event_type: LogEventType
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
