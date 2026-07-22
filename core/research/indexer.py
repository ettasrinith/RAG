"""Research indexing pipeline — takes selected PaperCards and indexes them."""
from __future__ import annotations

import importlib
import time
from datetime import datetime
from pathlib import Path
from threading import Event
from urllib.parse import quote

from core.config import load_config
from core.embedder import embed
from core.vector_store import VectorStore
from core.indexer import _doc_to_rows
from connectors.base import Document
from core.logging import get_logger

log = get_logger("research_indexer")
from core.research.models import PaperCard
from core.research.catalog import PaperCatalog


def _emit(event: dict, progress_cb) -> None:
    if progress_cb:
        progress_cb(event)


def _load_connector_for_source(source: str) -> object | None:
    """Try to instantiate a lightweight connector for PDF/text fetching."""
    registry = {
        "arxiv": "connectors.arxiv.reader:ArxivConnector",
        "semantic_scholar": "connectors.semantic_scholar.reader:SemanticScholarConnector",
        "openalex": "connectors.openalex.reader:OpenAlexConnector",
    }
    entry = registry.get(source)
    if not entry:
        return None
    module_path, class_name = entry.split(":")
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls({"enabled": True, "max_results": 1, "delay_seconds": 0})
    except Exception as e:
        log.warning("connector %s not available: %s", key, e)
        return None


def _paper_to_document(paper: PaperCard) -> Document:
    """Convert a PaperCard into a Document suitable for _doc_to_rows."""
    sections = []
    if paper.title:
        sections.append(f"Title: {paper.title}")
    if paper.authors:
        sections.append(f"Authors: {', '.join(paper.authors)}")
    if paper.venue:
        sections.append(f"Venue: {paper.venue}")
    if paper.year:
        sections.append(f"Year: {paper.year}")
    if paper.citation_count:
        sections.append(f"Citations: {paper.citation_count}")
    if paper.doi:
        sections.append(f"DOI: {paper.doi}")
    if paper.arxiv_id:
        sections.append(f"arXiv ID: {paper.arxiv_id}")
    if paper.abstract:
        sections.append(f"Abstract:\n{paper.abstract}")
    content = "\n\n".join(sections).strip()

    pid = paper.paper_id or quote((paper.title or "paper")[:80])
    source_prefix = paper.source or "research"

    return Document(
        id=f"{source_prefix}:{pid}",
        content=content,
        title=paper.title or pid,
        source=source_prefix,
        url=paper.abs_url or paper.pdf_url or "",
        author=", ".join(paper.authors),
        created_at=datetime(paper.year, 1, 1) if paper.year else None,
        updated_at=datetime(paper.year, 1, 1) if paper.year else None,
        metadata={
            "path": pid,
            "paper_id": pid,
            "abstract": paper.abstract,
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
            "venue": paper.venue,
            "year": paper.year,
            "citation_count": paper.citation_count or 0,
            "pdf_url": paper.pdf_url,
            "abs_url": paper.abs_url,
            "authors": paper.authors,
            "mode": source_prefix,
        },
    )


def index_papers(
    papers: list[PaperCard],
    collection: str = "default",
    progress_cb=None,
    stop_event: Event | None = None,
) -> dict:
    """Index selected papers into the research_store.

    Returns summary dict.
    """
    config = load_config()
    emb_cfg = config["embedding"]
    chunk_cfg = config["chunking"]

    research_cfg = config.get("research_store", {})
    store_path = research_cfg.get("path", "./data/lancedb")
    table_name = research_cfg.get("table", "research")

    store = VectorStore(
        path=store_path,
        table=table_name,
        dim=emb_cfg["dim"],
        schema_type="research",
    )

    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)

    started = datetime.now()
    _emit({"type": "started", "time": started.isoformat()}, progress_cb)

    total_papers = 0
    total_chunks = 0
    errors: list[str] = []

    for idx, paper in enumerate(papers):
        if stop_event and stop_event.is_set():
            _emit({"type": "cancelled"}, progress_cb)
            break

        if catalog.is_indexed(paper.paper_id):
            _emit({"type": "paper_skipped", "paper_id": paper.paper_id,
                    "reason": "already indexed"}, progress_cb)
            continue

        try:
            doc = _paper_to_document(paper)

            rows = _doc_to_rows(
                doc,
                chunk_size=chunk_cfg["chunk_size"],
                overlap=chunk_cfg["chunk_overlap"],
                model_name=emb_cfg["model"],
                batch_size=emb_cfg["batch_size"],
                repo=collection,
                hierarchy_path="",
            )

            if rows:
                store.upsert(rows)
                total_chunks += len(rows)

            catalog.mark_indexed(paper.paper_id, {
                "title": paper.title,
                "source": paper.source,
                "collection": collection,
                "indexed_at": datetime.now().isoformat(),
            })

            total_papers += 1
            _emit({
                "type": "paper_indexed",
                "paper_id": paper.paper_id,
                "title": paper.title,
                "chunks": len(rows),
                "total_papers": total_papers,
                "total_chunks": total_chunks,
            }, progress_cb)

        except Exception as e:
            errors.append(f"{paper.paper_id}: {e}")
            _emit({"type": "paper_error", "paper_id": paper.paper_id,
                    "error": str(e)}, progress_cb)

    store.ensure_fts()

    elapsed = datetime.now() - started
    result = {
        "total_papers": total_papers,
        "total_chunks": total_chunks,
        "total_rows": store.count(),
        "elapsed": round(elapsed.total_seconds(), 1),
        "errors": errors,
        "collection": collection,
        "cancelled": stop_event.is_set() if stop_event else False,
    }

    _emit({"type": "done", **result}, progress_cb)
    return result
