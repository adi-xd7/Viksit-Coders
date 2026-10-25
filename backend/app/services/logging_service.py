"""Structured JSON event logger for observability across agent actions."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional


class StructuredLogger:
    """Logs structured JSON events for auditability, execution trace, and grading."""

    def __init__(self, agent_name: str = "loki", log_file: Optional[str] = None):
        self.agent_name = agent_name
        self.log_file = log_file
        self.events: list[dict[str, Any]] = []
        self._logger = logging.getLogger(f"ragnarok.{agent_name}")

    def log_event(self, event_type: str, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record an event with timestamp, agent name, case ID, and structured payload."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "case_id": case_id,
            "event_type": event_type,
            "payload": payload,
        }
        self.events.append(event)
        self._logger.info(json.dumps(event))

        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
            except Exception as e:
                self._logger.warning(f"Failed to write log to {self.log_file}: {e}")

        return event

    def log_search(self, case_id: str, query: str, filters: dict[str, Any], result_doc_ids: list[str]) -> None:
        self.log_event("search", case_id, {
            "query": query,
            "filters": filters,
            "matched_count": len(result_doc_ids),
            "doc_ids": result_doc_ids,
        })

    def log_claim(self, case_id: str, claim_id: str, stance: str, statement: str, citations: list[str]) -> None:
        self.log_event("claim_submitted", case_id, {
            "claim_id": claim_id,
            "stance": stance,
            "statement": statement,
            "citations": citations,
        })

    def log_attack(self, case_id: str, challenge_id: str, target_claim_id: str, challenge_type: str, objection: str) -> None:
        self.log_event("cross_examination_attack", case_id, {
            "challenge_id": challenge_id,
            "target_claim_id": target_claim_id,
            "challenge_type": challenge_type,
            "objection": objection,
        })

    def log_concession(self, case_id: str, concession_id: str, target_claim_id: str, action: str, reason: str) -> None:
        self.log_event("concession_made", case_id, {
            "concession_id": concession_id,
            "target_claim_id": target_claim_id,
            "action": action,
            "reason": reason,
        })

    def log_memory_access(self, case_id: str, action: str, key: str, details: dict[str, Any]) -> None:
        self.log_event("memory_access", case_id, {
            "action": action,
            "key": key,
            "details": details,
        })

    def log_error(self, case_id: str, error_message: str, context: Optional[dict[str, Any]] = None) -> None:
        self.log_event("error", case_id, {
            "error_message": error_message,
            "context": context or {},
        })

    def get_events(self, case_id: Optional[str] = None, event_type: Optional[str] = None) -> list[dict[str, Any]]:
        results = self.events
        if case_id:
            results = [e for e in results if e["case_id"] == case_id]
        if event_type:
            results = [e for e in results if e["event_type"] == event_type]
        return results

    def clear(self) -> None:
        self.events.clear()
