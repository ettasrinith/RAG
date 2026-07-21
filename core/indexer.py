"""Pipeline that runs every enabled connector -> chunks -> embeds -> stores.

Features:
- Incremental sync (skip unchanged files)
- Contextual RAG (LLM summaries)
- Knowledge graph extraction
- Hierarchy indexing
- Cancellable via stop_event
"""
from __future__ import annotations

import importlib
import json
import time
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Iterator

from core.chunker import chunk_text
from core.config import load_config
from core.embedder import embed
from core.vector_store import VectorStore
from core.sync_state import SyncState
from core.hierarchy import HierarchyIndex
from connectors.base import BaseConnector, Document


CONNECTOR_REGISTRY: dict[str, str] = {
    "github_files": "connectors.github.files:GitHubFilesConnector",
    "github_commits": "connectors.github.commits:GitHubCommitsConnector",
    "website": "connectors.website.crawler:WebsiteCrawlerConnector",
    "documents": "connectors.documents.reader:DocumentsConnector",
    "arxiv": "connectors.arxiv.reader:ArxivConnector",
    "youtube": "connectors.youtube.reader:YouTubeTranscriptConnector",
    "openalex": "connectors.openalex.reader:OpenAlexConnector",
    "semantic_scholar": "connectors.semantic_scholar.reader:SemanticScholarConnector",
    "confluence": "connectors.confluence.reader:ConfluenceConnector",
}


def _load_connector(key: str, config: dict) -> BaseConnector | None:
    if key not in CONNECTOR_REGISTRY:
        return None
    module_path, class_name = CONNECTOR_REGISTRY[key].split(":")
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        return None
    cls = getattr(module, class_name)
    return cls(config)


def _doc_to_rows(doc: Document, chunk_size: int, overlap: int,
                 model_name: str, batch_size: int, repo: str = "",
                 contextual_rag=None, hierarchy_path: str = "") -> list[dict]:
    pieces = chunk_text(doc.content, chunk_size=chunk_size, overlap=overlap)
    if not pieces:
        return []

    # Contextual RAG: summarize each chunk, then embed summary + chunk together
    # so retrieval actually benefits from the generated context.
    summaries = ["" for _ in pieces]
    if contextual_rag is not None:
        try:
            summaries = contextual_rag.summarize_batch(pieces)
        except Exception:
            summaries = None
        if not summaries or len(summaries) != len(pieces):
            summaries = ["" for _ in pieces]

    to_embed = []
    for p, s in zip(pieces, summaries):
        if s and s.strip():
            to_embed.append(f"search_document: {s}\n\n{p}")
        else:
            to_embed.append(f"search_document: {p}")
    vectors = embed(to_embed, model_name=model_name, batch_size=batch_size)

    doc_summary = summaries[0] if summaries[0] else (pieces[0][:200] if pieces else "")

    if not hierarchy_path and doc.title:
        parts = doc.title.split("/")
        hierarchy_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

    rows = []
    for idx, (chunk, vec, s) in enumerate(zip(pieces, vectors, summaries)):
        rows.append({
            "id": f"{doc.id}::chunk{idx}",
            "doc_id": doc.id,
            "source": doc.source,
            "repo": repo,
            "title": doc.title,
            "url": doc.url,
            "author": doc.author,
            "text": chunk,
            "summary": s,
            "hierarchy_path": f"{repo}/{hierarchy_path}" if hierarchy_path else repo,
            "vector": vec,
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else "",
        })
    return rows


def _emit(event: dict, progress_cb) -> None:
    if progress_cb:
        progress_cb(event)


def run_indexing(progress_cb=None, repo_path: str | None = None,
                 force_full: bool = False,
                 stop_event: Event | None = None) -> dict:
    config = load_config()

    repo_name = ""
    repo_path_resolved = repo_path or ""
    github_cfg = config.get("connectors", {}).get("github_files", {})
    github_mode = (github_cfg.get("mode") or "").strip().lower()

    if repo_path:
        repo_name = Path(repo_path).name
        if "github_files" in config["connectors"]:
            config["connectors"]["github_files"]["local_path"] = repo_path
            config["connectors"]["github_files"]["mode"] = "local"
        config["connectors"]["github_files"]["enabled"] = True
    elif github_mode == "github":
        repo_name = github_cfg.get("repo", "") or "github-repo"
    elif github_mode == "documents":
        doc_cfg = config.get("connectors", {}).get("documents", {})
        repo_name = (doc_cfg.get("label") or "documents").strip() or "documents"
    elif github_mode == "arxiv":
        arxiv_cfg = config.get("connectors", {}).get("arxiv", {})
        repo_name = (arxiv_cfg.get("label") or "arxiv-papers").strip() or "arxiv-papers"
        config["connectors"]["arxiv"]["enabled"] = True
    elif github_mode == "openalex":
        oa_cfg = config.get("connectors", {}).get("openalex", {})
        repo_name = (oa_cfg.get("label") or "openalex-papers").strip() or "openalex-papers"
        config["connectors"]["openalex"]["enabled"] = True
    elif github_mode == "semantic_scholar":
        s2_cfg = config.get("connectors", {}).get("semantic_scholar", {})
        repo_name = (s2_cfg.get("label") or "semantic-scholar").strip() or "semantic-scholar"
        config["connectors"]["semantic_scholar"]["enabled"] = True
    elif github_mode == "confluence":
        cf_cfg = config.get("connectors", {}).get("confluence", {})
        repo_name = (cf_cfg.get("label") or "confluence").strip() or "confluence"
        config["connectors"]["confluence"]["enabled"] = True
    elif github_mode == "youtube":
        yt_cfg = config.get("connectors", {}).get("youtube", {})
        repo_name = (yt_cfg.get("label") or "youtube-transcripts").strip() or "youtube-transcripts"
        config["connectors"]["youtube"]["enabled"] = True
    elif github_mode == "zip":
        zip_cfg = config.get("connectors", {}).get("documents", {})
        repo_name = (zip_cfg.get("label") or "zip-upload").strip() or "zip-upload"
        config["connectors"]["documents"]["enabled"] = True
    else:
        # Local mode: derive a stable repo identity from the configured path so
        # incremental sync, hierarchy and the knowledge graph also run via CLI.
        repo_path_resolved = github_cfg.get("local_path", "") or ""
        repo_name = Path(repo_path_resolved).name if repo_path_resolved else ""

    emb_cfg = config["embedding"]
    chunk_cfg = config["chunking"]
    store_cfg = config["vector_store"]
    sync_cfg = config.get("sync", {})
    hierarchy_cfg = config.get("hierarchy", {})
    rag_cfg = config.get("contextual_rag", {})
    kg_cfg = config.get("knowledge_graph", {})

    store = VectorStore(
        path=store_cfg["path"],
        table=store_cfg["table"],
        dim=emb_cfg["dim"],
    )

    sync_state = None
    if sync_cfg.get("enabled", False):
        sync_state = SyncState(sync_cfg.get("track_state", "./data/sync_state.json"))

    hierarchy = None
    if hierarchy_cfg.get("enabled", False) and repo_name:
        hierarchy = HierarchyIndex(repo_name, hierarchy_cfg.get("max_depth", 10))

    contextual_rag = None
    if rag_cfg.get("enabled", False):
        try:
            from core.contextual_rag import ContextualRAG
            contextual_rag = ContextualRAG(
                config["llm"],
                prompt=rag_cfg.get("summary_prompt"),
                batch_size=rag_cfg.get("batch_size", 10),
            )
        except Exception:
            pass

    kg_index = None
    if kg_cfg.get("enabled", False) and repo_name:
        try:
            from core.knowledge_graph import KnowledgeGraphIndex
            kg_index = KnowledgeGraphIndex()
        except Exception:
            pass

    if stop_event and stop_event.is_set():
        return {"cancelled": True}

    started = datetime.now()
    _emit({"type": "started", "time": started.isoformat()}, progress_cb)

    total_docs = 0
    total_chunks = 0
    errors = []
    skipped_incremental = 0
    indexed_paths: list[str] = []

    for key, conn_cfg in config["connectors"].items():
        if stop_event and stop_event.is_set():
            _emit({"type": "cancelled"}, progress_cb)
            break

        if not conn_cfg.get("enabled", False):
            continue

        connector = _load_connector(key, conn_cfg)
        if connector is not None and hasattr(connector, "get_repo_name"):
            connector_repo = connector.get_repo_name()
            if connector_repo:
                repo_name = connector_repo
        if connector is None:
            errors.append(f"connector '{key}' not implemented")
            _emit({"type": "connector_skipped", "key": key, "reason": "not implemented"}, progress_cb)
            continue

        if not getattr(connector, "persist", True):
            _emit({"type": "connector_skipped", "key": key,
                   "reason": "pull-only source (answered live, e.g. /web/ask)"}, progress_cb)
            continue

        _emit({"type": "connector_start", "key": key}, progress_cb)

        changed_files = None
        incremental_supported = key in {"github_files"}
        if incremental_supported and sync_state and not force_full and repo_name and repo_path_resolved:
            changed_files = connector.get_changed_files(repo_path_resolved, sync_state, repo_name)
            if changed_files is not None and len(changed_files) == 0:
                _emit({"type": "connector_skipped", "key": key,
                       "reason": "no changes since last sync"}, progress_cb)
                skipped_incremental += 1
                continue

        batch: list[dict] = []
        doc_count = 0
        current_file_state: dict[str, str] = {}
        connector_paths: list[str] = []

        try:
            for doc in connector.load_documents():
                if stop_event and stop_event.is_set():
                    _emit({"type": "cancelled"}, progress_cb)
                    break

                if changed_files is not None:
                    doc_path = doc.metadata.get("path", doc.title)
                    if doc_path not in changed_files:
                        continue

                hierarchy_path = ""
                doc_path = doc.metadata.get("path", doc.title)
                if hierarchy:
                    hierarchy_path = "/".join(doc_path.split("/")[:-1]) if "/" in doc_path else ""

                rows = _doc_to_rows(
                    doc,
                    chunk_size=chunk_cfg["chunk_size"],
                    overlap=chunk_cfg["chunk_overlap"],
                    model_name=emb_cfg["model"],
                    batch_size=emb_cfg["batch_size"],
                    repo=repo_name,
                    contextual_rag=contextual_rag,
                    hierarchy_path=hierarchy_path,
                )

                if kg_index:
                    try:
                        kg_index.build_from_doc(repo_name, doc.id, doc.content[:5000])
                    except Exception:
                        pass

                if sync_state and repo_name:
                    mtime = doc.updated_at.isoformat() if doc.updated_at else ""
                    current_file_state[doc.metadata.get("path", doc.title)] = mtime

                indexed_paths.append(doc_path)
                connector_paths.append(doc_path)

                batch.extend(rows)
                total_docs += 1
                total_chunks += len(rows)
                doc_count += 1

                _emit({
                    "type": "doc_indexed",
                    "key": key,
                    "doc": doc.title,
                    "chunks": len(rows),
                    "total_docs": total_docs,
                    "total_chunks": total_chunks,
                }, progress_cb)

                if len(batch) >= 500:
                    store.upsert(batch)
                    batch = []

            if stop_event and stop_event.is_set():
                _emit({"type": "cancelled"}, progress_cb)
                break

            if batch:
                store.upsert(batch)

            if changed_files is not None and sync_state and repo_name and key == "github_files":
                deleted = [f for f in changed_files
                          if f not in current_file_state]
                if deleted:
                    for doc_path in deleted:
                        doc_id = f"github_file:{repo_name}:{doc_path}"
                        store.delete_by_doc(doc_id)

            if sync_state and repo_name:
                sync_state.set_file_state(repo_name, current_file_state)

            if hierarchy:
                hierarchy.build_from_files(connector_paths)

            if kg_index:
                try:
                    kg_index.save_all()
                except Exception:
                    pass

            if sync_state and repo_name:
                sync_state.set_last_indexed(repo_name, key)

            _emit({"type": "connector_done", "key": key, "docs": doc_count}, progress_cb)

        except Exception as e:
            errors.append(f"{key}: {str(e)}")
            _emit({"type": "connector_error", "key": key, "error": str(e)}, progress_cb)

    store.ensure_fts()

    cancelled = stop_event and stop_event.is_set()
    elapsed = datetime.now() - started
    result = {
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "total_rows": store.count(),
        "elapsed": round(elapsed.total_seconds(), 1),
        "errors": errors,
        "skipped_incremental": skipped_incremental,
        "cancelled": cancelled,
    }

    if hierarchy:
        result["hierarchy_nodes"] = len(hierarchy.nodes)
    if kg_index:
        kg = kg_index.graphs.get(repo_name) if repo_name else None
        result["kg_entities"] = len(kg.entities) if kg else 0

    _emit({"type": "done", **result}, progress_cb)
    return result


if __name__ == "__main__":
    def _print_progress(event):
        print(json.dumps(event))

    run_indexing(progress_cb=_print_progress)
