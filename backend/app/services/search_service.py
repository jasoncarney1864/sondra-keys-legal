"""
Search service for querying documents using Azure Cognitive Search.
Handles both full-text and vector-based semantic search.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass

from azure.search.documents import SearchClient
from azure.search.documents.models import (
    VectorizedQuery,
    QueryType,
    QueryLanguage,
)
from azure.core.credentials import AzureKeyCredential

from backend.app.core.config import settings
from backend.app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Represents a single search result."""

    document_id: str
    chunk_id: str
    content: str
    score: float
    metadata: dict


class SearchService:
    """
    Manages document search using Azure Cognitive Search.
    Supports full-text search and semantic/vector search.
    """

    def __init__(self):
        """Initialize the search service."""
        self.search_endpoint = f"https://{settings.azure.search_service_name}.search.windows.net"
        self.index_name = settings.azure.search_index_name
        self.credential = AzureKeyCredential(settings.azure.search_api_key)
        self.client = SearchClient(
            endpoint=self.search_endpoint,
            index_name=self.index_name,
            credential=self.credential,
        )
        self.embedding_service = EmbeddingService()

    async def search_full_text(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Perform full-text search on documents.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional OData filter expression

        Returns:
            List of search results ranked by relevance

        Raises:
            ValueError: If query is empty
            Exception: If search fails
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        try:
            logger.info(f"Full-text search for: {query}")
            
            search_results = self.client.search(
                search_text=query,
                query_type=QueryType.SIMPLE,
                top=top_k,
                filter=filters,
            )

            results = []
            for result in search_results:
                search_result = SearchResult(
                    document_id=result["document_id"],
                    chunk_id=result["chunk_id"],
                    content=result["content"],
                    score=result["@search.score"],
                    metadata=result.get("metadata", {}),
                )
                results.append(search_result)

            logger.info(f"Found {len(results)} full-text results")
            return results

        except Exception as e:
            logger.error(f"Full-text search failed: {str(e)}")
            raise

    async def search_semantic(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Perform semantic (vector) search on documents.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional OData filter expression

        Returns:
            List of semantically similar results

        Raises:
            ValueError: If query is empty
            Exception: If embedding or search fails
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        try:
            logger.info(f"Semantic search for: {query}")
            
            # Generate embedding for query
            query_embedding = await self.embedding_service.embed_text(query)
            
            # Create vectorized query
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top_k,
                fields="embedding",
            )

            # Perform vector search
            search_results = self.client.search(
                search_text=None,
                vector_queries=[vector_query],
                top=top_k,
                filter=filters,
                select=["document_id", "chunk_id", "content", "metadata"],
            )

            results = []
            for result in search_results:
                search_result = SearchResult(
                    document_id=result["document_id"],
                    chunk_id=result["chunk_id"],
                    content=result["content"],
                    score=result["@search.score"],
                    metadata=result.get("metadata", {}),
                )
                results.append(search_result)

            logger.info(f"Found {len(results)} semantic results")
            return results

        except Exception as e:
            logger.error(f"Semantic search failed: {str(e)}")
            raise

    async def search_hybrid(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Perform hybrid search combining full-text and semantic search.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional OData filter expression

        Returns:
            List of combined results deduplicated and ranked

        Raises:
            ValueError: If query is empty
            Exception: If search fails
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        try:
            logger.info(f"Hybrid search for: {query}")
            
            # Generate embedding for vector search
            query_embedding = await self.embedding_service.embed_text(query)
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top_k,
                fields="embedding",
            )

            # Perform hybrid search
            search_results = self.client.search(
                search_text=query,
                vector_queries=[vector_query],
                query_type=QueryType.SEMANTIC,
                query_language=QueryLanguage.EN_US,
                top=top_k * 2,  # Get more to deduplicate
                filter=filters,
                select=["document_id", "chunk_id", "content", "metadata"],
            )

            # Deduplicate by chunk_id and take top_k
            seen_chunks = {}
            results = []
            for result in search_results:
                chunk_id = result["chunk_id"]
                if chunk_id not in seen_chunks:
                    search_result = SearchResult(
                        document_id=result["document_id"],
                        chunk_id=chunk_id,
                        content=result["content"],
                        score=result["@search.score"],
                        metadata=result.get("metadata", {}),
                    )
                    results.append(search_result)
                    seen_chunks[chunk_id] = True

                    if len(results) >= top_k:
                        break

            logger.info(f"Found {len(results)} hybrid results")
            return results

        except Exception as e:
            logger.error(f"Hybrid search failed: {str(e)}")
            raise

    async def search_by_document(
        self,
        document_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """
        Search within a specific document.

        Args:
            document_id: ID of the document to search within
            query: Search query string
            top_k: Number of results to return

        Returns:
            List of search results from the document

        Raises:
            ValueError: If query or document_id is empty
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        if not document_id or not document_id.strip():
            raise ValueError("Document ID cannot be empty")

        # Create filter for specific document
        filter_expression = f"document_id eq '{document_id}'"

        # Use semantic search with document filter
        return await self.search_semantic(query, top_k, filter_expression)
