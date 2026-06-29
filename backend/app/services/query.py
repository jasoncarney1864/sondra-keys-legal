"""
Concrete RAG (Retrieval-Augmented Generation) query service.

Implements the full legal question-answering pipeline:
1. Embed the question
2. Retrieve relevant context via hybrid search
3. Construct a grounded prompt with guardrails
4. Call Azure OpenAI chat model
5. Parse response and map citations
"""

from __future__ import annotations

import structlog
import time
import re
from typing import Any

from openai import AsyncAzureOpenAI, RateLimitError, AuthenticationError, APIConnectionError
from openai._exceptions import APIStatusError

from backend.app.core.config import settings
from backend.app.core.exceptions import (
    LLMServiceException,
    LLMRateLimitException,
    LLMContextLengthException,
)
from backend.app.models.schemas import (
    QueryRequest,
    QueryResponse,
    CitationSchema,
    SearchResultSchema,
)
from backend.app.services.interfaces import (
    AbstractQueryService,
    AbstractSearchService,
)

logger = structlog.get_logger(__name__)


class QueryService(AbstractQueryService):
    """
    Concrete RAG service for legal document Q&A.

    Orchestrates embedding, retrieval, prompt construction, LLM inference,
    and citation synthesis to deliver grounded answers with verifiable sources.
    """

    def __init__(self, search_service: AbstractSearchService):
        """
        Initialize the query service.

        Args:
            search_service: Injected search service for hybrid chunk retrieval
        """
        self.search_service = search_service

        # Use Azure OpenAI consistently for both embeddings and chat completion.
        self.openai_client = AsyncAzureOpenAI(
            api_key=settings.ai.openai_api_key,
            api_version=settings.ai.openai_api_version,
            azure_endpoint=str(settings.ai.openai_endpoint),
        )

        self.chat_model = settings.ai.openai_deployment_name
        self.embedding_model = settings.openai.embedding_model
        self.embedding_dimension = 1536

        logger.info(
            "query_service_initialized",
            chat_model=self.chat_model,
            embedding_model=self.embedding_model,
        )

    async def answer_query(
        self,
        request: QueryRequest,
    ) -> QueryResponse:
        """
        Execute the full RAG pipeline.

        Pipeline:
        1. Embed the question
        2. Perform hybrid search (BM25 + KNN)
        3. Construct a context-grounded prompt
        4. Call Azure OpenAI chat model
        5. Parse response and build citations
        6. Return structured answer with sources

        Args:
            request: QueryRequest containing question, filters, and parameters

        Returns:
            QueryResponse with answer, citations, model info, and latency

        Raises:
            LLMRateLimitException: On OpenAI rate limit (HTTP 429)
            LLMContextLengthException: On context window exceeded
            LLMServiceException: On other OpenAI API failures
        """
        start_time = time.time()

        logger.info(
            "rag_pipeline_started",
            question_length=len(request.question),
            top_k=request.top_k,
            max_citations=request.max_citations,
        )

        try:
            # ================================================================
            # Step 1: Vectorize the question
            # ================================================================
            logger.debug("embedding_question_started")
            query_vector = await self._embed_question(request.question)
            logger.debug("embedding_question_completed", vector_dim=len(query_vector))

            # ================================================================
            # Step 2: Retrieve relevant chunks via hybrid search
            # ================================================================
            logger.debug("hybrid_search_started", top_k=request.top_k)
            search_results = await self._retrieve_context(
                question=request.question,
                query_vector=query_vector,
                top_k=request.top_k,
                document_ids=request.document_ids,
            )
            logger.info(
                "hybrid_search_completed",
                chunks_retrieved=len(search_results),
            )

            if not search_results:
                logger.warning("no_context_retrieved_for_question")
                answer = (
                    "I was unable to find relevant information in the indexed "
                    "documents to answer your question. Please refine your query "
                    "or upload additional documents."
                )
                return QueryResponse(
                    question=request.question,
                    answer=answer,
                    citations=[],
                    model_used=self.chat_model,
                    latency_ms=int((time.time() - start_time) * 1000),
                )

            # ================================================================
            # Step 3: Format context and construct prompt
            # ================================================================
            logger.debug("prompt_construction_started")
            system_prompt = self._construct_system_prompt()
            user_message = self._construct_user_message(
                question=request.question,
                search_results=search_results,
            )
            logger.debug(
                "prompt_construction_completed",
                system_prompt_length=len(system_prompt),
                user_message_length=len(user_message),
            )

            # ================================================================
            # Step 4: Call the chat model
            # ================================================================
            logger.debug("llm_inference_started", model=self.chat_model)
            try:
                answer = await self._call_llm(system_prompt, user_message)
                logger.info("llm_inference_completed", answer_length=len(answer))
            except LLMServiceException as llm_error:
                logger.warning(
                    "llm_inference_fallback_to_context_summary error=%s",
                    str(llm_error)[:500],
                )
                answer = self._build_fallback_answer(search_results)

            # ================================================================
            # Step 5: Map citations
            # ================================================================
            logger.debug("citation_synthesis_started")
            citations = self._build_citations(
                search_results,
                max_citations=request.max_citations,
            )
            logger.debug("citation_synthesis_completed", citations_count=len(citations))

            # ================================================================
            # Step 6: Return response
            # ================================================================
            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "rag_pipeline_completed",
                citations_returned=len(citations),
                latency_ms=latency_ms,
            )

            return QueryResponse(
                question=request.question,
                answer=answer,
                citations=citations,
                model_used=self.chat_model,
                latency_ms=latency_ms,
            )

        except LLMRateLimitException:
            logger.warning("llm_rate_limit_exceeded")
            raise
        except LLMContextLengthException:
            logger.warning("llm_context_length_exceeded")
            raise
        except LLMServiceException:
            logger.error("llm_service_error", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"rag_pipeline_unexpected_error: {type(e).__name__}", exc_info=True)
            raise LLMServiceException(
                message=f"RAG pipeline failed: {type(e).__name__}",
                detail="An unexpected error occurred during question answering.",
            ) from e

    # ================================================================
    # Private helper methods
    # ================================================================

    async def _embed_question(self, question: str) -> list[float]:
        """
        Embed the question using Azure OpenAI embeddings API.

        Args:
            question: The user's question text

        Returns:
            Vector embedding (1536-dimensional)

        Raises:
            LLMServiceException: On embedding API failure
        """
        try:
            response = await self.openai_client.embeddings.create(
                input=question,
                model=self.embedding_model,
            )
            embedding = response.data[0].embedding
            logger.debug("question_embedded_successfully", dim=len(embedding))
            return embedding
        except RateLimitError as e:
            logger.warning(f"embedding_rate_limit: {e}")
            raise LLMRateLimitException(
                message="Rate limit exceeded during embedding generation.",
                detail="Please try again in a few moments.",
            ) from e
        except APIStatusError as e:
            if e.status_code == 429:
                logger.warning(f"embedding_rate_limit_http429: {e}")
                raise LLMRateLimitException(
                    message="Rate limit exceeded during embedding generation.",
                    detail="Please try again in a few moments.",
                ) from e
            logger.warning(
                "embedding_api_fallback_zero_vector status_code=%s detail=%s",
                e.status_code,
                str(getattr(e, "message", e))[:300],
            )
            return [0.0] * self.embedding_dimension
        except (AuthenticationError, APIConnectionError) as e:
            # Keep Ask flow available in local/dev if embedding credentials drift.
            logger.warning(
                "embedding_fallback_zero_vector error_type=%s detail=%s",
                type(e).__name__,
                str(e)[:300],
            )
            return [0.0] * self.embedding_dimension
        except Exception as e:
            logger.warning(
                "embedding_unexpected_fallback_zero_vector error_type=%s detail=%s",
                type(e).__name__,
                str(e)[:300],
            )
            return [0.0] * self.embedding_dimension

    async def _retrieve_context(
        self,
        question: str,
        query_vector: list[float],
        top_k: int,
        document_ids: list | None = None,
    ) -> list[SearchResultSchema]:
        """
        Retrieve relevant chunks via hybrid search.

        Calls the search service's hybrid_search method which combines
        BM25 (keyword matching) and KNN (semantic similarity) via RRF.

        Args:
            question: Original user question (for BM25 matching)
            query_vector: Embedded question (for KNN matching)
            top_k: Maximum chunks to retrieve
            document_ids: Optional list of document IDs to restrict search

        Returns:
            List of SearchResultSchema sorted by relevance score

        Raises:
            LLMServiceException: On search service failure
        """
        try:
            scoped_document_ids = [str(d) for d in document_ids] if document_ids else None

            results = await self.search_service.hybrid_search(
                query_text=question,
                query_vector=query_vector,
                top_k=top_k,
                document_ids=scoped_document_ids,
            )

            # Fallback path: if scoped hybrid retrieval returned nothing,
            # run a broader vector-only retrieval within the same scope.
            if not results and scoped_document_ids:
                fallback_top_k = min(max(top_k * 4, 12), 50)
                logger.info(
                    "context_retrieval_fallback_vector",
                    scoped_documents=len(scoped_document_ids),
                    fallback_top_k=fallback_top_k,
                )
                results = await self.search_service.vector_search(
                    query_vector=query_vector,
                    top_k=fallback_top_k,
                    document_ids=scoped_document_ids,
                )

            logger.info("context_retrieved", count=len(results))
            return results

        except Exception as e:
            logger.error(f"hybrid_search_failed: {type(e).__name__}: {e}", exc_info=True)
            raise LLMServiceException(
                message="Context retrieval failed.",
                detail="Failed to retrieve relevant document chunks.",
            ) from e

    def _construct_system_prompt(self) -> str:
        """
        Build the system prompt with guardrails for legal Q&A.

        The system prompt instructs the model to:
        - Answer ONLY using provided context
        - Never fabricate or hallucinate
        - Admit when context is insufficient
        - Cite specific sections when making claims
        - Adopt a legal/professional tone

        Returns:
            System prompt string
        """
        return """\
You are an expert legal assistant helping users understand contracts and legal documents.

Your task is to answer user questions using ONLY the provided document context.

CRITICAL RULES:
1. Answer ONLY based on the verbatim text and sections provided below.
2. NEVER make up, infer, or hallucinate information not explicitly stated.
3. If the provided context does not contain enough information to answer the question, \
say: "The provided documents do not contain sufficient information to answer this question."
4. When making claims or citing specific terms, ALWAYS reference the document section \
or clause number (e.g., "Section 3.2" or "Article VI").
5. Be precise and concise. Avoid speculation or external legal knowledge.
6. If a term is defined in the documents (e.g., "Lessor," "Force Majeure"), use that definition.

TONE: Professional, authoritative, and trustworthy. Explain complex legal concepts in plain English.

Now, answer the user's question using only the provided context blocks:\
"""

    def _construct_user_message(
        self,
        question: str,
        search_results: list[SearchResultSchema],
    ) -> str:
        """
        Format the user message with numbered context blocks and the question.

        Constructs a prompt that includes:
        1. Numbered context blocks (one per retrieved chunk) with metadata
        2. The original user question

        Args:
            question: User's question
            search_results: Retrieved chunks with metadata

        Returns:
            Formatted user message string
        """
        # Build numbered context blocks
        context_blocks = []
        for i, result in enumerate(search_results, start=1):
            header_parts = []

            # Include file name
            if result.file_name:
                header_parts.append(f"Document: {result.file_name}")

            # Include section title if available
            if result.section_title:
                header_parts.append(f"Section: {result.section_title}")

            # Include page number if available
            if result.page_number:
                header_parts.append(f"Page: {result.page_number}")

            # Include chunk index for precise referencing
            header_parts.append(f"[Chunk {result.chunk_index}]")

            header = " | ".join(header_parts)
            context_blocks.append(f"[{i}] {header}\n{result.content}")

        context_str = "\n\n".join(context_blocks)

        # Construct final message
        user_message = f"""\
CONTEXT:
{context_str}

QUESTION:
{question}

Please answer the above question using ONLY the provided context. \
If insufficient information is available, state that clearly.\
"""

        return user_message

    def _build_fallback_answer(self, search_results: list[SearchResultSchema]) -> str:
        """Build a grounded fallback answer when chat completion is unavailable."""
        if not search_results:
            return (
                "I could not generate an AI-written answer right now, and no supporting "
                "document context was available."
            )

        top = search_results[:3]
        bullets: list[str] = []
        for item in top:
            snippet = self._clean_fallback_snippet(item.content)
            label = item.section_title or f"chunk {item.chunk_index}"
            bullets.append(f"- {item.file_name} ({label}): {snippet}")

        bullet_block = "\n".join(bullets)

        return (
            "AI answer generation is temporarily unavailable (Azure OpenAI deployment "
            "configuration issue), but I found relevant source context for your question:\n\n"
            f"{bullet_block}\n\n"
            "Use the citations below to review the original source text."
        )

    def _clean_fallback_snippet(self, content: str) -> str:
        """Remove common scrape noise so fallback bullets stay readable."""
        # Some indexed chunks contain escaped newlines from serialized metadata text.
        normalized = content.replace("\\n", "\n")

        # Remove common CSS selector fragments and declaration blocks that leak from scraped pages.
        normalized = re.sub(
            r"\.[A-Za-z0-9_-]+(?:[:]{1,2}[A-Za-z0-9_-]+)?\s*\{[^}]{0,200}\}",
            " ",
            normalized,
        )

        # Drop metadata preamble lines so users see only meaningful source content.
        metadata_prefixes = (
            "source title:",
            "source url:",
            "regulation:",
            "effective date:",
        )
        cleaned_lines: list[str] = []
        for raw_line in normalized.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.lower().startswith(metadata_prefixes):
                continue
            cleaned_lines.append(line)

        snippet = " ".join(cleaned_lines)
        snippet = re.sub(r"\s+", " ", snippet).strip()

        if len(snippet) > 260:
            snippet = f"{snippet[:257]}..."

        return snippet

    async def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
    ) -> str:
        """
        Call Azure OpenAI chat completion API.

        Args:
            system_prompt: System message with guardrails
            user_message: User message with context and question

        Returns:
            Model's response text

        Raises:
            LLMRateLimitException: On rate limit (429)
            LLMContextLengthException: On context window exceeded
            LLMServiceException: On other API errors
        """
        try:
            request_kwargs: dict[str, Any] = {
                "model": self.chat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_completion_tokens": 1024,  # Sufficient for most legal explanations
            }

            # GPT-5 serverless deployments only accept default sampling values.
            # Keep deterministic overrides for prior chat models.
            if not self.chat_model.lower().startswith("gpt-5"):
                request_kwargs["temperature"] = 0.2
                request_kwargs["top_p"] = 0.95

            response = await self.openai_client.chat.completions.create(**request_kwargs)

            answer = response.choices[0].message.content
            logger.debug(
                "llm_response_received",
                answer_length=len(answer) if answer else 0,
                finish_reason=response.choices[0].finish_reason,
            )

            return answer or ""

        except RateLimitError as e:
            logger.warning(f"llm_rate_limit: {e}")
            raise LLMRateLimitException(
                message="OpenAI rate limit exceeded.",
                detail="Please try again in a few moments.",
            ) from e

        except APIStatusError as e:
            # Check for specific error codes
            if e.status_code == 429:
                logger.warning(f"llm_rate_limit_http429: {e}")
                raise LLMRateLimitException(
                    message="OpenAI rate limit exceeded.",
                    detail="Please try again in a few moments.",
                ) from e

            if e.status_code == 400:
                # Only treat genuine context-window overflows as such; other
                # 400s (e.g. unsupported parameters) are real service errors.
                error_message = str(e).lower()
                error_code = getattr(e, "code", "") or ""
                if error_code == "context_length_exceeded" or (
                    "context length" in error_message
                    or "maximum context" in error_message
                ):
                    logger.warning(f"llm_context_exceeded: {e}")
                    raise LLMContextLengthException(
                        message="The assembled prompt exceeds the model's context window.",
                        detail="Try asking a more specific question or search for fewer documents.",
                    ) from e

            logger.error(f"llm_api_error: {e.status_code}: {e.message}")
            raise LLMServiceException(
                message=f"OpenAI API error: {e.status_code}",
                detail="Failed to generate answer from the LLM.",
            ) from e

        except (AuthenticationError, APIConnectionError) as e:
            logger.error(f"llm_connection_error: {type(e).__name__}: {e}")
            raise LLMServiceException(
                message=f"OpenAI connection failed: {type(e).__name__}",
                detail="Failed to reach the language model service.",
            ) from e

        except Exception as e:
            logger.error(f"llm_unexpected_error: {type(e).__name__}: {e}", exc_info=True)
            raise LLMServiceException(
                message=f"LLM call failed: {type(e).__name__}",
                detail="An unexpected error occurred during answer generation.",
            ) from e

    def _build_citations(
        self,
        search_results: list[SearchResultSchema],
        max_citations: int = 5,
    ) -> list[CitationSchema]:
        """
        Map search results to structured citation objects.

        Truncates to max_citations and extracts all available metadata
        (file name, page number, section title, snippet).

        Args:
            search_results: Retrieved chunks from search service
            max_citations: Maximum citations to include

        Returns:
            List of CitationSchema objects
        """
        citations = []

        for result in search_results[:max_citations]:
            citation = CitationSchema(
                document_id=result.document_id,
                file_name=result.file_name or "",
                chunk_index=result.chunk_index,
                page_number=result.page_number,
                section_title=result.section_title,
                snippet=result.content,  # Verbatim text from the chunk
            )
            citations.append(citation)

        logger.debug("citations_built", count=len(citations), max=max_citations)
        return citations
