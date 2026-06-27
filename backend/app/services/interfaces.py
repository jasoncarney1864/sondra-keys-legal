"""
Abstract service interfaces for the document processing pipeline.

Concrete implementations (Azure, mock, etc.) must satisfy these contracts.
Routes and orchestration code depend only on these abstractions.
"""

from abc import ABC, abstractmethod
from typing import Any

from backend.app.models.schemas import (
    AnalysisResultSchema,
    BlobUploadResultSchema,
    ChunkCreateSchema,
    QueryRequest,
    QueryResponse,
    SearchResultSchema,
)


class AbstractStorageService(ABC):
    """Contract for blob storage operations."""

    @abstractmethod
    async def upload_to_blob(
        self,
        file_data: bytes,
        file_name: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> BlobUploadResultSchema:
        """
        Upload raw bytes to blob storage.

        Returns a BlobUploadResultSchema containing the canonical URL
        that can be passed to the extraction service.

        Raises:
            BlobUploadException: on SDK or network failure.
        """
        ...

    @abstractmethod
    async def delete_blob(self, blob_name: str) -> None:
        """
        Remove a blob by its storage name.

        Raises:
            BlobNotFoundException: if the blob does not exist.
            BlobDeleteException: on SDK or network failure.
        """
        ...

    @abstractmethod
    async def get_blob_url(self, blob_name: str) -> str:
        """Return a pre-authenticated URL for a stored blob."""
        ...

    @abstractmethod
    async def download_blob(self, blob_name: str) -> bytes:
        """Download blob content bytes by blob name."""
        ...


class AbstractExtractionService(ABC):
    """Contract for document intelligence / metadata extraction."""

    @abstractmethod
    async def extract_metadata_with_doc_intel(
        self,
        blob_url: str,
        *,
        document_id: str,
    ) -> AnalysisResultSchema:
        """
        Submit a blob URL to the extraction engine and return structured results.

        Implementations handle polling / long-running operation patterns
        internally and surface only the final result.

        Raises:
            DocumentIntelligenceException: on API error.
            ExtractionTimeoutException: if the operation does not complete
                within the configured timeout window.
        """
        ...


class AbstractDocumentService(AbstractStorageService, AbstractExtractionService):
    """
    Composed interface representing the full document lifecycle:
    upload → extract → return structured metadata.

    A single concrete class may implement both halves, or they may be
    injected separately and composed at the route / orchestration layer.
    """

    @abstractmethod
    async def load_parsed_json(self, blob_name: str) -> dict[str, Any] | None:
        """Load cached parsed-document JSON by blob name.

        Returns None when the cache artifact does not exist.
        """
        ...

    @abstractmethod
    async def save_parsed_json(
        self,
        blob_name: str,
        payload: dict[str, Any],
    ) -> str:
        """Persist parsed-document JSON and return the stored blob name."""
        ...


# ---------------------------------------------------------------------------
# Chunking contract
# ---------------------------------------------------------------------------


class AbstractChunker(ABC):
    """Contract for document text-splitting strategies.

    Implementations may use character-level, token-level, or structure-aware
    splitting. The interface is synchronous because splitting is CPU-bound
    and should not hold the async event loop.
    """

    @property
    @abstractmethod
    def chunk_size(self) -> int:
        """Target character count per chunk."""
        ...

    @property
    @abstractmethod
    def chunk_overlap(self) -> int:
        """Character overlap between consecutive chunks."""
        ...

    @abstractmethod
    def split_document(
        self,
        analysis_result: AnalysisResultSchema,
    ) -> list[ChunkCreateSchema]:
        """Split a fully extracted document into indexable chunks.

        Implementations must:
        - Populate ``document_id`` from ``analysis_result.document_id``.
        - Populate ``page_number`` and ``section_title`` where derivable
          from ``analysis_result.structure``.
        - Assign ``chunk_index`` as a zero-based, contiguous sequence.
        - Never return empty ``content`` strings.

        Raises:
            ValueError: if ``analysis_result.text`` is empty or whitespace-only.
        """
        ...


# ---------------------------------------------------------------------------
# Search / vector store contract
# ---------------------------------------------------------------------------


class AbstractSearchService(ABC):
    """Contract for vector and hybrid search operations against the document index.

    Implementations wrap the Azure AI Search SDK (or any substitute) and are
    responsible for embedding generation, index management, and result mapping.
    """

    @abstractmethod
    async def index_chunks(
        self,
        document_id: str,
        chunks: list[ChunkCreateSchema],
        file_name: str = "",
    ) -> None:
        """Upsert chunk documents into the search index.

        Implementations must generate and attach embeddings before the upsert.
        On partial failure, the implementation should surface the error rather
        than silently skipping chunks.

        Raises:
            SearchIndexException: on SDK or network failure.
        """
        ...

    @abstractmethod
    async def vector_search(
        self,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchResultSchema]:
        """Pure KNN vector search — no BM25 text-scoring component.

        Use when the query is already embedded and exact keyword matching
        is not required (e.g., semantic paraphrasing over clause language).

        Implementations should honor ``document_ids`` by applying an
        index-level filter when provided.
        """
        ...

    @abstractmethod
    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchResultSchema]:
        """Reciprocal-rank fusion of BM25 full-text and KNN vector search.

        Preferred for legal Q&A because defined terms and clause references
        benefit from exact keyword matching alongside semantic retrieval.

        Implementations should honor ``document_ids`` by applying an
        index-level filter when provided.
        """
        ...

    @abstractmethod
    async def delete_document_chunks(self, document_id: str) -> None:
        """Remove all index entries associated with a document.

        Called during document deletion to keep the search index consistent
        with the database. Must be idempotent — no error if document is absent.

        Raises:
            SearchIndexException: on SDK or network failure.
        """
        ...


# ---------------------------------------------------------------------------
# RAG query contract
# ---------------------------------------------------------------------------


class AbstractQueryService(ABC):
    """Contract for the legal RAG query engine.

    Implementations execute the full retrieval-augmented generation pipeline:

    1. **Embed** — Vectorize ``request.question`` using the OpenAI embeddings
       API (same model used during indexing, e.g. ``text-embedding-3-small``).

    2. **Retrieve** — Call ``AbstractSearchService.hybrid_search()`` with the
       question text and its embedding vector to obtain the top-K candidate
       chunks via reciprocal-rank fusion of BM25 + KNN.  If
       ``request.document_ids`` is set, restrict results to those documents
       (either via a pre-filter passed to the search call or post-filter on
       the returned list).

    3. **Prompt construction** — Assemble a two-message payload:
       - *System*: Legal RAG persona — instructs the model to answer strictly
         from the provided context, never fabricate, and always cite section
         numbers when making claims.
       - *User*: Numbered context blocks (one per retrieved chunk, including
         file name and section title as headers) followed by the question.

    4. **Generate** — Submit the payload to the configured OpenAI chat model
       and receive the answer string.

    5. **Map citations** — Match each chunk consumed in the context to a
       ``CitationSchema``, propagating ``page_number``, ``section_title``, and
       a verbatim ``snippet`` from ``SearchResultSchema.content``.  Truncate to
       ``request.max_citations``.

    6. **Return** — Wrap everything in a ``QueryResponse`` including
       ``model_used``, ``latency_ms``, and the ordered ``citations`` list.
    """

    @abstractmethod
    async def answer_query(
        self,
        request: QueryRequest,
    ) -> QueryResponse:
        """Execute the RAG pipeline and return a grounded answer with citations.

        Raises:
            LLMServiceException: on OpenAI API error.
            LLMRateLimitException: on upstream rate-limit response (HTTP 429).
            LLMContextLengthException: if the assembled prompt exceeds the
                configured model's context window.
        """
        ...
