"""Agent Private Memory system.

Ensures strict agent memory isolation (Odin cannot read Thor or Loki memory),
sanitizes stored lessons, prevents secret leakage, and treats memories as untrusted data.
Supports in-memory and optional persistent SQLite storage.
"""

from __future__ import annotations

import datetime
import os
import re
import sqlite3
import threading
import uuid
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.models import AgentRole


class MemoryEntry(BaseModel):
    """Structured memory entry with full provenance."""
    memory_id: str = Field(default_factory=lambda: f"MEM-{uuid.uuid4().hex[:8]}")
    agent: AgentRole
    topic: Optional[str] = None
    lesson: str
    evidence: Optional[str] = None
    case_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


class MemoryAccessError(PermissionError):
    """Raised when an agent attempts to access another agent's private memory."""
    pass


def sanitize_lesson_text(text: str) -> str:
    """Sanitizes memory text to remove potential credentials or secrets."""
    if not text:
        return text
    # Redact Anthropic keys or long hex/base64 tokens
    s = re.sub(r"sk-ant-[a-zA-Z0-9_\-]{10,}", "[REDACTED_API_KEY]", text)
    # Redact Bearer tokens with space
    s = re.sub(r"\bBearer\s+[a-zA-Z0-9_\-\.]{10,}", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
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
    return s.strip()


class MemoryStore:
    """Thread-safe store for isolated agent memories with optional SQLite persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("MEMORY_DB_PATH", None)
        self._lock = threading.Lock()
        self._store: Dict[AgentRole, List[MemoryEntry]] = {
            AgentRole.HEIMDALL: [],
            AgentRole.THOR: [],
            AgentRole.LOKI: [],
            AgentRole.ODIN: [],
        }
        self._conn: Optional[sqlite3.Connection] = None
        if self.db_path:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initializes SQLite schema for agent memory persistence."""
        if not self._conn:
            return
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_memories (
                    memory_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    topic TEXT,
                    lesson TEXT NOT NULL,
                    evidence TEXT,
                    case_id TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_agent ON agent_memories (agent)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_topic ON agent_memories (topic)")
            self._conn.commit()

    def remember(
        self,
        agent: AgentRole | str,
        lesson: str,
        evidence: Optional[str] = None,
        topic: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> MemoryEntry:
        """Stores an evidence-backed judicial or advocacy lesson in the agent's private memory."""
        agent_role = AgentRole(agent) if isinstance(agent, str) else agent
        safe_lesson = sanitize_lesson_text(lesson)
        safe_evidence = sanitize_lesson_text(evidence) if evidence else None

        entry = MemoryEntry(
            agent=agent_role,
            topic=topic,
            lesson=safe_lesson,
            evidence=safe_evidence,
            case_id=case_id,
        )

        with self._lock:
            self._store[agent_role].append(entry)

            if self._conn:
                try:
                    cursor = self._conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO agent_memories (memory_id, agent, topic, lesson, evidence, case_id, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.memory_id,
                            entry.agent.value,
                            entry.topic,
                            entry.lesson,
                            entry.evidence,
                            entry.case_id,
                            entry.timestamp,
                        ),
                    )
                    self._conn.commit()
                except Exception as e:
                    raise RuntimeError(f"Memory store SQLite insert failed: {e}") from e

        return entry

    def recall(
        self,
        agent: Optional[AgentRole | str] = None,
        topic: Optional[str] = None,
        requesting_agent: Optional[AgentRole | str] = None,
        target_agent: Optional[AgentRole | str] = None,
    ) -> List[MemoryEntry]:
        """Recalls lessons from the agent's private memory.

        Strict Isolation Rule:
        An agent can ONLY recall their own memory. Attempting to read another agent's
        memory raises MemoryAccessError.
        """
        # Resolve target role and requesting role flexibly
        resolved_target = target_agent or agent
        if resolved_target is None:
            resolved_target = requesting_agent

        if resolved_target is None:
            raise ValueError("Must specify an agent to recall memories for.")

        target_role = AgentRole(resolved_target) if isinstance(resolved_target, str) else resolved_target
        req_role = (
            AgentRole(requesting_agent)
            if isinstance(requesting_agent, str)
            else (requesting_agent or target_role)
        )

        if req_role != target_role:
            raise MemoryAccessError(
                f"Agent '{req_role.value}' is not permitted to access private memory of agent '{target_role.value}'."
            )

        with self._lock:
            entries = list(self._store.get(req_role, []))

        if topic:
            topic_lower = topic.lower()
            return [
                e
                for e in entries
                if (e.topic and topic_lower in e.topic.lower()) or topic_lower in e.lesson.lower()
            ]
        return entries

    def clear(self, agent: Optional[AgentRole | str] = None) -> None:
        """Clears memory for testing."""
        with self._lock:
            if agent:
                role = AgentRole(agent) if isinstance(agent, str) else agent
                self._store[role] = []
            else:
                for k in self._store:
                    self._store[k] = []

    def close(self) -> None:
        """Closes the underlying SQLite connection if any."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass


# Shared singleton instance
default_memory_store = MemoryStore()


def remember(
    agent: AgentRole | str,
    lesson: str,
    evidence: Optional[str] = None,
    topic: Optional[str] = None,
    case_id: Optional[str] = None,
) -> MemoryEntry:
    """Convenience functional interface for remember."""
    return default_memory_store.remember(
        agent=agent,
        lesson=lesson,
        evidence=evidence,
        topic=topic,
        case_id=case_id,
    )


def recall(
    agent: AgentRole | str,
    topic: Optional[str] = None,
    requesting_agent: Optional[AgentRole | str] = None,
) -> List[MemoryEntry]:
    """Convenience functional interface for recall (self-access enforced)."""
    return default_memory_store.recall(
        agent=agent,
        topic=topic,
        requesting_agent=requesting_agent,
    )
