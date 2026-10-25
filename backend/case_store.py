"""Persistent case and trial registry for Odin Courtroom.

Persists cases, trial states, and artifacts (rulings, briefings) to SQLite
and file directories with thread-safe concurrency control and secret sanitization.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from backend.models import Briefing, CaseFile, EventVerificationStatus, Ruling
from backend.logbook import redact_secrets

logger = logging.getLogger("case_store")


class CaseRecord(BaseModel):
    """Metadata representation of a persisted investigation case."""
    case_id: str
    query: str
    as_of: str
    verification_status: str
    verification_reason: Optional[str] = None
    target_country_sector_pairs: List[Tuple[str, str]] = Field(default_factory=list)
    status: str = "created"  # created, running, completed, failed, awaiting_research
    created_at: str
    updated_at: str


class TrialRecord(BaseModel):
    """Execution status and metadata for a trial run."""
    trial_id: str
    case_id: str
    status: str  # pending, running, completed, failed, awaiting_research, limits_exhausted, incomplete, event_not_real
    current_node: Optional[str] = None
    run_count: int = 1
    max_runs: int = 3
    max_rounds: int = 2
    start_time: str
    end_time: Optional[str] = None
    is_awaiting_research: bool = False
    is_completed: bool = False
    error_message: Optional[str] = None
    snapshot_path: Optional[str] = None
    briefing_path: Optional[str] = None
    created_at: str
    updated_at: str


class CaseStore:
    """Thread-safe SQLite and file-backed case and trial registry."""

    def __init__(self, db_path: Optional[str] = None, output_dir: Optional[str] = None):
        self.output_dir = output_dir or os.path.join("logs", "cases")
        self.db_path = db_path or os.path.join(self.output_dir, "cases.db")
        self._lock = threading.Lock()
        self._running_cases: Set[str] = set()

        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            os.makedirs(self.output_dir, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initializes tables for cases, trials, and trial artifacts."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    verification_reason TEXT,
                    target_pairs_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_node TEXT,
                    run_count INTEGER NOT NULL,
                    max_runs INTEGER NOT NULL,
                    max_rounds INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    is_awaiting_research INTEGER NOT NULL,
                    is_completed INTEGER NOT NULL,
                    error_message TEXT,
                    snapshot_path TEXT,
                    briefing_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases (case_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trial_artifacts (
                    trial_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    rulings_json TEXT,
                    briefing_json TEXT,
                    final_state_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (trial_id) REFERENCES trials (trial_id)
                )
            """)
            self._conn.commit()

    def check_health(self) -> bool:
        """Verifies database connectivity and responsiveness."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            return row is not None and row[0] == 1

    # =========================================================================
    # Concurrency Lock Operations
    # =========================================================================
    def acquire_case_lock(self, case_id: str) -> bool:
        """Attempts to acquire exclusive execution lock for a case."""
        with self._lock:
            if case_id in self._running_cases:
                return False
            self._running_cases.add(case_id)
            return True

    def release_case_lock(self, case_id: str) -> None:
        """Releases the execution lock for a case."""
        with self._lock:
            self._running_cases.discard(case_id)

    def is_case_running(self, case_id: str) -> bool:
        """Checks if a trial is currently active for the case."""
        with self._lock:
            return case_id in self._running_cases

    # =========================================================================
    # Case Operations
    # =========================================================================
    def create_case(
        self,
        case_file: CaseFile,
        status: str = "created",
    ) -> CaseRecord:
        """Persists a new CaseFile record."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        target_pairs = getattr(case_file, "target_pairs", getattr(case_file, "target_country_sector_pairs", [])) or []
        pairs_json = json.dumps(target_pairs)

        with self._lock:
            # Check existing
            cursor = self._conn.cursor()
            cursor.execute("SELECT case_id FROM cases WHERE case_id = ?", (case_file.case_id,))
            if cursor.fetchone():
                raise ValueError(f"Case with ID '{case_file.case_id}' already exists.")

            cursor.execute(
                """
                INSERT INTO cases (
                    case_id, query, as_of, verification_status, verification_reason,
                    target_pairs_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_file.case_id,
                    case_file.query,
                    case_file.as_of,
                    case_file.verification_status.value if hasattr(case_file.verification_status, "value") else str(case_file.verification_status),
                    case_file.verification_reason,
                    pairs_json,
                    status,
                    now_iso,
                    now_iso,
                ),
            )
            self._conn.commit()

        # Save to filesystem if output directory is defined
        if self.output_dir and self.db_path != ":memory:":
            try:
                case_dir = os.path.join(self.output_dir, case_file.case_id)
                os.makedirs(case_dir, exist_ok=True)
                case_json_path = os.path.join(case_dir, "case.json")
                with open(case_json_path, "w", encoding="utf-8") as f:
                    json.dump(
                        redact_secrets({
                            "case_id": case_file.case_id,
                            "query": case_file.query,
                            "as_of": case_file.as_of,
                            "verification_status": case_file.verification_status.value if hasattr(case_file.verification_status, "value") else str(case_file.verification_status),
                            "verification_reason": case_file.verification_reason,
                            "target_country_sector_pairs": target_pairs,
                            "status": status,
                            "created_at": now_iso,
                            "updated_at": now_iso,
                        }),
                        f,
                        indent=2,
                    )
            except Exception as e:
                logger.warning("Failed to write case.json file for %s: %s", case_file.case_id, e)

        return CaseRecord(
            case_id=case_file.case_id,
            query=case_file.query,
            as_of=case_file.as_of,
            verification_status=case_file.verification_status.value if hasattr(case_file.verification_status, "value") else str(case_file.verification_status),
            verification_reason=case_file.verification_reason,
            target_country_sector_pairs=target_pairs,
            status=status,
            created_at=now_iso,
            updated_at=now_iso,
        )

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        """Retrieves a single case by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            if not row:
                return None

            return CaseRecord(
                case_id=row["case_id"],
                query=row["query"],
                as_of=row["as_of"],
                verification_status=row["verification_status"],
                verification_reason=row["verification_reason"],
                target_country_sector_pairs=json.loads(row["target_pairs_json"] or "[]"),
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_cases(self, limit: int = 20, offset: int = 0) -> Tuple[List[CaseRecord], int]:
        """Lists cases with stable ordering (created_at DESC) and pagination."""
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cases")
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT * FROM cases ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            )
            rows = cursor.fetchall()
            items = [
                CaseRecord(
                    case_id=r["case_id"],
                    query=r["query"],
                    as_of=r["as_of"],
                    verification_status=r["verification_status"],
                    verification_reason=r["verification_reason"],
                    target_country_sector_pairs=json.loads(r["target_pairs_json"] or "[]"),
                    status=r["status"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
            return items, total

    def update_case(
        self,
        case_id: str,
        status: Optional[str] = None,
        verification_status: Optional[str] = None,
        verification_reason: Optional[str] = None,
    ) -> Optional[CaseRecord]:
        """Updates case status and verification details."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            if not row:
                return None

            new_status = status or row["status"]
            new_v_stat = verification_status or row["verification_status"]
            new_v_reason = verification_reason if verification_reason is not None else row["verification_reason"]

            cursor.execute(
                """
                UPDATE cases
                SET status = ?, verification_status = ?, verification_reason = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (new_status, new_v_stat, new_v_reason, now_iso, case_id),
            )
            self._conn.commit()

            return CaseRecord(
                case_id=case_id,
                query=row["query"],
                as_of=row["as_of"],
                verification_status=new_v_stat,
                verification_reason=new_v_reason,
                target_country_sector_pairs=json.loads(row["target_pairs_json"] or "[]"),
                status=new_status,
                created_at=row["created_at"],
                updated_at=now_iso,
            )

    # =========================================================================
    # Trial Operations
    # =========================================================================
    def create_trial(
        self,
        case_id: str,
        trial_id: str,
        max_runs: int = 3,
        max_rounds: int = 2,
        status: str = "pending",
    ) -> TrialRecord:
        """Initializes a trial record for execution tracking."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO trials (
                    trial_id, case_id, status, current_node, run_count, max_runs, max_rounds,
                    start_time, end_time, is_awaiting_research, is_completed, error_message,
                    snapshot_path, briefing_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    case_id,
                    status,
                    None,
                    1,
                    max_runs,
                    max_rounds,
                    now_iso,
                    None,
                    0,
                    0,
                    None,
                    None,
                    None,
                    now_iso,
                    now_iso,
                ),
            )
            self._conn.commit()

        return TrialRecord(
            trial_id=trial_id,
            case_id=case_id,
            status=status,
            current_node=None,
            run_count=1,
            max_runs=max_runs,
            max_rounds=max_rounds,
            start_time=now_iso,
            end_time=None,
            is_awaiting_research=False,
            is_completed=False,
            error_message=None,
            snapshot_path=None,
            briefing_path=None,
            created_at=now_iso,
            updated_at=now_iso,
        )

    def get_trial(self, trial_id: str, case_id: Optional[str] = None) -> Optional[TrialRecord]:
        """Retrieves a trial record, enforcing optional case isolation."""
        with self._lock:
            cursor = self._conn.cursor()
            if case_id:
                cursor.execute("SELECT * FROM trials WHERE trial_id = ? AND case_id = ?", (trial_id, case_id))
            else:
                cursor.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,))
            row = cursor.fetchone()
            if not row:
                return None

            return TrialRecord(
                trial_id=row["trial_id"],
                case_id=row["case_id"],
                status=row["status"],
                current_node=row["current_node"],
                run_count=row["run_count"],
                max_runs=row["max_runs"],
                max_rounds=row["max_rounds"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                is_awaiting_research=bool(row["is_awaiting_research"]),
                is_completed=bool(row["is_completed"]),
                error_message=row["error_message"],
                snapshot_path=row["snapshot_path"],
                briefing_path=row["briefing_path"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_trials(self, case_id: str) -> List[TrialRecord]:
        """Lists all trials executed for a specific case."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM trials WHERE case_id = ? ORDER BY created_at DESC", (case_id,))
            rows = cursor.fetchall()
            return [
                TrialRecord(
                    trial_id=r["trial_id"],
                    case_id=r["case_id"],
                    status=r["status"],
                    current_node=r["current_node"],
                    run_count=r["run_count"],
                    max_runs=r["max_runs"],
                    max_rounds=r["max_rounds"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                    is_awaiting_research=bool(r["is_awaiting_research"]),
                    is_completed=bool(r["is_completed"]),
                    error_message=r["error_message"],
                    snapshot_path=r["snapshot_path"],
                    briefing_path=r["briefing_path"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    def update_trial(
        self,
        trial_id: str,
        status: Optional[str] = None,
        current_node: Optional[str] = None,
        run_count: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        is_awaiting_research: Optional[bool] = None,
        is_completed: Optional[bool] = None,
        error_message: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        briefing_path: Optional[str] = None,
    ) -> Optional[TrialRecord]:
        """Updates trial status and execution progress."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,))
            row = cursor.fetchone()
            if not row:
                return None

            new_status = status or row["status"]
            new_node = current_node if current_node is not None else row["current_node"]
            new_run_count = run_count if run_count is not None else row["run_count"]
            new_start = start_time or row["start_time"]
            new_end = end_time if end_time is not None else row["end_time"]
            new_awaiting = int(is_awaiting_research) if is_awaiting_research is not None else row["is_awaiting_research"]
            new_completed = int(is_completed) if is_completed is not None else row["is_completed"]
            new_error = error_message if error_message is not None else row["error_message"]
            new_snap = snapshot_path if snapshot_path is not None else row["snapshot_path"]
            new_brief = briefing_path if briefing_path is not None else row["briefing_path"]

            cursor.execute(
                """
                UPDATE trials
                SET status = ?, current_node = ?, run_count = ?, start_time = ?, end_time = ?,
                    is_awaiting_research = ?, is_completed = ?, error_message = ?,
                    snapshot_path = ?, briefing_path = ?, updated_at = ?
                WHERE trial_id = ?
                """,
                (
                    new_status,
                    new_node,
                    new_run_count,
                    new_start,
                    new_end,
                    new_awaiting,
                    new_completed,
                    new_error,
                    new_snap,
                    new_brief,
                    now_iso,
                    trial_id,
                ),
            )
            self._conn.commit()

            return TrialRecord(
                trial_id=trial_id,
                case_id=row["case_id"],
                status=new_status,
                current_node=new_node,
                run_count=new_run_count,
                max_runs=row["max_runs"],
                max_rounds=row["max_rounds"],
                start_time=new_start,
                end_time=new_end,
                is_awaiting_research=bool(new_awaiting),
                is_completed=bool(new_completed),
                error_message=new_error,
                snapshot_path=new_snap,
                briefing_path=new_brief,
                created_at=row["created_at"],
                updated_at=now_iso,
            )

    # =========================================================================
    # Artifact Operations (Rulings, Briefings)
    # =========================================================================
    def save_trial_artifacts(
        self,
        trial_id: str,
        case_id: str,
        rulings: Optional[List[Ruling]] = None,
        briefing: Optional[Briefing] = None,
        final_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stores final trial artifacts (rulings, briefing) with secret sanitization."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rulings_json = json.dumps([r.model_dump() for r in (rulings or [])]) if rulings is not None else None
        briefing_json = json.dumps(redact_secrets(briefing.model_dump())) if briefing is not None else None
        final_state_json = json.dumps(redact_secrets(final_state)) if final_state is not None else None

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO trial_artifacts (
                    trial_id, case_id, rulings_json, briefing_json, final_state_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (trial_id, case_id, rulings_json, briefing_json, final_state_json, now_iso),
            )
            self._conn.commit()

    def get_trial_rulings(self, trial_id: str, case_id: Optional[str] = None) -> Optional[List[Ruling]]:
        """Retrieves rulings produced in a trial."""
        with self._lock:
            cursor = self._conn.cursor()
            if case_id:
                cursor.execute(
                    "SELECT rulings_json FROM trial_artifacts WHERE trial_id = ? AND case_id = ?",
                    (trial_id, case_id),
                )
            else:
                cursor.execute("SELECT rulings_json FROM trial_artifacts WHERE trial_id = ?", (trial_id,))
            row = cursor.fetchone()
            if not row or not row["rulings_json"]:
                return None

            try:
                raw_list = json.loads(row["rulings_json"])
                return [Ruling.model_validate(item) for item in raw_list]
            except Exception as e:
                logger.error("Failed to parse rulings for trial %s: %s", trial_id, e)
                return None

    def get_trial_briefing(self, trial_id: str, case_id: Optional[str] = None) -> Optional[Briefing]:
        """Retrieves the Phase 5 Briefing generated for a trial."""
        with self._lock:
            cursor = self._conn.cursor()
            if case_id:
                cursor.execute(
                    "SELECT briefing_json FROM trial_artifacts WHERE trial_id = ? AND case_id = ?",
                    (trial_id, case_id),
                )
            else:
                cursor.execute("SELECT briefing_json FROM trial_artifacts WHERE trial_id = ?", (trial_id,))
            row = cursor.fetchone()
            if not row or not row["briefing_json"]:
                return None

            try:
                raw_dict = json.loads(row["briefing_json"])
                return Briefing.model_validate(raw_dict)
            except Exception as e:
                logger.error("Failed to parse briefing for trial %s: %s", trial_id, e)
                return None


# Default instance
default_case_store = CaseStore()
