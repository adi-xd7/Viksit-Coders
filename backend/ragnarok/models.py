"""Core data contracts shared by every module.

Rules encoded here:
- Verdicts are exactly established | contested | conceded | rejected.
- Missing numbers stay None; they never become zero.
- Every claim carries at least one citation; attacks must name counter-evidence
  or a concrete evidence gap; defenses must bring new evidence.
- Exposure estimates state metric, unit, period and evidence refs.
- Metadata is normalised for search, but the original raw values are kept.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class AgentName(StrEnum):
    HEIMDALL = "heimdall"
    THOR = "thor"
    LOKI = "loki"
    ODIN = "odin"
    SYSTEM = "system"
    USER = "user"


ADVOCATES = (AgentName.THOR, AgentName.LOKI)


class Verdict(StrEnum):
    ESTABLISHED = "established"
    CONTESTED = "contested"
    CONCEDED = "conceded"  # proponent withdrew / acknowledged the attack
    REJECTED = "rejected"  # Odin judged it unsupported or invalid


class ClaimType(StrEnum):
    FACT = "fact"
    INFERENCE = "inference"


class EventStatus(StrEnum):
    ESTABLISHED = "established"
    DISPROVED = "disproved"
    UNCERTAIN = "uncertain"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DocFormat(StrEnum):
    PDF = "pdf"
    TXT = "txt"
    DOCX = "docx"


class DamageKind(StrEnum):
    EMPTY = "empty"
    TRUNCATED = "truncated"
    BAD_ENCODING = "bad_encoding"
    UNPARSEABLE = "unparseable"
    MISSING_HEADER = "missing_header"
    METADATA_CONFLICT = "metadata_conflict"
    DUPLICATE = "duplicate"  # exact duplicate of another document
    POSSIBLE_DUPLICATE = "possible_duplicate"  # near-duplicate; never merged
    HEADER_ONLY = "header_only"  # metadata header but no body text
    MALFORMED = "malformed"  # broken structure, e.g. repeated or missing [Pn] markers
    BAD_METADATA = "bad_metadata"  # unparseable date, tier out of range, ...
    NOT_IN_MANIFEST = "not_in_manifest"
    HASH_MISMATCH = "hash_mismatch"  # file differs from the pack's published checksum


# Kinds that mean the content itself is damaged or unreliable to read. The other
# kinds (duplicates, metadata conflicts, not in manifest) are notices: the
# document is readable but needs care.
DAMAGE_KINDS = frozenset({
    DamageKind.EMPTY, DamageKind.TRUNCATED, DamageKind.BAD_ENCODING, DamageKind.UNPARSEABLE,
    DamageKind.MISSING_HEADER, DamageKind.HEADER_ONLY, DamageKind.MALFORMED, DamageKind.BAD_METADATA,
    DamageKind.HASH_MISMATCH,
})


class RelationType(StrEnum):
    DUPLICATE_OF = "duplicate_of"  # exact duplicate (same normalised content)
    NEAR_DUPLICATE_OF = "near_duplicate_of"  # similar; never auto-merged
    CORRECTS = "corrects"
    RETRACTS = "retracts"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"


class RowStatus(StrEnum):
    VALID = "valid"
    MISSING_VALUE = "missing_value"
    BAD_NUMBER = "bad_number"
    DUPLICATE_ROW = "duplicate_row"
    TRUNCATED = "truncated"
    MALFORMED = "malformed"  # unparseable period or row structure
    OUT_OF_WINDOW = "out_of_window"


class LogEventType(StrEnum):
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
    CLOCK_VIOLATION_BLOCKED = "CLOCK_VIOLATION_BLOCKED"
    LIMIT_HIT = "LIMIT_HIT"
    ERROR = "ERROR"
    # lifecycle events
    INGEST = "INGEST"
    DAMAGED_INPUT = "DAMAGED_INPUT"
    RUN_START = "RUN_START"
    RUN_END = "RUN_END"
    BRIEFING = "BRIEFING"
    CASE_FILE = "CASE_FILE"  # Heimdall's case file / verification
    STAGE = "STAGE"  # state-machine transition
    SUFFICIENCY = "SUFFICIENCY"  # Odin's sufficiency assessment (code turns it into a send-back or a briefing)
    PRECHECK = "PRECHECK"  # code pre-checks on a claim before Odin rules
    RESEARCH_PLAN = "RESEARCH_PLAN"  # Heimdall's targeted queries for a send-back
    NEW_EVIDENCE = "NEW_EVIDENCE"  # evidence first found in run n (and, after Odin, its effect)
    MEMORY_APPLIED = "MEMORY_APPLIED"  # a recalled lesson changed what an agent did (original vs changed action)
    LLM_USAGE = "LLM_USAGE"  # model requests of the case (by agent, stage, label; repairs; tokens)
    LLM_CACHE_HIT = "LLM_CACHE_HIT"  # a resumed case replayed a finished step from its own response cache
    MODEL_SWITCH = "MODEL_SWITCH"  # a model's daily quota was used up (or it kept failing): the next model answered


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_PARA_REF_RE = re.compile(r"^P\d+$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_BACKGROUND_EVENT_VALUES = {"", "none", "null", "n/a", "na", "background", "-"}


def _check_id(v: str, what: str) -> str:
    if not _ID_RE.match(v):
        raise ValueError(f"invalid {what}: {v!r}")
    return v


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


class MetadataConflict(_Model):
    field: str
    header_value: str | None
    manifest_value: str | None
    resolution: str  # e.g. "header used", "kept both"


class DocMeta(_Model):
    """Normalised document metadata. `raw` keeps the original key/value pairs."""

    doc_id: str
    event_id: str | None  # None => background document (no event)
    title: str
    source_name: str
    source_type: str  # lower-case, open set (unseen packs may add types)
    reliability_tier: int | None = Field(default=None, ge=1, le=4)
    pub_date: date | None = None  # None only for unreadable files with no manifest entry; never passes an as_of gate
    pub_time: time | None = None
    country: str | None = None
    sector: str | None = None  # lower-case for filtering
    language: str | None = None
    file_name: str | None = None
    format: DocFormat | None = None
    raw: dict[str, str] = Field(default_factory=dict)
    conflicts: list[MetadataConflict] = Field(default_factory=list)

    @field_validator("doc_id")
    @classmethod
    def _doc_id_ok(cls, v: str) -> str:
        return _check_id(v, "doc_id")

    @field_validator("source_type", "sector", "language")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.strip().lower() if isinstance(v, str) and v.strip() else (None if v is None else v)

    @field_validator("pub_date", mode="before")
    @classmethod
    def _strict_date(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip() == "":
            return None
        if isinstance(v, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.strip()):
            raise ValueError(f"pub_date must be YYYY-MM-DD, got {v!r}")
        return v

    @property
    def is_background(self) -> bool:
        return self.event_id is None

    @property
    def published_at(self) -> datetime | None:
        if self.pub_date is None:
            return None
        return datetime.combine(self.pub_date, self.pub_time or time(0, 0))

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], **extra: Any) -> "DocMeta":
        """Build from a header/manifest dict with any key capitalisation.

        Upper-case keys win over lower-case duplicates; originals are kept in `raw`.
        """
        norm: dict[str, Any] = {}
        for k, v in raw.items():
            key = str(k).strip().lower()
            if key not in norm or str(k).isupper():
                norm[key] = v

        def get(*names: str) -> Any:
            for n in names:
                if n in norm and norm[n] is not None and str(norm[n]).strip() != "":
                    return norm[n]
            return None

        event = get("event_id")
        event_id = None if event is None or str(event).strip().lower() in _BACKGROUND_EVENT_VALUES else str(event).strip()
        tier = get("reliability", "reliability_tier", "tier")
        fmt = get("format")
        data: dict[str, Any] = {
            "doc_id": str(get("doc_id") or "").strip(),
            "event_id": event_id,
            "title": str(get("title") or "").strip(),
            "source_name": str(get("source_name") or "").strip(),
            "source_type": str(get("source_type") or "unknown"),
            "reliability_tier": int(str(tier).strip()) if tier is not None and str(tier).strip().isdigit() else None,
            "pub_date": str(get("pub_date") or "").strip(),
            "pub_time": get("pub_time"),
            "country": get("country"),
            "sector": get("sector"),
            "language": get("language"),
            "file_name": get("file", "file_name"),
            "format": str(fmt).strip().lower() if fmt else None,
            "raw": {str(k): str(v) for k, v in raw.items()},
        }
        data.update(extra)
        return cls(**data)


class DamageFlag(_Model):
    kind: DamageKind
    detail: str
    paragraph_ref: str | None = None


class InjectionFlag(_Model):
    """A suspicious span. The source text is never deleted or rewritten."""

    paragraph_ref: str | None
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    pattern: str
    field: str | None = None  # set when the span is in metadata (header key, file properties) rather than a paragraph
    excerpt: str
    severity: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def _span(self) -> "InjectionFlag":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class DocRelation(_Model):
    type: RelationType
    target_doc_id: str
    evidence: str = ""  # why the relation was detected


class Paragraph(_Model):
    ref: str  # stable ref, e.g. "P3" (from the document's own [P3] marker when present)
    ordinal: int = Field(ge=0)
    text: str  # original text (whitespace-normalised only)
    evidence_text: str | None = None  # text shown to agents, flagged spans marked; None => same as text

    @field_validator("ref")
    @classmethod
    def _ref_ok(cls, v: str) -> str:
        if not _PARA_REF_RE.match(v):
            raise ValueError(f"bad paragraph ref {v!r}")
        return v


class ParserInfo(_Model):
    parser: str  # e.g. "pypdf", "python-docx", "text"
    version: str = ""
    encoding: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Document(_Model):
    """A parsed document.

    file_sha256 hashes the original bytes on disk (never modified). content_sha256
    hashes the normalised body (paragraph texts, whitespace collapsed, case folded)
    and is what exact-duplicate detection compares.
    """

    meta: DocMeta
    paragraphs: list[Paragraph] = Field(default_factory=list)
    text: str = ""  # full decoded text, header included, as extracted
    file_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # None only when the file could not be read at all
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parser: ParserInfo
    pack_id: str
    ingested_at: datetime = Field(default_factory=_utcnow)
    damage_flags: list[DamageFlag] = Field(default_factory=list)
    injection_flags: list[InjectionFlag] = Field(default_factory=list)
    relations: list[DocRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_refs(self) -> "Document":
        refs = [p.ref for p in self.paragraphs]
        if len(refs) != len(set(refs)):
            raise ValueError(f"duplicate paragraph refs in {self.meta.doc_id}")
        return self

    def paragraph(self, ref: str) -> Paragraph | None:
        return next((p for p in self.paragraphs if p.ref == ref), None)

    @property
    def is_damaged(self) -> bool:
        return any(f.kind in DAMAGE_KINDS for f in self.damage_flags)

    @property
    def is_exact_duplicate(self) -> bool:
        return any(r.type == RelationType.DUPLICATE_OF for r in self.relations)


# --------------------------------------------------------------------------- #
# Trade data
# --------------------------------------------------------------------------- #


class TradeRow(_Model):
    row_id: str  # stable: "<table_id>#R<row_number>"
    table_id: str
    source_doc_id: str
    row_number: int = Field(ge=1)
    paragraph_ref: str | None = None  # for prose layouts
    origin: str
    destination: str
    sector: str
    period: str | None  # YYYY-MM; None only for malformed rows whose period could not be read
    value: float | None = None
    currency: str | None = None
    volume: float | None = None
    volume_unit: str | None = None
    status: RowStatus = RowStatus.VALID
    damage_reason: str | None = None
    raw_text: str
    provenance: str  # parser + layout, e.g. "prose-v1"
    warnings: list[str] = Field(default_factory=list)  # suspicious but not invalid, e.g. value identical to previous month

    @field_validator("period")
    @classmethod
    def _period(cls, v: str | None) -> str | None:
        if v is not None and not _PERIOD_RE.match(v):
            raise ValueError(f"period must be YYYY-MM, got {v!r}")
        return v

    @field_validator("sector")
    @classmethod
    def _sector_lower(cls, v: str) -> str:
        return v.strip().lower()

    @model_validator(mode="after")
    def _consistency(self) -> "TradeRow":
        if self.row_id != f"{self.table_id}#R{self.row_number}":
            raise ValueError("row_id must be '<table_id>#R<row_number>'")
        if self.status == RowStatus.VALID:
            if self.period is None:
                raise ValueError("a valid row must have a period")
            if self.value is None:
                raise ValueError("a valid row must have a value (missing values are not valid rows)")
            if self.value < 0 or (self.volume is not None and self.volume < 0):
                raise ValueError("negative trade value/volume cannot be a valid row")
            if self.currency is None:
                raise ValueError("a valid row with a value must state its currency")
        else:
            if not self.damage_reason:
                raise ValueError("non-valid rows must record a damage_reason")
        if self.status == RowStatus.MISSING_VALUE and self.value is not None:
            raise ValueError("missing_value rows must keep value=None (never repaired silently)")
        return self


class TradeTable(_Model):
    table_id: str
    source_doc_id: str
    origin: str
    destination: str
    sector: str
    unit: str | None = None
    event_id: str | None = None
    layout: Literal["fixed", "prose"]
    rows: list[TradeRow] = Field(default_factory=list)
    damage_flags: list[DamageFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rows_belong(self) -> "TradeTable":
        for r in self.rows:
            if r.table_id != self.table_id:
                raise ValueError(f"row {r.row_id} does not belong to table {self.table_id}")
        return self


# --------------------------------------------------------------------------- #
# Evidence, calculations and estimates
# --------------------------------------------------------------------------- #


class Citation(_Model):
    doc_id: str
    paragraph_ref: str | None = None
    row_id: str | None = None
    pub_date: date
    quote: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def _locator(self) -> "Citation":
        if not self.paragraph_ref and not self.row_id:
            raise ValueError("a citation needs a paragraph_ref or a row_id")
        if self.paragraph_ref and not _PARA_REF_RE.match(self.paragraph_ref):
            raise ValueError(f"bad paragraph ref {self.paragraph_ref!r}")
        return self


class CalcInput(_Model):
    row_id: str | None = None  # None only for an explicit, named parameter
    label: str
    value: float | None


class CalculationRecord(_Model):
    """Output of a deterministic Python calculation; inputs keep their row refs."""

    calc_id: str
    operation: str  # e.g. "sum", "pct_change", "share", "difference"
    inputs: list[CalcInput] = Field(min_length=1)
    parameters: dict[str, float | str] = Field(default_factory=dict)
    result: float | None
    unit: str
    formula: str
    excluded_rows: dict[str, str] = Field(default_factory=dict)  # row_id -> reason
    notes: str = ""
    as_of: date | None = None  # the date gate the input rows were read under
    rows_requested: int = Field(0, ge=0)
    complete: bool = True  # False => some requested rows were excluded; a result, if any, is partial

    @model_validator(mode="after")
    def _missing_stays_missing(self) -> "CalculationRecord":
        if any(i.value is None for i in self.inputs) and self.result is not None:
            raise ValueError("a calculation with a missing input cannot produce a result")
        if self.excluded_rows and self.complete:
            raise ValueError("a calculation that excluded rows cannot be marked complete")
        return self


class ExposureEstimate(_Model):
    estimate_id: str
    agent: AgentName
    country: str
    sector: str
    metric: str  # short metric name, e.g. "trade_value_lost_vs_prior_year"
    metric_definition: str = Field(min_length=10)
    unit: str  # e.g. "USD M", "percent", "tonnes"
    currency: str | None = None
    period: str  # e.g. "2026-09..2026-12" or "next quarter"
    denominator: str | None = None  # required for percentages
    low: float | None = None
    high: float | None = None
    insufficient_evidence: bool = False
    evidence: list[Citation] = Field(default_factory=list)
    trade_row_refs: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    uncertainty_note: str = ""

    @model_validator(mode="after")
    def _range(self) -> "ExposureEstimate":
        if self.insufficient_evidence:
            if not self.missing_data:
                raise ValueError("insufficient_evidence estimates must list the missing data")
            return self
        if self.low is None or self.high is None:
            raise ValueError("low and high are required unless insufficient_evidence=True")
        if self.low > self.high:
            raise ValueError("low must be <= high")
        if self.unit.lower() in {"percent", "%", "pct"} and not self.denominator:
            raise ValueError("percentage estimates must state their denominator")
        if not self.evidence and not self.trade_row_refs:
            raise ValueError("an estimate needs evidence citations or trade-row refs")
        return self


# --------------------------------------------------------------------------- #
# Case file and trial artefacts
# --------------------------------------------------------------------------- #


class CaseFile(_Model):
    case_id: str
    question: str = Field(min_length=5)
    as_of: date
    created_at: datetime = Field(default_factory=_utcnow)
    countries: list[str] = Field(default_factory=list)  # whose exposure the question asks about
    sectors: list[str] = Field(default_factory=list)  # commodities/sectors the question asks about
    related_countries: list[str] = Field(default_factory=list)  # exporters, transit, alternative suppliers
    commodities: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    candidate_event_ids: list[str] = Field(default_factory=list)
    event_status: EventStatus = EventStatus.UNCERTAIN
    event_verification_notes: str = ""
    event_citations: list[Citation] = Field(default_factory=list)
    evidence_doc_ids: list[str] = Field(default_factory=list)
    trade_table_ids: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)  # corrections / retractions / contradictions noted
    run_number: int = Field(1, ge=1)

    @field_validator("case_id")
    @classmethod
    def _case_id_ok(cls, v: str) -> str:
        return _check_id(v, "case_id")

    @model_validator(mode="after")
    def _citations_in_window(self) -> "CaseFile":
        late = [c.doc_id for c in self.event_citations if c.pub_date > self.as_of]
        if late:
            raise ValueError(f"event citations published after as_of: {late}")
        return self


class Claim(_Model):
    claim_id: str
    run_number: int = Field(ge=1)
    agent: AgentName
    text: str = Field(min_length=10)
    country: str | None = None
    sector: str | None = None
    claim_type: ClaimType
    citations: list[Citation] = Field(min_length=1)  # no claim without a source
    assumptions: list[str] = Field(default_factory=list)
    exposure: ExposureEstimate | None = None
    limitations: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    revises_claim_id: str | None = None  # run n >= 2: the earlier claim this one replaces

    @model_validator(mode="after")
    def _agent_owns_estimate(self) -> "Claim":
        if self.exposure is not None and self.exposure.agent != self.agent:
            raise ValueError("a claim's exposure estimate must belong to the same agent")
        return self


class Attack(_Model):
    attack_id: str
    run_number: int = Field(ge=1)
    round_number: int = Field(1, ge=1)
    attacker: AgentName
    target_claim_id: str
    target_agent: AgentName
    objection: str = Field(min_length=20)  # specific, not generic disagreement
    counter_evidence: list[Citation] = Field(default_factory=list)
    evidence_gap: str | None = None
    why_it_matters: str = Field(min_length=10)

    @model_validator(mode="after")
    def _meaningful(self) -> "Attack":
        if self.attacker == self.target_agent:
            raise ValueError("an agent cannot attack its own claim")
        if self.attacker not in ADVOCATES or self.target_agent not in ADVOCATES:
            raise ValueError("cross-examination is between Thor and Loki")
        if not self.counter_evidence and not (self.evidence_gap and len(self.evidence_gap) >= 10):
            raise ValueError("an attack needs counter-evidence or a concrete evidence gap")
        return self


class Defense(_Model):
    defense_id: str
    run_number: int = Field(ge=1)
    defender: AgentName
    attack_id: str
    claim_id: str
    argument: str = Field(min_length=20)
    new_evidence: list[Citation] = Field(min_length=1)  # otherwise it must be a Concession


class Concession(_Model):
    concession_id: str
    run_number: int = Field(ge=1)
    agent: AgentName
    claim_id: str
    attack_id: str | None = None
    reason: str = Field(min_length=10)
    partial: bool = False
    revised_claim_text: str | None = None

    @model_validator(mode="after")
    def _partial_needs_revision(self) -> "Concession":
        if self.partial and not self.revised_claim_text:
            raise ValueError("a partial concession must state the revised claim")
        return self


class Ruling(_Model):
    ruling_id: str
    run_number: int = Field(ge=1)
    claim_id: str
    verdict: Verdict
    claim_type: ClaimType  # Odin's own classification, may differ from the advocate's
    rationale: str = Field(min_length=20)
    citations_valid: bool
    citation_issues: list[str] = Field(default_factory=list)
    supporting_citations: list[Citation] = Field(default_factory=list)
    contradicting_citations: list[Citation] = Field(default_factory=list)
    concession_id: str | None = None

    @model_validator(mode="after")
    def _verdict_rules(self) -> "Ruling":
        if self.verdict == Verdict.CONCEDED and not self.concession_id:
            raise ValueError("a 'conceded' verdict must reference the proponent's concession")
        if self.verdict == Verdict.ESTABLISHED and not self.citations_valid:
            raise ValueError("a claim with invalid citations cannot be established")
        return self


class MissingEvidence(_Model):
    description: str = Field(min_length=10)
    why_needed: str = Field(min_length=10)
    countries: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)


class SendBack(_Model):
    """Odin names what is missing; he never assigns tasks to agents."""

    sendback_id: str
    run_number: int = Field(ge=1)
    reason: str = Field(min_length=10)
    missing: list[MissingEvidence] = Field(min_length=1)


class BriefingFinding(_Model):
    claim_id: str
    ruling_id: str
    verdict: Verdict
    claim_type: ClaimType
    text: str
    citations: list[Citation] = Field(min_length=1)


class ExposureRow(_Model):
    country: str
    sector: str
    thor: ExposureEstimate | None = None
    loki: ExposureEstimate | None = None
    odin: ExposureEstimate | None = None
    unavailable: dict[str, str] = Field(default_factory=dict)  # agent -> why no (justifiable) estimate is shown
    note: str = ""


class Outlook(_Model):
    text: str = Field(min_length=10)
    assumptions: list[str] = Field(min_length=1)


class SourceRef(_Model):
    doc_id: str
    title: str
    pub_date: date
    pub_time: time | None = None
    source_name: str
    reliability_tier: int | None = None


class RunSummary(_Model):
    """One investigation run, so the briefing can show run 1 vs run 2."""

    run_number: int = Field(ge=1)
    claims: list[str] = Field(default_factory=list)  # claim IDs ruled in this run
    verdicts: dict[str, str] = Field(default_factory=dict)  # claim ID -> verdict
    sufficient: bool | None = None
    sufficiency_reason: str = ""
    sendback_missing: list[str] = Field(default_factory=list)  # what Odin named as missing at the end of the run
    new_evidence: list[str] = Field(default_factory=list)  # refs first found in this run (run >= 2)
    note: str = ""


class Briefing(_Model):
    case_id: str
    as_of: date
    status: Literal["complete", "partial", "incomplete"]
    runs_completed: int = Field(ge=0)
    executive_summary: str = Field(min_length=20)
    event_status: EventStatus
    event_citations: list[Citation] = Field(default_factory=list)
    established: list[BriefingFinding] = Field(default_factory=list)
    contested: list[BriefingFinding] = Field(default_factory=list)
    conceded: list[BriefingFinding] = Field(default_factory=list)
    rejected: list[BriefingFinding] = Field(default_factory=list)
    exposure_table: list[ExposureRow] = Field(default_factory=list)
    outlook: Outlook
    sources: list[SourceRef] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
    evidence_quality_notes: list[str] = Field(default_factory=list)
    traps_and_failures: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)  # claim and estimate assumptions behind the findings
    uncertainty: list[str] = Field(default_factory=list)  # estimate uncertainty notes and confidence
    dropped_citations: list[str] = Field(default_factory=list)  # failed the build-time citation/provenance check
    runs: list[RunSummary] = Field(default_factory=list)
    superseded: list[str] = Field(default_factory=list)  # earlier claims replaced or withdrawn in a later run
    generated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _consistent(self) -> "Briefing":
        for section, verdict in (
            (self.established, Verdict.ESTABLISHED),
            (self.contested, Verdict.CONTESTED),
            (self.conceded, Verdict.CONCEDED),
            (self.rejected, Verdict.REJECTED),
        ):
            for f in section:
                if f.verdict != verdict:
                    raise ValueError(f"finding {f.claim_id} with verdict {f.verdict} filed under {verdict}")
        cited = [c for f in self.established + self.contested + self.conceded + self.rejected for c in f.citations]
        late = sorted({c.doc_id for c in cited + self.event_citations if c.pub_date > self.as_of})
        if late:
            raise ValueError(f"briefing cites documents published after as_of: {late}")
        if self.status == "complete" and self.missing_data_notes and self.event_status == EventStatus.UNCERTAIN:
            raise ValueError("a briefing with an uncertain event and missing data cannot be 'complete'")
        return self


# --------------------------------------------------------------------------- #
# Memory and audit log
# --------------------------------------------------------------------------- #


class MemoryEntry(_Model):
    memory_id: str
    agent: AgentName
    lesson: str = Field(min_length=10)  # general: names, IDs, dates and numbers are masked
    context: str = ""  # evidence/event context the lesson came from (never shown as a lesson)
    case_scope: str | None = None  # None => general lesson
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)
    kind: str = "lesson"  # e.g. rejected_claim, sendback_gap, useful_query
    stages: list[str] = Field(default_factory=list)  # where it is recalled: research, sendback, brief, cross_exam, ruling
    times_seen: int = Field(1, ge=1)
    source_case: str | None = None
    source_run: int | None = None
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("agent")
    @classmethod
    def _real_agent(cls, v: AgentName) -> AgentName:
        if v in (AgentName.SYSTEM, AgentName.USER):
            raise ValueError("memory belongs to one of the four agents")
        return v


class LogEvent(_Model):
    seq: int | None = None  # assigned by the append-only store
    case_id: str
    run_number: int = Field(0, ge=0)
    ts: datetime = Field(default_factory=_utcnow)
    agent: AgentName
    type: LogEventType
    summary: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)  # doc ids, row ids, claim ids...
