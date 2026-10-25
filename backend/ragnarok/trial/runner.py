"""Core case functions shared by the CLI and the API (no duplicate logic).

- run_case: run one trial to the end (blocking) on its own SQLite connection.
- CaseRunner: run cases in background threads (API), bounded concurrency.
- case_status / case_results: read a case's state and results from its saved
  files, so what the API reports is exactly what was persisted.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ragnarok.config import Settings
from ragnarok.llm.client import Backend
from ragnarok.models import AgentName, LogEvent, LogEventType
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store
from ragnarok.trial.machine import Stage, Trial, TrialResult, new_case_id

CASE_ID = re.compile(r"^case-[A-Za-z0-9-]{1,80}$")
TERMINAL = {Stage.DONE.value, Stage.STOPPED.value, Stage.FAILED.value}


def run_case(question: str, as_of: date, settings: Settings, *, service: RetrievalService | None = None,
             backend: Backend | None = None, case_id: str | None = None, stop_after: Stage | None = None) -> TrialResult:
    """Run one case to completion. `service` (if given) is forked so the case gets its own
    SQLite connection while sharing the loaded index and embedder."""
    svc = service.fork() if service is not None else RetrievalService(Store(settings.db_path), settings)
    try:
        trial = Trial(question, as_of, svc.store, settings, backend=backend, service=svc, case_id=case_id)
        return trial.run(stop_after)
    finally:
        svc.store.close()


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def case_dir(settings: Settings, case_id: str) -> Path:
    # The pattern allows only letters, digits and "-": no separators, dots or drive letters, so the
    # path cannot leave CASES_DIR. (No resolve() comparison: on Windows it changes once a folder exists.)
    if not CASE_ID.match(case_id):
        raise ValueError("invalid case id")
    return settings.cases_dir / case_id


def case_status(settings: Settings, case_id: str, running: bool = False) -> dict | None:
    """running | complete | partial | failed, plus the stage and briefing status behind it.
    partial = finished with an incomplete or partial briefing, or stopped (event disproved)."""
    d = case_dir(settings, case_id)
    state = _read(d / "state.json")
    if state is None:
        return {"case_id": case_id, "status": "running", "stage": "START"} if running else None
    stage, bstatus = state.get("stage"), state.get("briefing_status")
    if running and stage not in TERMINAL:
        status = "running"
    elif stage == Stage.DONE.value:
        status = "complete" if bstatus == "complete" else "partial"
    elif stage == Stage.STOPPED.value:
        status = "partial"
    elif stage == Stage.FAILED.value:
        status = "failed"
    elif state.get("stop_after"):
        status = "partial"  # stopped early on request (CLI --stop-after): finished, but no briefing
    else:
        status = "running" if running else "failed"  # not running and not finished: interrupted
    out = {"case_id": case_id, "status": status, "stage": stage, "briefing_status": bstatus,
           "question": state.get("question"), "as_of": state.get("as_of"), "history": state.get("history", []),
           "runs_completed": state.get("runs_completed", 0), "notes": state.get("notes", []),
           "stop_reason": state.get("stop_reason"), "usage": state.get("usage", {})}
    if status == "failed" and stage not in TERMINAL:
        out["notes"] = out["notes"] + ["case interrupted before it finished (process stopped)"]
    if (d / "limitations.md").exists():
        out["limitations"] = (d / "limitations.md").read_text(encoding="utf-8")
    return out


def case_results(settings: Settings, case_id: str) -> dict:
    d = case_dir(settings, case_id)
    md = d / "briefing.md"
    return {"briefing": _read(d / "briefing.json"), "briefing_markdown": md.read_text(encoding="utf-8") if md.exists() else None,
            "case_file": _read(d / "case_file.json"), "claims": _read(d / "claims.json"),
            "cross_exam": _read(d / "cross_exam.json"), "rulings": _read(d / "rulings.json"),
            "runs": sorted(p.name for p in d.glob("run-*") if p.is_dir())}


class CaseRunner:
    """Background trial threads for the API. Bounded by settings.max_concurrent_cases."""

    def __init__(self, settings: Settings, service_getter: Callable[[], RetrievalService],
                 backend_factory: Callable[[], Backend] | None = None) -> None:
        self.settings = settings
        self.service_getter = service_getter
        self.backend_factory = backend_factory
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    def running(self) -> list[str]:
        with self.lock:
            return [c for c, t in self.threads.items() if t.is_alive()]

    def is_running(self, case_id: str) -> bool:
        t = self.threads.get(case_id)
        return bool(t and t.is_alive())

    def start(self, question: str, as_of: date) -> str:
        with self.lock:
            if sum(t.is_alive() for t in self.threads.values()) >= self.settings.max_concurrent_cases:
                raise RuntimeError("too many cases running")
            case_id = new_case_id(question, as_of)
            service = self.service_getter()
            backend = self.backend_factory() if self.backend_factory else None
            t = threading.Thread(target=self._run, args=(question, as_of, case_id, service, backend), daemon=True,
                                 name=case_id)
            self.threads[case_id] = t
            t.start()
            return case_id

    def _run(self, question, as_of, case_id, service, backend) -> None:
        try:
            run_case(question, as_of, self.settings, service=service, backend=backend, case_id=case_id)
        except Exception as exc:  # noqa: BLE001 - recorded, never silent (Trial.run already records its own)
            with Store(self.settings.db_path) as s:
                s.append_event(LogEvent(case_id=case_id, agent=AgentName.SYSTEM, type=LogEventType.ERROR,
                                        summary=f"case runner error: {type(exc).__name__}: {exc}"[:500]))

    def join(self, case_id: str, timeout: float | None = None) -> None:
        t = self.threads.get(case_id)
        if t:
            t.join(timeout)
