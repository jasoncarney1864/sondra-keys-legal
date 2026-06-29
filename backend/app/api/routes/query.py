"""
Q&A query route: POST /api/query
"""

import logging
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, status
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies import (
    get_current_session,
    get_current_user_id,
    get_db_session,
    get_query_service,
)
from backend.app.models.db import UserDocumentAccessORM, UserSessionORM
from backend.app.models.schemas import QueryRequest, QueryResponse
from backend.app.services.interfaces import AbstractQueryService

import structlog
logger = structlog.get_logger(__name__)

router = APIRouter()


def _hash_identifier(raw_value: str | None) -> str | None:
    """Return a short stable hash for correlation without exposing raw identifiers."""
    if not raw_value:
        return None
    return sha256(raw_value.encode("utf-8")).hexdigest()[:16]


def _set_trace_correlation_attributes(
    *,
    user_id: str,
    session_id: str,
    active_document_id: str | None,
    scoped_document_ids: list,
    selection_source: str,
) -> None:
    """Attach hashed correlation attributes to the current FastAPI request span."""
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    user_hash = _hash_identifier(user_id)
    session_hash = _hash_identifier(session_id)
    active_document_hash = _hash_identifier(active_document_id)
    scoped_document_hashes = [
        hashed for hashed in (_hash_identifier(str(doc_id)) for doc_id in scoped_document_ids) if hashed
    ]

    if user_hash:
        span.set_attribute("sondra.user.hash", user_hash)
    if session_hash:
        span.set_attribute("sondra.session.hash", session_hash)
    if active_document_hash:
        span.set_attribute("sondra.active_document.hash", active_document_hash)

    span.set_attribute("sondra.selection_source", selection_source)
    span.set_attribute("sondra.scoped_document.count", len(scoped_document_ids))
    if scoped_document_hashes:
        span.set_attribute("sondra.scoped_document.hashes", scoped_document_hashes)


@router.post(
    "",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Answer a legal question using document context",
)
async def query_documents(
    request: QueryRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    current_session: UserSessionORM = Depends(get_current_session),
    query_service: AbstractQueryService = Depends(get_query_service),
) -> QueryResponse:
    """
    Execute the full RAG pipeline against indexed document content.

    Embeds the question, performs hybrid search, constructs a context-grounded
    prompt, calls the LLM, and returns a structured answer with rich citations.

    Raises:
        LLMRateLimitException (429): Upstream rate limit hit.
        LLMServiceException (503): Upstream OpenAI API failure.
    """
    logger.info(
        "query_received",
        question_preview=request.question[:80],
        document_ids=[str(d) for d in request.document_ids] if request.document_ids else None,
        top_k=request.top_k,
        max_citations=request.max_citations,
        user_id=current_user_id,
        session_id=str(current_session.id),
        active_document_id=(
            str(current_session.active_document_id)
            if current_session.active_document_id
            else None
        ),
    )

    effective_document_ids = request.document_ids
    selection_source = "explicit"

    if not effective_document_ids:
        if current_session.active_document_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No active document selected for this session. "
                    "Select an active document first or pass document_ids explicitly."
                ),
            )
        effective_document_ids = [current_session.active_document_id]
        selection_source = "session_active_document"

    allowed_ids_stmt = select(UserDocumentAccessORM.document_id).where(
        UserDocumentAccessORM.user_id == current_user_id,
        UserDocumentAccessORM.document_id.in_(effective_document_ids),
    )
    allowed_ids = {row[0] for row in (await session.execute(allowed_ids_stmt)).all()}

    missing_ids = [doc_id for doc_id in effective_document_ids if doc_id not in allowed_ids]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more requested documents are not available for this user.",
        )

    scoped_document_ids = [doc_id for doc_id in effective_document_ids if doc_id in allowed_ids]
    scoped_request = request.model_copy(update={"document_ids": scoped_document_ids})

    logger.info(
        "query_scope_resolved",
        user_id=current_user_id,
        session_id=str(current_session.id),
        active_document_id=(
            str(current_session.active_document_id)
            if current_session.active_document_id
            else None
        ),
        selection_source=selection_source,
        scoped_document_ids=[str(d) for d in scoped_document_ids],
    )

    _set_trace_correlation_attributes(
        user_id=current_user_id,
        session_id=str(current_session.id),
        active_document_id=(
            str(current_session.active_document_id)
            if current_session.active_document_id
            else None
        ),
        scoped_document_ids=scoped_document_ids,
        selection_source=selection_source,
    )

    response = await query_service.answer_query(scoped_request)

    logger.info(
        "query_completed",
        citations_returned=len(response.citations),
        model_used=response.model_used,
        latency_ms=response.latency_ms,
    )

    return response
