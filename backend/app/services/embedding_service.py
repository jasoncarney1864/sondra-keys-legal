"""
Embedding service for generating vector embeddings from text chunks.
Uses Azure OpenAI to create embeddings for semantic search.
"""

import logging
from typing import List
import numpy as np
from openai import AsyncAzureOpenAI

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings for text chunks using Azure OpenAI.
    Embeddings are used for semantic search and similarity matching.
    """

    def __init__(self):
        """Initialize the embedding service with Azure OpenAI client."""
        self.client = AsyncAzureOpenAI(
            api_key=settings.ai.openai_api_key,
            api_version=settings.ai.openai_api_version,
            azure_endpoint=str(settings.ai.openai_endpoint),
        )
        self.deployment_name = settings.ai.openai_deployment_name
        self.embedding_model = "text-embedding-3-small"
        self.embedding_dimension = 1536

    async def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Vector embedding as list of floats

        Raises:
            ValueError: If text is empty
            Exception: If Azure OpenAI API fails
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        try:
            logger.debug(f"Embedding text of length {len(text)}")
            
            response = await self.client.embeddings.create(
                input=text,
                model=self.embedding_model,
            )
            
            embedding = response.data[0].embedding
            logger.debug(f"Generated embedding with dimension {len(embedding)}")
            
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            raise

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a single batch.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings, one per input text

        Raises:
            ValueError: If texts list is empty
            Exception: If Azure OpenAI API fails
        """
        if not texts:
            raise ValueError("Texts list cannot be empty")

        try:
            logger.info(f"Embedding batch of {len(texts)} texts")
            
            response = await self.client.embeddings.create(
                input=texts,
                model=self.embedding_model,
            )
            
            # Sort by index to maintain order
            embeddings = sorted(response.data, key=lambda x: x.index)
            embedding_list = [item.embedding for item in embeddings]
            
            logger.info(f"Generated {len(embedding_list)} embeddings")
            
            return embedding_list
            
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {str(e)}")
            raise

    def compute_similarity(
        self, embedding1: List[float], embedding2: List[float]
    ) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score between -1 and 1

        Raises:
            ValueError: If embeddings have different dimensions
        """
        if len(embedding1) != len(embedding2):
            raise ValueError(
                f"Embedding dimensions must match: {len(embedding1)} vs {len(embedding2)}"
            )

        # Convert to numpy arrays
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        # Compute cosine similarity
        dot_product = np.dot(vec1, vec2)
        magnitude1 = np.linalg.norm(vec1)
        magnitude2 = np.linalg.norm(vec2)

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        similarity = dot_product / (magnitude1 * magnitude2)
        return float(similarity)

    def rank_by_similarity(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[tuple[str, List[float]]],
        top_k: int = 5,
    ) -> List[tuple[str, float]]:
        """
        Rank candidate embeddings by similarity to query embedding.

        Args:
            query_embedding: Query vector
            candidate_embeddings: List of (id, embedding) tuples
            top_k: Number of top results to return

        Returns:
            List of (id, similarity_score) tuples, sorted by score (highest first)

        Raises:
            ValueError: If top_k exceeds number of candidates
        """
        if top_k > len(candidate_embeddings):
            raise ValueError(
                f"top_k ({top_k}) cannot exceed number of candidates ({len(candidate_embeddings)})"
            )

        # Compute similarities
        similarities = []
        for candidate_id, candidate_embedding in candidate_embeddings:
            similarity = self.compute_similarity(query_embedding, candidate_embedding)
            similarities.append((candidate_id, similarity))

        # Sort by similarity (descending) and return top_k
        ranked = sorted(similarities, key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
