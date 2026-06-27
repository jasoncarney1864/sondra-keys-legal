"""
Application configuration using Pydantic Settings.
Manages all environment variables and configuration for the FastAPI application.
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, AnyHttpUrl, field_validator


class AzureSettings(BaseSettings):
    """Azure-specific configuration."""

    # Azure Content Understanding
    content_understanding_endpoint: str = Field(
        ..., 
        description="Azure Content Understanding API endpoint URL"
    )
    content_understanding_key: str = Field(
        ..., 
        description="Azure Content Understanding API key"
    )

    # Azure Cognitive Search (for vector storage)
    search_service_name: str = Field(
        ..., 
        description="Azure Cognitive Search service name"
    )
    search_api_key: str = Field(
        ..., 
        description="Azure Cognitive Search API key"
    )
    search_index_name: str = Field(
        default="legal-documents",
        description="Azure Cognitive Search index name"
    )

    # Azure Blob Storage
    blob_account_name: str = Field(
        ..., 
        description="Azure Blob Storage account name"
    )
    blob_account_key: str = Field(
        ..., 
        description="Azure Blob Storage account key"
    )
    blob_container_name: str = Field(
        default="documents",
        description="Blob container for storing uploaded documents"
    )

    class Config:
        env_prefix = "AZURE_"
        case_sensitive = False


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    database_url: str = Field(
        default="sqlite+aiosqlite:///./legal_qa.db",
        description="Database connection URL"
    )
    database_echo: bool = Field(
        default=False,
        description="Echo SQL queries in logs"
    )

    class Config:
        env_prefix = "DB_"
        case_sensitive = False


class AISettings(BaseSettings):
    """AI and LLM configuration."""

    # Azure OpenAI for Q&A generation
    openai_api_key: str = Field(
        ..., 
        description="Azure OpenAI API key"
    )
    openai_endpoint: AnyHttpUrl = Field(
        ..., 
        description="Azure OpenAI endpoint URL"
    )
    openai_deployment_name: str = Field(
        ..., 
        description="Azure OpenAI deployment name (e.g., 'gpt-4')"
    )
    openai_api_version: str = Field(
        default="2024-02-15-preview",
        description="Azure OpenAI API version"
    )

    # Chunking strategy
    chunk_size: int = Field(
        default=1024,
        description="Size of text chunks for processing"
    )
    chunk_overlap: int = Field(
        default=20,
        description="Overlap between consecutive chunks"
    )

    class Config:
        env_prefix = "AI_"
        case_sensitive = False


class OpenAISettings(BaseSettings):
    """Standard (non-Azure) OpenAI configuration used for embeddings."""

    api_key: str = Field(
        ...,
        description="OpenAI API key used for embedding generation"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model name"
    )
    chat_model: str = Field(
        default="gpt-4o",
        description="OpenAI chat model name used for answer generation"
    )

    class Config:
        env_prefix = "OPENAI_"
        case_sensitive = False


class SecuritySettings(BaseSettings):
    """Security configuration."""

    auth_mode: str = Field(
        default="api_key",
        description="Authentication mode: api_key or oidc"
    )

    api_key: str = Field(
        ..., 
        description="API key for protecting endpoints"
    )
    default_dev_user_id: str = Field(
        default="local-dev-user",
        description="Fallback user identity when auth_mode=api_key"
    )
    oidc_issuer: str | None = Field(
        default=None,
        description="OIDC token issuer URL"
    )
    oidc_audience: str | None = Field(
        default=None,
        description="OIDC expected audience value"
    )
    oidc_jwks_url: str | None = Field(
        default=None,
        description="OIDC JWKS endpoint URL"
    )
    oidc_user_id_claim: str = Field(
        default="sub",
        description="Claim name used as stable user identifier"
    )
    oidc_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"],
        description="Allowed JWT signature algorithms"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins"
    )
    max_file_size_mb: int = Field(
        default=50,
        description="Maximum allowed file upload size in MB"
    )
    allowed_file_types: list[str] = Field(
        default=[".pdf", ".docx", ".doc", ".txt"],
        description="Allowed file types for upload"
    )

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, v: str) -> str:
        """Validate configured authentication mode."""
        valid_modes = {"api_key", "oidc"}
        if v not in valid_modes:
            raise ValueError(f"auth_mode must be one of {valid_modes}")
        return v

    class Config:
        env_prefix = "SECURITY_"
        case_sensitive = False


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    log_format: str = Field(
        default="json",
        description="Log format (json, text)"
    )

    class Config:
        env_prefix = "LOG_"
        case_sensitive = False


class Settings(BaseSettings):
    """Main application settings combining all sub-settings."""

    # Application metadata
    app_name: str = Field(
        default="Sondra Keys Legal QA",
        description="Application name"
    )
    app_version: str = Field(
        default="0.1.0",
        description="Application version"
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    environment: str = Field(
        default="development",
        description="Environment (development, staging, production)"
    )
    startup_index_sanity_check_enabled: bool = Field(
        default=True,
        description="Enable startup index duplicate-identity sanity checks"
    )
    startup_index_sanity_auto_cleanup_duplicates: bool = Field(
        default=False,
        description=(
            "Automatically remove duplicate index document_ids when the "
            "canonical ID is deterministic (UUIDv5)"
        )
    )
    startup_index_sanity_page_size: int = Field(
        default=1000,
        ge=100,
        le=1000,
        description="Page size for startup index sanity scans"
    )
    user_session_ttl_minutes: int = Field(
        default=10080,
        ge=60,
        le=43200,
        description="TTL for user sessions in minutes"
    )
    user_session_retention_cleanup_enabled: bool = Field(
        default=True,
        description="Run startup cleanup for expired user sessions"
    )
    user_session_retention_grace_minutes: int = Field(
        default=60,
        ge=0,
        le=10080,
        description="Extra grace window before deleting expired sessions"
    )
    parsed_json_cache_enabled: bool = Field(
        default=True,
        description="Enable parsed PDF JSON caching in blob storage"
    )
    parsed_json_cache_prefix: str = Field(
        default="parsed",
        description="Blob prefix used for cached parsed document JSON"
    )
    parsed_json_cache_parser_version: str = Field(
        default="prebuilt-layout-v1",
        description="Parser version tag stored with cached parsed JSON"
    )
    parsed_json_retention_cleanup_enabled: bool = Field(
        default=True,
        description="Run startup cleanup hook for stale parsed JSON cache references"
    )
    parsed_json_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        description="Age threshold in days for parsed JSON cache cleanup consideration"
    )
    parsed_json_retention_delete_blobs: bool = Field(
        default=False,
        description=(
            "When true, startup retention cleanup deletes stale parsed JSON blobs "
            "from storage and clears DB pointers"
        )
    )

    # Sub-configurations
    azure: AzureSettings = Field(default_factory=AzureSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ai: AISettings = Field(default_factory=AISettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        valid_envs = {"development", "staging", "production"}
        if v not in valid_envs:
            raise ValueError(f"Environment must be one of {valid_envs}")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
