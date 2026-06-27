from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update

from backend.app.core.config import settings
from backend.app.models.db import DocumentRecordORM, ProcessingStatus
from backend.app.models.schemas import (
    AnalysisResultSchema,
    BlobUploadResultSchema,
    ChunkCreateSchema,
    DocumentHeadingSchema,
    DocumentMetadataSchema,
    DocumentStructureSchema,
)
from backend.app.services.orchestrator import DocumentPipelineOrchestrator


class FakeDocumentService:
    def __init__(self) -> None:
        self.cache: dict[str, dict] = {}
        self.extract_calls = 0
        self.load_calls = 0
        self.save_calls = 0

    async def upload_to_blob(self, file_data, file_name, *, content_type="application/octet-stream"):
        return BlobUploadResultSchema(
            blob_name=file_name,
            blob_url=f"https://example.blob/{file_name}",
            content_type=content_type,
            size_bytes=len(file_data),
        )

    async def delete_blob(self, blob_name: str) -> None:
        return None

    async def get_blob_url(self, blob_name: str) -> str:
        return f"https://example.blob/{blob_name}?sig=test"

    async def load_parsed_json(self, blob_name: str):
        self.load_calls += 1
        return self.cache.get(blob_name)

    async def save_parsed_json(self, blob_name: str, payload: dict):
        self.save_calls += 1
        self.cache[blob_name] = payload
        return blob_name

    async def extract_metadata_with_doc_intel(self, blob_url: str, *, document_id: str):
        self.extract_calls += 1
        return AnalysisResultSchema(
            document_id=document_id,
            file_name="cache-test.pdf",
            text="This is a parsed test document.",
            metadata=DocumentMetadataSchema(
                file_name="cache-test.pdf",
                page_count=1,
                document_type="pdf",
                extraction_date=datetime.now(timezone.utc),
            ),
            structure=DocumentStructureSchema(
                headings=[DocumentHeadingSchema(text="Section 1", level="h1", confidence=1.0)],
                sections=["Section 1"],
            ),
            raw_extraction={"source": "fake"},
        )


class FakeChunker:
    chunk_size = 1024
    chunk_overlap = 20

    def split_document(self, analysis_result: AnalysisResultSchema):
        return [
            ChunkCreateSchema(
                document_id=analysis_result.document_id,
                chunk_index=0,
                content=analysis_result.text,
                page_number=1,
                section_title="Section 1",
                start_position=0,
                end_position=len(analysis_result.text),
            )
        ]


class FakeSearchService:
    async def index_chunks(self, document_id: str, chunks, file_name: str = "") -> None:
        return None

    async def vector_search(self, query_vector, top_k: int, document_ids=None):
        return []

    async def hybrid_search(self, query_text: str, query_vector, top_k: int, document_ids=None):
        return []

    async def delete_document_chunks(self, document_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_parsed_json_cache_miss_then_hit_reuse(db_session_maker):
    old_cache_setting = settings.parsed_json_cache_enabled
    old_prefix = settings.parsed_json_cache_prefix
    old_parser_version = settings.parsed_json_cache_parser_version

    settings.parsed_json_cache_enabled = True
    settings.parsed_json_cache_prefix = "parsed"
    settings.parsed_json_cache_parser_version = "prebuilt-layout-v1"

    try:
        document_id = uuid4()
        blob_name = "content/cache-hash-123"

        async with db_session_maker() as session:
            session.add(
                DocumentRecordORM(
                    id=document_id,
                    file_name="cache-test.pdf",
                    file_size_bytes=1024,
                    content_type="application/pdf",
                    blob_name=blob_name,
                    blob_url="",
                    processing_status=ProcessingStatus.PENDING,
                )
            )
            await session.commit()

        fake_document_service = FakeDocumentService()
        orchestrator = DocumentPipelineOrchestrator(
            document_service=fake_document_service,
            chunker=FakeChunker(),
            search_service=FakeSearchService(),
        )

        await orchestrator.run_pipeline(
            document_id=document_id,
            file_bytes=b"%PDF-1.4 cache test",
            file_name="cache-test.pdf",
            session_factory=db_session_maker,
        )

        async with db_session_maker() as session:
            await session.execute(
                update(DocumentRecordORM)
                .where(DocumentRecordORM.id == document_id)
                .values(
                    processing_status=ProcessingStatus.PENDING,
                    completed_timestamp=None,
                    error_message=None,
                )
            )
            await session.commit()

        await orchestrator.run_pipeline(
            document_id=document_id,
            file_bytes=b"%PDF-1.4 cache test",
            file_name="cache-test.pdf",
            session_factory=db_session_maker,
        )

        assert fake_document_service.load_calls == 2
        assert fake_document_service.save_calls == 1
        assert fake_document_service.extract_calls == 1

        async with db_session_maker() as session:
            doc = await session.get(DocumentRecordORM, document_id)
            assert doc is not None
            assert doc.parsed_json_blob_name == "parsed/cache-hash-123.json"
            assert doc.parser_version == "prebuilt-layout-v1"
            assert doc.processing_status == ProcessingStatus.COMPLETED
    finally:
        settings.parsed_json_cache_enabled = old_cache_setting
        settings.parsed_json_cache_prefix = old_prefix
        settings.parsed_json_cache_parser_version = old_parser_version
