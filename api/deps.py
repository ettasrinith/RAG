from __future__ import annotations

import warnings
from pathlib import Path
from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from core.config import load_config, ROOT
from core.llm import LLMClient
from core.registry.database import get_session as get_db_session_raw, init_db
from core.vector_store import VectorStore
from services.collection_service import CollectionService
from services.document_service import DocumentService
from services.job_service import JobService

config = load_config()

_store_path = config["vector_store"]["path"]
if not Path(_store_path).is_absolute():
    _store_path = str(ROOT / _store_path)

_store: VectorStore | None = None
_research_store: VectorStore | None = None
_llm: LLMClient | None = None

# Optional new-style document index (LanceDBDocumentIndex).
# Populated by get_document_index() when the backend config requests it.
_document_index = None
_research_index = None


def reset(store: bool = True, research_store: bool = True, llm: bool = True) -> None:
    """Reset global singletons — primarily for test isolation between sessions."""
    global _store, _research_store, _llm, _document_index, _research_index
    if store:
        _store = None
    if research_store:
        _research_store = None
    if llm:
        _llm = None
    _document_index = None
    _research_index = None


def reload_config() -> None:
    """Reload config from disk and reset singletons that depend on it."""
    global config, _store_path
    config = load_config()
    _store_path = config["vector_store"]["path"]
    if not Path(_store_path).is_absolute():
        _store_path = str(ROOT / _store_path)
    reset()


def get_store() -> VectorStore:
    """Get the legacy VectorStore singleton (dict-based interface).

    .. deprecated::
        Use :func:`get_document_index` for new code. ``VectorStore`` is
        kept for backward compatibility and will be removed in a future
        release.
    """
    global _store
    if _store is None:
        warnings.warn(
            "VectorStore is deprecated; use get_document_index() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _store = VectorStore(
            path=_store_path,
            table=config["vector_store"]["table"],
            dim=config["embedding"]["dim"],
        )
    return _store


def get_research_store() -> VectorStore:
    """Get the legacy research VectorStore singleton.

    .. deprecated::
        Use :func:`get_document_index` with ``schema_type="research"``
        for new code.
    """
    global _research_store
    if _research_store is None:
        warnings.warn(
            "VectorStore is deprecated; use get_document_index() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _research_cfg = config.get("research_store", {})
        _research_store_path = _research_cfg.get("path", "./data/lancedb")
        if not Path(_research_store_path).is_absolute():
            _research_store_path = str(ROOT / _research_store_path)
        _research_store = VectorStore(
            path=_research_store_path,
            table=_research_cfg.get("table", "research"),
            dim=config["embedding"]["dim"],
            schema_type="research",
        )
    return _research_store


def get_document_index():
    """Get the new-style DocumentIndex singleton.

    Uses the factory to create the appropriate backend (LanceDB by default).
    Supports ``schema_type="research"`` for the research store.

    The backend is selected via config::

        vector_store:
          backend: lancedb    # "lancedb", "vespa", "opensearch", etc.
          path: ./data/lancedb
          table: knowledge
    """
    global _document_index
    if _document_index is not None:
        return _document_index

    from core.index_backend_factory import create_document_index

    backend_name = config.get("vector_store", {}).get("backend", "lancedb")
    table = config["vector_store"]["table"]
    dim = config["embedding"]["dim"]

    _document_index = create_document_index(
        backend=backend_name,
        path=_store_path,
        table=table,
        embedding_dim=dim,
    )
    return _document_index


def get_research_index():
    """Get the new-style DocumentIndex singleton for the research store."""
    global _research_index
    if _research_index is not None:
        return _research_index

    from core.index_backend_factory import create_document_index

    _research_cfg = config.get("research_store", {})
    _research_store_path = _research_cfg.get("path", "./data/lancedb")
    if not Path(_research_store_path).is_absolute():
        _research_store_path = str(ROOT / _research_store_path)

    backend_name = _research_cfg.get("backend", "lancedb")
    table = _research_cfg.get("table", "research")
    dim = config["embedding"]["dim"]

    _research_index = create_document_index(
        backend=backend_name,
        path=_research_store_path,
        table=table,
        embedding_dim=dim,
        schema_type="research",
    )
    return _research_index


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient(config["llm"])
    return _llm


def get_db_session() -> Generator[Session, None, None]:
    init_db()
    session = get_db_session_raw()
    try:
        yield session
    finally:
        session.close()


def get_session():
    yield from get_db_session()


def get_collection_service(session: Session = Depends(get_session)) -> CollectionService:
    return CollectionService(session)


def get_document_service(session: Session = Depends(get_session)) -> DocumentService:
    return DocumentService(session, get_store())


def get_job_service(session: Session = Depends(get_session)) -> JobService:
    return JobService(session)
