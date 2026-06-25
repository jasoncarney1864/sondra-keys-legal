"""
FastAPI application initialization and configuration.
Main entry point for the Sondra Keys Legal Q&A backend.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import structlog

from backend.app.core.config import settings
from backend.app.api.routes import documents, query, health

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Configure root logger
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=getattr(logging, settings.logging.log_level),
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for application startup and shutdown events.
    """
    # Startup
    logger.info(
        "application_startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
    yield
    # Shutdown
    logger.info("application_shutdown")


# Initialize FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="Document Q&A backend with plain-English legal explanations",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
    openapi_url="/api/openapi.json" if settings.debug else None,
)

# Security middleware: Trusted hosts only
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1"],
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)


# ============================================================================
# Exception Handlers
# ============================================================================


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    logger.warning(
        "validation_error",
        error=str(exc),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc), "error_type": "validation_error"},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle unexpected errors."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_type": "internal_error"},
    )


# ============================================================================
# API Routes
# ============================================================================

# Health check
app.include_router(health.router, prefix="/health", tags=["health"])

# Document management
app.include_router(
    documents.router,
    prefix="/api/documents",
    tags=["documents"],
)

# Q&A queries
app.include_router(
    query.router,
    prefix="/api/query",
    tags=["query"],
)


# ============================================================================
# Root Endpoint
# ============================================================================


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "documentation": "/api/docs" if settings.debug else None,
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.logging.log_level.lower(),
    )
