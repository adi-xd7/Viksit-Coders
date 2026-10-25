"""Case management and multi-agent debate routers (Part 8)."""

from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.executive_briefing import ExecutiveBriefing
from backend.app.schemas.feedback_loop import TrialRecord
from backend.app.schemas.api import (
    CaseCreateRequest,
    DebateRunRequest,
    CaseSummaryResponse,
    ErrorResponse,
)
from backend.app.services.case_store import InMemoryCaseStore, default_case_store
from backend.app.services.debate_orchestrator import DebateOrchestrator
from backend.app.services.executive_briefing import ExecutiveBriefingGenerator
from backend.app.services.retrieval import (
    BaseRetrievalService,
    RunemarkCorpusRetrievalService,
    MockRetrievalService,
)

router = APIRouter(prefix="/cases", tags=["Cases & Debates"])


def get_default_retrieval_service() -> BaseRetrievalService:
    """Resolve Runemark corpus directory if available, else fallback to mock."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[3] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if pack_dir.exists() and pack_dir.is_dir():
        return RunemarkCorpusRetrievalService(str(pack_dir))
    return MockRetrievalService()


def get_orchestrator() -> DebateOrchestrator:
    """Dependency provider for DebateOrchestrator."""
    return DebateOrchestrator(
        retrieval_service=get_default_retrieval_service(),
        max_retries=2,
    )


def get_briefing_generator() -> ExecutiveBriefingGenerator:
    """Dependency provider for ExecutiveBriefingGenerator."""
    return ExecutiveBriefingGenerator()


def get_case_store() -> InMemoryCaseStore:
    """Dependency provider for case and result repository."""
    return default_case_store


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "",
    response_model=CaseFile,
    status_code=status.HTTP_201_CREATED,
    summary="Register a CaseFile",
    description="Validate and register a new supply chain disruption case.",
    responses={
        400: {"model": ErrorResponse, "description": "Validation error in CaseFile parameters"},
    },
)
def create_case(
    request: CaseCreateRequest,
    store: InMemoryCaseStore = Depends(get_case_store),
) -> CaseFile:
    cid = request.case_id.strip()
    if not cid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="case_id must be a non-empty string.",
        )

    # Validate date strictly
    try:
        datetime.strptime(request.as_of_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid as_of_date format '{request.as_of_date}'. Expected YYYY-MM-DD.",
        )

    case_file = CaseFile(
        case_id=cid,
        question=request.question,
        as_of_date=request.as_of_date,
        event_id=request.event_id,
        is_verified=request.is_verified,
    )
    return store.register_case(case_file)


@router.get(
    "",
    response_model=list[CaseSummaryResponse],
    summary="List Registered Cases",
    description="Retrieve summaries of all registered cases and their debate/briefing completion status.",
)
def list_cases(
    store: InMemoryCaseStore = Depends(get_case_store),
) -> list[CaseSummaryResponse]:
    cases = store.list_cases()
    summaries: list[CaseSummaryResponse] = []

    for c in cases:
        deb_res = store.get_debate_result(c.case_id)
        brf = store.get_briefing(c.case_id)
        deb_status = deb_res.status if deb_res else None
        is_suff = None
        if deb_res and deb_res.odin_adjudication:
            is_suff = deb_res.odin_adjudication.is_evidence_sufficient

        summaries.append(CaseSummaryResponse(
            case_id=c.case_id,
            question=c.question,
            as_of_date=c.as_of_date,
            event_id=c.event_id,
            has_debate_result=deb_res is not None,
            has_briefing=brf is not None,
            debate_status=deb_status,
            is_evidence_sufficient=is_suff,
        ))

    return summaries


@router.get(
    "/{case_id}",
    response_model=CaseFile,
    summary="Get CaseFile Details",
    description="Retrieve a registered CaseFile by its unique case_id.",
    responses={
        404: {"model": ErrorResponse, "description": "Case not found"},
    },
)
def get_case(
    case_id: str,
    store: InMemoryCaseStore = Depends(get_case_store),
) -> CaseFile:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' was not found.",
        )
    return case


@router.post(
    "/{case_id}/debate",
    response_model=DebateResult,
    summary="Execute Adversarial Debate",
    description=(
        "Run the full multi-agent courtroom debate (Heimdall verification, Loki/Thor rounds, "
        "Odin judicial adjudication, and bounded sufficiency feedback loop). "
        "Automatically generates and caches the Executive Briefing upon completion."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Case not found"},
        409: {"model": ErrorResponse, "description": "Debate execution already in progress"},
        500: {"model": ErrorResponse, "description": "Fatal agent orchestration error"},
    },
)
async def run_debate(
    case_id: str,
    request: Optional[DebateRunRequest] = None,
    store: InMemoryCaseStore = Depends(get_case_store),
    orchestrator: DebateOrchestrator = Depends(get_orchestrator),
    briefing_gen: ExecutiveBriefingGenerator = Depends(get_briefing_generator),
) -> DebateResult:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found. Register the case before starting a debate.",
        )

    if store.is_running(case_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A debate for case '{case_id}' is already currently running.",
        )

    max_retries = request.max_retries if request else None

    store.set_running(case_id, True)
    try:
        # Offload synchronous multi-agent reasoning to threadpool
        debate_result: DebateResult = await run_in_threadpool(
            orchestrator.run_debate,
            case_file=case,
            max_retries=max_retries,
        )
        store.store_debate_result(case_id, debate_result)

        # Generate and cache executive briefing
        briefing = briefing_gen.generate_briefing(debate_result)
        store.store_briefing(case_id, briefing)

        return debate_result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fatal agent orchestration error during debate: {str(exc)}",
        )
    finally:
        store.set_running(case_id, False)


@router.get(
    "/{case_id}/results",
    response_model=DebateResult,
    summary="Retrieve Debate Results",
    description="Retrieve the completed DebateResult deliverable for a case.",
    responses={
        404: {"model": ErrorResponse, "description": "Case or debate results not found"},
    },
)
def get_debate_results(
    case_id: str,
    store: InMemoryCaseStore = Depends(get_case_store),
) -> DebateResult:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' was not found.",
        )

    res = store.get_debate_result(case_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No debate results found for case '{case_id}'. Execute debate first.",
        )
    return res


@router.get(
    "/{case_id}/briefing",
    response_model=ExecutiveBriefing,
    summary="Retrieve Executive Briefing",
    description="Retrieve or generate the authoritative human-readable Executive Briefing for a case.",
    responses={
        404: {"model": ErrorResponse, "description": "Case or required debate results not found"},
    },
)
def get_executive_briefing(
    case_id: str,
    store: InMemoryCaseStore = Depends(get_case_store),
    briefing_gen: ExecutiveBriefingGenerator = Depends(get_briefing_generator),
) -> ExecutiveBriefing:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' was not found.",
        )

    # Check cached briefing
    briefing = store.get_briefing(case_id)
    if briefing:
        return briefing

    # Otherwise generate from DebateResult if available
    res = store.get_debate_result(case_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No debate result available to generate an executive briefing for case '{case_id}'.",
        )

    briefing = briefing_gen.generate_briefing(res)
    store.store_briefing(case_id, briefing)
    return briefing


@router.get(
    "/{case_id}/trials",
    response_model=list[TrialRecord],
    summary="Retrieve Trial History",
    description="Retrieve the ordered trial records and sufficiency audit trace for a case.",
    responses={
        404: {"model": ErrorResponse, "description": "Case or debate trials not found"},
    },
)
def get_trial_history(
    case_id: str,
    store: InMemoryCaseStore = Depends(get_case_store),
) -> list[TrialRecord]:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' was not found.",
        )

    res = store.get_debate_result(case_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No debate trials found for case '{case_id}'. Execute debate first.",
        )
    return res.trial_history
