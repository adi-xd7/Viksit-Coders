"""Health check endpoint router for RAGNAROK PS3 (Part 8)."""

from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter

from backend.app.schemas.api import HealthResponse

router = APIRouter(tags=["System"])


def check_corpus_available() -> bool:
    """Check if the official Runemark dev_pack_E5 corpus directory is accessible."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[3] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    return pack_dir.exists() and pack_dir.is_dir()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System Health & Readiness",
    description="Check responsiveness of the API service and accessibility of the Runemark corpus.",
)
def get_health() -> HealthResponse:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    corpus_ok = check_corpus_available()
    return HealthResponse(
        status="healthy",
        service="ragnarok-ps3-courtroom",
        version="1.0.0",
        timestamp=now_iso,
        corpus_available=corpus_ok,
        storage_type="in_memory",
    )
