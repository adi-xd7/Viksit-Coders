"""Retrieval contracts shared by the search service, agents' tools, API and dashboard."""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ragnarok.models import AgentName, TradeRow


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _lower_list(v: object) -> list[str] | None:
    if v is None:
        return None
    items = [v] if isinstance(v, str) else list(v)  # type: ignore[arg-type]
    out = [str(x).strip().lower() for x in items if str(x).strip()]
    return sorted(set(out)) or None


class SearchFilters(_Model):
    """Metadata filters; every field set must match (AND). Lists match any element (OR)."""

    country: list[str] | None = None
    sector: list[str] | None = None  # matches document SECTOR or the commodity of its trade table
    event_id: list[str] | None = None  # "none" selects background documents
    source_type: list[str] | None = None
    max_reliability: int | None = Field(None, ge=1, le=4)  # tier number: 2 => tiers 1 and 2 only
    date_from: date | None = None  # publication date range (the as_of gate still applies)
    date_to: date | None = None
    doc_ids: list[str] | None = None
    include_duplicates: bool = False  # exact duplicates are hidden by default

    @field_validator("country", "sector", "event_id", "source_type", mode="before")
    @classmethod
    def _norm(cls, v: object) -> list[str] | None:
        return _lower_list(v)

    @field_validator("doc_ids", mode="before")
    @classmethod
    def _ids(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        items = [v] if isinstance(v, str) else list(v)  # type: ignore[arg-type]
        return sorted({str(x).strip() for x in items if str(x).strip()}) or None

    @model_validator(mode="after")
    def _range(self) -> "SearchFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self


class HitScores(_Model):
    rrf: float
    bm25_rank: int | None = None
    bm25: float | None = None
    vector_rank: int | None = None
    cosine: float | None = None


class SearchHit(_Model):
    chunk_id: str  # "<doc_id>#<paragraph_ref>"
    doc_id: str
    paragraph_ref: str
    text: str  # evidence text: flagged instruction spans withheld or marked
    title: str
    pub_date: date
    pub_time: time | None = None
    reliability_tier: int | None = None
    source_name: str
    source_type: str
    country: str | None = None
    sector: str | None = None
    table_sectors: list[str] = Field(default_factory=list)
    event_id: str | None = None
    damage: list[str] = Field(default_factory=list)  # damage kinds on the document
    injection_flagged: bool = False  # this paragraph contains flagged text
    possible_duplicate_of: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None  # set only when duplicates were requested
    corrects: list[str] = Field(default_factory=list)
    corrected_by: list[str] = Field(default_factory=list)  # only corrections published on or before as_of
    scores: HitScores


class SearchResult(_Model):
    query: str
    query_norm: str
    as_of: date
    agent: AgentName
    filters: SearchFilters
    limit: int
    hits: list[SearchHit]
    candidates: int  # paragraphs that passed the filters and the as_of gate
    reused: bool = False  # True => served from the query cache (identical request)
    query_seq: int | None = None  # audit seq of this QUERY event
    first_query_seq: int | None = None  # audit seq of the original QUERY when reused


class ParagraphView(_Model):
    ref: str
    text: str
    injection_flagged: bool = False


class DocView(_Model):
    """A document as an agent may see it under an as_of date."""

    doc_id: str
    status: Literal["ok", "blocked", "not_found"]
    reason: str = ""
    title: str | None = None
    pub_date: date | None = None
    pub_time: time | None = None
    reliability_tier: int | None = None
    source_name: str | None = None
    source_type: str | None = None
    country: str | None = None
    sector: str | None = None
    event_id: str | None = None
    paragraphs: list[ParagraphView] = Field(default_factory=list)
    missing_refs: list[str] = Field(default_factory=list)
    damage: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)  # "duplicate_of X", "corrected_by Y", ...


class TradeQuery(_Model):
    origin: list[str] | None = None
    destination: list[str] | None = None
    sector: list[str] | None = None
    period_from: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    period_to: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    table_ids: list[str] | None = None
    row_ids: list[str] | None = None
    valid_only: bool = False  # invalid rows are returned (with status/reason) unless asked otherwise
    include_duplicates: bool = False  # rows from exact-duplicate documents are hidden by default

    @field_validator("origin", "destination", "sector", mode="before")
    @classmethod
    def _norm(cls, v: object) -> list[str] | None:
        return _lower_list(v)


class TradeResult(_Model):
    as_of: date
    agent: AgentName
    query: TradeQuery
    rows: list[TradeRow]
    blocked: list[str] = Field(default_factory=list)  # explicitly requested IDs withheld by the as_of gate
    not_found: list[str] = Field(default_factory=list)
