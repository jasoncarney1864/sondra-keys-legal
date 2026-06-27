"""
Global exception handlers for the Sondra Keys Legal API.

Each handler maps one layer of the custom exception hierarchy to a
specific HTTP status code and a safe, client-facing ErrorResponse body.
Internal error details (cloud SDK traces, raw messages) are logged server-
side but never surfaced in API responses.

Registration order in main.py matters: more-specific subtypes must be
registered BEFORE their parent classes so Starlette matches the tightest
handler first.

  FileSizeExceededException   → 413
  UnsupportedFileTypeException → 400
  DocumentValidationException  → 400  (catch-all for the validation branch)
  BlobNotFoundException        → 404
  StorageServiceException      → 503  (covers BlobUploadException, BlobDeleteException)
  ExtractionEngineException    → 503  (covers DocumentIntelligenceException, ExtractionTimeoutException)
  LLMRateLimitException        → 429
  LLMServiceException          → 503  (covers LLMContextLengthException)
  SondraBaseException          → 500  (safety net for any unhandled subtype)
"""

import structlog

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.app.core.exceptions import (
    BlobNotFoundException,
    DocumentValidationException,
    ExtractionEngineException,
    FileSizeExceededException,
    LLMRateLimitException,
    LLMServiceException,
    SondraBaseException,
    StorageServiceException,
    UnsupportedFileTypeException,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _error_body(error_type: str, detail: str, request: Request) -> dict:
    """Build the canonical ErrorResponse payload (matches ErrorResponse schema)."""
    return {
        "error_type": error_type,
        "detail": detail,
        "request_id": request.headers.get("X-Request-ID"),
    }


# ---------------------------------------------------------------------------
# Validation layer  (413 / 400)
# ---------------------------------------------------------------------------


async def file_size_exceeded_handler(
    request: Request, exc: FileSizeExceededException
) -> JSONResponse:
    logger.warning(
        "file_size_exceeded",
        path=request.url.path,
        internal_detail=exc.detail,
    )
    return JSONResponse(
        status_code=413,
        content=_error_body("file_size_exceeded", exc.message, request),
    )


async def unsupported_file_type_handler(
    request: Request, exc: UnsupportedFileTypeException
) -> JSONResponse:
    logger.warning(
        "unsupported_file_type",
        path=request.url.path,
        internal_detail=exc.detail,
    )
    return JSONResponse(
        status_code=400,
        content=_error_body("unsupported_file_type", exc.message, request),
    )


async def document_validation_handler(
    request: Request, exc: DocumentValidationException
) -> JSONResponse:
    """Catch-all for any DocumentValidationException not handled by a subtype handler."""
    logger.warning(
        "document_validation_error",
        path=request.url.path,
        internal_detail=exc.detail,
    )
    return JSONResponse(
        status_code=400,
        content=_error_body("document_validation_error", exc.message, request),
    )


# ---------------------------------------------------------------------------
# Storage layer  (404 / 503)
# ---------------------------------------------------------------------------


async def blob_not_found_handler(
    request: Request, exc: BlobNotFoundException
) -> JSONResponse:
    logger.warning(
        "blob_not_found",
        path=request.url.path,
        internal_detail=exc.detail,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body("blob_not_found", exc.message, request),
    )


async def storage_service_handler(
    request: Request, exc: StorageServiceException
) -> JSONResponse:
    """Covers BlobUploadException and BlobDeleteException as well."""
    logger.error(
        "storage_service_error",
        path=request.url.path,
        internal_detail=exc.detail,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content=_error_body(
            "storage_unavailable",
            "Storage service is temporarily unavailable. Please try again shortly.",
            request,
        ),
    )


# ---------------------------------------------------------------------------
# Extraction layer  (503)
# ---------------------------------------------------------------------------


async def extraction_engine_handler(
    request: Request, exc: ExtractionEngineException
) -> JSONResponse:
    """Covers DocumentIntelligenceException and ExtractionTimeoutException."""
    logger.error(
        "extraction_engine_error",
        path=request.url.path,
        internal_detail=exc.detail,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content=_error_body(
            "extraction_unavailable",
            "Document extraction service is temporarily unavailable. Please try again shortly.",
            request,
        ),
    )


# ---------------------------------------------------------------------------
# LLM layer  (429 / 503)
# ---------------------------------------------------------------------------


async def llm_rate_limit_handler(
    request: Request, exc: LLMRateLimitException
) -> JSONResponse:
    logger.warning("llm_rate_limit", path=request.url.path)
    return JSONResponse(
        status_code=429,
        content=_error_body(
            "llm_rate_limit",
            "AI service rate limit reached. Please retry in a few seconds.",
            request,
        ),
    )


async def llm_service_handler(
    request: Request, exc: LLMServiceException
) -> JSONResponse:
    """Covers LLMContextLengthException and any other LLMServiceException subtype."""
    logger.error(
        "llm_service_error",
        path=request.url.path,
        internal_detail=exc.detail,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content=_error_body(
            "llm_unavailable",
            "AI service is temporarily unavailable. Please try again shortly.",
            request,
        ),
    )


# ---------------------------------------------------------------------------
# Safety net  (500)
# ---------------------------------------------------------------------------


async def sondra_base_handler(
    request: Request, exc: SondraBaseException
) -> JSONResponse:
    """Catches any SondraBaseException subtype that escaped a more-specific handler."""
    logger.error(
        "unhandled_application_error",
        path=request.url.path,
        internal_detail=exc.detail,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_error", "An unexpected error occurred.", request),
    )
