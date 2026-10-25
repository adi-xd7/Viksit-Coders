"""Trial orchestration and business service layer for Odin Courtroom API."""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.case_store import CaseRecord, CaseStore, TrialRecord, default_case_store
from backend.logbook import LogBook, default_logbook
from backend.models import (
    AgentRole,
    Briefing,
    CaseFile,
    EventVerificationStatus,
    LogEventType,
    Ruling,
)
from backend.llm import LLMClient, default_llm_client
from backend.trial import TrialGraphBuilder, run_trial

logger = logging.getLogger("service")


class ServiceError(Exception):
    """Base domain service exception."""
    def __init__(self, message: str, error_code: str = "SERVICE_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class CaseNotFoundError(ServiceError):
    def __init__(self, case_id: str):
        super().__init__(f"Case '{case_id}' not found.", error_code="CASE_NOT_FOUND")


class TrialNotFoundError(ServiceError):
    def __init__(self, trial_id: str):
        super().__init__(f"Trial '{trial_id}' not found.", error_code="TRIAL_NOT_FOUND")


class TrialConflictError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, error_code="TRIAL_ALREADY_RUNNING")


class BriefingNotReadyError(ServiceError):
    def __init__(self, message: str = "Briefing is not ready: trial is still executing."):
        super().__init__(message, error_code="BRIEFING_NOT_READY")


class AwaitingResearchError(ServiceError):
    def __init__(self, message: str = "Briefing unavailable: investigation is awaiting additional research from Heimdall."):
        super().__init__(message, error_code="TRIAL_AWAITING_RESEARCH")


class TrialService:
    """Coordinates case management, trial execution, and artifact retrieval."""

    def __init__(
        self,
        case_store: Optional[CaseStore] = None,
        logbook: Optional[LogBook] = None,
        llm_client: Optional[LLMClient] = None,
        builder_factory: Optional[Callable[[], TrialGraphBuilder]] = None,
    ):
        self.case_store = case_store or default_case_store
        self.logbook = logbook or default_logbook
        self.llm_client = llm_client
        self.builder_factory = builder_factory

    # =========================================================================
    # Case Management
    # =========================================================================
    def create_case(
        self,
        query: str,
        as_of: str,
        case_id: Optional[str] = None,
        target_country_sector_pairs: Optional[List[Tuple[str, str]]] = None,
    ) -> CaseRecord:
        """Validates and persists a new CaseFile."""
        cid = case_id or f"CASE-{uuid.uuid4().hex[:8].upper()}"

        cf = CaseFile(
            case_id=cid,
            query=query,
            as_of=as_of,
            target_pairs=target_country_sector_pairs or [],
            verification_status=EventVerificationStatus.REAL,  # Initial assumption; verified by Heimdall during trial
        )

        try:
            record = self.case_store.create_case(cf, status="created")
        except ValueError as e:
            raise ServiceError(str(e), error_code="CASE_ALREADY_EXISTS")

        # Audit logging
        self.logbook.record_event(
            LogEventType.QUERY,
            case_id=cid,
            run_num=1,
            round_num=1,
            agent=AgentRole.ODIN,
            payload={"action": "case_created", "case_id": cid, "query": query, "as_of": as_of},
        )

        return record

    def get_case(self, case_id: str) -> CaseRecord:
        """Retrieves a case or raises CaseNotFoundError."""
        record = self.case_store.get_case(case_id)
        if not record:
            raise CaseNotFoundError(case_id)
        return record

    def list_cases(self, limit: int = 20, offset: int = 0) -> Tuple[List[CaseRecord], int]:
        """Lists cases with pagination."""
        return self.case_store.list_cases(limit=limit, offset=offset)

    # =========================================================================
    # Trial Execution
    # =========================================================================
    async def start_trial(
        self,
        case_id: str,
        max_runs: int = 3,
        max_rounds: int = 2,
        background: bool = False,
    ) -> TrialRecord:
        """Initiates a LangGraph trial run for a case."""
        case = self.get_case(case_id)

        # Check concurrent lock
        if not self.case_store.acquire_case_lock(case_id):
            raise TrialConflictError(f"A trial is already in progress for case '{case_id}'.")

        trial_id = f"TRIAL-{uuid.uuid4().hex[:8].upper()}"
        trial = self.case_store.create_trial(
            case_id=case_id,
            trial_id=trial_id,
            max_runs=max_runs,
            max_rounds=max_rounds,
            status="pending",
        )

        if background:
            # Asynchronous background task execution
            asyncio.create_task(self._run_trial_async(case=case, trial=trial))
            # Return immediate pending/running status
            return self.case_store.get_trial(trial_id) or trial

        # Synchronous execution
        await self._run_trial_async(case=case, trial=trial)
        updated = self.case_store.get_trial(trial_id)
        return updated or trial

    async def _run_trial_async(self, case: CaseRecord, trial: TrialRecord) -> None:
        """Executes the Phase 4 LangGraph trial and persists Phase 5 artifacts."""
        trial_id = trial.trial_id
        case_id = case.case_id

        try:
            self.case_store.update_trial(
                trial_id=trial_id,
                status="running",
                current_node="heimdall",
                start_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
            self.case_store.update_case(case_id, status="running")

            # Audit logging: TRIAL_STARTED
            self.logbook.record_event(
                LogEventType.QUERY,
                case_id=case_id,
                run_num=1,
                round_num=1,
                agent=AgentRole.ODIN,
                payload={"action": "trial_started", "trial_id": trial_id, "query": case.query, "as_of": case.as_of},
            )

            # Build graph using custom builder or standard factory
            llm = self.llm_client or default_llm_client
            if not llm.api_key and llm._mock_handler is None:
                import os
                if not os.getenv("ANTHROPIC_API_KEY"):
                    from backend.llm import deterministic_offline_adjudication
                    llm.set_mock_handler(deterministic_offline_adjudication)

            if self.builder_factory:
                builder = self.builder_factory()
            else:
                builder = TrialGraphBuilder(
                    llm_client=llm,
                    logbook=self.logbook,
                    output_dir=self.case_store.output_dir,
                )

            final_state = await run_trial(
                question=case.query,
                as_of=case.as_of,
                case_id=case_id,
                max_runs=trial.max_runs,
                max_rounds=trial.max_rounds,
                builder=builder,
            )

            overall_status = final_state.get("overall_status", "completed")
            rulings = final_state.get("rulings", [])
            briefing = final_state.get("briefing")

            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            is_awaiting = overall_status == "send_back_loop"
            is_completed = overall_status in ("ready_for_briefing", "terminated_limits_exhausted", "event_not_real", "incomplete")

            status_map = {
                "ready_for_briefing": "completed",
                "send_back_loop": "awaiting_research",
                "terminated_limits_exhausted": "limits_exhausted",
                "incomplete": "incomplete",
                "event_not_real": "event_not_real",
            }
            mapped_status = status_map.get(overall_status, overall_status)

            # Persist rulings, briefing, and state in CaseStore
            self.case_store.save_trial_artifacts(
                trial_id=trial_id,
                case_id=case_id,
                rulings=rulings,
                briefing=briefing,
                final_state=final_state,
            )

            # Update trial record
            self.case_store.update_trial(
                trial_id=trial_id,
                status=mapped_status,
                current_node=final_state.get("current_node", "briefing"),
                run_count=final_state.get("run_count", 1),
                end_time=now_iso,
                is_awaiting_research=is_awaiting,
                is_completed=is_completed,
                error_message=final_state.get("incomplete_reason") or (final_state.get("errors", [None])[0] if final_state.get("errors") else None),
                snapshot_path=final_state.get("persisted_snapshot_path"),
                briefing_path=final_state.get("persisted_briefing_path"),
            )

            # Update case record verification if updated by Heimdall
            case_file = final_state.get("case_file")
            v_stat = None
            v_reason = None
            if case_file:
                v_stat = case_file.verification_status.value if hasattr(case_file.verification_status, "value") else str(case_file.verification_status)
                v_reason = case_file.verification_reason

            self.case_store.update_case(
                case_id=case_id,
                status=mapped_status,
                verification_status=v_stat,
                verification_reason=v_reason,
            )

            # Audit logging: TRIAL_COMPLETED
            self.logbook.record_event(
                LogEventType.QUERY,
                case_id=case_id,
                run_num=final_state.get("run_count", 1),
                round_num=1,
                agent=AgentRole.ODIN,
                payload={"action": "trial_finished", "trial_id": trial_id, "status": mapped_status},
            )

        except Exception as e:
            logger.exception("Error during trial execution for trial %s", trial_id)
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            sanitized_err = f"Trial execution error: {type(e).__name__}"

            self.case_store.update_trial(
                trial_id=trial_id,
                status="failed",
                end_time=now_iso,
                is_completed=False,
                error_message=sanitized_err,
            )
            self.case_store.update_case(case_id, status="failed")

            # Audit logging: ERROR
            self.logbook.record_event(
                LogEventType.ERROR,
                case_id=case_id,
                run_num=1,
                round_num=1,
                agent=AgentRole.ODIN,
                payload={"action": "trial_failed", "trial_id": trial_id, "error": sanitized_err},
            )
        finally:
            self.case_store.release_case_lock(case_id)

    # =========================================================================
    # Trial Status & Artifact Retrieval
    # =========================================================================
    def get_trial_status(self, case_id: str, trial_id: str) -> TrialRecord:
        """Retrieves trial record with case isolation verification."""
        # Ensure case exists
        self.get_case(case_id)

        trial = self.case_store.get_trial(trial_id=trial_id, case_id=case_id)
        if not trial:
            raise TrialNotFoundError(trial_id)
        return trial

    def get_trial_rulings(self, case_id: str, trial_id: str) -> List[Ruling]:
        """Retrieves final Odin rulings for a trial."""
        trial = self.get_trial_status(case_id=case_id, trial_id=trial_id)

        if trial.status in ("pending", "running"):
            raise BriefingNotReadyError("Rulings are not ready: trial is still in progress.")

        rulings = self.case_store.get_trial_rulings(trial_id=trial_id, case_id=case_id)
        if rulings is None:
            # If trial failed or event was not_real before rulings were produced
            return []
        return rulings

    def get_trial_briefing(self, case_id: str, trial_id: str) -> Briefing:
        """Retrieves the Phase 5 Briefing for a completed trial."""
        trial = self.get_trial_status(case_id=case_id, trial_id=trial_id)

        if trial.status in ("pending", "running"):
            raise BriefingNotReadyError("Briefing is not ready: trial is still in progress.")

        if trial.is_awaiting_research or trial.status == "awaiting_research":
            raise AwaitingResearchError(
                "Briefing unavailable: investigation is awaiting additional research from Heimdall."
            )

        briefing = self.case_store.get_trial_briefing(trial_id=trial_id, case_id=case_id)
        if not briefing:
            raise ServiceError("No briefing was generated for this trial.", error_code="BRIEFING_NOT_AVAILABLE")

        return briefing


# Default instance
default_trial_service = TrialService()
