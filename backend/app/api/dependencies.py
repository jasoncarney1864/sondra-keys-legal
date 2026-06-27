"""
FastAPI dependency providers for the Sondra Keys Legal API.

Each function in this module is a FastAPI dependency — wired into route
signatures via Depends(). This keeps routes decoupled from concrete
implementations and makes unit-testing trivial via dependency_overrides.

Service singleton pattern:
  DocumentProcessor initialises lazy Azure clients on first use, so it is
  safe to construct once at import time and reuse across all requests.
  _create_document_processor() is cached with lru_cache(maxsize=1) to
  guarantee a single instance per worker process.
"""

import logging
import uuid
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import jwt
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jwt import PyJWKClient, PyJWTError

from backend.app.core.config import settings
from backend.app.core.database import get_session
from backend.app.models.db import (
    UserRecordORM,
    UserSessionORM,
)
from backend.app.models.schemas import SessionCreateResponse
from backend.app.services.document_processor import DocumentProcessor
from backend.app.services.interfaces import AbstractDocumentService, AbstractQueryService, AbstractSearchService
from backend.app.services.orchestrator import DocumentPipelineOrchestrator
from backend.app.services.hud_sources import HUDCuratedSourceAdapter, HUDIngestionService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document service
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _create_document_processor() -> DocumentProcessor:
    """Construct the concrete document service once per worker process."""
    return DocumentProcessor()


def get_document_service() -> AbstractDocumentService:
    """
    Inject the concrete document service.

    Routes declare this as:
        service: AbstractDocumentService = Depends(get_document_service)

    Tests override it as:
        app.dependency_overrides[get_document_service] = lambda: MockDocumentService()
    """
    return _create_document_processor()


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------


async def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """
    Validate the X-API-Key request header.

    Raises HTTP 401 on missing or invalid key so callers never need to
    handle auth themselves — just declare this as a dependency.
    """
    if x_api_key != settings.security.api_key:
        logger.warning("invalid_api_key_attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


# ---------------------------------------------------------------------------
# Database session injection
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Inject an async database session into route handlers.

    Routes declare this as:
        session: AsyncSession = Depends(get_db_session)

    The session is guaranteed to be closed on normal completion or exception.
    If an exception propagates, the transaction is rolled back automatically.
    """
    async for session in get_session():
        yield session


@lru_cache(maxsize=1)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    """Create and cache PyJWT JWKS client."""
    return PyJWKClient(jwks_url)


def _decode_oidc_token(token: str) -> dict:
    """Validate and decode OIDC JWT."""
    if not settings.security.oidc_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC JWKS URL is not configured.",
        )

    try:
        signing_key = _get_jwks_client(settings.security.oidc_jwks_url).get_signing_key_from_jwt(token).key

        decode_kwargs = {
            "algorithms": settings.security.oidc_algorithms,
        }
        if settings.security.oidc_audience:
            decode_kwargs["audience"] = settings.security.oidc_audience
        if settings.security.oidc_issuer:
            decode_kwargs["issuer"] = settings.security.oidc_issuer

        return jwt.decode(token, signing_key, **decode_kwargs)
    except PyJWTError as e:
        logger.warning("oidc_token_validation_failed error=%s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        ) from e


async def get_current_user_id(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """
    Resolve the caller's stable user identity.

    Current behavior:
    - auth_mode=api_key: requires valid X-API-Key and uses configured dev user ID.
    - auth_mode=oidc: expects Bearer JWT and extracts configured user claim.
    """
    if settings.security.auth_mode == "api_key":
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-API-Key header.",
            )
        await require_api_key(x_api_key)
        return settings.security.default_dev_user_id

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = _decode_oidc_token(token)

    user_claim = settings.security.oidc_user_id_claim
    user_id = str(payload.get(user_claim) or "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Bearer token missing '{user_claim}' claim.",
        )

    return user_id


async def ensure_user_record(session: AsyncSession, user_id: str) -> UserRecordORM:
    """Get or create persistent user record."""
    user = await session.get(UserRecordORM, user_id)
    if user is None:
        user = UserRecordORM(
            id=user_id,
            display_name=None,
        )
        session.add(user)
        await session.flush()

    user.last_seen_at = datetime.now(timezone.utc)
    return user


def _session_expiry() -> datetime:
    """Return expiry timestamp for newly created user sessions."""
    return datetime.now(timezone.utc) + timedelta(minutes=settings.user_session_ttl_minutes)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize naive/aware datetimes to timezone-aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def create_user_session(session: AsyncSession, user_id: str) -> UserSessionORM:
    """Create a new persisted user session."""
    await ensure_user_record(session, user_id)
    session_obj = UserSessionORM(
        user_id=user_id,
        active_document_id=None,
        expires_at=_session_expiry(),
    )
    session.add(session_obj)
    await session.commit()
    await session.refresh(session_obj)
    return session_obj


async def get_current_session(
    session: AsyncSession = Depends(get_db_session),
    user_id: str = Depends(get_current_user_id),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> UserSessionORM:
    """
    Resolve active user session from X-Session-Id, creating one if absent.

    This enables sticky active-document mode per login session while keeping
    API callers simple (session auto-provision on first request).
    """
    await ensure_user_record(session, user_id)

    now = datetime.now(timezone.utc)
    session_obj: UserSessionORM | None = None

    if x_session_id:
        try:
            parsed_id = uuid.UUID(x_session_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Session-Id format.",
            ) from e

        session_obj = await session.get(UserSessionORM, parsed_id)
        if session_obj and session_obj.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to the current user.",
            )

        if session_obj and _as_utc(session_obj.expires_at) < now:
            session_obj = None
    else:
        latest_stmt = (
            select(UserSessionORM)
            .where(
                UserSessionORM.user_id == user_id,
            )
            .order_by(UserSessionORM.last_accessed_at.desc())
            .limit(1)
        )
        session_obj = (await session.execute(latest_stmt)).scalar_one_or_none()
        if session_obj and _as_utc(session_obj.expires_at) < now:
            session_obj = None

    if session_obj is None:
        session_obj = UserSessionORM(
            user_id=user_id,
            active_document_id=None,
            expires_at=_session_expiry(),
        )
        session.add(session_obj)
        await session.flush()

    session_obj.last_accessed_at = now
    await session.commit()
    await session.refresh(session_obj)
    return session_obj


def build_session_create_response(session_obj: UserSessionORM) -> SessionCreateResponse:
    """Map ORM session to API response payload."""
    return SessionCreateResponse(
        session_id=session_obj.id,
        user_id=session_obj.user_id,
        active_document_id=session_obj.active_document_id,
        created_at=session_obj.created_at,
        expires_at=session_obj.expires_at,
    )


# ---------------------------------------------------------------------------
# Search service
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _create_search_service() -> AbstractSearchService:
    """Construct the concrete search service once per worker process."""
    from backend.app.services.search import AzureAISearchService
    return AzureAISearchService()


def get_search_service() -> AbstractSearchService:
    """
    Inject the concrete search service.

    Routes declare this as:
        search: AbstractSearchService = Depends(get_search_service)

    Tests override it as:
        app.dependency_overrides[get_search_service] = lambda: MockSearchService()
    """
    return _create_search_service()


# ---------------------------------------------------------------------------
# Chunker service
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _create_chunker():
    """Construct the concrete chunker once per worker process."""
    from backend.app.services.chunker import RecursiveCharacterChunker
    return RecursiveCharacterChunker(
        chunk_size=settings.ai.chunk_size,
        chunk_overlap=settings.ai.chunk_overlap,
    )


def get_chunker():
    """
    Inject the concrete chunker.

    Routes declare this as:
        chunker: AbstractChunker = Depends(get_chunker)
    """
    return _create_chunker()


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def get_pipeline_orchestrator(
    document_service: AbstractDocumentService = Depends(get_document_service),
    chunker = Depends(get_chunker),
    search_service: AbstractSearchService = Depends(get_search_service),
) -> DocumentPipelineOrchestrator:
    """
    Construct and inject the pipeline orchestrator.

    Resolves all necessary service dependencies and returns a configured
    orchestrator instance ready to execute the processing pipeline.

    Routes declare this as:
        orchestrator: DocumentPipelineOrchestrator = Depends(get_pipeline_orchestrator)
    """
    return DocumentPipelineOrchestrator(
        document_service=document_service,
        chunker=chunker,
        search_service=search_service,
    )


# ---------------------------------------------------------------------------
# Query service
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _create_query_service() -> AbstractQueryService:
    """Construct the concrete query service once per worker process."""
    from backend.app.services.query import QueryService
    return QueryService(search_service=_create_search_service())


def get_query_service() -> AbstractQueryService:
    """
    Inject the concrete RAG query service.

    Routes declare this as:
        query_service: AbstractQueryService = Depends(get_query_service)

    Tests override it as:
        app.dependency_overrides[get_query_service] = lambda: MockQueryService()
    """
    return _create_query_service()


# ---------------------------------------------------------------------------
# HUD ingestion service
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _create_hud_source_adapter() -> HUDCuratedSourceAdapter:
    """Construct the HUD source adapter once per worker process."""
    return HUDCuratedSourceAdapter()


def get_hud_ingestion_service(
    search_service: AbstractSearchService = Depends(get_search_service),
    chunker=Depends(get_chunker),
) -> HUDIngestionService:
    """Inject HUD ingestion coordinator for source sync/list routes."""
    return HUDIngestionService(
        source_adapter=_create_hud_source_adapter(),
        search_service=search_service,
        chunker=chunker,
    )


