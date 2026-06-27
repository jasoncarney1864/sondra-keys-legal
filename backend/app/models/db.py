"""
SQLAlchemy 2.x ORM models for persistent document storage.

Pydantic schemas in schemas.py are the API/service-layer contracts.
These classes are the persistence-layer contracts — they define table structure
and are the sole source of truth for migrations.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRecordORM(Base):
    """Authenticated user identity record."""

    __tablename__ = "user_records"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    sessions: Mapped[list[UserSessionORM]] = relationship(
        "UserSessionORM",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    document_links: Mapped[list[UserDocumentAccessORM]] = relationship(
        "UserDocumentAccessORM",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    uploaded_documents: Mapped[list[DocumentRecordORM]] = relationship(
        "DocumentRecordORM",
        back_populates="uploaded_by_user",
        lazy="select",
    )


class UserSessionORM(Base):
    """Per-login user session with sticky active document context."""

    __tablename__ = "user_sessions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    active_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped[UserRecordORM] = relationship("UserRecordORM", back_populates="sessions")
    active_document: Mapped[DocumentRecordORM | None] = relationship(
        "DocumentRecordORM",
        foreign_keys=[active_document_id],
        lazy="select",
    )


class UserDocumentAccessORM(Base):
    """User-level access mapping to documents."""

    __tablename__ = "user_document_access"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped[UserRecordORM] = relationship("UserRecordORM", back_populates="document_links")
    document: Mapped[DocumentRecordORM] = relationship("DocumentRecordORM", back_populates="user_links")


class DocumentRecordORM(Base):
    """Persisted metadata for every uploaded document."""

    __tablename__ = "document_records"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Blob storage cross-references
    blob_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    blob_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    parsed_json_blob_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parsed_json_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Extraction metadata (populated after Document Intelligence completes)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Processing lifecycle — transitions: PENDING → EXTRACTING → CHUNKING → INDEXING → COMPLETED
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processingstatus"),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Populated only when processing_status = FAILED",
    )

    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    completed_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    chunks: Mapped[list[DocumentChunkORM]] = relationship(
        "DocumentChunkORM",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="select",
    )
    uploaded_by_user: Mapped[UserRecordORM | None] = relationship(
        "UserRecordORM",
        back_populates="uploaded_documents",
        foreign_keys=[uploaded_by_user_id],
        lazy="select",
    )
    user_links: Mapped[list[UserDocumentAccessORM]] = relationship(
        "UserDocumentAccessORM",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="select",
    )


class DocumentChunkORM(Base):
    """A single text slice derived from a DocumentRecordORM.

    Each row represents one unit of retrieval — the content that will be
    embedded, indexed, and returned as a citation in Q&A responses.
    """

    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Sequence within the document — determines citation order
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Provenance — carries the extraction context forward into citations
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Cross-reference to the Azure AI Search vector index entry
    embedding_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Key of the corresponding document in the search index",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    document: Mapped[DocumentRecordORM] = relationship(
        "DocumentRecordORM", back_populates="chunks"
    )
