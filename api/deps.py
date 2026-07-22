from __future__ import annotations

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


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(
            path=_store_path,
            table=config["vector_store"]["table"],
            dim=config["embedding"]["dim"],
        )
    return _store


def get_research_store() -> VectorStore:
    global _research_store
    if _research_store is None:
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
