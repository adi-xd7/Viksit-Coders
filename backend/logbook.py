"""Shared append-only SQLite and JSONL audit logbook.

Records auditable trial events (QUERY, RETRIEVED, CLAIM, ATTACK, DEFENSE, CONCESSION,
RULING, SENDBACK, MEMORY_READ, MEMORY_WRITE, TRAP_INJECTION, LIMIT_HIT, ERROR)
with automatic secret redaction, robust persistence, and query support.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from backend.models import AgentRole, LogEvent, LogEventType

logger = logging.getLogger("logbook")

SECRET_KEY_PATTERNS = [
    re.compile(r"^api[_-]?key$", re.IGNORECASE),
    re.compile(r"^auth(?:orization)?$", re.IGNORECASE),
    re.compile(r"^secret$", re.IGNORECASE),
    re.compile(r"^token$", re.IGNORECASE),
    re.compile(r"^password$", re.IGNORECASE),
    re.compile(r"^passwd$", re.IGNORECASE),
    re.compile(r"^credentials?$", re.IGNORECASE),
    re.compile(r"^bearer$", re.IGNORECASE),
    re.compile(r".*_key$", re.IGNORECASE),
    re.compile(r".*_token$", re.IGNORECASE),
    re.compile(r".*_secret$", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
]


def redact_secrets(obj: Any) -> Any:
    """Recursively redacts API keys, tokens, and authorization secrets from log payloads."""
    if isinstance(obj, str):
        # Redact Anthropic keys, bearer tokens, or secret patterns
        s = re.sub(r"sk-ant-[a-zA-Z0-9_\-]{10,}", "[REDACTED_API_KEY]", obj)
        s = re.sub(
            r"((?:bearer|token|api[_-]?key|password|secret))\s*[:=]\s*[^\s,;&\"']+",
            r"\1=[REDACTED]",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"(Authorization:\s*Bearer\s+)[^\s,;&\"']+",
            r"\1[REDACTED]",
            s,
            flags=re.IGNORECASE,
        )
        return s
    elif isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            k_str = str(k)
            if any(pat.match(k_str) for pat in SECRET_KEY_PATTERNS):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = redact_secrets(v)
        return clean
    elif isinstance(obj, (list, tuple, set)):
        return [redact_secrets(item) for item in obj]
    elif isinstance(obj, BaseModel):
        return redact_secrets(obj.model_dump())
    return obj


class LogBook:
    """Audit logbook persisting to SQLite and JSONL."""

    def __init__(self, db_path: Optional[str] = None, jsonl_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("LOGBOOK_DB_PATH", ":memory:")
        self.jsonl_path = jsonl_path or os.getenv("LOGBOOK_JSONL_PATH", None)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initializes SQLite schema for append-only audit trail."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    run_num INTEGER NOT NULL,
                    round_num INTEGER NOT NULL,
                    agent TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_case_id ON audit_events (case_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON audit_events (event_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent ON audit_events (agent)")
            self._conn.commit()

    def log(
        self,
        event_type: LogEventType | str,
        agent: AgentRole | str,
        case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        run_num: int = 1,
        round_num: int = 1,
        event_id: Optional[str] = None,
    ) -> LogEvent:
        """Records an event into both SQLite and JSONL audit logs with secret redaction."""
        e_type = LogEventType(event_type) if isinstance(event_type, str) else event_type
        a_role = AgentRole(agent) if isinstance(agent, str) else agent

        safe_payload = redact_secrets(payload or {})
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        eid = event_id or f"EVT-{uuid.uuid4().hex[:10]}"

        event = LogEvent(
            event_id=eid,
            case_id=case_id,
            run_num=run_num,
            round_num=round_num,
            agent=a_role,
            event_type=e_type,
            payload=safe_payload,
            timestamp=now_ts,
        )

        payload_json = json.dumps(safe_payload, default=str)

        # 1. Append to SQLite
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, case_id, run_num, round_num, agent, event_type, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.case_id,
                        event.run_num,
                        event.round_num,
                        event.agent.value,
                        event.event_type.value,
                        payload_json,
                        event.timestamp,
                    ),
                )
                self._conn.commit()
        except Exception as e:
            raise RuntimeError(f"Audit logbook SQLite write failed for event '{eid}': {e}") from e

        # 2. Append to JSONL file if path is specified
        if self.jsonl_path:
            try:
                line = json.dumps(event.model_dump(), default=str) + "\n"
                with open(self.jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                raise RuntimeError(f"Audit logbook JSONL write failed for event '{eid}': {e}") from e

        return event

    def get_events(
        self,
        case_id: Optional[str] = None,
        event_type: Optional[LogEventType | str] = None,
        agent: Optional[AgentRole | str] = None,
    ) -> List[LogEvent]:
        """Queries logged events filtered by case_id, event_type, or agent."""
        query = "SELECT event_id, case_id, run_num, round_num, agent, event_type, payload_json, timestamp FROM audit_events WHERE 1=1"
        params: List[Any] = []

        if case_id:
            query += " AND case_id = ?"
            params.append(case_id)
        if event_type:
            e_val = event_type.value if isinstance(event_type, LogEventType) else str(event_type)
            query += " AND event_type = ?"
            params.append(e_val)
        if agent:
            a_val = agent.value if isinstance(agent, AgentRole) else str(agent)
            query += " AND agent = ?"
            params.append(a_val)

        query += " ORDER BY timestamp ASC"

        events: List[LogEvent] = []
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        for r in rows:
            eid, cid, r_num, rnd_num, ag_str, et_str, p_json, ts = r
            events.append(
                LogEvent(
                    event_id=eid,
                    case_id=cid,
                    run_num=r_num,
                    round_num=rnd_num,
                    agent=AgentRole(ag_str),
                    event_type=LogEventType(et_str),
                    payload=json.loads(p_json),
                    timestamp=ts,
                )
            )
        return events

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass


# Shared default logbook instance
default_logbook = LogBook()


def log_event(
    event_type: LogEventType | str,
    agent: AgentRole | str,
    case_id: str,
    payload: Optional[Dict[str, Any]] = None,
    run_num: int = 1,
    round_num: int = 1,
) -> LogEvent:
    """Convenience functional interface for logging audit events."""
    return default_logbook.log(
        event_type=event_type,
        agent=agent,
        case_id=case_id,
        payload=payload,
        run_num=run_num,
        round_num=round_num,
    )
