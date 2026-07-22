"""Factory for creating DocumentIndex backends.

Follows Onyx's pattern: the factory reads config and instantiates
the appropriate backend. New backends (Vespa, OpenSearch, etc.)
register themselves here.
"""
from __future__ import annotations

from core.interfaces import DocumentIndex


def create_document_index(
    backend: str = "lancedb",
    path: str = "./data/lancedb",
    table: str = "knowledge",
    embedding_dim: int = 768,
    schema_type: str = "default",
) -> DocumentIndex:
    """Create a DocumentIndex backend based on config.

    Args:
        backend: The backend type ("lancedb", "vespa", "opensearch", etc.)
        path: Data path (for local backends) or connection URI (for remote)
        table: Table/index name
        embedding_dim: Embedding dimension
        schema_type: "default" or "research"

    Returns:
        A DocumentIndex instance implementing all capability mixins.
    """
    if backend == "lancedb":
        from core.lancedb_backend import LanceDBDocumentIndex

        return LanceDBDocumentIndex(
            path=path,
            table=table,
            embedding_dim=embedding_dim,
            schema_type=schema_type,
        )
    elif backend == "dummy":
        # Used for testing — returns empty results
        from core.interfaces import DocumentIndex

        return _DummyDocumentIndex()
    else:
        raise ValueError(f"Unknown document index backend: {backend}")


class _DummyDocumentIndex(DocumentIndex):
    """Dummy backend for testing. Returns empty results."""

    def __init__(self):
        self._count = 0

    def verify_and_create_index_if_necessary(self, embedding_dim: int) -> None:
        pass

    def index(self, chunks: list) -> int:
        self._count += len(chunks)
        return len(chunks)

    def delete(self, doc_id: str) -> int:
        return 0

    def update_access(self, doc_id: str, access) -> bool:
        return True

    def hybrid_search(self, query, vector, filters=None, user_acl=None, k=10):
        return []

    def keyword_search(self, query, filters=None, user_acl=None, k=10):
        return []

    def vector_search(self, vector, filters=None, user_acl=None, k=10):
        return []

    def count(self) -> int:
        return self._count

    def count_by_repo(self) -> dict[str, int]:
        return {}

    def clear(self) -> None:
        self._count = 0
