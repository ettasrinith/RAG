"""Abstract connector interfaces following Onyx's Load/Poll/Slim pattern.

Connectors come in three types:
- **LoadConnector**: Bulk indexes all documents from a source (re-index).
- **PollConnector**: Incrementally updates documents within a time window.
- **SlimConnector**: Lightweight ID-only check used for pruning.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Protocol

from core.interfaces import Document, Section

# Type aliases
SecondsSinceUnixEpoch = float
GenerateDocumentsOutput = Generator[list[Document | "HierarchyNode"], None, None]
GenerateSlimDocumentOutput = Generator[list["SlimDocument" | "HierarchyNode"], None, None]


class IndexingHeartbeatInterface(Protocol):
    """Protocol for liveness signaling during long connector runs."""

    def signal(self) -> None:
        ...


@dataclass
class HierarchyNode:
    """A folder/directory node in a repository hierarchy."""
    id: str
    name: str
    parent_id: str | None = None
    children: list["HierarchyNode"] = field(default_factory=list)


@dataclass
class SlimDocument:
    """Lightweight document reference for pruning checks."""
    id: str
    updated_at: str | None = None


# ── Base Connector ─────────────────────────────────────────────────────


class BaseConnector(ABC):
    """Abstract base for all connectors.

    Subclass one or more of LoadConnector, PollConnector, SlimConnector.
    """

    @abstractmethod
    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Accept access information the connector needs."""
        ...

    def parse_metadata(self) -> dict[str, Any] | None:
        """Return connector-specific metadata shown in the admin UI."""
        return None

    def validate_connector_settings(self) -> None:
        """Validate that the connector can operate (e.g., credentials work)."""
        pass


# ── Load Connector (Full Re-index) ─────────────────────────────────────


class LoadConnector(BaseConnector, ABC):
    """Bulk-indexes documents to reflect a point-in-time state.

    Used for initial indexing and full re-index operations.
    """

    @abstractmethod
    def load_from_state(self) -> GenerateDocumentsOutput:
        """Yield batches of documents from the source.

        Each batch is a list of Document or HierarchyNode objects.
        The connector is responsible for reading ALL documents
        from its source every time this is called.
        """
        ...


# ── Poll Connector (Incremental) ───────────────────────────────────────


class PollConnector(BaseConnector, ABC):
    """Incrementally updates documents within a time range.

    Used for ongoing sync — only fetches documents changed
    between start and end timestamps.
    """

    @abstractmethod
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Yield batches of documents changed in the given time window."""
        ...


# ── Slim Connector (Pruning) ───────────────────────────────────────────


class SlimConnector(BaseConnector, ABC):
    """Lightweight ID-only retrieval used by the background pruning job.

    Must return exactly the same document IDs as the main connector
    (Load or Poll) would for the same time window.
    """

    @abstractmethod
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Yield batches of SlimDocument IDs from the source."""
        ...


# ── Registry ────────────────────────────────────────────────────────────

_connector_registry: dict[str, type[BaseConnector]] = {}


def register_connector(name: str, connector_cls: type[BaseConnector]) -> None:
    """Register a connector class under a given name."""
    _connector_registry[name] = connector_cls


def get_connector(name: str) -> type[BaseConnector]:
    """Get a connector class by name."""
    cls = _connector_registry.get(name)
    if not cls:
        raise KeyError(f"Unknown connector: {name}. Available: {list(_connector_registry)}")
    return cls


def list_connectors() -> list[str]:
    """List all registered connector names."""
    return list(_connector_registry)


# ── Helper: from connector output to Document objects ──────────────────


def doc_from_section(
    title: str,
    source: str,
    repo: str,
    text: str,
    url: str = "",
    author: str = "",
    doc_id: str | None = None,
    **kwargs,
) -> Document:
    """Create a Document from a single text block (simplest case)."""
    import hashlib
    did = doc_id or hashlib.md5(text.encode()).hexdigest()
    return Document(
        id=did,
        doc_id=did,
        title=title,
        source=source,
        repo=repo,
        sections=[Section(text=text)],
        url=url,
        author=author,
        **kwargs,
    )
