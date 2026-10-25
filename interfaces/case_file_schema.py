"""
Case File schema — the shared contract between Heimdall and all other agents.

Thor, Loki, and Odin consume the CaseFile that Heimdall produces.
This module defines the data structures so every agent agrees on the shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any


# ── Verification status ──────────────────────────────────────────────────────

class VerificationStatus:
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAKE = "fake"
    RETRACTED = "retracted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


# ── Sub-structures ───────────────────────────────────────────────────────────

@dataclass
class EventInfo:
    """Core metadata about the disruption event."""
    event_id: str = ""
    name: str = ""
    description: str = ""
    countries: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievedDocument:
    """A single document retrieved from Runemark."""
    doc_id: str
    title: str
    source_name: str
    source_type: str
    reliability: int
    pub_date: str
    country: str
    sector: str
    event_id: str
    file_name: str
    relevance_score: float = 0.0
    snippet: str = ""
    is_retracted: bool = False
    retracted_by: str | None = None
    is_unreliable: bool = False
    unreliability_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeTable:
    """A parsed trade table extracted from a document."""
    doc_id: str
    title: str
    source_name: str
    pub_date: str
    country: str
    sector: str
    origin: str = ""
    destination: str = ""
    commodity: str = ""
    period: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationResult:
    """Outcome of Heimdall's event-verification step."""
    status: str = VerificationStatus.UNVERIFIED
    confidence: float = 0.0
    reason: str = ""
    supporting_doc_ids: list[str] = field(default_factory=list)
    contradicting_doc_ids: list[str] = field(default_factory=list)
    retracted_doc_ids: list[str] = field(default_factory=list)
    fake_indicators: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Case File ────────────────────────────────────────────────────────────────

@dataclass
class CaseFile:
    """
    The master artifact that Heimdall produces for the courtroom.

    Thor, Loki, and Odin consume this — never Heimdall's private memory.
    """
    question: str = ""
    as_of_date: str = ""
    created_at: str = ""
    updated_at: str = ""
    search_round: int = 1
    event: EventInfo = field(default_factory=EventInfo)
    documents: list[RetrievedDocument] = field(default_factory=list)
    trade_tables: list[TradeTable] = field(default_factory=list)
    verification: VerificationResult = field(default_factory=VerificationResult)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Convert the full case file to a plain dict (JSON-ready)."""
        return {
            "question": self.question,
            "as_of_date": self.as_of_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "search_round": self.search_round,
            "event": self.event.to_dict(),
            "documents": [d.to_dict() for d in self.documents],
            "trade_tables": [t.to_dict() for t in self.trade_tables],
            "verification": self.verification.to_dict(),
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "CaseFile":
        cf = cls()
        cf.question = data.get("question", "")
        cf.as_of_date = data.get("as_of_date", "")
        cf.created_at = data.get("created_at", "")
        cf.updated_at = data.get("updated_at", "")
        cf.search_round = data.get("search_round", 1)
        cf.event = EventInfo(**data.get("event", {}))
        cf.documents = [RetrievedDocument(**d) for d in data.get("documents", [])]
        cf.trade_tables = [TradeTable(**t) for t in data.get("trade_tables", [])]
        cf.verification = VerificationResult(**data.get("verification", {}))
        cf.metadata = data.get("metadata", {})
        return cf

    @classmethod
    def from_json(cls, json_str: str) -> "CaseFile":
        return cls.from_dict(json.loads(json_str))
