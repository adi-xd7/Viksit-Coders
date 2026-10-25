"""
Structured JSON-lines logger for Heimdall.

Every significant action is recorded: queries, retrievals, verifications,
case-file mutations, memory updates, and failures.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config


class HeimdallLogger:
    """Append-only JSONL logger that writes to both file and stderr."""

    def __init__(self, log_path: Path | None = None):
        self._path = log_path or config.HEIMDALL_LOG_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Core writer ──────────────────────────────────────────────────────

    def _write(self, event_type: str, data: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": "heimdall",
            "event": event_type,
            **data,
        }
        line = json.dumps(record, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Also echo to stderr for live visibility
        print(f"[Heimdall][{event_type}] {json.dumps(data, default=str)}", file=sys.stderr)

    # ── Convenience methods ──────────────────────────────────────────────

    def query(self, question: str, as_of_date: str, search_round: int = 1) -> None:
        self._write("query", {
            "question": question,
            "as_of_date": as_of_date,
            "search_round": search_round,
        })

    def retrieved_documents(self, doc_ids: list[str], query: str,
                            search_mode: str = "hybrid") -> None:
        self._write("retrieved_documents", {
            "doc_ids": doc_ids,
            "query": query,
            "search_mode": search_mode,
            "count": len(doc_ids),
        })

    def retrieved_trade_tables(self, doc_ids: list[str]) -> None:
        self._write("retrieved_trade_tables", {
            "doc_ids": doc_ids,
            "count": len(doc_ids),
        })

    def event_verification(self, event_id: str, status: str,
                           confidence: float, reason: str) -> None:
        self._write("event_verification", {
            "event_id": event_id,
            "status": status,
            "confidence": confidence,
            "reason": reason,
        })

    def case_file_created(self, question: str, search_round: int) -> None:
        self._write("case_file_created", {
            "question": question,
            "search_round": search_round,
        })

    def case_file_updated(self, reason: str, search_round: int) -> None:
        self._write("case_file_updated", {
            "reason": reason,
            "search_round": search_round,
        })

    def research(self, reason: str, search_round: int,
                  previous_doc_ids: list[str]) -> None:
        self._write("re_search", {
            "reason": reason,
            "search_round": search_round,
            "previous_doc_count": len(previous_doc_ids),
        })

    def memory_change(self, action: str, detail: str) -> None:
        self._write("memory_change", {
            "action": action,
            "detail": detail,
        })

    def failure(self, operation: str, error: str,
                doc_id: str | None = None) -> None:
        self._write("failure", {
            "operation": operation,
            "error": error,
            "doc_id": doc_id,
        })

    def injection_detected(self, doc_id: str, snippet: str) -> None:
        self._write("injection_detected", {
            "doc_id": doc_id,
            "snippet": snippet[:200],
        })

    def info(self, message: str, **extra: Any) -> None:
        self._write("info", {"message": message, **extra})
