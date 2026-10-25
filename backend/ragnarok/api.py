"""FastAPI entry point. Phase 0 exposes only a health check; endpoints are added per phase.

Run: .venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend
"""

from __future__ import annotations

from fastapi import FastAPI

from ragnarok import __version__
from ragnarok.config import get_settings

app = FastAPI(title="Trial of the Nine Realms", version=__version__)


@app.get("/api/health")
def health() -> dict[str, object]:
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "has_api_key": s.has_api_key,
        "models": {"fast": s.model_fast, "advocate": s.model_advocate, "judge": s.model_judge},
        "packs_dir_exists": s.packs_dir.is_dir(),
    }
