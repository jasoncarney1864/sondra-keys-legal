"""
Session management routes for sticky active-document behavior.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies import (
    build_session_create_response,
    create_user_session,
    get_current_session,
    get_current_user_id,
    get_db_session,
)
from backend.app.models.db import DocumentRecordORM, UserDocumentAccessORM, UserSessionORM
from backend.app.models.schemas import (
    ActiveDocumentResponse,
    SessionCreateResponse,
    SessionListResponse,
    SessionSummary,
    SetActiveDocumentRequest,
)

router = APIRouter()


@router.post("", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    session: AsyncSession = Depends(get_db_session),
    user_id: str = Depends(get_current_user_id),
) -> SessionCreateResponse:
    """Create and return a fresh user session."""
    session_obj = await create_user_session(session, user_id)
    return build_session_create_response(session_obj)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    session: AsyncSession = Depends(get_db_session),
    user_id: str = Depends(get_current_user_id),
) -> SessionListResponse:
    """List sessions for current user, newest first."""
    total_count = (
        await session.execute(
            select(func.count(UserSessionORM.id)).where(UserSessionORM.user_id == user_id)
        )
    ).scalar() or 0

    stmt = (
        select(UserSessionORM, DocumentRecordORM)
        .outerjoin(DocumentRecordORM, UserSessionORM.active_document_id == DocumentRecordORM.id)
        .where(UserSessionORM.user_id == user_id)
        .order_by(UserSessionORM.last_accessed_at.desc())
        .limit(100)
    )
    rows = (await session.execute(stmt)).all()

    summaries = [
        SessionSummary(
            session_id=session_obj.id,
            active_document_id=session_obj.active_document_id,
            active_document_file_name=doc.file_name if doc else None,
            created_at=session_obj.created_at,
            last_accessed_at=session_obj.last_accessed_at,
            expires_at=session_obj.expires_at,
        )
        for session_obj, doc in rows
    ]

    return SessionListResponse(sessions=summaries, total_count=total_count)


@router.get("/current", response_model=SessionCreateResponse)
async def get_current_session_info(
    current_session: UserSessionORM = Depends(get_current_session),
) -> SessionCreateResponse:
    """Return current resolved session from X-Session-Id or auto-created session."""
    return build_session_create_response(current_session)


@router.put("/current/active-document", response_model=ActiveDocumentResponse)
async def set_active_document(
    request: SetActiveDocumentRequest,
    session: AsyncSession = Depends(get_db_session),
    current_session: UserSessionORM = Depends(get_current_session),
    user_id: str = Depends(get_current_user_id),
) -> ActiveDocumentResponse:
    """Set current session active document, ensuring user has access."""
    access_stmt = select(UserDocumentAccessORM).where(
        UserDocumentAccessORM.user_id == user_id,
        UserDocumentAccessORM.document_id == request.document_id,
    )
    access = (await session.execute(access_stmt)).scalar_one_or_none()
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for current user.",
        )

    doc = await session.get(DocumentRecordORM, request.document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document does not exist.",
        )

    current_session.active_document_id = request.document_id
    await session.commit()

    return ActiveDocumentResponse(
        session_id=current_session.id,
        active_document_id=request.document_id,
        active_document_file_name=doc.file_name,
    )


@router.delete("/current/active-document", response_model=ActiveDocumentResponse)
async def clear_active_document(
    session: AsyncSession = Depends(get_db_session),
    current_session: UserSessionORM = Depends(get_current_session),
) -> ActiveDocumentResponse:
    """Clear active document for current session."""
    current_session.active_document_id = None
    await session.commit()

    return ActiveDocumentResponse(
        session_id=current_session.id,
        active_document_id=None,
        active_document_file_name=None,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Delete a user-owned session and its sticky active-document context."""
    session_obj = await session.get(UserSessionORM, session_id)
    if session_obj is None or session_obj.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found for current user.",
        )

    # Session-specific context is limited to the active_document_id pointer.
    session_obj.active_document_id = None
    await session.delete(session_obj)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
