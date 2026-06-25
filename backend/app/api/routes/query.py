"""
Q&A query endpoints for asking questions about uploaded documents.
Uses semantic search and LLM to provide plain-English answers.
"""

import logging
from typing import Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from backend.app.services.search_service import SearchService
from backend.app.services.llm_service import LLMService
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Enums
# ============================================================================


class SearchType(str, Enum):
    """Search strategy type."""

    SEMANTIC = "semantic"
    FULL_TEXT = "full_text"
    HYBRID = "hybrid"


# ============================================================================
# Pydantic Models
# ============================================================================


class QueryRequest(BaseModel):
    """Request model for asking a question about a document."""

    document_id: str = Field(
        ...,
        description="ID of the document to query",
    )
    question: str = Field(
        ...,
        description="Natural language question about the document",
        min_length=3,
        max_length=500,
    )
    search_type: SearchType = Field(
        default=SearchType.HYBRID,
        description="Type of search to use",
    )
    top_k: int = Field(
        default=5,
        description="Number of search results to use",
        ge=1,
        le=20,
    )


class SearchResult(BaseModel):
    """A single search result."""

    chunk_id: str
    content: str
    relevance_score: float


class QueryResponse(BaseModel):
    """Response model for Q&A query."""

    question: str
    answer: str
    sources: list[SearchResult]
    search_type: SearchType
    confidence_score: float = Field(
        default=0.8,
        description="Confidence in the answer (0-1)",
    )


class TermExplanationRequest(BaseModel):
    """Request model for explaining a legal term."""

    term: str = Field(
        ...,
        description="The legal term to explain",
        min_length=2,
        max_length=100,
    )
    context: Optional[str] = Field(
        None,
        description="Optional context where the term appears",
    )


class TermExplanationResponse(BaseModel):
    """Response model for term explanation."""

    term: str
    explanation: str


# ============================================================================
# Dependencies
# ============================================================================


async def verify_api_key(api_key: Optional[str] = None) -> None:
    """
    Verify API key from request header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Raises:
        HTTPException: If API key is invalid
    """
    if api_key != settings.security.api_key:
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/ask",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
)
async def ask_question(
    request: QueryRequest,
    api_key: str = Depends(verify_api_key),
) -> QueryResponse:
    """
    Ask a question about a document.
    
    Returns a plain-English answer based on the document content,
    using semantic search to find relevant sections and an LLM
    to explain them in accessible language.
    
    Args:
        request: Query request with document ID and question
        api_key: API key for authentication
        
    Returns:
        Answer with source chunks and confidence score
        
    Raises:
        HTTPException: If document not found or processing fails
    """
    try:
        logger.info(
            "ask_question",
            document_id=request.document_id,
            question=request.question[:50],
            search_type=request.search_type,
        )
        
        # Initialize services
        search_service = SearchService()
        llm_service = LLMService()
        
        # Search for relevant document chunks
        if request.search_type == SearchType.SEMANTIC:
            search_results = await search_service.search_semantic(
                query=request.question,
                top_k=request.top_k,
                filters=f"document_id eq '{request.document_id}'",
            )
        elif request.search_type == SearchType.FULL_TEXT:
            search_results = await search_service.search_full_text(
                query=request.question,
                top_k=request.top_k,
                filters=f"document_id eq '{request.document_id}'",
            )
        else:  # HYBRID
            search_results = await search_service.search_hybrid(
                query=request.question,
                top_k=request.top_k,
                filters=f"document_id eq '{request.document_id}'",
            )
        
        if not search_results:
            logger.warning(
                "no_search_results",
                document_id=request.document_id,
                question=request.question[:50],
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant information found in document",
            )
        
        # Combine search results into context
        document_context = "\n\n".join(
            [f"[Section {i+1}]\n{result.content}"
             for i, result in enumerate(search_results[:3])]
        )
        
        # Generate answer
        answer = await llm_service.answer_question(
            question=request.question,
            document_context=document_context,
            document_title=request.document_id,
        )
        
        # Convert search results to response format
        sources = [
            SearchResult(
                chunk_id=result.chunk_id,
                content=result.content[:200] + "..." if len(result.content) > 200 else result.content,
                relevance_score=result.score,
            )
            for result in search_results
        ]
        
        logger.info(
            "question_answered",
            document_id=request.document_id,
            sources_count=len(sources),
        )
        
        return QueryResponse(
            question=request.question,
            answer=answer,
            sources=sources,
            search_type=request.search_type,
            confidence_score=min(1.0, sum(r.relevance_score for r in sources) / len(sources)),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "question_processing_failed",
            document_id=request.document_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process question: {str(e)}",
        )


@router.post(
    "/explain-term",
    response_model=TermExplanationResponse,
    status_code=status.HTTP_200_OK,
)
async def explain_term(
    request: TermExplanationRequest,
    api_key: str = Depends(verify_api_key),
) -> TermExplanationResponse:
    """
    Get a plain-English explanation of a legal term.
    
    Args:
        request: Term explanation request
        api_key: API key for authentication
        
    Returns:
        Plain-English explanation of the term
        
    Raises:
        HTTPException: If explanation generation fails
    """
    try:
        logger.info(
            "explain_term",
            term=request.term,
        )
        
        llm_service = LLMService()
        
        explanation = await llm_service.explain_term(
            term=request.term,
            context=request.context,
        )
        
        logger.info(
            "term_explained",
            term=request.term,
        )
        
        return TermExplanationResponse(
            term=request.term,
            explanation=explanation,
        )
        
    except Exception as e:
        logger.error(
            "term_explanation_failed",
            term=request.term,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to explain term: {str(e)}",
        )
