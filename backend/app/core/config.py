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
        default="sqlite:///./legal_qa.db",
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


class SecuritySettings(BaseSettings):
    """Security configuration."""

    api_key: str = Field(
        ..., 
        description="API key for protecting endpoints"
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

    # Sub-configurations
    azure: AzureSettings = Field(default_factory=AzureSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ai: AISettings = Field(default_factory=AISettings)
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
