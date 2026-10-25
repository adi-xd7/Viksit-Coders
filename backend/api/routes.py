"""FastAPI route definitions for Odin Courtroom."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.api.schemas import (
    CaseListResponse,
    CaseResponse,
    CreateCaseRequest,
    ErrorResponse,
    HealthResponse,
    RulingsResponse,
    StartTrialRequest,
    TrialStatusResponse,
)
from backend.api.service import (
    AwaitingResearchError,
    BriefingNotReadyError,
    CaseNotFoundError,
    ServiceError,
    TrialConflictError,
    TrialNotFoundError,
    TrialService,
    default_trial_service,
)
from backend.models import Briefing

logger = logging.getLogger("api")

router = APIRouter()


def get_trial_service(request: Request) -> TrialService:
    """Dependency provider for TrialService."""
    if hasattr(request.app.state, "trial_service") and request.app.state.trial_service is not None:
        return request.app.state.trial_service
    return default_trial_service


def validate_id_str(val: str, name: str) -> str:
    """Validates alphanumeric identifier format to prevent path traversal."""
    if not val or not re.match(r"^[A-Za-z0-9_\-]+$", val):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_IDENTIFIER", "message": f"{name} contains invalid characters."},
        )
    if len(val) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_IDENTIFIER", "message": f"{name} exceeds maximum length of 64."},
        )
    return val


# =============================================================================
# Health Check Endpoint
# =============================================================================
@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
    description="Reports API process status and database connectivity.",
)
def health_check(service: TrialService = Depends(get_trial_service)) -> HealthResponse:
    db_ok = True
    try:
        db_ok = service.case_store.check_health()
    except Exception as e:
        logger.error("Database health check error: %s", e)
        db_ok = False

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version="1.0.0",
        process="healthy",
        database="healthy" if db_ok else "unhealthy",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


# =============================================================================
# Case Endpoints
# =============================================================================
@router.post(
    "/api/cases",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Cases"],
    summary="Create a new case",
    description="Registers a new supply-chain disruption case for trial analysis.",
)
def create_case(
    payload: CreateCaseRequest,
    service: TrialService = Depends(get_trial_service),
) -> CaseResponse:
    try:
        record = service.create_case(
            query=payload.query,
            as_of=payload.as_of,
            case_id=payload.case_id,
            target_country_sector_pairs=payload.target_country_sector_pairs,
        )
        return CaseResponse(
            case_id=record.case_id,
            query=record.query,
            as_of=record.as_of,
            verification_status=record.verification_status,
            verification_reason=record.verification_reason,
            target_country_sector_pairs=record.target_country_sector_pairs,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    except ServiceError as e:
        if e.error_code == "CASE_ALREADY_EXISTS":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": e.error_code, "message": e.message},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": e.error_code, "message": e.message},
        )
    except Exception as e:
        logger.exception("Unexpected error creating case")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Failed to create case due to an internal server error."},
        )


@router.get(
    "/api/cases",
    response_model=CaseListResponse,
    tags=["Cases"],
    summary="List investigation cases",
    description="Retrieves a paginated list of cases sorted by creation time descending.",
)
def list_cases(
    limit: int = Query(default=20, ge=1, le=100, description="Page limit (1 to 100)"),
    offset: int = Query(default=0, ge=0, description="Offset index"),
    service: TrialService = Depends(get_trial_service),
) -> CaseListResponse:
    records, total = service.list_cases(limit=limit, offset=offset)
    items = [
        CaseResponse(
            case_id=r.case_id,
            query=r.query,
            as_of=r.as_of,
            verification_status=r.verification_status,
            verification_reason=r.verification_reason,
            target_country_sector_pairs=r.target_country_sector_pairs,
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in records
    ]
    return CaseListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/cases/{case_id}",
    response_model=CaseResponse,
    tags=["Cases"],
    summary="Retrieve case details",
    description="Returns metadata and current status for an investigation case.",
)
def get_case(
    case_id: str,
    service: TrialService = Depends(get_trial_service),
) -> CaseResponse:
    validate_id_str(case_id, "case_id")
    try:
        record = service.get_case(case_id)
        return CaseResponse(
            case_id=record.case_id,
            query=record.query,
            as_of=record.as_of,
            verification_status=record.verification_status,
            verification_reason=record.verification_reason,
            target_country_sector_pairs=record.target_country_sector_pairs,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )


# =============================================================================
# Trial Execution Endpoints
# =============================================================================
@router.post(
    "/api/cases/{case_id}/trials",
    response_model=TrialStatusResponse,
    tags=["Trials"],
    summary="Initiate a trial run",
    description="Starts or queues a LangGraph courtroom trial for an existing case.",
)
async def start_trial(
    case_id: str,
    request: Request,
    payload: Optional[StartTrialRequest] = None,
    service: TrialService = Depends(get_trial_service),
) -> TrialStatusResponse:
    validate_id_str(case_id, "case_id")
    opts = payload or StartTrialRequest()

    try:
        trial = await service.start_trial(
            case_id=case_id,
            max_runs=opts.max_runs or 3,
            max_rounds=opts.max_rounds or 2,
            background=bool(opts.background),
        )
        return TrialStatusResponse(
            case_id=trial.case_id,
            trial_id=trial.trial_id,
            status=trial.status,
            current_node=trial.current_node,
            run_count=trial.run_count,
            max_runs=trial.max_runs,
            start_time=trial.start_time,
            end_time=trial.end_time,
            is_awaiting_research=trial.is_awaiting_research,
            is_completed=trial.is_completed,
            error_message=trial.error_message,
        )
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )
    except TrialConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": e.error_code, "message": e.message},
        )
    except Exception as e:
        logger.exception("Unexpected error executing trial for case %s", case_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Failed to start trial due to an internal server error."},
        )


@router.get(
    "/api/cases/{case_id}/trials/{trial_id}",
    response_model=TrialStatusResponse,
    tags=["Trials"],
    summary="Retrieve trial execution status",
    description="Returns current execution status and timestamps for a trial.",
)
def get_trial_status(
    case_id: str,
    trial_id: str,
    service: TrialService = Depends(get_trial_service),
) -> TrialStatusResponse:
    validate_id_str(case_id, "case_id")
    validate_id_str(trial_id, "trial_id")

    try:
        trial = service.get_trial_status(case_id=case_id, trial_id=trial_id)
        return TrialStatusResponse(
            case_id=trial.case_id,
            trial_id=trial.trial_id,
            status=trial.status,
            current_node=trial.current_node,
            run_count=trial.run_count,
            max_runs=trial.max_runs,
            start_time=trial.start_time,
            end_time=trial.end_time,
            is_awaiting_research=trial.is_awaiting_research,
            is_completed=trial.is_completed,
            error_message=trial.error_message,
        )
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )
    except TrialNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TRIAL_NOT_FOUND", "message": f"Trial '{trial_id}' not found for case '{case_id}'."},
        )


# =============================================================================
# Artifact Endpoints (Rulings & Briefing)
# =============================================================================
@router.get(
    "/api/cases/{case_id}/trials/{trial_id}/rulings",
    response_model=RulingsResponse,
    tags=["Rulings"],
    summary="Retrieve Odin's final rulings",
    description="Returns all binding judicial rulings produced by Odin for the specified trial.",
)
def get_trial_rulings(
    case_id: str,
    trial_id: str,
    service: TrialService = Depends(get_trial_service),
) -> RulingsResponse:
    validate_id_str(case_id, "case_id")
    validate_id_str(trial_id, "trial_id")

    try:
        rulings = service.get_trial_rulings(case_id=case_id, trial_id=trial_id)
        return RulingsResponse(
            case_id=case_id,
            trial_id=trial_id,
            rulings_count=len(rulings),
            rulings=rulings,
        )
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )
    except TrialNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TRIAL_NOT_FOUND", "message": f"Trial '{trial_id}' not found."},
        )
    except BriefingNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": e.error_code, "message": e.message},
        )


@router.get(
    "/api/cases/{case_id}/trials/{trial_id}/briefing",
    response_model=Briefing,
    tags=["Briefings"],
    summary="Retrieve validated trial briefing",
    description="Returns the Phase 5 judicial intelligence briefing with all sections and verified citations.",
)
def get_trial_briefing(
    case_id: str,
    trial_id: str,
    service: TrialService = Depends(get_trial_service),
) -> Briefing:
    validate_id_str(case_id, "case_id")
    validate_id_str(trial_id, "trial_id")

    try:
        briefing = service.get_trial_briefing(case_id=case_id, trial_id=trial_id)
        return briefing
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )
    except TrialNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TRIAL_NOT_FOUND", "message": f"Trial '{trial_id}' not found."},
        )
    except AwaitingResearchError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": e.error_code, "message": e.message},
        )
    except BriefingNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": e.error_code, "message": e.message},
        )
    except ServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": e.error_code, "message": e.message},
        )


@router.get(
    "/api/cases/{case_id}/trials/{trial_id}/submission",
    tags=["Submission"],
    summary="Retrieve complete submission deliverables package",
    description="Returns the official submission bundle (Final Output & Execution Trace) labeled per evaluation rubric.",
)
def get_submission_deliverables(
    case_id: str,
    trial_id: str,
    service: TrialService = Depends(get_trial_service),
) -> dict:
    validate_id_str(case_id, "case_id")
    validate_id_str(trial_id, "trial_id")

    try:
        deliverables = service.get_submission_deliverables(case_id=case_id, trial_id=trial_id)
        return deliverables
    except CaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )
    except TrialNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TRIAL_NOT_FOUND", "message": f"Trial '{trial_id}' not found."},
        )
    except Exception as e:
        logger.exception("Failed to assemble submission deliverables for %s / %s", case_id, trial_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "SUBMISSION_ASSEMBLY_FAILED", "message": str(e)},
        )

