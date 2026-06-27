"""
Custom exception hierarchy for Sondra Keys Legal API.

Maps infrastructure failures to distinct, catchable types so routes can
respond with precise HTTP status codes without leaking SDK error shapes.
"""


class SondraBaseException(Exception):
    """Root of all application-specific exceptions."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------


class StorageServiceException(SondraBaseException):
    """Raised when Azure Blob Storage operations fail."""


class BlobUploadException(StorageServiceException):
    """Raised when a blob upload to Azure Storage fails."""


class BlobNotFoundException(StorageServiceException):
    """Raised when a requested blob does not exist in the container."""


class BlobDeleteException(StorageServiceException):
    """Raised when deletion of a blob fails."""


# ---------------------------------------------------------------------------
# Extraction / Document Intelligence layer
# ---------------------------------------------------------------------------


class ExtractionEngineException(SondraBaseException):
    """Raised when document analysis via Azure Document Intelligence fails."""


class DocumentIntelligenceException(ExtractionEngineException):
    """Raised when the Azure Document Intelligence API returns an error."""


class ExtractionTimeoutException(ExtractionEngineException):
    """Raised when a Document Intelligence polling operation times out."""


# ---------------------------------------------------------------------------
# OpenAI / LLM layer
# ---------------------------------------------------------------------------


class LLMServiceException(SondraBaseException):
    """Raised when an OpenAI API call fails."""


class LLMRateLimitException(LLMServiceException):
    """Raised when the OpenAI rate limit is hit."""


class LLMContextLengthException(LLMServiceException):
    """Raised when the prompt exceeds the model's context window."""


# ---------------------------------------------------------------------------
# Validation / file intake
# ---------------------------------------------------------------------------


class DocumentValidationException(SondraBaseException):
    """Raised when an uploaded file fails content or policy validation."""


class UnsupportedFileTypeException(DocumentValidationException):
    """Raised when the uploaded file extension is not in the allowlist."""


class FileSizeExceededException(DocumentValidationException):
    """Raised when the uploaded file exceeds the configured size limit."""
