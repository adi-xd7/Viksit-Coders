"""FastAPI application entry point for Trial of the Nine Realms (Odin Courtroom)."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# Bootstrap project root so file can be run directly (python backend/app.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.api.routes import router
from backend.api.service import TrialService, default_trial_service

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")


def create_app(service: Optional[TrialService] = None) -> FastAPI:
    """Application factory for Odin Courtroom FastAPI server."""
    application = FastAPI(
        title="Trial of the Nine Realms: Odin Courtroom API",
        version="1.0.0",
        description=(
            "Autonomous judicial supply chain disruption impact analyzer. "
            "Exposes case registration, LangGraph trial execution, Odin rulings, and verified intelligence briefings."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Attach service to application state
    application.state.trial_service = service or default_trial_service

    # Enable CORS for frontend clients
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handlers
    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # If detail is already a dict with error and message, preserve it
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            payload = exc.detail
        else:
            payload = {
                "error": "HTTP_ERROR",
                "message": str(exc.detail),
            }
        return JSONResponse(status_code=exc.status_code, content=payload)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Format Pydantic validation errors cleanly without exposing internal details
        err_messages = []
        clean_errors = []
        for err in exc.errors():
            loc = " -> ".join([str(l) for l in err.get("loc", [])])
            msg = err.get("msg", "Invalid value")
            err_messages.append(f"{loc}: {msg}")
            clean_errors.append({
                "loc": [str(l) for l in err.get("loc", [])],
                "msg": str(msg),
                "type": str(err.get("type", "value_error")),
            })

        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "; ".join(err_messages),
                "details": clean_errors,
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred.",
            },
        )

    # Register API Routes
    application.include_router(router)

    # Serve Dashboard UI
    static_index = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_index):
        @application.get("/", include_in_schema=False)
        @application.get("/dashboard", include_in_schema=False)
        async def serve_dashboard():
            return FileResponse(static_index, media_type="text/html")

    return application


# Canonical app instance for uvicorn
app = create_app()


def main():
    """Runs the FastAPI server locally on port 8000: python -m backend.app or python backend/app.py"""
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True, app_dir=PROJECT_ROOT)


if __name__ == "__main__":
    main()
