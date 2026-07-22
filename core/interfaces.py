"""Abstract interfaces for the document index — following Onyx's capability-mixin pattern.

Each backend (LanceDB, Vespa, OpenSearch, etc.) implements these interfaces.
The factory picks the right backend at startup.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class Section:
    """A logical section within a document (paragraph, code block, etc.)."""
    text: str
    link: str = ""
    offset: int = 0


@dataclass
class Document:
    """A document to be indexed — the unit of ingestion."""
    id: str
    doc_id: str
    title: str
    source: str
    repo: str
    sections: list[Section]
    url: str = ""
    author: str = ""
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # Access control
    access_read: list[str] | None = None  # None = public
    access_write: list[str] | None = None
    access_owner: str = ""


@dataclass
class Chunk:
    """A single chunk ready for embedding and indexing."""
    id: str
    doc_id: str
    text: str
    title: str = ""
    source: str = ""
    repo: str = ""
    url: str = ""
    author: str = ""
    summary: str = ""
    hierarchy_path: str = ""
    vector: list[float] | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # Access control
    access_read: list[str] | None = None
    access_write: list[str] | None = None
    access_owner: str = ""


@dataclass
class SearchResult:
    """A single search result returned from any backend."""
    id: str
    doc_id: str
    title: str
    text: str
    source: str
    repo: str
    url: str
    author: str = ""
    summary: str = ""
    score: float = 0.0
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentAccess:
    """Set-based ACL following Onyx's pattern.

    A user is granted access if any entry in the user's ACL set
    intersects with the document's ACL set.
    """
    user_emails: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    is_public: bool = True

    def to_acl(self) -> set[str]:
        """Return the full ACL set for intersection checking."""
        acl = set(self.groups)
        acl.update(f"user:{e}" for e in self.user_emails)
        if self.is_public:
            acl.add("PUBLIC")
        return acl

    @staticmethod
    def user_acl(user_email: str | None, groups: list[str] | None = None) -> set[str]:
        """Build the ACL set for a given user."""
        acl = set(groups or [])
        if user_email:
            acl.add(f"user:{user_email}")
        acl.add("PUBLIC")
        return acl

    @staticmethod
    def check(user_acl: set[str], doc_acl: set[str]) -> bool:
        """Check if a user has access to a document (set intersection)."""
        return not user_acl.isdisjoint(doc_acl)


# ── Capability Mixin Interfaces ────────────────────────────────────────


class SchemaVerifiable(ABC):
    """Backend can verify and create its schema."""

    @abstractmethod
    def verify_and_create_index_if_necessary(self, embedding_dim: int) -> None:
        """Ensure the index schema exists and is compatible."""
        ...


class Indexable(ABC):
    """Backend can index chunks."""

    @abstractmethod
    def index(self, chunks: list[Chunk]) -> int:
        """Index a batch of chunks. Returns count indexed."""
        ...


class Deletable(ABC):
    """Backend can delete documents."""

    @abstractmethod
    def delete(self, doc_id: str) -> int:
        """Delete all chunks for a document. Returns count deleted."""
        ...


class Updatable(ABC):
    """Backend supports metadata updates without re-indexing."""

    @abstractmethod
    def update_access(self, doc_id: str, access: DocumentAccess) -> bool:
        """Update ACLs for a document without re-embedding."""
        ...


class HybridCapable(ABC):
    """Backend supports hybrid (vector + keyword) search."""

    @abstractmethod
    def hybrid_search(
        self,
        query: str,
        vector: list[float],
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Hybrid search combining vector and keyword retrieval."""
        ...

    @abstractmethod
    def keyword_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Keyword-only search."""
        ...

    @abstractmethod
    def vector_search(
        self,
        vector: list[float],
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Vector-only search."""
        ...


class Countable(ABC):
    """Backend can report row/document counts."""

    @abstractmethod
    def count(self) -> int:
        ...

    @abstractmethod
    def count_by_repo(self) -> dict[str, int]:
        ...


class Clearable(ABC):
    """Backend can clear all data."""

    @abstractmethod
    def clear(self) -> None:
        ...


# ── Composite Interface ────────────────────────────────────────────────


class DocumentIndex(
    SchemaVerifiable,
    Indexable,
    Deletable,
    Updatable,
    HybridCapable,
    Countable,
    Clearable,
    ABC,
):
    """Unified abstract interface for any document index backend.

    A backend must implement ALL of the capability mixins above.
    Follows Onyx's pattern of composable interfaces.
    """
    pass
