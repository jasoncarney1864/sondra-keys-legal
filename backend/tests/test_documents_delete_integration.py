from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.app.api.dependencies import (
    get_document_service,
    get_pipeline_orchestrator,
    get_search_service,
)
from backend.app.core.config import settings
from backend.app.models.db import (
    DocumentChunkORM,
    DocumentRecordORM,
    ProcessingStatus,
    UserDocumentAccessORM,
    UserRecordORM,
    UserSessionORM,
)


class StubDocumentService:
    def __init__(self):
        self.deleted_blobs: list[str] = []

    async def delete_blob(self, blob_name: str) -> None:
        self.deleted_blobs.append(blob_name)


class StubSearchService:
    def __init__(self):
        self.deleted_document_ids: list[str] = []

    async def delete_document_chunks(self, document_id: str) -> None:
        self.deleted_document_ids.append(document_id)


class StubOrchestrator:
    def __init__(self):
        self.pipeline_runs: list[str] = []

    async def run_pipeline(self, document_id, file_bytes, file_name, session_factory):
        self.pipeline_runs.append(str(document_id))


async def _seed_document_graph(db_session_maker, *, status: ProcessingStatus) -> tuple[str, UUID]:
    doc_id = uuid4()
    session_id = uuid4()

    async with db_session_maker() as session:
        primary_user = UserRecordORM(id=settings.security.default_dev_user_id)
        secondary_user = UserRecordORM(id="other-user")
        session.add_all([primary_user, secondary_user])

        doc = DocumentRecordORM(
            id=doc_id,
            file_name="lease.pdf",
            file_size_bytes=1234,
            content_type="application/pdf",
            uploaded_by_user_id=primary_user.id,
            blob_name="content/test-hash",
            blob_url="https://example.invalid/content/test-hash",
            parsed_json_blob_name="parsed-json/test-hash.json",
            processing_status=status,
        )
        session.add(doc)
        session.add(
            DocumentChunkORM(
                document_id=doc_id,
                chunk_index=0,
                content="sample",
                char_count=6,
                page_number=1,
                section_title="Test",
                start_position=0,
                end_position=6,
                embedding_id="chunk-0",
            )
        )

        session.add_all(
            [
                UserDocumentAccessORM(user_id=primary_user.id, document_id=doc_id),
                UserDocumentAccessORM(user_id=secondary_user.id, document_id=doc_id),
            ]
        )

        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        session.add_all(
            [
                UserSessionORM(
                    id=session_id,
                    user_id=primary_user.id,
                    active_document_id=doc_id,
                    expires_at=expires_at,
                ),
                UserSessionORM(
                    id=uuid4(),
                    user_id=secondary_user.id,
                    active_document_id=doc_id,
                    expires_at=expires_at,
                ),
            ]
        )

        await session.commit()

    return str(doc_id), doc_id


@pytest.mark.asyncio
async def test_delete_document_cleans_up_db_and_artifacts_for_failed_status(client, test_app, db_session_maker):
    stub_document_service = StubDocumentService()
    stub_search_service = StubSearchService()
    test_app.dependency_overrides[get_document_service] = lambda: stub_document_service
    test_app.dependency_overrides[get_search_service] = lambda: stub_search_service

    document_id, document_uuid = await _seed_document_graph(db_session_maker, status=ProcessingStatus.FAILED)

    response = await client.delete(
        f"/api/documents/{document_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert response.status_code == 204

    assert stub_search_service.deleted_document_ids == [document_id]
    assert set(stub_document_service.deleted_blobs) == {
        "content/test-hash",
        "parsed-json/test-hash.json",
    }

    async with db_session_maker() as session:
        doc = await session.get(DocumentRecordORM, document_uuid)
        assert doc is None

        chunks = (
            await session.execute(
                select(DocumentChunkORM).where(DocumentChunkORM.document_id == document_uuid)
            )
        ).scalars().all()
        assert chunks == []

        links = (
            await session.execute(
                select(UserDocumentAccessORM).where(UserDocumentAccessORM.document_id == document_uuid)
            )
        ).scalars().all()
        assert links == []

        active_sessions = (
            await session.execute(
                select(UserSessionORM).where(UserSessionORM.active_document_id == document_uuid)
            )
        ).scalars().all()
        assert active_sessions == []


@pytest.mark.asyncio
async def test_delete_document_is_idempotent_for_completed_status(client, test_app, db_session_maker):
    stub_document_service = StubDocumentService()
    stub_search_service = StubSearchService()
    test_app.dependency_overrides[get_document_service] = lambda: stub_document_service
    test_app.dependency_overrides[get_search_service] = lambda: stub_search_service

    document_id, _ = await _seed_document_graph(db_session_maker, status=ProcessingStatus.COMPLETED)

    first = await client.delete(
        f"/api/documents/{document_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert first.status_code == 204

    second = await client.delete(
        f"/api/documents/{document_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert second.status_code == 204


@pytest.mark.asyncio
async def test_delete_document_allows_reuse_of_blob_name_for_reingestion(client, test_app, db_session_maker):
    stub_document_service = StubDocumentService()
    stub_search_service = StubSearchService()
    test_app.dependency_overrides[get_document_service] = lambda: stub_document_service
    test_app.dependency_overrides[get_search_service] = lambda: stub_search_service

    document_id, _ = await _seed_document_graph(db_session_maker, status=ProcessingStatus.PENDING)

    response = await client.delete(
        f"/api/documents/{document_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert response.status_code == 204

    async with db_session_maker() as session:
        replacement = DocumentRecordORM(
            id=uuid4(),
            file_name="lease-reupload.pdf",
            file_size_bytes=4321,
            content_type="application/pdf",
            uploaded_by_user_id=settings.security.default_dev_user_id,
            blob_name="content/test-hash",
            blob_url="https://example.invalid/content/test-hash",
            processing_status=ProcessingStatus.PENDING,
        )
        session.add(replacement)
        await session.commit()

        persisted = await session.get(DocumentRecordORM, replacement.id)
        assert persisted is not None


@pytest.mark.asyncio
async def test_upload_delete_reupload_is_clean_and_reuses_document_identity(client, test_app):
    stub_document_service = StubDocumentService()
    stub_search_service = StubSearchService()
    stub_orchestrator = StubOrchestrator()
    test_app.dependency_overrides[get_document_service] = lambda: stub_document_service
    test_app.dependency_overrides[get_search_service] = lambda: stub_search_service
    test_app.dependency_overrides[get_pipeline_orchestrator] = lambda: stub_orchestrator

    file_bytes = b"same-bytes-for-reingestion"
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    session_response = await client.post(
        "/api/sessions",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]

    headers = {
        "X-API-Key": settings.security.api_key,
        "X-Session-Id": session_id,
    }

    upload_one = await client.post(
        "/api/documents/upload",
        headers=headers,
        files={
            "file": ("reingest.txt", file_bytes, "text/plain"),
        },
    )
    assert upload_one.status_code == 202
    payload_one = upload_one.json()
    assert payload_one["status"] == "pending"
    first_document_id = payload_one["document_id"]

    before_delete = await client.get(
        "/api/documents?skip=0&limit=50",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert before_delete.status_code == 200
    before_payload = before_delete.json()
    assert before_payload["total_count"] == 1
    assert before_payload["documents"][0]["document_id"] == first_document_id

    delete_response = await client.delete(
        f"/api/documents/{first_document_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert delete_response.status_code == 204
    assert stub_search_service.deleted_document_ids == [first_document_id]
    assert stub_document_service.deleted_blobs == [f"content/{content_hash}"]

    after_delete = await client.get(
        "/api/documents?skip=0&limit=50",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert after_delete.status_code == 200
    assert after_delete.json()["total_count"] == 0

    upload_two = await client.post(
        "/api/documents/upload",
        headers=headers,
        files={
            "file": ("reingest.txt", file_bytes, "text/plain"),
        },
    )
    assert upload_two.status_code == 202
    payload_two = upload_two.json()
    assert payload_two["status"] == "pending"
    assert payload_two["message"].startswith("Document queued for processing")
    second_document_id = payload_two["document_id"]

    # Deterministic ID proves clean recreation path without stale duplicate linkage.
    assert second_document_id == first_document_id

    after_reupload = await client.get(
        "/api/documents?skip=0&limit=50",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert after_reupload.status_code == 200
    after_reupload_payload = after_reupload.json()
    assert after_reupload_payload["total_count"] == 1
    assert after_reupload_payload["documents"][0]["document_id"] == second_document_id
