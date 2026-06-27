"""
Embedding service for generating vector embeddings from text chunks.
Uses Azure OpenAI to create embeddings for semantic search.
"""

import logging
import math
from typing import List
from openai import AsyncOpenAI

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings for text chunks using Azure OpenAI.
    Embeddings are used for semantic search and similarity matching.
    """

    def __init__(self):
        """Initialize the embedding service with the OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.openai.api_key)
        self.embedding_model = settings.openai.embedding_model
        self.embedding_dimension = 1536
        self.max_batch_size = 32

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
            logger.info(
                "Embedding batch of %d texts (sub-batch size=%d)",
                len(texts),
                self.max_batch_size,
            )

            embedding_list: List[List[float]] = []

            for i in range(0, len(texts), self.max_batch_size):
                batch = texts[i : i + self.max_batch_size]
                response = await self.client.embeddings.create(
                    input=batch,
                    model=self.embedding_model,
                )

                # Sort by index to maintain order within each sub-batch.
                batch_embeddings = sorted(response.data, key=lambda x: x.index)
                embedding_list.extend(item.embedding for item in batch_embeddings)

            logger.info("Generated %d embeddings", len(embedding_list))

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

        # Compute cosine similarity using pure Python
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        magnitude1 = math.sqrt(sum(a * a for a in embedding1))
        magnitude2 = math.sqrt(sum(b * b for b in embedding2))

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
