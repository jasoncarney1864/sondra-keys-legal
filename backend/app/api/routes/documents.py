"""
Document management routes: upload, retrieve, list, delete.
"""

import hashlib
import logging
import os
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies import (
    get_current_session,
    get_current_user_id,
    get_document_service,
    get_db_session,
    get_pipeline_orchestrator,
    get_search_service,
)
from backend.app.core.config import settings
from backend.app.core.database import async_session_maker
from backend.app.core.exceptions import BlobNotFoundException
from backend.app.core.exceptions import (
    FileSizeExceededException,
    UnsupportedFileTypeException,
)
from backend.app.models.db import (
    DocumentRecordORM,
    ProcessingStatus,
    UserDocumentAccessORM,
    UserSessionORM,
)
from backend.app.models.schemas import (
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentRecord,
    DocumentUploadResponse,
)
from backend.app.services.interfaces import AbstractDocumentService
from backend.app.services.orchestrator import DocumentPipelineOrchestrator

import structlog
logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_upload(filename: str, data: bytes) -> None:
    """
    Gate file size and extension before touching any external service.

    Raises FileSizeExceededException or UnsupportedFileTypeException so the
    global handlers in main.py convert them to 413 / 400 responses.
    """
    size_mb = len(data) / (1024 * 1024)
    if size_mb > settings.security.max_file_size_mb:
        raise FileSizeExceededException(
            f"File '{filename}' is {size_mb:.1f} MB — "
            f"maximum allowed is {settings.security.max_file_size_mb} MB."
        )

    _, ext = os.path.splitext(filename)
    if ext.lower() not in settings.security.allowed_file_types:
        raise UnsupportedFileTypeException(
            f"File type '{ext}' is not supported. "
            f"Allowed types: {', '.join(settings.security.allowed_file_types)}."
        )


def _compute_content_hash(data: bytes) -> str:
    """Return a stable SHA-256 hash for byte-level upload deduplication."""
    return hashlib.sha256(data).hexdigest()


def _deterministic_document_id(content_hash: str) -> UUID:
    """Map a content hash to a stable UUID for repeatable ingest identity."""
    return uuid5(NAMESPACE_URL, f"sondra-keys-legal:{content_hash}")


_NON_RETRYABLE_FAILURE_MARKERS = (
    "invalidcontent",
    "unsupported format",
    "file is corrupted",
    "password-protected",
    "encrypted",
)


def _is_non_retryable_failure(error_message: str | None) -> bool:
    """Return True when a failed ingest should not be automatically retried."""
    if not error_message:
        return False

    normalized = error_message.lower()
    return any(marker in normalized for marker in _NON_RETRYABLE_FAILURE_MARKERS)


async def _ensure_document_access(
    session: AsyncSession,
    user_id: str,
    document_id: UUID,
) -> None:
    """Create user-document access mapping if it does not exist."""
    existing = (
        await session.execute(
            select(UserDocumentAccessORM).where(
                UserDocumentAccessORM.user_id == user_id,
                UserDocumentAccessORM.document_id == document_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            UserDocumentAccessORM(
                user_id=user_id,
                document_id=document_id,
            )
        )
        await session.flush()


async def _has_document_access(
    session: AsyncSession,
    user_id: str,
    document_id: UUID,
) -> bool:
    """Return True if user has access link for this document."""
    access = (
        await session.execute(
            select(UserDocumentAccessORM).where(
                UserDocumentAccessORM.user_id == user_id,
                UserDocumentAccessORM.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    return access is not None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    current_session: UserSessionORM = Depends(get_current_session),
    orchestrator: DocumentPipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> DocumentUploadResponse:
    """
    Upload and queue a legal document for processing.

    Returns HTTP 202 Accepted immediately with a document record in PENDING state.
    Processing (extraction, chunking, indexing) runs asynchronously in the background.

    Pipeline (background): validate → blob upload → Document Intelligence →
    chunk splitting → embedding generation → search indexing → database persistence.

    Raises:
        FileSizeExceededException (413): File exceeds size limit
        UnsupportedFileTypeException (400): File type not supported
        StorageServiceException (503): Database or blob storage error
    """
    file_data = await file.read()

    # Validate before creating database record
    _validate_upload(file.filename, file_data)

    content_hash = _compute_content_hash(file_data)
    canonical_blob_name = f"content/{content_hash}"

    # Check if an identical file is already known.
    existing_stmt = select(DocumentRecordORM).where(
        DocumentRecordORM.blob_name == canonical_blob_name
    )
    existing_doc = (await session.execute(existing_stmt)).scalar_one_or_none()

    if existing_doc:
        await _ensure_document_access(session, current_user_id, existing_doc.id)
        current_session.active_document_id = existing_doc.id

        logger.info(
            "document_upload_deduplicated",
            existing_document_id=str(existing_doc.id),
            existing_status=existing_doc.processing_status.value,
            file_name=file.filename,
            file_size_bytes=len(file_data),
            content_hash_prefix=content_hash[:12],
            user_id=current_user_id,
            session_id=str(current_session.id),
            active_document_id=str(existing_doc.id),
        )

        if existing_doc.processing_status == ProcessingStatus.FAILED:
            if _is_non_retryable_failure(existing_doc.error_message):
                await session.commit()
                logger.info(
                    "document_processing_requeue_skipped_non_retryable",
                    document_id=str(existing_doc.id),
                    error_preview=(existing_doc.error_message or "")[:120],
                    user_id=current_user_id,
                    session_id=str(current_session.id),
                )
                return DocumentUploadResponse(
                    document_id=existing_doc.id,
                    file_name=existing_doc.file_name,
                    status=ProcessingStatus.FAILED.value,
                    message=(
                        "An identical failed document was found, but the failure "
                        "appears non-retryable (unsupported/corrupted content). "
                        "Reprocessing was not queued."
                    ),
                    chunks_created=0,
                )

            # Allow deterministic retry on the same document ID.
            existing_doc.processing_status = ProcessingStatus.PENDING
            existing_doc.error_message = None
            existing_doc.completed_timestamp = None
            await session.commit()

            background_tasks.add_task(
                orchestrator.run_pipeline,
                document_id=existing_doc.id,
                file_bytes=file_data,
                file_name=existing_doc.file_name,
                session_factory=async_session_maker,
            )

            logger.info(
                "document_processing_requeued",
                document_id=str(existing_doc.id),
                user_id=current_user_id,
                session_id=str(current_session.id),
            )

            return DocumentUploadResponse(
                document_id=existing_doc.id,
                file_name=existing_doc.file_name,
                status="pending",
                message=(
                    "An identical failed document was found. "
                    "Reprocessing has been queued."
                ),
                chunks_created=0,
            )

        # For completed or in-progress documents, do not enqueue a duplicate task.
        await session.commit()
        return DocumentUploadResponse(
            document_id=existing_doc.id,
            file_name=existing_doc.file_name,
            status=existing_doc.processing_status.value,
            message=(
                "An identical document is already being processed."
                if existing_doc.processing_status
                in {
                    ProcessingStatus.PENDING,
                    ProcessingStatus.EXTRACTING,
                    ProcessingStatus.CHUNKING,
                    ProcessingStatus.INDEXING,
                }
                else "An identical document has already been processed."
            ),
            chunks_created=0,
        )

    # Use a deterministic UUID so repeated uploads of identical bytes map to
    # the same search document keys even across DB resets/redeploys.
    document_id = _deterministic_document_id(content_hash)

    logger.info(
        "document_upload_initiated",
        document_id=str(document_id),
        file_name=file.filename,
        file_size_bytes=len(file_data),
        content_hash_prefix=content_hash[:12],
        user_id=current_user_id,
        session_id=str(current_session.id),
    )

    # Create initial database record in PENDING state
    doc_record = DocumentRecordORM(
        id=document_id,
        file_name=file.filename,
        file_size_bytes=len(file_data),
        content_type=file.content_type or "application/octet-stream",
        uploaded_by_user_id=current_user_id,
        blob_name=canonical_blob_name,
        blob_url="",  # Will be populated by orchestrator
        processing_status=ProcessingStatus.PENDING,
    )
    session.add(doc_record)
    session.add(
        UserDocumentAccessORM(
            user_id=current_user_id,
            document_id=document_id,
        )
    )
    current_session.active_document_id = document_id

    try:
        await session.commit()
    except IntegrityError:
        # Another concurrent upload likely inserted the same canonical blob first.
        await session.rollback()
        existing_doc = (await session.execute(existing_stmt)).scalar_one_or_none()
        if not existing_doc:
            raise

        logger.info(
            "document_upload_deduplicated_after_race",
            existing_document_id=str(existing_doc.id),
            existing_status=existing_doc.processing_status.value,
            content_hash_prefix=content_hash[:12],
            user_id=current_user_id,
            session_id=str(current_session.id),
            active_document_id=str(existing_doc.id),
        )

        await _ensure_document_access(session, current_user_id, existing_doc.id)
        current_session.active_document_id = existing_doc.id

        if existing_doc.processing_status == ProcessingStatus.FAILED:
            if _is_non_retryable_failure(existing_doc.error_message):
                await session.commit()
                logger.info(
                    "document_processing_requeue_skipped_non_retryable",
                    document_id=str(existing_doc.id),
                    error_preview=(existing_doc.error_message or "")[:120],
                    user_id=current_user_id,
                    session_id=str(current_session.id),
                )
                return DocumentUploadResponse(
                    document_id=existing_doc.id,
                    file_name=existing_doc.file_name,
                    status=ProcessingStatus.FAILED.value,
                    message=(
                        "An identical failed document was found, but the failure "
                        "appears non-retryable (unsupported/corrupted content). "
                        "Reprocessing was not queued."
                    ),
                    chunks_created=0,
                )

            existing_doc.processing_status = ProcessingStatus.PENDING
            existing_doc.error_message = None
            existing_doc.completed_timestamp = None
            await session.commit()

            background_tasks.add_task(
                orchestrator.run_pipeline,
                document_id=existing_doc.id,
                file_bytes=file_data,
                file_name=existing_doc.file_name,
                session_factory=async_session_maker,
            )

            logger.info(
                "document_processing_requeued",
                document_id=str(existing_doc.id),
                user_id=current_user_id,
                session_id=str(current_session.id),
            )

            return DocumentUploadResponse(
                document_id=existing_doc.id,
                file_name=existing_doc.file_name,
                status="pending",
                message=(
                    "An identical failed document was found. "
                    "Reprocessing has been queued."
                ),
                chunks_created=0,
            )

        await session.commit()
        return DocumentUploadResponse(
            document_id=existing_doc.id,
            file_name=existing_doc.file_name,
            status=existing_doc.processing_status.value,
            message=(
                "An identical document is already being processed."
                if existing_doc.processing_status
                in {
                    ProcessingStatus.PENDING,
                    ProcessingStatus.EXTRACTING,
                    ProcessingStatus.CHUNKING,
                    ProcessingStatus.INDEXING,
                }
                else "An identical document has already been processed."
            ),
            chunks_created=0,
        )

    logger.info(
        "document_record_created",
        document_id=str(document_id),
        status="pending",
        user_id=current_user_id,
        session_id=str(current_session.id),
    )

    # Hand off to background task (returns immediately)
    background_tasks.add_task(
        orchestrator.run_pipeline,
        document_id=document_id,
        file_bytes=file_data,
        file_name=file.filename,
        session_factory=async_session_maker,
    )

    logger.info(
        "document_processing_queued",
        document_id=str(document_id),
        user_id=current_user_id,
        session_id=str(current_session.id),
        active_document_id=str(current_session.active_document_id),
    )

    return DocumentUploadResponse(
        document_id=document_id,
        file_name=file.filename,
        status="pending",
        message="Document queued for processing. Check status via GET /{document_id}.",
        chunks_created=0,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
) -> DocumentListResponse:
    """
    List all uploaded documents with pagination.

    Returns documents sorted by upload_timestamp (newest first).
    """
    # Get total count
    count_result = await session.execute(
        select(func.count(UserDocumentAccessORM.document_id)).where(
            UserDocumentAccessORM.user_id == current_user_id
        )
    )
    total_count = count_result.scalar() or 0

    # Get paginated documents
    stmt = (
        select(DocumentRecordORM)
        .join(
            UserDocumentAccessORM,
            UserDocumentAccessORM.document_id == DocumentRecordORM.id,
        )
        .where(UserDocumentAccessORM.user_id == current_user_id)
        .order_by(DocumentRecordORM.upload_timestamp.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    doc_records = result.scalars().all()

    documents = [
        DocumentRecord(
            document_id=doc.id,
            file_name=doc.file_name,
            file_size_bytes=doc.file_size_bytes,
            upload_timestamp=doc.upload_timestamp,
            page_count=doc.page_count,
            processing_status=doc.processing_status.value,
            uploaded_by_user_id=doc.uploaded_by_user_id,
        )
        for doc in doc_records
    ]

    logger.info(
        "documents_listed",
        skip=skip,
        limit=limit,
        total_count=total_count,
        returned_count=len(documents),
        user_id=current_user_id,
    )

    return DocumentListResponse(
        documents=documents,
        total_count=total_count,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{document_id}/download",
)
async def download_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    service: AbstractDocumentService = Depends(get_document_service),
) -> Response:
    """Stream original uploaded document bytes as an attachment download."""
    try:
        parsed_id = UUID(document_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document ID format: {document_id}",
        ) from e

    if not await _has_document_access(session, current_user_id, parsed_id):
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    doc_record = await session.get(DocumentRecordORM, parsed_id)
    if not doc_record:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    if not doc_record.blob_name:
        raise HTTPException(
            status_code=409,
            detail="Original file is not available for download yet.",
        )

    file_bytes = await service.download_blob(doc_record.blob_name)
    encoded_name = quote(doc_record.file_name)

    logger.info(
        "document_download_streamed",
        document_id=document_id,
        user_id=current_user_id,
        file_name=doc_record.file_name,
    )

    return Response(
        content=file_bytes,
        media_type=doc_record.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


@router.get(
    "/{document_id}/download-url",
    response_model=DocumentDownloadResponse,
)
async def get_document_download_url(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    service: AbstractDocumentService = Depends(get_document_service),
) -> DocumentDownloadResponse:
    """Return a short-lived signed URL for downloading the original uploaded file."""
    try:
        parsed_id = UUID(document_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document ID format: {document_id}",
        ) from e

    if not await _has_document_access(session, current_user_id, parsed_id):
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    doc_record = await session.get(DocumentRecordORM, parsed_id)
    if not doc_record:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    if not doc_record.blob_name:
        raise HTTPException(
            status_code=409,
            detail="Original file is not available for download yet.",
        )

    download_url = await service.get_blob_url(doc_record.blob_name)

    logger.info(
        "document_download_url_generated",
        document_id=document_id,
        user_id=current_user_id,
    )

    return DocumentDownloadResponse(
        document_id=doc_record.id,
        file_name=doc_record.file_name,
        download_url=download_url,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRecord,
)
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
) -> DocumentRecord:
    """
    Retrieve metadata for a single document.

    Returns document record including processing status, page count, and error
    message (if processing failed).
    """
    # Try to parse as UUID
    try:
        from uuid import UUID
        parsed_id = UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document ID format: {document_id}",
        )

    if not await _has_document_access(session, current_user_id, parsed_id):
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    doc_record = await session.get(DocumentRecordORM, parsed_id)
    if not doc_record:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )

    logger.info(
        "document_retrieved",
        document_id=document_id,
        status=doc_record.processing_status.value,
    )

    return DocumentRecord(
        document_id=doc_record.id,
        file_name=doc_record.file_name,
        file_size_bytes=doc_record.file_size_bytes,
        upload_timestamp=doc_record.upload_timestamp,
        page_count=doc_record.page_count,
        processing_status=doc_record.processing_status.value,
        uploaded_by_user_id=doc_record.uploaded_by_user_id,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    service: AbstractDocumentService = Depends(get_document_service),
    search_service = Depends(get_search_service),
) -> None:
    """
    Delete a document and all associated data.

    Cascading cleanup:
    1. Delete chunks from search index
    2. Delete chunks from database
    3. Delete document metadata from database
    4. Delete blob from storage

    On partial failure, attempts to complete cleanup before propagating error.
    """
    # Try to parse as UUID
    try:
        from uuid import UUID
        parsed_id = UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document ID format: {document_id}",
        )

    # Validate ownership/access.
    # Idempotent behavior: if no mapping exists, treat as already deleted.
    access = (
        await session.execute(
            select(UserDocumentAccessORM).where(
                UserDocumentAccessORM.user_id == current_user_id,
                UserDocumentAccessORM.document_id == parsed_id,
            )
        )
    ).scalar_one_or_none()
    if access is None:
        logger.info(
            "document_deletion_noop_no_access",
            document_id=document_id,
            user_id=current_user_id,
        )
        return

    # Get document record. If mapping exists but record is gone, clean stale
    # mapping and return success (idempotent).
    doc_record = await session.get(DocumentRecordORM, parsed_id)
    if not doc_record:
        await session.delete(access)
        await session.commit()
        logger.warning(
            "document_deletion_stale_access_removed",
            document_id=document_id,
            user_id=current_user_id,
        )
        return

    logger.info(
        "document_deletion_initiated",
        document_id=document_id,
        file_name=doc_record.file_name,
    )

    # Step 1: Delete from search index.
    try:
        await search_service.delete_document_chunks(document_id)
        logger.info("search_index_cleanup_completed", document_id=document_id)
    except Exception as e:
        logger.error(
            f"search_index_cleanup_failed: {type(e).__name__}",
            document_id=document_id,
            error_detail=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to remove indexed chunks for this document. Retry deletion.",
        ) from e

    # Step 2: Delete all blob artifacts from storage.
    blob_names_to_delete = [doc_record.blob_name]
    if doc_record.parsed_json_blob_name:
        blob_names_to_delete.append(doc_record.parsed_json_blob_name)

    for blob_name in blob_names_to_delete:
        if not blob_name:
            continue

        try:
            await service.delete_blob(blob_name)
            logger.info(
                "blob_cleanup_completed",
                document_id=document_id,
                blob_name=blob_name,
            )
        except BlobNotFoundException:
            logger.info(
                "blob_cleanup_skipped_not_found",
                document_id=document_id,
                blob_name=blob_name,
            )
        except Exception as e:
            logger.error(
                f"blob_cleanup_failed: {type(e).__name__}",
                document_id=document_id,
                blob_name=blob_name,
                error_detail=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to remove stored document artifacts. Retry deletion.",
            ) from e

    # Step 3: Remove DB metadata and session/access references.
    # Keep this in one transaction for atomic database cleanup.
    try:
        await session.execute(
            update(UserSessionORM)
            .where(UserSessionORM.active_document_id == parsed_id)
            .values(active_document_id=None)
        )
        await session.execute(
            delete(UserDocumentAccessORM).where(
                UserDocumentAccessORM.document_id == parsed_id
            )
        )
        await session.delete(doc_record)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(
            f"document_db_cleanup_failed: {type(e).__name__}",
            document_id=document_id,
            error_detail=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document artifacts were removed but metadata cleanup failed. Retry deletion.",
        ) from e

    logger.info(
        "document_deletion_completed",
        document_id=document_id,
        file_name=doc_record.file_name,
    )

