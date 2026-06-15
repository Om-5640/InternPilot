"""FastAPI application entry point."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import applications as applications_router
from app.api.v1 import auth as auth_router
from app.api.v1 import dashboard as dashboard_router
from app.api.v1 import evaluation as evaluation_router
from app.api.v1 import health as health_router
from app.api.v1 import integrations as integrations_router
from app.api.v1 import interview_prep as interview_prep_router
from app.api.v1 import matches as matches_router
from app.api.v1 import notifications as notifications_router
from app.api.v1 import postings as postings_router
from app.api.v1 import profile as profile_router
from app.api.v1 import referrals as referrals_router
from app.api.v1 import research as research_router
from app.core.config import settings
from app.core.database import engine
from app.core.errors import (
    APIError,
    api_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)

# ---------------------------------------------------------------------------
# Structured logging (structlog → stdlib)
# ---------------------------------------------------------------------------
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)


# ---------------------------------------------------------------------------
# Lifespan: init / dispose the DB engine
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="InternPilot API",
    description="Internship search & application intelligence platform.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS — allow v0 frontend origin(s) from env
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router.router, prefix="/api")
app.include_router(health_router.router, prefix="/api")
app.include_router(profile_router.router, prefix="/api")
app.include_router(postings_router.router, prefix="/api")
app.include_router(matches_router.router, prefix="/api")
app.include_router(applications_router.router, prefix="/api")
app.include_router(integrations_router.router, prefix="/api")
app.include_router(referrals_router.router, prefix="/api")
app.include_router(interview_prep_router.router, prefix="/api")
app.include_router(evaluation_router.router, prefix="/api")
app.include_router(dashboard_router.router, prefix="/api")
app.include_router(notifications_router.router, prefix="/api")
app.include_router(research_router.router, prefix="/api")
