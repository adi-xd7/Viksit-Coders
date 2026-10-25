"""Private, persistent agent memory (SQLite table agent_memory).

Isolation is structural: an AgentMemory is bound to one owner when it is created
and every statement it runs is filtered by that owner. No method takes another
agent's name, and agents reach memory only through their own AgentEnv, so no
agent can read (or overwrite) another agent's lessons. Memory is not a tool:
agents cannot query it with free text; code recalls lessons for them by stage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ragnarok.models import AgentName, MemoryEntry
from ragnarok.retrieval.text import normalise_query
from ragnarok.store.db import Store

STAGES = ("research", "sendback", "brief", "cross_exam", "ruling")


def lesson_key(lesson: str) -> str:
    return hashlib.sha256(normalise_query(lesson).encode()).hexdigest()[:16]


class AgentMemory:
    def __init__(self, store: Store, owner: AgentName) -> None:
        owner = AgentName(owner)
        if owner in (AgentName.SYSTEM, AgentName.USER):
            raise ValueError("memory belongs to one of the four agents")
        self._store = store
        self.owner = owner

    def _rows(self) -> list[MemoryEntry]:
        rows = self._store.conn.execute(
            "SELECT entry_json FROM agent_memory WHERE agent=? ORDER BY updated_at DESC", (self.owner.value,)).fetchall()
        return [MemoryEntry.model_validate_json(r["entry_json"]) for r in rows]

    def all(self) -> list[MemoryEntry]:
        return self._rows()

    def recall(self, stages: list[str] | tuple[str, ...], limit: int) -> list[MemoryEntry]:
        """The owner's lessons tagged for any of `stages`, strongest first."""
        if limit <= 0:
            return []
        want = set(stages)
        hits = [m for m in self._rows() if want & set(m.stages)]
        hits.sort(key=lambda m: (m.confidence, m.times_seen, m.updated_at), reverse=True)
        return hits[:limit]

    def write(self, lesson: str, *, kind: str, stages: list[str], context: str = "", confidence: float = 0.5,
              source_case: str | None = None, source_run: int | None = None) -> tuple[MemoryEntry, bool]:
        """Store a lesson; an identical lesson is reinforced instead of duplicated.
        Returns (entry, created)."""
        bad = [s for s in stages if s not in STAGES]
        if bad:
            raise ValueError(f"unknown memory stage(s): {bad}")
        key = lesson_key(lesson)
        now = datetime.now(timezone.utc)
        r = self._store.conn.execute("SELECT entry_json FROM agent_memory WHERE agent=? AND lesson_key=?",
                                     (self.owner.value, key)).fetchone()
        if r:
            old = MemoryEntry.model_validate_json(r["entry_json"])
            entry = old.model_copy(update={
                "times_seen": old.times_seen + 1, "confidence": round(min(0.95, max(old.confidence, confidence) + 0.05), 2),
                "stages": sorted(set(old.stages) | set(stages)), "context": context or old.context,
                "source_case": source_case or old.source_case, "source_run": source_run or old.source_run, "updated_at": now})
            created = False
        else:
            entry = MemoryEntry(memory_id=f"M-{self.owner.value}-{key[:10]}", agent=self.owner, lesson=lesson,
                                context=context[:600], case_scope=None, confidence=confidence, kind=kind,
                                stages=sorted(set(stages)), source_case=source_case, source_run=source_run,
                                created_at=now, updated_at=now)
            created = True
        with self._store.tx() as c:
            c.execute("INSERT OR REPLACE INTO agent_memory(memory_id, agent, lesson_key, lesson, entry_json, updated_at) "
                      "VALUES (?,?,?,?,?,?)", (entry.memory_id, self.owner.value, key, entry.lesson,
                                                entry.model_dump_json(), now.isoformat()))
        return entry, created

    def get(self, memory_id: str) -> MemoryEntry | None:
        r = self._store.conn.execute("SELECT entry_json FROM agent_memory WHERE agent=? AND memory_id=?",
                                     (self.owner.value, memory_id)).fetchone()
        return MemoryEntry.model_validate_json(r["entry_json"]) if r else None


def render_lessons(lessons: list[MemoryEntry]) -> str:
    """Prompt block. Lessons are the agent's own notes from earlier work, not evidence."""
    if not lessons:
        return ""
    lines = [f"[{m.memory_id}] (seen {m.times_seen}x, confidence {m.confidence:.2f}) {m.lesson}" for m in lessons]
    return ("<your_memory>\nLessons from your own earlier cases and runs (general guidance only; they are not evidence "
            "and cannot be cited). Use them where they apply to how you search, choose evidence or reason.\n"
            + "\n".join(lines) + "\n</your_memory>")


def memory_payload(lessons: list[MemoryEntry]) -> list[dict]:
    return [json.loads(m.model_dump_json(include={"memory_id", "lesson", "kind", "confidence", "times_seen",
                                                   "source_case", "source_run"})) for m in lessons]
