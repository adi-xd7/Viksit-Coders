"""
Heimdall's private persistent memory.

Stores search history, previously returned doc IDs, verification outcomes,
and re-search metadata.  Persisted as a JSON file — never exposed directly
to other agents.  Shared information goes through the Case File.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from heimdall.logger import HeimdallLogger


class HeimdallMemory:
    """JSON-file-backed private memory for Heimdall."""

    def __init__(self, path: Path | None = None,
                 logger: HeimdallLogger | None = None):
        self._path = path or config.HEIMDALL_MEMORY_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger or HeimdallLogger()
        self._data: dict[str, Any] = self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return self._default()
        return self._default()

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, default=str)

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            "search_history": [],
            "returned_doc_ids": [],
            "verification_cache": {},
            "query_reformulations": [],
            "notes": [],
        }

    # ── Search history ───────────────────────────────────────────────────

    def record_search(self, query: str, doc_ids: list[str],
                      search_round: int, filters: dict | None = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "doc_ids": doc_ids,
            "search_round": search_round,
            "filters": filters or {},
        }
        self._data["search_history"].append(entry)
        # Accumulate returned doc IDs (for re-search de-duplication)
        for did in doc_ids:
            if did not in self._data["returned_doc_ids"]:
                self._data["returned_doc_ids"].append(did)
        self._save()
        self._logger.memory_change("record_search",
                                   f"round={search_round}, docs={len(doc_ids)}")

    def get_previously_returned_doc_ids(self) -> list[str]:
        return list(self._data.get("returned_doc_ids", []))

    def get_search_count(self) -> int:
        return len(self._data.get("search_history", []))

    # ── Verification cache ───────────────────────────────────────────────

    def cache_verification(self, event_id: str, result: dict) -> None:
        self._data["verification_cache"][event_id] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **result,
        }
        self._save()
        self._logger.memory_change("cache_verification",
                                   f"event={event_id}")

    def get_cached_verification(self, event_id: str) -> dict | None:
        return self._data.get("verification_cache", {}).get(event_id)

    # ── Query reformulations (for re-search) ─────────────────────────────

    def record_reformulation(self, original: str, reformulated: str) -> None:
        self._data["query_reformulations"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original": original,
            "reformulated": reformulated,
        })
        self._save()
        self._logger.memory_change("record_reformulation",
                                   f"'{original}' → '{reformulated}'")

    def get_past_queries(self) -> list[str]:
        queries = []
        for s in self._data.get("search_history", []):
            queries.append(s["query"])
        for r in self._data.get("query_reformulations", []):
            queries.append(r["reformulated"])
        return queries

    # ── Notes ────────────────────────────────────────────────────────────

    def add_note(self, note: str) -> None:
        self._data["notes"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": note,
        })
        self._save()
        self._logger.memory_change("add_note", note[:100])

    # ── Reset (for testing) ──────────────────────────────────────────────

    def reset(self) -> None:
        self._data = self._default()
        self._save()
        self._logger.memory_change("reset", "memory cleared")
