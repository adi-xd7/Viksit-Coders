"""FastAPI Application Entry Point for RAGNAROK PS3 Supply Chain Disruption Analyzer."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers.health import router as health_router, check_corpus_available
from backend.app.routers.cases import router as cases_router
from backend.app.schemas.api import ErrorResponse

logger = logging.getLogger("ragnarok.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for startup and shutdown resource auditing."""
    corpus_ok = check_corpus_available()
    status_str = "accessible" if corpus_ok else "not found (using mock fallback)"
    logger.info("RAGNAROK Courtroom Analyzer API started. Runemark corpus: %s", status_str)
    yield
    logger.info("RAGNAROK Courtroom Analyzer API shutting down.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title="RAGNAROK: Supply Chain Disruption Courtroom Analyzer",
        version="1.0.0",
        description=(
            "Adversarial Multi-Agent Courtroom System (Heimdall, Loki, Thor, Odin) "
            "evaluating supply chain disruptions with bounded sufficiency feedback loops "
            "and evidence-grounded executive briefing generation."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Enable CORS for frontend UI interaction
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handlers
    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        logger.warning("Validation error on %s: %s", request.url.path, str(exc))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(
                detail=str(exc),
                error_code="VALIDATION_ERROR",
            ).model_dump(),
        )

    @application.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception on %s: %s", request.url.path, str(exc), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                detail="An internal server error occurred during analysis.",
                error_code="INTERNAL_SERVER_ERROR",
            ).model_dump(),
        )

    # Root informational route
    @application.get(
        "/",
        tags=["System"],
        summary="API Root Information",
        description="Root entry point providing service metadata and documentation links.",
    )
    def root_info() -> dict[str, str]:
        return {
            "service": "RAGNAROK: Supply Chain Disruption Courtroom Analyzer",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
            "cases": "/cases",
        }

    # Register Routers (both root and /api/v1 prefixes for developer convenience)
    application.include_router(health_router)
    application.include_router(cases_router)

    # Also expose under /api/v1 prefix
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(cases_router, prefix="/api/v1")

    return application


app = create_app()
