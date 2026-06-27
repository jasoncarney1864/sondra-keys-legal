"""
Document processing service using Azure Blob Storage and Document Intelligence.

Implements the full document lifecycle:
  1. Upload file to Azure Blob Storage
  2. Extract metadata and text via Azure Document Intelligence
  3. Return structured results ready for chunking/embedding
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from typing import Optional
from uuid import UUID

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import ContainerClient

from backend.app.core.config import settings
from backend.app.core.exceptions import (
    BlobUploadException,
    BlobDeleteException,
    BlobNotFoundException,
    StorageServiceException,
    DocumentIntelligenceException,
)
from backend.app.models.schemas import (
    BlobUploadResultSchema,
    AnalysisResultSchema,
    DocumentMetadataSchema,
    DocumentStructureSchema,
    DocumentHeadingSchema,
)
from backend.app.services.interfaces import AbstractDocumentService


logger = logging.getLogger(__name__)


class DocumentProcessor(AbstractDocumentService):
    """
    Production-ready document processor implementing the AbstractDocumentService contract.

    Handles:
      - Uploading file bytes to Azure Blob Storage
      - Calling Azure Document Intelligence for structured extraction
      - Mapping raw API responses to Pydantic schemas
      - Defensive error handling with custom exception types
    """

    def __init__(self):
        """Initialize async Azure clients (lazy-loaded on first use)."""
        # Changed the type hint here to ContainerClient
        self._blob_container_client: Optional[ContainerClient] = None
        self._doc_intel_client: Optional[DocumentIntelligenceClient] = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """
        Lazily initialize Azure clients on first use.

        Connection is not established until this method is called, allowing
        the app to boot even if Azure is momentarily unavailable.
        """
        if self._initialized:
            return

        try:
            # Initialize Blob Container Client
            account_url = (
                f"https://{settings.azure.blob_account_name}.blob.core.windows.net"
            )
            self._blob_container_client = ContainerClient(
                account_url=account_url,
                container_name=settings.azure.blob_container_name,
                credential=settings.azure.blob_account_key,
            )
            try:
                await self._blob_container_client.create_container()
                logger.info(
                    "Created blob container: %s",
                    settings.azure.blob_container_name,
                )
            except ResourceExistsError:
                logger.debug(
                    "Blob container already exists: %s",
                    settings.azure.blob_container_name,
                )

            # Initialize Document Intelligence Client
            self._doc_intel_client = DocumentIntelligenceClient(
                endpoint=settings.azure.content_understanding_endpoint,
                credential=AzureKeyCredential(settings.azure.content_understanding_key)
            )

            self._initialized = True
            logger.info("Document processor clients initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Azure clients: {e}")
            raise

    # ────────────────────────────────────────────────────────────────────
    # AbstractStorageService methods
    # ────────────────────────────────────────────────────────────────────

    async def upload_to_blob(
        self,
        file_data: bytes,
        file_name: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> BlobUploadResultSchema:
        """
        Upload raw bytes to Azure Blob Storage.

        Args:
            file_data: Binary file content.
            file_name: Original file name (used as blob name).
            content_type: MIME type of the file.

        Returns:
            BlobUploadResultSchema with the canonical blob URL
            and metadata.

        Raises:
            BlobUploadException: If the upload fails.
        """
        await self._ensure_initialized()

        blob_name = file_name
        logger.info(
            f"Uploading blob: {blob_name} ({len(file_data)} bytes, "
            f"content_type={content_type})"
        )

        try:
            blob_client = self._blob_container_client.get_blob_client(blob_name)

            # For deduplicated uploads, reuse the canonical blob if it already
            # exists with the same size instead of overwriting it.
            try:
                props = await blob_client.get_blob_properties()
                if props and props.size == len(file_data):
                    blob_url = blob_client.url
                    logger.info(
                        "Blob already exists with matching size, reusing: %s",
                        blob_name,
                    )
                    return BlobUploadResultSchema(
                        blob_name=blob_name,
                        blob_url=blob_url,
                        content_type=content_type,
                        size_bytes=len(file_data),
                    )
            except ResourceNotFoundError:
                pass

            await blob_client.upload_blob(
                file_data,
                overwrite=True,
            )

            # Construct canonical blob URL
            blob_url = blob_client.url

            logger.info(f"Successfully uploaded blob: {blob_name}")

            return BlobUploadResultSchema(
                blob_name=blob_name,
                blob_url=blob_url,
                content_type=content_type,
                size_bytes=len(file_data),
            )

        except HttpResponseError as e:
            logger.error(f"Blob upload failed: {e.status_code} {e.message}")
            raise BlobUploadException(
                f"Failed to upload blob '{file_name}' to Azure Storage",
                detail=e.message,
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error during blob upload: {e}")
            raise BlobUploadException(
                f"Unexpected error uploading blob '{file_name}'",
                detail=str(e),
            ) from e

    async def delete_blob(self, blob_name: str) -> None:
        """
        Remove a blob from Azure Blob Storage by name.

        Args:
            blob_name: Name of the blob to delete.

        Raises:
            BlobNotFoundException: If the blob does not exist.
            BlobDeleteException: On other SDK or network failures.
        """
        await self._ensure_initialized()

        logger.info(f"Deleting blob: {blob_name}")

        try:
            blob_client = self._blob_container_client.get_blob_client(blob_name)
            await blob_client.delete_blob()
            logger.info(f"Successfully deleted blob: {blob_name}")

        except ResourceNotFoundError as e:
            logger.warning(f"Blob not found: {blob_name}")
            raise BlobNotFoundException(
                f"Blob '{blob_name}' does not exist in container "
                f"'{settings.azure.blob_container_name}'",
                detail=str(e),
            ) from e
        except HttpResponseError as e:
            logger.error(f"Blob deletion failed: {e.status_code} {e.message}")
            raise BlobDeleteException(
                f"Failed to delete blob '{blob_name}' from Azure Storage",
                detail=e.message,
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error deleting blob '{blob_name}': {e}")
            raise BlobDeleteException(
                f"Unexpected error deleting blob '{blob_name}'",
                detail=str(e),
            ) from e

    async def get_blob_url(self, blob_name: str) -> str:
        """
        Return a pre-authenticated URL for a stored blob.

        Generates a short-lived read SAS so Azure Document Intelligence can
        fetch private blobs during asynchronous analysis.

        Args:
            blob_name: Name of the blob.

        Returns:
            Canonical HTTPS URL to the blob.
        """
        await self._ensure_initialized()
        blob_client = self._blob_container_client.get_blob_client(blob_name)
        sas_token = generate_blob_sas(
            account_name=settings.azure.blob_account_name,
            container_name=settings.azure.blob_container_name,
            blob_name=blob_name,
            account_key=settings.azure.blob_account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        return f"{blob_client.url}?{sas_token}"

    async def download_blob(self, blob_name: str) -> bytes:
        """Download full blob content as bytes."""
        await self._ensure_initialized()

        try:
            blob_client = self._blob_container_client.get_blob_client(blob_name)
            data = await blob_client.download_blob()
            return await data.readall()
        except ResourceNotFoundError as e:
            raise BlobNotFoundException(
                f"Blob '{blob_name}' does not exist in container "
                f"'{settings.azure.blob_container_name}'",
                detail=str(e),
            ) from e
        except HttpResponseError as e:
            raise StorageServiceException(
                f"Failed to download blob '{blob_name}' from Azure Storage",
                detail=e.message,
            ) from e
        except Exception as e:
            raise StorageServiceException(
                f"Unexpected error downloading blob '{blob_name}'",
                detail=str(e),
            ) from e

    async def load_parsed_json(self, blob_name: str) -> dict[str, Any] | None:
        """Load parsed-document JSON cache from blob storage."""
        await self._ensure_initialized()
        blob_client = self._blob_container_client.get_blob_client(blob_name)

        try:
            data = await blob_client.download_blob()
            raw_bytes = await data.readall()
            return json.loads(raw_bytes.decode("utf-8"))
        except ResourceNotFoundError:
            return None

    async def save_parsed_json(
        self,
        blob_name: str,
        payload: dict[str, Any],
    ) -> str:
        """Persist parsed-document JSON cache to blob storage."""
        await self._ensure_initialized()
        blob_client = self._blob_container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(
            json.dumps(payload).encode("utf-8"),
            overwrite=True,
            content_type="application/json",
        )
        return blob_name

    # ────────────────────────────────────────────────────────────────────
    # AbstractExtractionService methods
    # ────────────────────────────────────────────────────────────────────

    async def extract_metadata_with_doc_intel(
        self,
        blob_url: str,
        *,
        document_id: str,
    ) -> AnalysisResultSchema:
        """
        Submit a blob URL to Azure Document Intelligence and return
        structured extraction results.

        The Document Intelligence service analyzes the document at the
        blob URL and returns layout, text, tables, key-value pairs, etc.

        Args:
            blob_url: HTTPS URL to the document blob (from upload_to_blob).
            document_id: Unique identifier for this document.

        Returns:
            AnalysisResultSchema with extracted text, metadata, and structure.

        Raises:
            DocumentIntelligenceException: If the API call fails or times out.
        """
        await self._ensure_initialized()

        logger.info(
            f"Submitting document for extraction: document_id={document_id}, "
            f"blob_url={blob_url}"
        )

        try:
            # Call Document Intelligence API with the blob URL
            poller = await self._doc_intel_client.begin_analyze_document(
                model_id="prebuilt-layout",
                body=AnalyzeDocumentRequest(url_source=blob_url),
            )

            # Poll for completion (Document Intelligence uses long-running operations)
            result = await poller.result()
            raw_result = result.as_dict() if hasattr(result, "as_dict") else result

            logger.info(
                f"Document extraction completed: document_id={document_id}"
            )

            # Map raw API response to AnalysisResultSchema
            doc_id = (
                UUID(document_id) 
                if isinstance(document_id, str) 
                else document_id
            )
            return self._map_to_analysis_result(raw_result, document_id=doc_id)

        except HttpResponseError as e:
            logger.error(
                f"Document Intelligence API error: {e.status_code} {e.message}"
            )
            raise DocumentIntelligenceException(
                f"Document Intelligence API call failed for document_id={document_id}",
                detail=e.message,
            ) from e
        except Exception as e:
            logger.error(
                f"Unexpected error during document extraction: {e}"
            )
            raise DocumentIntelligenceException(
                f"Unexpected error extracting document_id={document_id}",
                detail=str(e),
            ) from e

    # ────────────────────────────────────────────────────────────────────
    # Internal helpers for response mapping
    # ────────────────────────────────────────────────────────────────────

    def _map_to_analysis_result(
        self,
        raw_result: dict,
        document_id: UUID,
    ) -> AnalysisResultSchema:
        """
        Map Azure Document Intelligence API response to AnalysisResultSchema.

        Args:
            raw_result: Raw response dict from DocumentIntelligenceClient.
            document_id: UUID to attach to the result.

        Returns:
            AnalysisResultSchema ready for downstream processing.
        """
        text = self._extract_text(raw_result)
        metadata = self._extract_metadata(raw_result)
        structure = self._extract_structure(raw_result)

        return AnalysisResultSchema(
            document_id=document_id,
            file_name=metadata.file_name,
            text=text,
            metadata=metadata,
            structure=structure,
            raw_extraction=raw_result,
        )

    def _extract_text(self, raw_result: dict) -> str:
        """
        Extract concatenated plain-text from Document Intelligence response.

        Prioritizes `content` field from the top-level response.
        Falls back to concatenating paragraphs if available.

        Args:
            raw_result: Raw API response dict.

        Returns:
            Concatenated plain text.
        """
        # Try top-level content first
        if "content" in raw_result:
            return raw_result["content"]

        # Fall back to paragraphs if present
        text_parts = []
        if "pages" in raw_result:
            for page in raw_result["pages"]:
                if "lines" in page:
                    for line in page["lines"]:
                        if "content" in line:
                            text_parts.append(line["content"])

        return "\n\n".join(text_parts) if text_parts else ""

    def _extract_metadata(self, raw_result: dict) -> DocumentMetadataSchema:
        """
        Extract document-level metadata from the API response.

        Args:
            raw_result: Raw API response dict.

        Returns:
            DocumentMetadataSchema instance.
        """
        file_name = raw_result.get("analyzeResult", {}).get("apiVersion", "document")
        page_count = None
        document_type = None

        # Extract page count from pages array
        if "pages" in raw_result:
            page_count = len(raw_result["pages"])

        # Try to detect document type
        if "analyzeResult" in raw_result:
            analyze_result = raw_result["analyzeResult"]
            document_type = analyze_result.get("documentType")

        return DocumentMetadataSchema(
            file_name=file_name,
            page_count=page_count,
            document_type=document_type,
            extraction_date=datetime.utcnow(),
        )

    def _extract_structure(self, raw_result: dict) -> DocumentStructureSchema:
        """
        Extract document structure (headings, sections, etc.).

        Args:
            raw_result: Raw API response dict.

        Returns:
            DocumentStructureSchema instance.
        """
        headings: list[DocumentHeadingSchema] = []
        sections: list[str] = []

        if "pages" not in raw_result:
            return DocumentStructureSchema(headings=headings, sections=sections)

        # Extract structure from paragraphs if present
        for page in raw_result.get("pages", []):
            for para in page.get("paragraphs", []):
                role = para.get("role", "")

                # Capture headings
                if role.startswith("title") or role.startswith("heading"):
                    level = role.split(":")[-1] if ":" in role else "1"
                    headings.append(
                        DocumentHeadingSchema(
                            text=para.get("content", ""),
                            level=level,
                            confidence=para.get("confidence", 1.0),
                        )
                    )

                # Capture section markers
                if role == "sectionHeading":
                    sections.append(para.get("content", ""))

        return DocumentStructureSchema(headings=headings, sections=sections)
