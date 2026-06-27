from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import select

from backend.app.api.dependencies import get_hud_ingestion_service
from backend.app.core.config import settings
from backend.app.models.db import DocumentChunkORM, DocumentRecordORM, UserDocumentAccessORM, UserRecordORM
from backend.app.services.hud_sources import (
    HUDIngestionRecord,
    HUDIngestionService,
    HUDIngestionSummary,
    HUDSourceDocument,
)
from backend.app.models.schemas import ChunkCreateSchema


class StubChunker:
    def split_document(self, analysis_result):
        return [
            ChunkCreateSchema(
                document_id=analysis_result.document_id,
                chunk_index=0,
                content=analysis_result.text,
                page_number=None,
                section_title='stub-section',
                start_position=0,
                end_position=len(analysis_result.text),
            )
        ]


class StubSearchService:
    def __init__(self):
        self.deleted_document_ids: list[str] = []
        self.index_calls: list[tuple[str, int, str]] = []

    async def delete_document_chunks(self, document_id: str) -> None:
        self.deleted_document_ids.append(document_id)

    async def index_chunks(self, document_id: str, chunks, file_name: str = '') -> None:
        self.index_calls.append((document_id, len(chunks), file_name))


@dataclass
class StaticAdapter:
    documents: list[HUDSourceDocument]

    async def fetch_sources(self) -> list[HUDSourceDocument]:
        return self.documents


@pytest.mark.asyncio
async def test_hud_ingestion_sync_is_idempotent_and_updates_when_content_changes(
    db_session_maker,
    tmp_path,
    monkeypatch,
):
    user_id = settings.security.default_dev_user_id
    state_path = tmp_path / 'hud-state.json'

    monkeypatch.setattr(settings.hud, 'source_state_path', state_path.as_posix())
    monkeypatch.setattr(settings.hud, 'sync_enabled', True)

    source = HUDSourceDocument(
        source_id='fair-housing-act-overview',
        title='HUD Fair Housing Act Overview',
        source_url='https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview',
        regulation_id='42 U.S.C. 3601-3619 (Fair Housing Act)',
        effective_date='1968-04-11',
        content='Initial source content.',
    )

    adapter = StaticAdapter(documents=[source])
    search = StubSearchService()
    service = HUDIngestionService(
        source_adapter=adapter,
        search_service=search,
        chunker=StubChunker(),
    )

    async with db_session_maker() as session:
        first = await service.sync_sources(session=session, user_id=user_id)

    assert first.ingested_count == 1
    assert first.updated_count == 0
    assert first.skipped_count == 0
    assert first.failed_count == 0
    assert len(search.index_calls) == 1

    async with db_session_maker() as session:
        second = await service.sync_sources(session=session, user_id=user_id)

    assert second.ingested_count == 0
    assert second.updated_count == 0
    assert second.skipped_count == 1
    assert len(search.index_calls) == 1

    adapter.documents = [
        HUDSourceDocument(
            source_id='fair-housing-act-overview',
            title='HUD Fair Housing Act Overview',
            source_url='https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview',
            regulation_id='42 U.S.C. 3601-3619 (Fair Housing Act)',
            effective_date='1968-04-11',
            content='Updated source content with new detail.',
        )
    ]

    async with db_session_maker() as session:
        third = await service.sync_sources(session=session, user_id=user_id)

    assert third.ingested_count == 0
    assert third.updated_count == 1
    assert third.skipped_count == 0
    assert len(search.index_calls) == 2

    document_id = uuid5(NAMESPACE_URL, 'hud-source:fair-housing-act-overview')

    async with db_session_maker() as session:
        persisted = await session.get(DocumentRecordORM, document_id)
        assert persisted is not None
        assert persisted.file_name == '[HUD] HUD Fair Housing Act Overview'
        assert persisted.processing_status.value == 'completed'

        user = await session.get(UserRecordORM, user_id)
        assert user is not None

        chunks = (
            await session.execute(
                select(DocumentChunkORM).where(DocumentChunkORM.document_id == document_id)
            )
        ).scalars().all()
        assert len(chunks) == 1

        links = (
            await session.execute(
                select(UserDocumentAccessORM).where(
                    UserDocumentAccessORM.user_id == user_id,
                    UserDocumentAccessORM.document_id == document_id,
                )
            )
        ).scalars().all()
        assert len(links) == 1


class StubHUDIngestionService:
    def __init__(self, record: HUDIngestionRecord):
        self.record = record
        self.sync_calls = 0
        self.list_calls = 0

    async def sync_sources(self, session, user_id: str, force_refresh: bool = False):
        self.sync_calls += 1
        return HUDIngestionSummary(
            ingested_count=1,
            updated_count=0,
            skipped_count=0,
            failed_count=0,
            sources=[self.record],
        )

    async def list_sources_for_user(self, session, user_id: str):
        self.list_calls += 1
        return [self.record]


@pytest.mark.asyncio
async def test_hud_sync_and_sources_routes_return_expected_payload(client, test_app):
    record = HUDIngestionRecord(
        source_id='fair-housing-act-overview',
        document_id=uuid5(NAMESPACE_URL, 'hud-source:fair-housing-act-overview'),
        title='HUD Fair Housing Act Overview',
        source_url='https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview',
        regulation_id='42 U.S.C. 3601-3619 (Fair Housing Act)',
        effective_date='1968-04-11',
        processing_status='completed',
        operation='ingested',
        content_hash='abc123',
        last_synced_at=datetime.now(timezone.utc),
    )

    stub_service = StubHUDIngestionService(record)
    test_app.dependency_overrides[get_hud_ingestion_service] = lambda: stub_service

    sync_response = await client.post(
        '/api/hud/sync',
        headers={'X-API-Key': settings.security.api_key},
    )

    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload['ingested_count'] == 1
    assert sync_payload['failed_count'] == 0
    assert sync_payload['sources'][0]['source_id'] == 'fair-housing-act-overview'
    assert 'HUD User offers free dataset APIs' in sync_payload['strategy_note']

    sources_response = await client.get(
        '/api/hud/sources?ensure_synced=false',
        headers={'X-API-Key': settings.security.api_key},
    )

    assert sources_response.status_code == 200
    sources_payload = sources_response.json()
    assert sources_payload['total_count'] == 1
    assert sources_payload['sources'][0]['title'] == 'HUD Fair Housing Act Overview'

    assert stub_service.sync_calls == 1
    assert stub_service.list_calls == 1
