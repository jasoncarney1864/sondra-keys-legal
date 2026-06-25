"""
Document processing service using Azure Content Understanding.
Handles extraction of text, structure, and metadata from uploaded documents.
"""

import logging
import mimetypes
from typing import Optional
from datetime import datetime
import json

import httpx
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobClient

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    Processes documents using Azure Content Understanding API.
    Extracts text, metadata, and structure for downstream processing.
    """

    def __init__(self):
        """Initialize the document processor with Azure credentials."""
        self.endpoint = settings.azure.content_understanding_endpoint
        self.api_key = settings.azure.content_understanding_key
        self.api_version = "2024-11-01-preview"
        self.headers = {
            "api-key": self.api_key,
            "Content-Type": "application/octet-stream"
        }

    async def process_document(
        self,
        file_path: str,
        file_name: str,
        document_id: str,
    ) -> dict:
        """
        Process a document using Azure Content Understanding.

        Args:
            file_path: Local path to the document file
            file_name: Original file name
            document_id: Unique identifier for this document

        Returns:
            Dictionary containing processed document data:
                - text: Extracted text content
                - metadata: Document metadata (title, creation date, etc.)
                - structure: Document structure (headings, sections)
                - chunks: Pre-chunked content segments
                - processing_timestamp: When the document was processed

        Raises:
            ValueError: If file type is not supported
            httpx.HTTPError: If Azure API request fails
        """
        logger.info(f"Processing document: {file_name} (ID: {document_id})")

        # Validate file type
        self._validate_file_type(file_name)

        # Read file content
        with open(file_path, "rb") as f:
            file_content = f.read()

        # Call Azure Content Understanding API
        async with httpx.AsyncClient(timeout=60.0) as client:
            extraction_result = await self._call_content_understanding_api(
                client, file_content, file_name
            )

        # Parse and structure the results
        processed_data = self._structure_extraction_result(
            extraction_result, file_name, document_id
        )

        logger.info(f"Successfully processed document: {file_name}")
        return processed_data

    async def _call_content_understanding_api(
        self, client: httpx.AsyncClient, file_content: bytes, file_name: str
    ) -> dict:
        """
        Call the Azure Content Understanding API.

        Args:
            client: AsyncClient for HTTP requests
            file_content: Binary file content
            file_name: Original file name

        Returns:
            API response as dictionary
        """
        url = (
            f"{self.endpoint}/documentIntelligence:analyze"
            f"?api-version={self.api_version}"
        )

        try:
            response = await client.post(
                url,
                content=file_content,
                headers=self.headers,
                params={"features": "layout,readingOrder,formulas"}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Azure Content Understanding API error: {str(e)}")
            raise

    def _validate_file_type(self, file_name: str) -> None:
        """
        Validate that the file type is supported.

        Args:
            file_name: File name to validate

        Raises:
            ValueError: If file type is not supported
        """
        allowed_types = settings.security.allowed_file_types
        _, ext = mimetypes.guess_extension(file_name), file_name.lower()

        # Check by extension
        if not any(ext.endswith(t) for t in allowed_types):
            raise ValueError(
                f"File type not supported. Allowed: {', '.join(allowed_types)}"
            )

    def _structure_extraction_result(
        self, extraction_result: dict, file_name: str, document_id: str
    ) -> dict:
        """
        Structure the raw API response into a standardized format.

        Args:
            extraction_result: Raw API response
            file_name: Original file name
            document_id: Document identifier

        Returns:
            Structured document data
        """
        # Extract text from content items
        text_content = self._extract_text_from_content(extraction_result)

        # Extract metadata
        metadata = self._extract_metadata(extraction_result, file_name)

        # Extract document structure (headings, sections)
        structure = self._extract_structure(extraction_result)

        return {
            "document_id": document_id,
            "file_name": file_name,
            "text": text_content,
            "metadata": metadata,
            "structure": structure,
            "processing_timestamp": datetime.utcnow().isoformat(),
            "raw_extraction": extraction_result  # Store for debugging
        }

    def _extract_text_from_content(self, extraction_result: dict) -> str:
        """
        Extract readable text from the content items in the API response.

        Args:
            extraction_result: API response

        Returns:
            Concatenated text content
        """
        text_parts = []

        # Extract from analyzed_document.content
        if "analyzeResult" in extraction_result:
            analyze_result = extraction_result["analyzeResult"]

            if "content" in analyze_result:
                text_parts.append(analyze_result["content"])

            # If paragraphs are available, use them for cleaner structure
            if "paragraphs" in analyze_result:
                for paragraph in analyze_result["paragraphs"]:
                    if "content" in paragraph:
                        text_parts.append(paragraph["content"])

        return "\n\n".join(text_parts)

    def _extract_metadata(self, extraction_result: dict, file_name: str) -> dict:
        """
        Extract document metadata.

        Args:
            extraction_result: API response
            file_name: Original file name

        Returns:
            Metadata dictionary
        """
        metadata = {
            "file_name": file_name,
            "extraction_date": datetime.utcnow().isoformat(),
        }

        # Extract document-level properties if available
        if "analyzeResult" in extraction_result:
            analyze_result = extraction_result["analyzeResult"]

            # Page count
            if "pages" in analyze_result:
                metadata["page_count"] = len(analyze_result["pages"])

            # Document type detection
            if "documentType" in analyze_result:
                metadata["document_type"] = analyze_result["documentType"]

        return metadata

    def _extract_structure(self, extraction_result: dict) -> dict:
        """
        Extract document structure (headings, sections, etc.).

        Args:
            extraction_result: API response

        Returns:
            Structure information
        """
        structure = {
            "sections": [],
            "headings": []
        }

        if "analyzeResult" not in extraction_result:
            return structure

        analyze_result = extraction_result["analyzeResult"]

        # Extract headings from paragraphs if role is available
        if "paragraphs" in analyze_result:
            for paragraph in analyze_result["paragraphs"]:
                role = paragraph.get("role", "")

                if "heading" in role.lower():
                    structure["headings"].append({
                        "text": paragraph.get("content", ""),
                        "level": role,
                        "confidence": paragraph.get("confidence", 1.0)
                    })

        return structure
