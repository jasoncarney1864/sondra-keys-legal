"""
Concrete Azure AI Search service implementation.

Wraps the asynchronous Azure SDK SearchClient and bootstraps the backing index
through the Azure AI Search REST API. Implements the AbstractSearchService
contract for chunk indexing, vector search, and hybrid BM25+KNN retrieval.

All Azure SDK calls are wrapped in error handling that maps to custom exceptions.
"""

from __future__ import annotations

import logging

import aiohttp
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import (
    VectorizedQuery,
)
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.core.exceptions import StorageServiceException
from backend.app.models.schemas import (
    ChunkCreateSchema,
    SearchResultSchema,
)
from backend.app.services.interfaces import AbstractSearchService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Document schema for Azure Search
# ---------------------------------------------------------------------------


class ChunkDocument(BaseModel):
    """Schema of documents stored in the Azure Search index."""

    id: str  # Unique document ID in the index (chunk_id or "doc_id#chunk_index")
    document_id: str  # Parent document ID (for filtering/deletion)
    chunk_index: int  # Zero-based chunk sequence
    content: str  # The searchable text
    content_vector: list[float]  # Embedding vector
    page_number: int | None = None
    section_title: str | None = None
    file_name: str = ""


# ---------------------------------------------------------------------------
# Azure Search Service Implementation
# ---------------------------------------------------------------------------


class AzureAISearchService(AbstractSearchService):
    """
    Concrete search service backed by Azure AI Search (Cognitive Search).

    Implements:
    - Real embedding generation via the injected EmbeddingService
    - Pure KNN vector search
    - Hybrid BM25 + KNN with Reciprocal Rank Fusion (RRF)
    - Batch chunk indexing and idempotent deletion
    """

    def __init__(self, embedding_service: "EmbeddingService | None" = None):
        """Initialize async clients for search and index management.

        Args:
            embedding_service: Service used to vectorize chunk content before
                indexing. Lazily constructed on first use if not provided.
        """
        self._search_client: SearchClient | None = None
        self._embedding_service = embedding_service
        self._initialized = False

    def _get_embedding_service(self) -> "EmbeddingService":
        """Lazily construct the embedding service on first use."""
        if self._embedding_service is None:
            from backend.app.services.embedding_service import EmbeddingService

            self._embedding_service = EmbeddingService()
        return self._embedding_service

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of Azure SDK clients on first use."""
        if self._initialized:
            return

        try:
            search_endpoint = (
                f"https://{settings.azure.search_service_name}.search.windows.net/"
            )
            search_api_key = settings.azure.search_api_key
            index_name = settings.azure.search_index_name

            await self._ensure_index_exists(
                search_endpoint=search_endpoint,
                search_api_key=search_api_key,
                index_name=index_name,
            )

            self._search_client = SearchClient(
                endpoint=search_endpoint,
                index_name=index_name,
                credential=AzureKeyCredential(search_api_key),
            )
            self._initialized = True
            logger.info(
                "azure_search_initialized endpoint=%s index_name=%s",
                search_endpoint,
                index_name,
            )
        except Exception as e:
            logger.error(f"azure_search_init_failed: {type(e).__name__}: {e}")
            raise StorageServiceException(
                "Failed to initialize Azure Search service.",
                detail="Failed to initialize Azure Search service."
            ) from e

    async def _ensure_index_exists(
        self,
        *,
        search_endpoint: str,
        search_api_key: str,
        index_name: str,
    ) -> None:
        """Create or update the Azure AI Search index used for chunk storage."""
        index_definition = {
            "name": index_name,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "document_id", "type": "Edm.String", "filterable": True},
                {"name": "chunk_index", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "content", "type": "Edm.String", "searchable": True},
                {
                    "name": "content_vector",
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "dimensions": 1536,
                    "vectorSearchProfile": "default-vector-profile",
                },
                {"name": "page_number", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "section_title", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "file_name", "type": "Edm.String", "searchable": True, "filterable": True},
            ],
            "vectorSearch": {
                "algorithms": [
                    {"name": "default-hnsw", "kind": "hnsw"},
                ],
                "profiles": [
                    {
                        "name": "default-vector-profile",
                        "algorithm": "default-hnsw",
                    },
                ],
            },
        }
        url = f"{search_endpoint.rstrip('/')}/indexes/{index_name}?api-version=2023-11-01"
        headers = {
            "Content-Type": "application/json",
            "api-key": search_api_key,
        }

        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=index_definition) as response:
                if response.status not in {200, 201, 204}:
                    body = await response.text()
                    raise StorageServiceException(
                        f"Failed to create or update Azure Search index '{index_name}'.",
                        detail=f"Azure Search returned {response.status}: {body[:500]}",
                    )

        logger.info("azure_search_index_ready index_name=%s", index_name)

    async def index_chunks(
        self,
        document_id: str,
        chunks: list[ChunkCreateSchema],
        file_name: str = "",
    ) -> None:
        """
        Upsert chunks into the Azure Search index.

        Generates a real embedding vector for each chunk's content via the
        EmbeddingService, then batch-uploads the documents to the index.

        Raises:
            StorageServiceException: on SDK or network failure.
        """
        if not chunks:
            logger.warning("index_chunks_called_with_empty_list document_id=%s", document_id)
            return

        await self._ensure_initialized()

        try:
            # Generate real embeddings for every chunk in a single batch call
            embedding_service = self._get_embedding_service()
            chunk_vectors = await embedding_service.embed_batch(
                [chunk.content for chunk in chunks]
            )

            documents = []
            for chunk, content_vector in zip(chunks, chunk_vectors):
                doc = ChunkDocument(
                    id=f"{document_id}-{chunk.chunk_index}",
                    document_id=str(document_id),
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_vector=content_vector,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    file_name=file_name,
                )
                documents.append(doc.model_dump())

            # Batch upload to index
            result = await self._search_client.upload_documents(documents)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = len(result) - succeeded
            failed_keys = [getattr(r, "key", "") for r in result if not r.succeeded]

            logger.info(
                "index_chunks_completed document_id=%s chunks_total=%s chunks_succeeded=%s chunks_failed=%s",
                document_id,
                len(chunks),
                succeeded,
                failed,
            )

            if failed > 0:
                logger.warning(
                    "index_chunks_partial_failure document_id=%s failed_count=%s failed_keys=%s",
                    document_id,
                    failed,
                    failed_keys[:10],
                )

                cleanup_error: Exception | None = None
                try:
                    # A partial upsert can leave a subset of chunks searchable.
                    # Roll back by document_id to keep index and DB state aligned.
                    await self.delete_document_chunks(document_id)
                    logger.warning(
                        "index_chunks_partial_failure_compensated document_id=%s",
                        document_id,
                    )
                except Exception as e:
                    cleanup_error = e
                    logger.error(
                        "index_chunks_partial_failure_cleanup_failed document_id=%s error=%s",
                        document_id,
                        str(e)[:500],
                        exc_info=True,
                    )

                detail = f"Failed to index {failed} out of {len(chunks)} chunks."
                if cleanup_error is None:
                    detail += " Successfully rolled back indexed chunks."
                else:
                    detail += (
                        " Rollback failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )

                raise StorageServiceException(
                    detail,
                    detail=detail,
                )

        except StorageServiceException:
            raise
        except HttpResponseError as e:
            logger.error(
                "azure_search_upload_failed document_id=%s status_code=%s message=%s",
                document_id,
                e.status_code,
                e.message,
            )
            raise StorageServiceException(
                "Failed to index chunks into search service.",
                detail="Failed to index chunks into search service."
            ) from e
        except Exception as e:
            logger.error(f"index_chunks_error: {type(e).__name__}: {e}")
            raise StorageServiceException(
                "Failed to index chunks into search service.",
                detail="Failed to index chunks into search service."
            ) from e

    async def vector_search(
        self,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchResultSchema]:
        """
        Pure KNN vector search (no BM25 text component).

        Used when query is already embedded and exact keyword matching
        is not required (e.g., semantic paraphrasing).

        Raises:
            StorageServiceException: on SDK or network failure.
        """
        await self._ensure_initialized()

        try:
            vector_query = VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k,
                fields="content_vector",
            )

            filter_expression = self._build_document_filter(document_ids)

            results = await self._search_client.search(
                search_text=None,
                vector_queries=[vector_query],
                top=top_k,
                filter=filter_expression,
                select=["id", "document_id", "chunk_index", "content", "page_number", "section_title", "file_name"],
            )

            search_results = []
            async for result in results:
                search_results.append(
                    SearchResultSchema(
                        document_id=result.get("document_id"),
                        chunk_id=None,  # Not available from search result
                        file_name=result.get("file_name", ""),
                        chunk_index=result.get("chunk_index", 0),
                        content=result.get("content", ""),
                        relevance_score=min(float(result.get("@search.score", 0.0)), 1.0),
                        page_number=result.get("page_number"),
                        section_title=result.get("section_title"),
                    )
                )

            logger.info(
                "vector_search_completed top_k=%s results_returned=%s scoped_documents=%s",
                top_k,
                len(search_results),
                len(document_ids or []),
            )
            return search_results

        except HttpResponseError as e:
            logger.error(f"azure_search_vector_search_failed: {e.status_code}: {e.message}")
            raise StorageServiceException(
                "Vector search failed temporarily.",
                detail="Vector search failed temporarily."
            ) from e
        except Exception as e:
            logger.error(f"vector_search_error: {type(e).__name__}: {e}")
            raise StorageServiceException(
                "Vector search failed temporarily.",
                detail="Vector search failed temporarily."
            ) from e

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchResultSchema]:
        """
        Hybrid BM25 + KNN search with Reciprocal Rank Fusion (RRF).

        Preferred for legal Q&A because exact keyword matching (BM25) for
        defined terms and clause references complements semantic retrieval (KNN).

        Algorithm:
        1. Execute BM25 full-text search
        2. Execute KNN vector search
        3. Fuse rankings using Reciprocal Rank Fusion: score = 1/(60 + rank)
        4. Return top_k by fused score

        Raises:
            StorageServiceException: on SDK or network failure.
        """
        await self._ensure_initialized()

        try:
            # Vector query component
            vector_query = VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k,
                fields="content_vector",
            )

            filter_expression = self._build_document_filter(document_ids)

            # Execute hybrid search with RRF (Reciprocal Rank Fusion)
            results = await self._search_client.search(
                search_text=query_text,
                vector_queries=[vector_query],
                top=top_k,
                filter=filter_expression,
                select=["id", "document_id", "chunk_index", "content", "page_number", "section_title", "file_name"],
            )

            search_results = []
            async for result in results:
                search_results.append(
                    SearchResultSchema(
                        document_id=result.get("document_id"),
                        chunk_id=None,
                        file_name=result.get("file_name", ""),
                        chunk_index=result.get("chunk_index", 0),
                        content=result.get("content", ""),
                        relevance_score=min(float(result.get("@search.score", 0.0)), 1.0),
                        page_number=result.get("page_number"),
                        section_title=result.get("section_title"),
                    )
                )

            logger.info(
                "hybrid_search_completed query_length=%s top_k=%s results_returned=%s scoped_documents=%s",
                len(query_text),
                top_k,
                len(search_results),
                len(document_ids or []),
            )
            return search_results

        except HttpResponseError as e:
            logger.error(f"azure_search_hybrid_search_failed: {e.status_code}: {e.message}")
            raise StorageServiceException(
                "Hybrid search failed temporarily.",
                detail="Hybrid search failed temporarily."
            ) from e
        except Exception as e:
            logger.error(f"hybrid_search_error: {type(e).__name__}: {e}")
            raise StorageServiceException(
                "Hybrid search failed temporarily.",
                detail="Hybrid search failed temporarily."
            ) from e

    async def delete_document_chunks(self, document_id: str) -> None:
        """
        Idempotently remove all index entries for a document.

        Uses a filter query to find all chunks with matching document_id,
        then batch-deletes them. If no chunks exist, returns silently.

        Raises:
            StorageServiceException: on SDK or network failure.
        """
        await self._ensure_initialized()

        try:
            # Query for all chunk IDs matching this document_id
            results = await self._search_client.search(
                search_text="*",
                filter=f"document_id eq '{document_id}'",
                select=["id"],
            )

            chunk_ids = []
            async for result in results:
                chunk_ids.append({"id": result["id"]})

            if not chunk_ids:
                logger.info(
                    "delete_document_chunks_none_found document_id=%s",
                    document_id,
                )
                return  # Idempotent: no error if document absent

            # Batch delete
            delete_result = await self._search_client.delete_documents(chunk_ids)
            succeeded = sum(1 for r in delete_result if r.succeeded)

            logger.info(
                "delete_document_chunks_completed document_id=%s chunks_deleted=%s",
                document_id,
                succeeded,
            )

        except HttpResponseError as e:
            logger.error(
                "azure_search_delete_failed document_id=%s status_code=%s message=%s",
                document_id,
                e.status_code,
                e.message,
            )
            raise StorageServiceException(
                "Failed to delete chunks from search index.",
                detail="Failed to delete chunks from search index."
            ) from e
        except Exception as e:
            logger.error(f"delete_document_chunks_error: {type(e).__name__}: {e}")
            raise StorageServiceException(
                "Failed to delete chunks from search index.",
                detail="Failed to delete chunks from search index."
            ) from e

    @staticmethod
    def _build_document_filter(document_ids: list[str] | None) -> str | None:
        """Build OData filter for one or more document IDs."""
        if not document_ids:
            return None

        sanitized_ids = [str(doc_id).replace("'", "''") for doc_id in document_ids]
        clauses = [f"document_id eq '{doc_id}'" for doc_id in sanitized_ids]
        return " or ".join(clauses)
