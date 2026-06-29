"""
FastAPI application initialization and configuration.
Main entry point for the Sondra Keys Legal Q&A backend.
"""

import logging
import os
import sys
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import aiohttp
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import APIKeyHeader
from sqlalchemy import delete, select, update

import structlog

from backend.app.core.config import settings
from backend.app.core.database import async_session_maker, get_engine, init_db
from backend.app.api.routes import documents, query, health, hud, sessions
from backend.app.core.exception_handlers import (
    blob_not_found_handler,
    document_validation_handler,
    extraction_engine_handler,
    file_size_exceeded_handler,
    llm_rate_limit_handler,
    llm_service_handler,
    sondra_base_handler,
    storage_service_handler,
    unsupported_file_type_handler,
)
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
from backend.app.models.db import DocumentRecordORM, ProcessingStatus, UserSessionORM
from backend.app.services.document_processor import DocumentProcessor

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
logging.getLogger("azure").setLevel(logging.WARNING)

logger = structlog.get_logger(__name__)

INDEX_SANITY_LOCK_FILE = "/tmp/startup_index_sanity_check.lock"
SESSION_RETENTION_LOCK_FILE = "/tmp/startup_session_retention_cleanup.lock"


async def validate_azure_openai_deployments() -> None:
    """
    Validate that configured Azure OpenAI deployments exist and are accessible.

    Performs lightweight API calls to verify:
    - Chat completion deployment (AI_OPENAI_DEPLOYMENT_NAME)
    - Embedding deployment (OPENAI_EMBEDDING_MODEL)

    Logs warnings for missing deployments but does not fail startup.
    This allows the service to start even if Azure OpenAI is temporarily
    unavailable, with graceful degradation via fallback responses.
    """
    from openai import AsyncAzureOpenAI, APIStatusError

    logger.info("azure_openai_deployment_validation_started")

    client = AsyncAzureOpenAI(
        api_key=settings.ai.openai_api_key,
        api_version=settings.ai.openai_api_version,
        azure_endpoint=str(settings.ai.openai_endpoint),
    )

    chat_deployment = settings.ai.openai_deployment_name
    embedding_deployment = settings.openai.embedding_model
    issues = []

    # Test chat completion deployment
    try:
        await client.chat.completions.create(
            model=chat_deployment,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        logger.info(
            "azure_openai_chat_deployment_validated",
            deployment=chat_deployment,
        )
    except APIStatusError as e:
        if e.status_code == 404:
            error_msg = (
                f"Azure OpenAI chat deployment '{chat_deployment}' not found. "
                f"Check AI_OPENAI_DEPLOYMENT_NAME configuration. "
                f"Queries will return fallback context-only responses."
            )
            logger.error(
                "azure_openai_chat_deployment_not_found",
                deployment=chat_deployment,
                endpoint=str(settings.ai.openai_endpoint),
                error=str(e),
            )
            issues.append(error_msg)
        else:
            logger.warning(
                "azure_openai_chat_deployment_check_failed",
                deployment=chat_deployment,
                status=e.status_code,
                error=str(e),
            )
    except Exception as e:
        logger.warning(
            "azure_openai_chat_deployment_check_error",
            deployment=chat_deployment,
            error=f"{type(e).__name__}: {e}",
        )

    # Test embedding deployment
    try:
        await client.embeddings.create(
            model=embedding_deployment,
            input=["test"],
        )
        logger.info(
            "azure_openai_embedding_deployment_validated",
            deployment=embedding_deployment,
        )
    except APIStatusError as e:
        if e.status_code == 404:
            error_msg = (
                f"Azure OpenAI embedding deployment '{embedding_deployment}' not found. "
                f"Check OPENAI_EMBEDDING_MODEL configuration or create a deployment. "
                f"Document indexing and queries will use zero-vector fallback."
            )
            logger.error(
                "azure_openai_embedding_deployment_not_found",
                deployment=embedding_deployment,
                endpoint=str(settings.ai.openai_endpoint),
                error=str(e),
            )
            issues.append(error_msg)
        else:
            logger.warning(
                "azure_openai_embedding_deployment_check_failed",
                deployment=embedding_deployment,
                status=e.status_code,
                error=str(e),
            )
    except Exception as e:
        logger.warning(
            "azure_openai_embedding_deployment_check_error",
            deployment=embedding_deployment,
            error=f"{type(e).__name__}: {e}",
        )

    await client.close()

    if issues:
        logger.error(
            "azure_openai_deployment_validation_completed_with_issues",
            issue_count=len(issues),
        )
        for idx, issue in enumerate(issues, 1):
            logger.error(f"azure_openai_deployment_issue_{idx}", message=issue)
    else:
        logger.info("azure_openai_deployment_validation_completed")
PARSED_JSON_RETENTION_LOCK_FILE = "/tmp/startup_parsed_json_retention_cleanup.lock"


def log_database_persistence_context() -> None:
    """Emit startup diagnostics for DB persistence configuration."""
    db_url = settings.database.database_url

    logger.info(
        "database_configuration_detected",
        database_url=db_url,
    )

    if db_url.startswith("sqlite") and "/tmp/" in db_url:
        logger.warning(
            "database_persistence_risk_detected",
            reason="sqlite_path_in_tmp",
            recommendation=(
                "Use a persistent path (for containers, mount host storage and "
                "set DB_DATABASE_URL to sqlite+aiosqlite:////workspace/data/legal_qa.db)."
            ),
        )


async def reconcile_stale_processing_states() -> int:
    """Mark interrupted in-progress documents as FAILED during startup."""
    recovery_message = (
        "Recovered during startup: previous processing was interrupted before completion."
    )

    async with async_session_maker() as session:
        result = await session.execute(
            update(DocumentRecordORM)
            .where(
                DocumentRecordORM.processing_status.in_(
                    [
                        ProcessingStatus.EXTRACTING,
                        ProcessingStatus.CHUNKING,
                        ProcessingStatus.INDEXING,
                    ]
                )
            )
            .values(
                processing_status=ProcessingStatus.FAILED,
                error_message=recovery_message,
                completed_timestamp=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    return int(result.rowcount or 0)


def _uuid_version(value: str) -> int | None:
    """Return UUID version or None when value is not a valid UUID."""
    try:
        return UUID(value).version
    except Exception:
        return None


def _choose_canonical_document_id(document_ids: list[str]) -> str:
    """Prefer deterministic UUIDv5 IDs when selecting canonical doc identity."""
    uuid5_ids = [doc_id for doc_id in document_ids if _uuid_version(doc_id) == 5]
    preferred_ids = uuid5_ids or document_ids
    return sorted(preferred_ids)[0]


def _acquire_startup_index_sanity_lock() -> bool:
    """Allow only one worker per container to run index sanity checks."""
    return _acquire_startup_lock(
        INDEX_SANITY_LOCK_FILE,
        lock_name="startup_index_sanity_check",
    )


def _acquire_startup_lock(lock_file: str, *, lock_name: str) -> bool:
    """Create a startup lock file so only one worker runs a maintenance task."""
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception as e:
        # Fail open: run the check if lock creation had an unexpected issue.
        logger.warning(
            f"{lock_name}_lock_failed_open",
            error_detail=str(e)[:300],
        )
        return True


async def cleanup_expired_user_sessions() -> int:
    """Remove expired user sessions during startup maintenance."""
    if not settings.user_session_retention_cleanup_enabled:
        logger.info(
            "startup_expired_sessions_cleanup_skipped",
            reason="disabled",
        )
        return 0

    if not _acquire_startup_lock(
        SESSION_RETENTION_LOCK_FILE,
        lock_name="startup_expired_sessions_cleanup",
    ):
        logger.info(
            "startup_expired_sessions_cleanup_skipped",
            reason="another_worker_already_ran_cleanup",
        )
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.user_session_retention_grace_minutes,
    )

    try:
        async with async_session_maker() as session:
            result = await session.execute(
                delete(UserSessionORM).where(UserSessionORM.expires_at < cutoff)
            )
            await session.commit()
    except Exception as e:
        logger.error(
            "startup_expired_sessions_cleanup_failed",
            error_detail=str(e)[:500],
            exc_info=True,
        )
        return 0

    deleted_count = int(result.rowcount or 0)
    logger.info(
        "startup_expired_sessions_cleanup_completed",
        deleted_count=deleted_count,
        cutoff_iso=cutoff.isoformat(),
        grace_minutes=settings.user_session_retention_grace_minutes,
    )
    return deleted_count


async def run_parsed_json_retention_cleanup() -> None:
    """Apply startup retention policy to stale parsed JSON cache references."""
    if not settings.parsed_json_cache_enabled:
        logger.info(
            "startup_parsed_json_retention_cleanup_skipped",
            reason="parsed_json_cache_disabled",
        )
        return

    if not settings.parsed_json_retention_cleanup_enabled:
        logger.info(
            "startup_parsed_json_retention_cleanup_skipped",
            reason="disabled",
        )
        return

    if not _acquire_startup_lock(
        PARSED_JSON_RETENTION_LOCK_FILE,
        lock_name="startup_parsed_json_retention_cleanup",
    ):
        logger.info(
            "startup_parsed_json_retention_cleanup_skipped",
            reason="another_worker_already_ran_cleanup",
        )
        return

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.parsed_json_retention_days,
    )

    try:
        async with async_session_maker() as session:
            stale_stmt = select(DocumentRecordORM).where(
                DocumentRecordORM.parsed_json_blob_name.is_not(None),
                DocumentRecordORM.parsed_json_cached_at.is_not(None),
                DocumentRecordORM.parsed_json_cached_at < cutoff,
            )
            stale_docs = (await session.execute(stale_stmt)).scalars().all()

            candidate_count = len(stale_docs)
            deleted_blob_count = 0
            missing_blob_count = 0
            failed_blob_delete_count = 0
            cleared_reference_count = 0

            if stale_docs and settings.parsed_json_retention_delete_blobs:
                processor = DocumentProcessor()
                for doc in stale_docs:
                    blob_name = (doc.parsed_json_blob_name or "").strip()
                    if not blob_name:
                        continue

                    delete_succeeded = False
                    try:
                        await processor.delete_blob(blob_name)
                        deleted_blob_count += 1
                        delete_succeeded = True
                    except BlobNotFoundException:
                        missing_blob_count += 1
                        delete_succeeded = True
                    except Exception as e:
                        failed_blob_delete_count += 1
                        logger.warning(
                            "startup_parsed_json_retention_blob_delete_failed",
                            document_id=str(doc.id),
                            blob_name=blob_name,
                            error_detail=str(e)[:300],
                        )

                    if delete_succeeded:
                        doc.parsed_json_blob_name = None
                        doc.parser_version = None
                        doc.parsed_json_cached_at = None
                        cleared_reference_count += 1

                if cleared_reference_count:
                    await session.commit()

            logger.info(
                "startup_parsed_json_retention_cleanup_completed",
                candidate_count=candidate_count,
                delete_enabled=settings.parsed_json_retention_delete_blobs,
                retention_days=settings.parsed_json_retention_days,
                cutoff_iso=cutoff.isoformat(),
                deleted_blob_count=deleted_blob_count,
                missing_blob_count=missing_blob_count,
                failed_blob_delete_count=failed_blob_delete_count,
                cleared_reference_count=cleared_reference_count,
            )
    except Exception as e:
        logger.error(
            "startup_parsed_json_retention_cleanup_failed",
            error_detail=str(e)[:500],
            exc_info=True,
        )
        return


def _detect_duplicate_index_groups(
    index_docs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Identify same-content duplicate document IDs grouped by file and chunk set."""
    by_file_name: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))

    for doc in index_docs:
        file_name = str(doc.get("file_name") or "").strip()
        document_id = str(doc.get("document_id") or "").strip()
        chunk_index = doc.get("chunk_index")

        if not file_name or not document_id or not isinstance(chunk_index, int):
            continue

        by_file_name[file_name][document_id].add(chunk_index)

    duplicate_groups: list[dict[str, object]] = []

    for file_name, chunks_by_document_id in by_file_name.items():
        if len(chunks_by_document_id) < 2:
            continue

        by_fingerprint: dict[tuple[int, ...], list[str]] = defaultdict(list)
        for document_id, chunk_indices in chunks_by_document_id.items():
            fingerprint = tuple(sorted(chunk_indices))
            by_fingerprint[fingerprint].append(document_id)

        for chunk_fingerprint, document_ids in by_fingerprint.items():
            if len(document_ids) < 2:
                continue

            canonical_document_id = _choose_canonical_document_id(document_ids)
            duplicate_document_ids = sorted(
                doc_id for doc_id in document_ids if doc_id != canonical_document_id
            )

            duplicate_groups.append(
                {
                    "file_name": file_name,
                    "chunk_count": len(chunk_fingerprint),
                    "canonical_document_id": canonical_document_id,
                    "canonical_uuid_version": _uuid_version(canonical_document_id),
                    "duplicate_document_ids": duplicate_document_ids,
                }
            )

    return duplicate_groups


async def _fetch_index_documents_for_sanity(page_size: int) -> list[dict[str, object]]:
    """Read index documents in pages for startup sanity checks."""
    endpoint = f"https://{settings.azure.search_service_name}.search.windows.net"
    url = (
        f"{endpoint}/indexes/{settings.azure.search_index_name}"
        "/docs/search?api-version=2023-11-01"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": settings.azure.search_api_key,
    }

    scanned_docs: list[dict[str, object]] = []
    skip = 0

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            body = {
                "search": "*",
                "select": "id,document_id,file_name,chunk_index",
                "top": page_size,
                "skip": skip,
            }

            async with session.post(url, headers=headers, json=body) as response:
                if response.status != 200:
                    response_text = (await response.text())[:500]
                    raise RuntimeError(
                        f"Index scan failed with status={response.status}: {response_text}"
                    )

                payload = await response.json(content_type=None)

            batch = payload.get("value", [])
            scanned_docs.extend(batch)

            if len(batch) < page_size:
                break

            skip += page_size

    return scanned_docs


async def run_startup_index_sanity_check() -> None:
    """Detect duplicate index identities and optionally clean safe groups."""
    if not settings.startup_index_sanity_check_enabled:
        logger.info(
            "startup_index_sanity_check_skipped",
            reason="disabled",
        )
        return

    if not _acquire_startup_index_sanity_lock():
        logger.info(
            "startup_index_sanity_check_skipped",
            reason="another_worker_already_ran_check",
        )
        return

    try:
        index_docs = await _fetch_index_documents_for_sanity(
            page_size=settings.startup_index_sanity_page_size,
        )
    except Exception as e:
        logger.error(
            "startup_index_sanity_check_scan_failed",
            error_detail=str(e)[:500],
            exc_info=True,
        )
        return

    duplicate_groups = _detect_duplicate_index_groups(index_docs)
    duplicate_document_ids_total = sum(
        len(group["duplicate_document_ids"]) for group in duplicate_groups
    )

    for group in duplicate_groups:
        logger.warning(
            "startup_index_duplicate_group_detected",
            file_name=group["file_name"],
            chunk_count=group["chunk_count"],
            canonical_document_id=group["canonical_document_id"],
            duplicate_document_ids=group["duplicate_document_ids"],
        )

    cleanup_attempted = 0
    cleanup_succeeded = 0
    cleanup_skipped_unsafe = 0
    cleanup_failed = 0

    if settings.startup_index_sanity_auto_cleanup_duplicates and duplicate_groups:
        from backend.app.services.search import AzureAISearchService

        search_service = AzureAISearchService()

        for group in duplicate_groups:
            canonical_uuid_version = group["canonical_uuid_version"]
            duplicate_document_ids = list(group["duplicate_document_ids"])

            if canonical_uuid_version != 5:
                cleanup_skipped_unsafe += len(duplicate_document_ids)
                logger.warning(
                    "startup_index_duplicate_cleanup_skipped",
                    reason="canonical_document_id_not_uuid5",
                    file_name=group["file_name"],
                    canonical_document_id=group["canonical_document_id"],
                    duplicate_document_ids=duplicate_document_ids,
                )
                continue

            for duplicate_document_id in duplicate_document_ids:
                cleanup_attempted += 1
                try:
                    await search_service.delete_document_chunks(duplicate_document_id)
                    cleanup_succeeded += 1
                    logger.warning(
                        "startup_index_duplicate_cleanup_applied",
                        removed_document_id=duplicate_document_id,
                        kept_document_id=group["canonical_document_id"],
                        file_name=group["file_name"],
                    )
                except Exception as e:
                    cleanup_failed += 1
                    logger.error(
                        "startup_index_duplicate_cleanup_failed",
                        removed_document_id=duplicate_document_id,
                        kept_document_id=group["canonical_document_id"],
                        file_name=group["file_name"],
                        error_detail=str(e)[:500],
                        exc_info=True,
                    )

    logger.info(
        "startup_index_sanity_check_completed",
        scanned_chunks=len(index_docs),
        duplicate_groups=len(duplicate_groups),
        duplicate_document_ids=duplicate_document_ids_total,
        cleanup_enabled=settings.startup_index_sanity_auto_cleanup_duplicates,
        cleanup_attempted=cleanup_attempted,
        cleanup_succeeded=cleanup_succeeded,
        cleanup_skipped_unsafe=cleanup_skipped_unsafe,
        cleanup_failed=cleanup_failed,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for application startup and shutdown events.

    Startup:
    - Initialize database schema (create tables if not exist)

    Shutdown:
    - Dispose async engine connection pool
    """
    # Startup
    logger.info(
        "application_startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
    log_database_persistence_context()

    # Initialize database schema
    try:
        await init_db()
        logger.info("database_schema_initialized")
        reconciled_count = await reconcile_stale_processing_states()
        logger.info(
            "startup_stale_state_reconciliation_completed",
            reconciled_count=reconciled_count,
        )
        await cleanup_expired_user_sessions()
        await run_parsed_json_retention_cleanup()
        await run_startup_index_sanity_check()
        await validate_azure_openai_deployments()
    except Exception as e:
        logger.error(f"database_init_failed: {type(e).__name__}: {e}", exc_info=True)

    yield

    # Shutdown
    logger.info("application_shutdown")
    try:
        engine = get_engine()
        await engine.dispose()
        logger.info("database_engine_disposed")
    except Exception as e:
        logger.error(f"database_disposal_failed: {type(e).__name__}: {e}", exc_info=True)

# Define the security scheme for Swagger documentation
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Initialize FastAPI application ONE time with the security dependency
app = FastAPI(
    title=settings.app_name,
    description="Document Q&A backend with plain-English legal explanations",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
    openapi_url="/api/openapi.json" if settings.debug else None,
    # This line forces the global Authorize button to appear
    dependencies=[Depends(api_key_header)] if settings.debug else None,
)

# Security middleware: Trusted hosts only
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.security.trusted_hosts,
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
#
# Registration order: most-specific subtypes first so Starlette matches
# the tightest handler before falling through to parent-class handlers.
# ============================================================================

# --- Validation layer (413 / 400) ---
app.add_exception_handler(FileSizeExceededException, file_size_exceeded_handler)
app.add_exception_handler(UnsupportedFileTypeException, unsupported_file_type_handler)
app.add_exception_handler(DocumentValidationException, document_validation_handler)

# --- Storage layer (404 / 503) ---
app.add_exception_handler(BlobNotFoundException, blob_not_found_handler)
app.add_exception_handler(StorageServiceException, storage_service_handler)

# --- Extraction layer (503) ---
app.add_exception_handler(ExtractionEngineException, extraction_engine_handler)

# --- LLM layer (429 / 503) ---
app.add_exception_handler(LLMRateLimitException, llm_rate_limit_handler)
app.add_exception_handler(LLMServiceException, llm_service_handler)

# --- Safety net (500) ---
app.add_exception_handler(SondraBaseException, sondra_base_handler)


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

# User sessions
app.include_router(
    sessions.router,
    prefix="/api/sessions",
    tags=["sessions"],
)

# HUD sources and sync
app.include_router(
    hud.router,
    prefix="/api/hud",
    tags=["hud"],
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
