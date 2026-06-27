"""
HUD source adapters and ingestion orchestration.

This module powers the HUD-specific corpus used by the HUD Ask site.
It supports resilient source fetching, deterministic dedupe/upsert,
and search/index synchronization with citation-ready metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.models.db import (
    DocumentChunkORM,
    DocumentRecordORM,
    ProcessingStatus,
    UserDocumentAccessORM,
)
from backend.app.models.schemas import (
    AnalysisResultSchema,
    ChunkCreateSchema,
    DocumentMetadataSchema,
    DocumentStructureSchema,
)
from backend.app.services.interfaces import AbstractSearchService

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class HUDSourceDocument:
    """Normalized HUD source payload used for ingestion."""

    source_id: str
    title: str
    source_url: str
    regulation_id: str
    effective_date: str | None
    content: str


@dataclass
class HUDIngestionRecord:
    """Source-level ingestion summary for API responses and logs."""

    source_id: str
    document_id: UUID
    title: str
    source_url: str
    regulation_id: str
    effective_date: str | None
    processing_status: str
    operation: str
    content_hash: str
    last_synced_at: datetime


@dataclass
class HUDIngestionSummary:
    """Aggregate HUD sync outcome."""

    ingested_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    sources: list[HUDIngestionRecord]


class AbstractHUDSourceAdapter(ABC):
    """Contract for collecting HUD legal/policy source content."""

    @abstractmethod
    async def fetch_sources(self) -> list[HUDSourceDocument]:
        """Return normalized source documents ready for ingestion."""
        ...


_HUD_SOURCE_CATALOG: list[dict[str, str]] = [
    {
        "source_id": "fair-housing-act-overview",
        "title": "HUD Fair Housing Act Overview",
        "source_url": "https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview",
        "regulation_id": "42 U.S.C. 3601-3619 (Fair Housing Act)",
        "effective_date": "1968-04-11",
        "fallback_excerpt": (
            "The Fair Housing Act protects people from discrimination when they are renting, buying, "
            "or securing financing for housing. Protected classes include race, color, national origin, "
            "religion, sex, familial status, and disability. It is unlawful to refuse to rent or sell housing, "
            "set different terms, provide different services, or make housing unavailable based on a protected "
            "class. The Act also prohibits discriminatory advertising and coercion related to fair housing rights. "
            "HUD enforces these requirements through complaint investigations and administrative actions."
        ),
    },
    {
        "source_id": "cfr-title-24-part-5",
        "title": "24 CFR Part 5: General HUD Program Requirements",
        "source_url": "https://www.ecfr.gov/current/title-24/subtitle-A/part-5",
        "regulation_id": "24 CFR Part 5",
        "effective_date": "current",
        "fallback_excerpt": (
            "Title 24 CFR Part 5 provides general HUD requirements that apply across assisted housing programs. "
            "It defines terms, occupancy and income verification requirements, and program integrity obligations. "
            "Part 5 includes provisions related to annual income determination, adjusted income, and verification "
            "of family composition. HUD-assisted housing administrators must follow these requirements when making "
            "eligibility and rent determinations."
        ),
    },
    {
        "source_id": "hud-user-datasets-api",
        "title": "HUD User Datasets API Scope Note",
        "source_url": "https://www.huduser.gov/portal/dataset/fmr-api.html",
        "regulation_id": "HUD User API (FMR and Income Limits)",
        "effective_date": "current",
        "fallback_excerpt": (
            "HUD User provides free API access to datasets such as Fair Market Rents and Income Limits. "
            "Access requires account registration and bearer token usage. These APIs are focused on program "
            "datasets and not full statutory legal text. For legal Q&A, API dataset outputs should be treated "
            "as supplemental context and combined with authoritative law and regulation sources."
        ),
    },
]


class HUDCuratedSourceAdapter(AbstractHUDSourceAdapter):
    """Fetch curated HUD/public sources with resilient live-fetch fallback."""

    _html_tag_pattern = re.compile(r"<[^>]+>")
    _script_style_pattern = re.compile(
        r"<(script|style)[^>]*>.*?</\\1>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    async def fetch_sources(self) -> list[HUDSourceDocument]:
        documents: list[HUDSourceDocument] = []
        timeout = httpx.Timeout(settings.hud.fetch_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for source in _HUD_SOURCE_CATALOG:
                fallback_content = source["fallback_excerpt"]
                content = fallback_content

                if settings.hud.enable_live_fetch:
                    fetched = await self._fetch_with_retry(client, source["source_url"])
                    if fetched and len(fetched) >= 400:
                        content = fetched

                documents.append(
                    HUDSourceDocument(
                        source_id=source["source_id"],
                        title=source["title"],
                        source_url=source["source_url"],
                        regulation_id=source["regulation_id"],
                        effective_date=source.get("effective_date") or None,
                        content=content,
                    )
                )

        logger.info("hud_sources_fetched", count=len(documents))
        return documents

    async def _fetch_with_retry(self, client: httpx.AsyncClient, source_url: str) -> str | None:
        """Fetch and normalize source text with retry/backoff and 429 handling."""
        for attempt in range(1, settings.hud.fetch_max_retries + 1):
            try:
                response = await client.get(source_url)
                if response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "rate_limited",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return self._normalize_source_text(response.text)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response is not None and exc.response.status_code in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not retryable or attempt == settings.hud.fetch_max_retries:
                    logger.warning(
                        "hud_source_fetch_http_failed",
                        source_url=source_url,
                        status_code=(exc.response.status_code if exc.response else None),
                        attempt=attempt,
                    )
                    return None
            except httpx.RequestError:
                if attempt == settings.hud.fetch_max_retries:
                    logger.warning(
                        "hud_source_fetch_network_failed",
                        source_url=source_url,
                        attempt=attempt,
                    )
                    return None

            backoff = settings.hud.fetch_backoff_seconds * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)

        return None

    def _normalize_source_text(self, html: str) -> str:
        """Convert HTML to compact plain text for ingestion."""
        without_scripts = self._script_style_pattern.sub(" ", html)
        without_tags = self._html_tag_pattern.sub(" ", without_scripts)
        decoded = unescape(without_tags)
        normalized = re.sub(r"\\s+", " ", decoded).strip()
        return normalized


class HUDIngestionService:
    """Coordinate HUD source ingest, dedupe/upsert, and user access mapping."""

    def __init__(
        self,
        source_adapter: AbstractHUDSourceAdapter,
        search_service: AbstractSearchService,
        chunker,
    ):
        self.source_adapter = source_adapter
        self.search_service = search_service
        self.chunker = chunker

    async def sync_sources(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        force_refresh: bool = False,
    ) -> HUDIngestionSummary:
        if not settings.hud.sync_enabled:
            return HUDIngestionSummary(
                ingested_count=0,
                updated_count=0,
                skipped_count=0,
                failed_count=0,
                sources=[],
            )

        sources = await self.source_adapter.fetch_sources()
        state = self._load_state()
        source_state: dict[str, dict[str, Any]] = state.setdefault("sources", {})

        ingested_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        results: list[HUDIngestionRecord] = []

        for source in sources:
            try:
                record = await self._sync_single_source(
                    session=session,
                    user_id=user_id,
                    source=source,
                    source_state=source_state,
                    force_refresh=force_refresh,
                )
                results.append(record)

                if record.operation == "ingested":
                    ingested_count += 1
                elif record.operation == "updated":
                    updated_count += 1
                else:
                    skipped_count += 1
            except Exception as exc:
                failed_count += 1
                await session.rollback()
                logger.error(
                    "hud_source_sync_failed",
                    source_id=source.source_id,
                    error_detail=str(exc)[:500],
                    exc_info=True,
                )

        self._save_state(state)

        logger.info(
            "hud_sources_sync_completed",
            ingested_count=ingested_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )

        return HUDIngestionSummary(
            ingested_count=ingested_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            sources=results,
        )

    async def list_sources_for_user(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[HUDIngestionRecord]:
        state = self._load_state()
        source_state: dict[str, dict[str, Any]] = state.get("sources", {})

        sources: list[HUDIngestionRecord] = []

        for source_id, payload in source_state.items():
            document_id = UUID(payload["document_id"])
            record = await session.get(DocumentRecordORM, document_id)
            if record is None:
                continue

            await self._ensure_user_document_access(session, user_id, document_id)

            synced_at_raw = payload.get("last_synced_at")
            synced_at = (
                datetime.fromisoformat(synced_at_raw)
                if isinstance(synced_at_raw, str)
                else datetime.now(timezone.utc)
            )

            sources.append(
                HUDIngestionRecord(
                    source_id=source_id,
                    document_id=document_id,
                    title=payload.get("title", record.file_name),
                    source_url=payload.get("source_url", record.blob_url),
                    regulation_id=payload.get("regulation_id", "HUD"),
                    effective_date=payload.get("effective_date"),
                    processing_status=record.processing_status.value,
                    operation="existing",
                    content_hash=payload.get("content_hash", ""),
                    last_synced_at=synced_at,
                )
            )

        await session.commit()

        return sorted(sources, key=lambda item: item.title.lower())

    async def _sync_single_source(
        self,
        session: AsyncSession,
        user_id: str,
        source: HUDSourceDocument,
        source_state: dict[str, dict[str, Any]],
        force_refresh: bool,
    ) -> HUDIngestionRecord:
        document_id = uuid5(NAMESPACE_URL, f"hud-source:{source.source_id}")
        content_hash = hashlib.sha256(source.content.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        existing_record = await session.get(DocumentRecordORM, document_id)

        previous_state = source_state.get(source.source_id)
        unchanged = (
            previous_state
            and previous_state.get("content_hash") == content_hash
            and existing_record is not None
            and not force_refresh
        )

        if unchanged:
            await self._ensure_user_document_access(session, user_id, document_id)
            await session.commit()
            return HUDIngestionRecord(
                source_id=source.source_id,
                document_id=document_id,
                title=source.title,
                source_url=source.source_url,
                regulation_id=source.regulation_id,
                effective_date=source.effective_date,
                processing_status=existing_record.processing_status.value,
                operation="skipped",
                content_hash=content_hash,
                last_synced_at=datetime.fromisoformat(previous_state["last_synced_at"]),
            )

        source_metadata_line = (
            f"Regulation: {source.regulation_id} | "
            f"Effective: {source.effective_date or 'unspecified'} | "
            f"Source: {source.source_url}"
        )
        corpus_text = (
            f"Source Title: {source.title}\\n"
            f"Source URL: {source.source_url}\\n"
            f"Regulation: {source.regulation_id}\\n"
            f"Effective Date: {source.effective_date or 'unspecified'}\\n\\n"
            f"{source.content}"
        )

        analysis_result = AnalysisResultSchema(
            document_id=document_id,
            file_name=f"[HUD] {source.title}",
            text=corpus_text,
            metadata=DocumentMetadataSchema(
                file_name=f"[HUD] {source.title}",
                page_count=None,
                document_type="hud_source",
                extraction_date=now,
            ),
            structure=DocumentStructureSchema(sections=[source.regulation_id]),
            raw_extraction=None,
        )

        chunks = self.chunker.split_document(analysis_result)
        for chunk in chunks:
            chunk.section_title = source_metadata_line

        operation = "ingested"
        if existing_record is None:
            existing_record = DocumentRecordORM(
                id=document_id,
                file_name=f"[HUD] {source.title}",
                file_size_bytes=len(corpus_text.encode("utf-8")),
                content_type="text/plain",
                uploaded_by_user_id=None,
                blob_name=f"hud/source/{source.source_id}",
                blob_url=source.source_url,
                processing_status=ProcessingStatus.COMPLETED,
                completed_timestamp=now,
                parser_version="hud-ingestion-v1",
            )
            session.add(existing_record)
        else:
            operation = "updated"
            existing_record.file_name = f"[HUD] {source.title}"
            existing_record.file_size_bytes = len(corpus_text.encode("utf-8"))
            existing_record.content_type = "text/plain"
            existing_record.blob_name = f"hud/source/{source.source_id}"
            existing_record.blob_url = source.source_url
            existing_record.processing_status = ProcessingStatus.COMPLETED
            existing_record.error_message = None
            existing_record.completed_timestamp = now
            existing_record.parser_version = "hud-ingestion-v1"

        await session.flush()

        await self.search_service.delete_document_chunks(str(document_id))
        await session.execute(
            delete(DocumentChunkORM).where(DocumentChunkORM.document_id == document_id)
        )

        await self.search_service.index_chunks(
            str(document_id),
            chunks,
            file_name=f"[HUD] {source.title}",
        )

        session.add_all(
            [
                DocumentChunkORM(
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    char_count=chunk.char_count,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    start_position=chunk.start_position,
                    end_position=chunk.end_position,
                    embedding_id=None,
                )
                for chunk in chunks
            ]
        )

        await self._ensure_user_document_access(session, user_id, document_id)
        await session.commit()

        source_state[source.source_id] = {
            "document_id": str(document_id),
            "title": source.title,
            "source_url": source.source_url,
            "regulation_id": source.regulation_id,
            "effective_date": source.effective_date,
            "content_hash": content_hash,
            "last_synced_at": now.isoformat(),
        }

        return HUDIngestionRecord(
            source_id=source.source_id,
            document_id=document_id,
            title=source.title,
            source_url=source.source_url,
            regulation_id=source.regulation_id,
            effective_date=source.effective_date,
            processing_status=ProcessingStatus.COMPLETED.value,
            operation=operation,
            content_hash=content_hash,
            last_synced_at=now,
        )

    async def _ensure_user_document_access(
        self,
        session: AsyncSession,
        user_id: str,
        document_id: UUID,
    ) -> None:
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

    def _load_state(self) -> dict[str, Any]:
        state_path = Path(settings.hud.source_state_path)
        if not state_path.exists():
            return {"version": 1, "sources": {}}

        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("hud_state_load_failed_resetting")
            return {"version": 1, "sources": {}}

    def _save_state(self, payload: dict[str, Any]) -> None:
        state_path = Path(settings.hud.source_state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
