from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship

from core.registry.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class CollectionModel(Base):
    __tablename__ = "collections"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True)
    kind = Column(String(50), nullable=False, default="notes")
    source_config = Column(JSON, default=dict)
    doc_count = Column(Integer, default=0)
    last_indexed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="idle")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    documents = relationship("DocumentModel", back_populates="collection", cascade="all, delete-orphan")
    jobs = relationship("IndexJobModel", back_populates="collection", cascade="all, delete-orphan")


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=_uuid)
    collection_id = Column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_type = Column(String(50), default="file")
    uri = Column(Text, default="")
    authors = Column(Text, default="")
    tldr = Column(Text, default="")
    checksum = Column(String(64), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    collection = relationship("CollectionModel", back_populates="documents")
    chunks = relationship("ChunkModel", back_populates="document", cascade="all, delete-orphan")
    paper = relationship("PaperModel", back_populates="document", uselist=False, cascade="all, delete-orphan")


class ChunkModel(Base):
    __tablename__ = "chunks"

    id = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    char_start = Column(Integer, default=0)
    char_end = Column(Integer, default=0)
    context = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    document = relationship("DocumentModel", back_populates="chunks")


class PaperModel(Base):
    __tablename__ = "papers"

    id = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    abstract = Column(Text, default="")
    venue = Column(String(200), default="")
    year = Column(Integer, nullable=True)
    citation_count = Column(Integer, default=0)
    doi = Column(String(200), default="")
    related_paper_ids = Column(JSON, default=list)

    document = relationship("DocumentModel", back_populates="paper")


class IndexJobModel(Base):
    __tablename__ = "index_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    collection_id = Column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    state = Column(String(20), default="queued")
    items_done = Column(Integer, default=0)
    items_total = Column(Integer, default=0)
    progress = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    finished_at = Column(DateTime, nullable=True)

    collection = relationship("CollectionModel", back_populates="jobs")
