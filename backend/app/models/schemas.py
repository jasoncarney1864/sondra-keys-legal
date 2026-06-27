"""
Canonical Pydantic schemas for all API request/response payloads.

These are the shared data contracts referenced by routes, services, and tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, computed_field


# ---------------------------------------------------------------------------
# Blob storage contracts
# ---------------------------------------------------------------------------


class BlobUploadResultSchema(BaseModel):
    """Returned by AbstractStorageService.upload_to_blob."""

    blob_name: str = Field(..., description="Unique name of the blob in the container")
    blob_url: HttpUrl = Field(..., description="Canonical URL to the uploaded object")
    content_type: str
    size_bytes: int


# ---------------------------------------------------------------------------
# Document Intelligence / extraction contracts
# ---------------------------------------------------------------------------


class DocumentHeadingSchema(BaseModel):
    text: str
    level: str
    confidence: float = Field(ge=0.0, le=1.0)


class DocumentStructureSchema(BaseModel):
    headings: list[DocumentHeadingSchema] = []
    sections: list[str] = []


class DocumentMetadataSchema(BaseModel):
    file_name: str
    page_count: int | None = None
    document_type: str | None = None
    extraction_date: datetime


class AnalysisResultSchema(BaseModel):
    """
    Structured output from AbstractExtractionService.extract_metadata_with_doc_intel.
    Passed downstream to the chunker, embedder, and search index.
    """

    document_id: UUID
    file_name: str
    text: str = Field(..., description="Full extracted plain-text content")
    metadata: DocumentMetadataSchema
    structure: DocumentStructureSchema = Field(default_factory=DocumentStructureSchema)
    raw_extraction: dict[str, Any] | None = Field(
        default=None,
        description="Verbatim API response payload — retained for debugging only",
        exclude=True,
    )


# ---------------------------------------------------------------------------
# API request / response schemas (used by routes)
# ---------------------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    """Returned from POST /api/documents/upload."""

    document_id: UUID
    file_name: str
    status: str
    message: str
    chunks_created: int


class DocumentRecord(BaseModel):
    """Single document entry in list/detail responses."""

    document_id: UUID
    file_name: str
    file_size_bytes: int
    upload_timestamp: datetime
    page_count: int | None = None
    processing_status: str = "completed"
    uploaded_by_user_id: str | None = None


class DocumentListResponse(BaseModel):
    """Returned from GET /api/documents."""

    documents: list[DocumentRecord]
    total_count: int
    skip: int
    limit: int


class QueryRequest(BaseModel):
    """Payload for POST /api/query."""

    question: str = Field(..., min_length=5, max_length=1000)
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Scope the search to specific documents. Omit to search all.",
    )
    top_k: int = Field(default=5, ge=1, le=20)
    max_citations: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of citations to surface in the response.",
    )


class SessionCreateResponse(BaseModel):
    """Returned from POST /api/sessions."""

    session_id: UUID
    user_id: str
    active_document_id: UUID | None = None
    created_at: datetime
    expires_at: datetime


class SessionSummary(BaseModel):
    """Summary payload for listing user sessions."""

    session_id: UUID
    active_document_id: UUID | None = None
    active_document_file_name: str | None = None
    created_at: datetime
    last_accessed_at: datetime
    expires_at: datetime


class SessionListResponse(BaseModel):
    """Returned from GET /api/sessions."""

    sessions: list[SessionSummary]
    total_count: int


class SetActiveDocumentRequest(BaseModel):
    """Payload for setting the active document for a session."""

    document_id: UUID


class ActiveDocumentResponse(BaseModel):
    """Returned from active document set/clear/get operations."""

    session_id: UUID
    active_document_id: UUID | None = None
    active_document_file_name: str | None = None


class CitationSchema(BaseModel):
    """Rich provenance record linking an answer claim back to a specific document section."""

    document_id: UUID
    file_name: str
    chunk_index: int
    page_number: int | None = None
    section_title: str | None = None
    snippet: str = Field(..., description="Verbatim excerpt from the chunk used to ground this claim")


class QueryResponse(BaseModel):
    """Returned from POST /api/query."""

    model_config = {"protected_namespaces": ()}

    question: str
    answer: str
    citations: list[CitationSchema] = []
    model_used: str
    latency_ms: float


class ErrorResponse(BaseModel):
    """Standard error envelope for all 4xx / 5xx responses."""

    error_type: str
    detail: str
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Chunking pipeline contracts
# ---------------------------------------------------------------------------


class ChunkCreateSchema(BaseModel):
    """Produced by AbstractChunker.split_document; consumed by AbstractSearchService.index_chunks.

    Represents a single unit of retrieval before it is persisted or indexed.
    The document_id ties the chunk back to its parent DocumentRecordORM row.
    """

    document_id: UUID
    chunk_index: int = Field(..., ge=0, description="Zero-based position within the document")
    content: str = Field(..., min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    start_position: int = Field(default=0, ge=0, description="Character offset in full document text")
    end_position: int = Field(default=0, ge=0, description="Character offset in full document text")

    @computed_field
    @property
    def char_count(self) -> int:
        return len(self.content)


class ChunkReadSchema(ChunkCreateSchema):
    """ChunkCreateSchema extended with DB-assigned fields after persistence."""

    id: UUID
    embedding_id: str | None = Field(
        default=None,
        description="Key of the corresponding entry in the Azure AI Search index",
    )
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Search result contracts
# ---------------------------------------------------------------------------


class SearchResultSchema(BaseModel):
    """Unified search result returned by AbstractSearchService methods.

    Merges the relevant fields from both the search index and the DB record
    so that routes can build CitationSchema objects without a second DB lookup.
    """

    document_id: UUID
    chunk_id: UUID | None = None
    file_name: str
    chunk_index: int
    content: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    page_number: int | None = None
    section_title: str | None = None
