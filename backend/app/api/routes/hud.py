"""HUD source sync and listing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies import (
    get_current_user_id,
    get_db_session,
    get_hud_ingestion_service,
)
from backend.app.models.schemas import (
    HUDSourceListResponse,
    HUDSourceRecord,
    HUDSyncResponse,
)
from backend.app.services.hud_sources import HUDIngestionService

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/sync", response_model=HUDSyncResponse)
async def sync_hud_sources(
    refresh: bool = Query(
        default=False,
        description="Force re-fetch and reindex even when content hash has not changed.",
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    hud_service: HUDIngestionService = Depends(get_hud_ingestion_service),
) -> HUDSyncResponse:
    """Sync HUD/public legal sources into the local HUD corpus."""
    summary = await hud_service.sync_sources(
        session=session,
        user_id=current_user_id,
        force_refresh=refresh,
    )

    return HUDSyncResponse(
        ingested_count=summary.ingested_count,
        updated_count=summary.updated_count,
        skipped_count=summary.skipped_count,
        failed_count=summary.failed_count,
        sources=[
            HUDSourceRecord(
                source_id=source.source_id,
                document_id=source.document_id,
                title=source.title,
                source_url=source.source_url,
                regulation_id=source.regulation_id,
                effective_date=source.effective_date,
                processing_status=source.processing_status,
                operation=source.operation,
                last_synced_at=source.last_synced_at,
            )
            for source in summary.sources
        ],
        strategy_note=(
            "HUD User offers free dataset APIs (FMR/Income Limits) but not complete legal text. "
            "This endpoint ingests authoritative HUD/public legal-policy sources for grounded Q&A."
        ),
    )


@router.get("/sources", response_model=HUDSourceListResponse)
async def list_hud_sources(
    ensure_synced: bool = Query(
        default=True,
        description="Run idempotent sync before listing sources.",
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user_id: str = Depends(get_current_user_id),
    hud_service: HUDIngestionService = Depends(get_hud_ingestion_service),
) -> HUDSourceListResponse:
    """List HUD corpus sources available to the current user."""
    if ensure_synced:
        await hud_service.sync_sources(
            session=session,
            user_id=current_user_id,
            force_refresh=False,
        )

    sources = await hud_service.list_sources_for_user(
        session=session,
        user_id=current_user_id,
    )

    return HUDSourceListResponse(
        sources=[
            HUDSourceRecord(
                source_id=source.source_id,
                document_id=source.document_id,
                title=source.title,
                source_url=source.source_url,
                regulation_id=source.regulation_id,
                effective_date=source.effective_date,
                processing_status=source.processing_status,
                operation=source.operation,
                last_synced_at=source.last_synced_at,
            )
            for source in sources
        ],
        total_count=len(sources),
    )
