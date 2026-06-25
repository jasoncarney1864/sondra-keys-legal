"""
Document management endpoints for upload, retrieval, and deletion.
Handles document lifecycle in the Q&A system.
"""

import logging
import os
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.services.document_processor import DocumentProcessor
from backend.app.services.chunker import RecursiveCharacterChunker

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class DocumentMetadata(BaseModel):
    """Metadata about an uploaded document."""

    document_id: str
    file_name: str
    file_size: int
    upload_timestamp: str
    page_count: Optional[int] = None
    processing_status: str = "completed"


class DocumentUploadResponse(BaseModel):
    """Response after document upload and processing."""

    document_id: str
    file_name: str
    status: str
    message: str
    chunks_created: int


class DocumentListResponse(BaseModel):
    """Response with list of documents."""

    documents: list[DocumentMetadata]
    total_count: int


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
    # In a real app, you'd validate against a database or secrets store
    # For now, we compare against the configured API key
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
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key),
) -> DocumentUploadResponse:
    """
    Upload and process a legal document.
    
    Accepts PDF, DOCX, DOC, and TXT files. Extracts text, generates chunks,
    and prepares for semantic search.
    
    Args:
        file: Document file to upload
        api_key: API key for authentication (header: X-API-Key)
        
    Returns:
        Upload response with document ID and chunk count
        
    Raises:
        HTTPException: If file type not supported or processing fails
    """
    # Validate file size
    file_content = await file.read()
    file_size_mb = len(file_content) / (1024 * 1024)
    
    if file_size_mb > settings.security.max_file_size_mb:
        logger.warning(
            f"File too large: {file.filename} ({file_size_mb:.2f}MB)",
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.security.max_file_size_mb}MB",
        )

    # Validate file type
    _, ext = os.path.splitext(file.filename)
    if ext.lower() not in settings.security.allowed_file_types:
        logger.warning(
            f"Invalid file type: {ext}",
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type not supported. Allowed: {', '.join(settings.security.allowed_file_types)}",
        )

    try:
        # Generate unique document ID
        document_id = str(uuid4())
        
        # Save file temporarily
        temp_path = f"/tmp/{document_id}_{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(file_content)
        
        # Process document
        processor = DocumentProcessor()
        processed_data = await processor.process_document(
            file_path=temp_path,
            file_name=file.filename,
            document_id=document_id,
        )
        
        # Chunk the document
        chunker = RecursiveCharacterChunker(
            chunk_size=settings.ai.chunk_size,
            chunk_overlap=settings.ai.chunk_overlap,
        )
        chunks = chunker.chunk_text(processed_data["text"])
        
        # In production, would store chunks in search index here
        chunk_count = len(chunks)
        
        # Clean up temp file
        os.remove(temp_path)
        
        logger.info(
            "document_uploaded",
            document_id=document_id,
            file_name=file.filename,
            chunk_count=chunk_count,
        )
        
        return DocumentUploadResponse(
            document_id=document_id,
            file_name=file.filename,
            status="processed",
            message=f"Document processed successfully. {chunk_count} chunks created.",
            chunks_created=chunk_count,
        )
        
    except Exception as e:
        logger.error(
            "document_processing_failed",
            file_name=file.filename,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {str(e)}",
        )


@router.get(
    "/{document_id}",
    response_model=DocumentMetadata,
)
async def get_document_metadata(
    document_id: str,
    api_key: str = Depends(verify_api_key),
) -> DocumentMetadata:
    """
    Get metadata for a specific document.
    
    Args:
        document_id: The document ID
        api_key: API key for authentication
        
    Returns:
        Document metadata
        
    Raises:
        HTTPException: If document not found
    """
    # In production, would fetch from database
    # For now, return a placeholder
    logger.info("get_document_metadata", document_id=document_id)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document {document_id} not found",
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: str,
    api_key: str = Depends(verify_api_key),
) -> None:
    """
    Delete a document and its associated chunks.
    
    Args:
        document_id: The document ID to delete
        api_key: API key for authentication
        
    Returns:
        None
        
    Raises:
        HTTPException: If document not found
    """
    # In production, would delete from database and search index
    logger.info("document_deleted", document_id=document_id)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document {document_id} not found",
    )


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    api_key: str = Depends(verify_api_key),
    skip: int = 0,
    limit: int = 20,
) -> DocumentListResponse:
    """
    List all uploaded documents with pagination.
    
    Args:
        api_key: API key for authentication
        skip: Number of documents to skip
        limit: Maximum number of documents to return
        
    Returns:
        List of documents with pagination info
    """
    logger.info("list_documents", skip=skip, limit=limit)
    
    # In production, would fetch from database
    return DocumentListResponse(
        documents=[],
        total_count=0,
    )
