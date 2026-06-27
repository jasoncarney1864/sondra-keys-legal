"""
Asynchronous document processing pipeline orchestrator.

Manages the complete document lifecycle: blob upload → extraction →
chunking → embedding → search indexing → database persistence.

The orchestrator is stateless and reusable — a single instance can process
many documents concurrently via Background Tasks (or Celery in production).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.exceptions import SondraBaseException
from backend.app.models.db import DocumentRecordORM, DocumentChunkORM, ProcessingStatus
from backend.app.models.schemas import AnalysisResultSchema
from backend.app.services.interfaces import (
    AbstractDocumentService,
    AbstractChunker,
    AbstractSearchService,
)
from backend.app.utils.text_splitter import normalize_whitespace

import structlog
logger = structlog.get_logger(__name__)


def _default_parsed_json_blob_name(blob_name: str, document_id: UUID) -> str:
    """Build deterministic blob name for parsed-document JSON cache."""
    if blob_name.startswith("content/"):
        content_hash = blob_name.split("/", 1)[1]
        return f"{settings.parsed_json_cache_prefix}/{content_hash}.json"
    return f"{settings.parsed_json_cache_prefix}/{document_id}.json"


class DocumentPipelineOrchestrator:
    """
    Orchestrates the full document processing pipeline.

    Manages state transitions, database updates, and cleanup on failure.
    Designed to be called asynchronously from FastAPI's BackgroundTasks.
    """

    def __init__(
        self,
        document_service: AbstractDocumentService,
        chunker: AbstractChunker,
        search_service: AbstractSearchService,
    ):
        """
        Initialize with concrete service implementations.

        Args:
            document_service: Upload/extraction service
            chunker: Text splitting strategy
            search_service: Index/search operations
        """
        self.document_service = document_service
        self.chunker = chunker
        self.search_service = search_service

    async def run_pipeline(
        self,
        document_id: UUID,
        file_bytes: bytes,
        file_name: str,
        session_factory: async_sessionmaker,
    ) -> None:
        """
        Execute the complete document processing pipeline.

        Transitions: PENDING → EXTRACTING → CHUNKING → INDEXING → COMPLETED

        Args:
            document_id: Unique document identifier
            file_bytes: Raw file content
            file_name: Original filename for display
            session_factory: AsyncSessionMaker for database access

        On failure:
            - Rolls back current transaction
            - Marks document as FAILED
            - Stores error message in database
            - Logs full exception for debugging
        """
        session = None
        indexed_in_search = False
        compensation_cleanup_succeeded = False
        compensation_cleanup_error: str | None = None
        try:
            # Create a new session for this pipeline execution
            async with session_factory() as session:
                # Get the document record from database
                doc_record = await session.get(DocumentRecordORM, document_id)
                if not doc_record:
                    raise ValueError(f"Document {document_id} not found in database")

                # Idempotency guard: skip duplicate invocations for in-flight/completed docs.
                if doc_record.processing_status == ProcessingStatus.COMPLETED:
                    logger.info(
                        "pipeline_idempotent_skip",
                        document_id=str(document_id),
                        reason="already_completed",
                    )
                    return

                if doc_record.processing_status in {
                    ProcessingStatus.EXTRACTING,
                    ProcessingStatus.CHUNKING,
                    ProcessingStatus.INDEXING,
                }:
                    logger.info(
                        "pipeline_idempotent_skip",
                        document_id=str(document_id),
                        reason="already_in_progress",
                        state=doc_record.processing_status.value,
                    )
                    return

                # ================================================================
                # State 1: EXTRACTING
                # ================================================================
                logger.info(
                    "pipeline_state_transition",
                    document_id=str(document_id),
                    state="EXTRACTING",
                )

                doc_record.processing_status = ProcessingStatus.EXTRACTING
                await session.flush()

                # Upload to blob storage
                blob_result = await self.document_service.upload_to_blob(
                    file_bytes,
                    file_name=doc_record.blob_name,
                    content_type="application/octet-stream",
                )

                doc_record.blob_name = blob_result.blob_name
                doc_record.blob_url = str(blob_result.blob_url)

                analysis: AnalysisResultSchema
                parsed_cache_blob_name = (
                    doc_record.parsed_json_blob_name
                    or _default_parsed_json_blob_name(blob_result.blob_name, document_id)
                )

                cached_payload = None
                if settings.parsed_json_cache_enabled:
                    cached_payload = await self.document_service.load_parsed_json(
                        parsed_cache_blob_name
                    )

                if cached_payload:
                    analysis = AnalysisResultSchema.model_validate(cached_payload)
                    logger.info(
                        "parsed_json_cache_hit",
                        document_id=str(document_id),
                        parsed_json_blob_name=parsed_cache_blob_name,
                    )
                else:
                    # Extract metadata via Document Intelligence
                    extraction_url = await self.document_service.get_blob_url(
                        blob_result.blob_name
                    )
                    analysis = await self.document_service.extract_metadata_with_doc_intel(
                        blob_url=extraction_url,
                        document_id=str(document_id),
                    )

                    if settings.parsed_json_cache_enabled:
                        await self.document_service.save_parsed_json(
                            parsed_cache_blob_name,
                            analysis.model_dump(mode="json"),
                        )
                        logger.info(
                            "parsed_json_cache_saved",
                            document_id=str(document_id),
                            parsed_json_blob_name=parsed_cache_blob_name,
                        )

                if settings.parsed_json_cache_enabled:
                    doc_record.parsed_json_blob_name = parsed_cache_blob_name
                    doc_record.parser_version = settings.parsed_json_cache_parser_version
                    doc_record.parsed_json_cached_at = datetime.now(timezone.utc)

                # Update document record with extraction results
                doc_record.page_count = analysis.metadata.page_count
                await session.flush()

                logger.info(
                    "extraction_completed",
                    document_id=str(document_id),
                    page_count=analysis.metadata.page_count,
                )

                # ================================================================
                # State 2: CHUNKING
                # ================================================================
                logger.info(
                    "pipeline_state_transition",
                    document_id=str(document_id),
                    state="CHUNKING",
                )

                doc_record.processing_status = ProcessingStatus.CHUNKING
                await session.flush()

                # Normalize text before chunking (clean extraction artifacts)
                clean_text = normalize_whitespace(analysis.text)
                analysis.text = clean_text

                # Split document into chunks
                chunks = self.chunker.split_document(analysis)

                if not chunks:
                    raise ValueError(
                        f"Chunker returned zero chunks for document {document_id}"
                    )

                logger.info(
                    "chunking_completed",
                    document_id=str(document_id),
                    chunks_created=len(chunks),
                )

                # ================================================================
                # State 3: INDEXING
                # ================================================================
                logger.info(
                    "pipeline_state_transition",
                    document_id=str(document_id),
                    state="INDEXING",
                )

                doc_record.processing_status = ProcessingStatus.INDEXING
                await session.flush()

                # Index chunks in search service (generates embeddings internally)
                await self.search_service.index_chunks(
                    str(document_id),
                    chunks,
                    file_name=file_name,
                )
                indexed_in_search = True

                # Simultaneously persist chunks to database
                chunk_orm_rows = []
                for chunk in chunks:
                    chunk_orm = DocumentChunkORM(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        char_count=chunk.char_count,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        start_position=chunk.start_position,
                        end_position=chunk.end_position,
                        embedding_id=None,  # Will be populated by embedding service
                    )
                    chunk_orm_rows.append(chunk_orm)

                session.add_all(chunk_orm_rows)
                await session.flush()

                logger.info(
                    "indexing_completed",
                    document_id=str(document_id),
                    chunks_indexed=len(chunks),
                    chunks_persisted=len(chunk_orm_rows),
                )

                # ================================================================
                # State 4: COMPLETED
                # ================================================================
                logger.info(
                    "pipeline_state_transition",
                    document_id=str(document_id),
                    state="COMPLETED",
                )

                doc_record.processing_status = ProcessingStatus.COMPLETED
                await session.commit()

                logger.info(
                    "pipeline_completed",
                    document_id=str(document_id),
                    duration_stages=4,
                )

        except Exception as e:
            # ================================================================
            # ERROR: FAILED state with rollback
            # ================================================================
            logger.error(
                f"pipeline_failed: {type(e).__name__}",
                document_id=str(document_id),
                error_detail=str(e)[:500],  # Truncate to DB column limit
                exc_info=True,
            )

            # If indexing already succeeded, compensate by deleting indexed
            # chunks to keep search state aligned with failed DB persistence.
            if indexed_in_search:
                try:
                    await self.search_service.delete_document_chunks(str(document_id))
                    compensation_cleanup_succeeded = True
                    logger.warning(
                        "pipeline_compensation_cleanup_completed",
                        document_id=str(document_id),
                        cleanup_target="search_chunks",
                    )
                except Exception as cleanup_error:
                    compensation_cleanup_error = str(cleanup_error)
                    logger.error(
                        "pipeline_compensation_cleanup_failed",
                        document_id=str(document_id),
                        cleanup_target="search_chunks",
                        error_detail=compensation_cleanup_error[:500],
                        exc_info=True,
                    )

            # Attempt rollback and error record update
            try:
                async with session_factory() as error_session:
                    doc_record = await error_session.get(DocumentRecordORM, document_id)
                    if doc_record:
                        doc_record.processing_status = ProcessingStatus.FAILED
                        error_message = str(e)
                        if isinstance(e, SondraBaseException) and e.detail:
                            if e.detail != error_message:
                                error_message = f"{error_message} | detail={e.detail}"

                        if indexed_in_search and compensation_cleanup_succeeded:
                            error_message += " [indexed chunks rolled back]"
                        elif indexed_in_search and compensation_cleanup_error:
                            error_message += (
                                " [indexed chunks rollback failed: "
                                f"{compensation_cleanup_error}]"
                            )

                        doc_record.error_message = error_message[:500]  # Truncate for DB storage
                        await error_session.commit()
                    else:
                        logger.warning(
                            "error_handler_document_not_found",
                            document_id=str(document_id),
                        )
            except Exception as rollback_error:
                logger.error(
                    f"error_handler_failed: {type(rollback_error).__name__}",
                    document_id=str(document_id),
                    error_detail=str(rollback_error),
                    exc_info=True,
                )

            # BackgroundTasks run after the 202 response has already started.
            # Keep failures visible through logs and persisted FAILED status,
            # but do not re-raise into Starlette's response lifecycle.
            return
