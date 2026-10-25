"""Thread-safe in-memory case and result repository (Part 8)."""

import threading
from typing import Optional

from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.executive_briefing import ExecutiveBriefing


class InMemoryCaseStore:
    """
    Thread-safe repository holding cases, debate results, and executive briefings in memory.

    NOTE: As per the existing project specification, storage is in-memory for the duration
    of the process. Results do not persist across server restarts.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cases: dict[str, CaseFile] = {}
        self._debate_results: dict[str, DebateResult] = {}
        self._briefings: dict[str, ExecutiveBriefing] = {}
        self._running_cases: set[str] = set()

    def register_case(self, case_file: CaseFile) -> CaseFile:
        """Register or update a CaseFile."""
        with self._lock:
            # Store a deep copy so external mutations do not affect repository state
            stored = case_file.model_copy(deep=True)
            self._cases[case_file.case_id] = stored
            return stored

    def get_case(self, case_id: str) -> Optional[CaseFile]:
        """Retrieve a CaseFile by case_id."""
        with self._lock:
            case = self._cases.get(case_id)
            return case.model_copy(deep=True) if case else None

    def list_cases(self) -> list[CaseFile]:
        """Return all registered CaseFiles in registration order."""
        with self._lock:
            return [c.model_copy(deep=True) for c in self._cases.values()]

    def store_debate_result(self, case_id: str, result: DebateResult) -> None:
        """Store the completed or partial DebateResult."""
        with self._lock:
            self._debate_results[case_id] = result.model_copy(deep=True)

    def get_debate_result(self, case_id: str) -> Optional[DebateResult]:
        """Retrieve DebateResult for a case_id."""
        with self._lock:
            res = self._debate_results.get(case_id)
            return res.model_copy(deep=True) if res else None

    def store_briefing(self, case_id: str, briefing: ExecutiveBriefing) -> None:
        """Cache an ExecutiveBriefing for a case_id."""
        with self._lock:
            self._briefings[case_id] = briefing.model_copy(deep=True)

    def get_briefing(self, case_id: str) -> Optional[ExecutiveBriefing]:
        """Retrieve cached ExecutiveBriefing for a case_id."""
        with self._lock:
            b = self._briefings.get(case_id)
            return b.model_copy(deep=True) if b else None

    def is_running(self, case_id: str) -> bool:
        """Check if an adversarial debate is currently executing for this case_id."""
        with self._lock:
            return case_id in self._running_cases

    def set_running(self, case_id: str, running: bool) -> None:
        """Mark a case_id as actively executing or idle."""
        with self._lock:
            if running:
                self._running_cases.add(case_id)
            else:
                self._running_cases.discard(case_id)

    def clear(self) -> None:
        """Reset repository state (primarily for isolated unit tests)."""
        with self._lock:
            self._cases.clear()
            self._debate_results.clear()
            self._briefings.clear()
            self._running_cases.clear()


# Global singleton instance for the FastAPI application lifecycle
default_case_store = InMemoryCaseStore()
