"""Loki-only private persistent memory with case isolation and provenance."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    """An individual knowledge item or lesson learned with provenance and confidence."""
    key: str
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance_doc_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = Field(default_factory=dict)


class CaseMemory(BaseModel):
    """Isolated memory storage for a specific case."""
    case_id: str
    executed_queries: set[str] = Field(default_factory=set)
    examined_doc_ids: set[str] = Field(default_factory=set)
    conceded_claims: list[dict[str, Any]] = Field(default_factory=list)
    lessons: dict[str, MemoryItem] = Field(default_factory=dict)
    opponent_claims_seen: list[str] = Field(default_factory=list)


class LokiMemoryService:
    """
    Manages private, persistent memory for the Loki agent.
    Strictly isolated per case_id and isolated from other agents.
    """

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else None
        self._cases: dict[str, CaseMemory] = {}
        if self.storage_path and self.storage_path.exists():
            self._load_from_disk()

    def _get_or_create_case(self, case_id: str) -> CaseMemory:
        if case_id not in self._cases:
            self._cases[case_id] = CaseMemory(case_id=case_id)
        return self._cases[case_id]

    def record_query(self, case_id: str, query: str) -> bool:
        """
        Record a search query.
        Returns:
            True if this is a fresh query.
            False if query was ALREADY run for this case (violating NFR5).
        """
        normalized_query = query.strip().lower()
        mem = self._get_or_create_case(case_id)
        if normalized_query in mem.executed_queries:
            return False
        mem.executed_queries.add(normalized_query)
        self._save_to_disk()
        return True

    def has_query_been_run(self, case_id: str, query: str) -> bool:
        """Check if query was previously executed for this case."""
        normalized_query = query.strip().lower()
        mem = self._get_or_create_case(case_id)
        return normalized_query in mem.executed_queries

    def record_examined_sources(self, case_id: str, doc_ids: list[str]) -> None:
        """Track document IDs examined during retrieval for provenance."""
        mem = self._get_or_create_case(case_id)
        for doc_id in doc_ids:
            mem.examined_doc_ids.add(doc_id.strip())
        self._save_to_disk()

    def record_lesson(
        self,
        case_id: str,
        key: str,
        statement: str,
        confidence: float,
        provenance_doc_ids: list[str],
        context: Optional[dict[str, Any]] = None,
    ) -> MemoryItem:
        """Store a structured lesson learned during cross-examination or runs."""
        mem = self._get_or_create_case(case_id)
        item = MemoryItem(
            key=key,
            statement=statement,
            confidence=confidence,
            provenance_doc_ids=provenance_doc_ids,
            context=context or {},
        )
        mem.lessons[key] = item
        self._save_to_disk()
        return item

    def record_concession(
        self,
        case_id: str,
        concession_id: str,
        claim_id: str,
        reason: str,
        adjusted_range: Optional[str] = None
    ) -> None:
        """Record that Loki conceded on a specific claim so it never repeats the mistake."""
        mem = self._get_or_create_case(case_id)
        mem.conceded_claims.append({
            "concession_id": concession_id,
            "claim_id": claim_id,
            "reason": reason,
            "adjusted_range": adjusted_range,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._save_to_disk()

    def record_opponent_claim(self, case_id: str, claim_id: str) -> None:
        """Track opponent claims seen in the case."""
        mem = self._get_or_create_case(case_id)
        if claim_id not in mem.opponent_claims_seen:
            mem.opponent_claims_seen.append(claim_id)
            self._save_to_disk()

    def get_conceded_claim_ids(self, case_id: str) -> set[str]:
        """Return IDs of claims already conceded in this case."""
        mem = self._get_or_create_case(case_id)
        return {item["claim_id"] for item in mem.conceded_claims}

    def get_lessons(self, case_id: str) -> dict[str, MemoryItem]:
        """Retrieve all lessons recorded for this case."""
        mem = self._get_or_create_case(case_id)
        return mem.lessons

    def get_all_examined_doc_ids(self, case_id: str) -> list[str]:
        """List all doc IDs examined for this case."""
        mem = self._get_or_create_case(case_id)
        return sorted(list(mem.examined_doc_ids))

    def clear_case_memory(self, case_id: str) -> None:
        """Reset memory for a specific case without affecting other cases."""
        if case_id in self._cases:
            del self._cases[case_id]
            self._save_to_disk()

    def _save_to_disk(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for cid, case_mem in self._cases.items():
                data[cid] = {
                    "case_id": case_mem.case_id,
                    "executed_queries": list(case_mem.executed_queries),
                    "examined_doc_ids": list(case_mem.examined_doc_ids),
                    "conceded_claims": case_mem.conceded_claims,
                    "lessons": {k: v.model_dump() for k, v in case_mem.lessons.items()},
                    "opponent_claims_seen": case_mem.opponent_claims_seen,
                }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cid, case_data in data.items():
                self._cases[cid] = CaseMemory(
                    case_id=case_data.get("case_id", cid),
                    executed_queries=set(case_data.get("executed_queries", [])),
                    examined_doc_ids=set(case_data.get("examined_doc_ids", [])),
                    conceded_claims=case_data.get("conceded_claims", []),
                    lessons={
                        k: MemoryItem(**v)
                        for k, v in case_data.get("lessons", {}).items()
                    },
                    opponent_claims_seen=case_data.get("opponent_claims_seen", []),
                )
        except Exception:
            pass
