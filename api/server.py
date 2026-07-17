"""FastAPI server — search + chat + index + graph endpoints."""
from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import load_config, save_config, ROOT
from core.embedder import embed, embed_query
from core.llm import LLMClient
from core.indexer import run_indexing
from core.vector_store import VectorStore
from core.hybrid_search import hybrid_search
from core.sync_state import SyncState
from core.chunker import chunk_text
from core.uploads import create_upload_dir, cleanup_upload_dir, extract_zip_safe, sanitize_name
from core.hierarchy import HierarchyIndex
from connectors.website.crawler import WebsiteCrawlerConnector

config = load_config()
store = VectorStore(
    path=config["vector_store"]["path"],
    table=config["vector_store"]["table"],
    dim=config["embedding"]["dim"],
)
llm = LLMClient(config["llm"])
sync_state = SyncState(config.get("sync", {}).get("track_state", "./data/sync_state.json"))

# Optional API-key guard. Only enforced when KH_API_KEY is set in the environment.
API_KEY = os.environ.get("KH_API_KEY", "")


def _require_auth(request: Request):
    if not API_KEY:
        return
    provided = request.headers.get("X-API-Key") or request.query_params.get("token", "")
    if provided != API_KEY:
        raise HTTPException(status_code=401, detail="missing or invalid API key")

_reranker = None
_reranker_lock = threading.Lock()
_reranker_config = config.get("search", {})

_kg_index = None
_kg_lock = threading.Lock()

_stop_event = threading.Event()
_index_lock = threading.Lock()
_indexing_in_progress = False
_current_index_result = None


def _recreate_runtime() -> None:
    global config, store, llm, sync_state, _reranker, _kg_index, _reranker_config
    config = load_config()
    store = VectorStore(
        path=config["vector_store"]["path"],
        table=config["vector_store"]["table"],
        dim=config["embedding"]["dim"],
    )
    llm = LLMClient(config["llm"])
    sync_state = SyncState(config.get("sync", {}).get("track_state", "./data/sync_state.json"))
    _reranker = None
    _kg_index = None
    _reranker_config = config.get("search", {})


def get_reranker():
    global _reranker
    if _reranker is None and _reranker_config.get("rerank", False):
        with _reranker_lock:
            if _reranker is None:
                try:
                    from core.reranker import get_reranker as _get
                    _reranker = _get(_reranker_config.get("rerank_model",
                        "cross-encoder/ms-marco-MiniLM-L-6-v2"))
                except Exception:
                    pass
    return _reranker


def get_kg():
    global _kg_index
    if _kg_index is None and config.get("knowledge_graph", {}).get("enabled"):
        with _kg_lock:
            if _kg_index is None:
                try:
                    from core.knowledge_graph import KnowledgeGraphIndex
                    _kg_index = KnowledgeGraphIndex()
                except Exception:
                    pass
    return _kg_index


def _maybe_rerank(query: str, results: list[dict], top_k: int) -> list[dict]:
    if not config.get("search", {}).get("rerank", False):
        return results[:top_k]
    try:
        from core.reranker import rerank as _rerank
        model = config.get("search", {}).get(
            "rerank_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        return _rerank(query, results, top_k=top_k, model_name=model)
    except Exception:
        return results[:top_k]


def retrieve(query: str, k: int, source: str | None = None, repo: str | None = None,
             hierarchy: str | None = None, hybrid: bool = True,
             rerank: bool | None = None) -> list[dict]:
    """Shared retrieval pipeline used by both /search and /chat."""
    qvec = embed_query(query, model_name=config["embedding"]["model"])
    if hybrid:
        vector_hits = store.search(qvec, k=max(k * 2, 20),
                                   source_filter=source, repo_filter=repo,
                                   hierarchy_filter=hierarchy)
        fts_hits = store.fts_search(query, k=max(k * 2, 20), repo_filter=repo)
        results = hybrid_search(vector_hits, fts_hits,
                                vector_weight=0.7, fts_weight=0.3, top_k=k * 2)
    else:
        results = store.search(qvec, k=k, source_filter=source,
                               repo_filter=repo, hierarchy_filter=hierarchy)
    do_rerank = rerank if rerank is not None else config.get("search", {}).get("rerank", False)
    return _maybe_rerank(query, results, k) if do_rerank else results[:k]


def _sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


app = FastAPI(title="Knowledge Hub")

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=100)
    source: str | None = None
    repo: str | None = None
    hierarchy: str | None = None
    hybrid: bool = True
    rerank: bool | None = None


class ChatRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=8, ge=1, le=50)
    source: str | None = None
    repo: str | None = None


class WebAskRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    urls: list[str] | None = None
    max_pages: int | None = Field(default=None, ge=1, le=5000)
    max_depth: int | None = Field(default=None, ge=0, le=10)
    k: int = Field(default=8, ge=1, le=50)
    rerank: bool | None = None


class IndexRequest(BaseModel):
    repo_path: str = Field(default="", max_length=500)
    force_full: bool = False


class ConfigUpdate(BaseModel):
    repo_path: str | None = None
    github_mode: str | None = None
    github_repo: str | None = None
    github_pat: str | None = None
    github_branch: str | None = None
    github_files_enabled: bool | None = None
    github_commits_enabled: bool | None = None
    website_enabled: bool | None = None
    website_label: str | None = None
    website_start_urls: list[str] | None = None
    website_sitemap_urls: list[str] | None = None
    website_same_domain_only: bool | None = None
    website_include_patterns: list[str] | None = None
    website_exclude_patterns: list[str] | None = None
    website_max_pages: int | None = Field(default=None, ge=1, le=5000)
    website_max_depth: int | None = Field(default=None, ge=0, le=10)
    website_delay_seconds: float | None = Field(default=None, ge=0.0, le=10.0)
    website_min_text_chars: int | None = Field(default=None, ge=0, le=5000)
    website_respect_robots_txt: bool | None = None
    documents_enabled: bool | None = None
    documents_label: str | None = None
    documents_paths: list[str] | None = None
    documents_recursive: bool | None = None
    documents_max_file_size_kb: int | None = Field(default=None, ge=1, le=500000)
    documents_min_text_chars: int | None = Field(default=None, ge=0, le=500000)
    arxiv_enabled: bool | None = None
    arxiv_label: str | None = None
    arxiv_ids: list[str] | None = None
    arxiv_urls: list[str] | None = None
    arxiv_include_pdf_text: bool | None = None
    youtube_enabled: bool | None = None
    youtube_label: str | None = None
    youtube_urls: list[str] | None = None
    youtube_video_ids: list[str] | None = None
    youtube_languages: list[str] | None = None
    youtube_include_timestamps: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    llm_max_tokens: int | None = Field(default=None, ge=100, le=16384)
    embedding_model: str | None = None
    chunk_size: int | None = Field(default=None, ge=64, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1024)
    top_k: int | None = Field(default=None, ge=1, le=100)
    rerank: bool | None = None


class GraphQueryRequest(BaseModel):
    repo: str
    entity: str


@app.get("/", response_class=HTMLResponse)
def root():
    index = UI_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h1>Knowledge Hub</h1><p>UI not built yet — POST to /search or /chat.</p>"


@app.get("/health")
def health():
    return {
        "ok": True,
        "rows": store.count(),
        "repos": store.list_repos(),
        "repo_counts": store.count_by_repo(),
        "embedding_model": config["embedding"]["model"],
        "llm_model": config["llm"]["model"],
        "indexing": _indexing_in_progress,
        "features": {
            "hybrid_search": True,
            "rerank": config.get("search", {}).get("rerank", False),
            "contextual_rag": config.get("contextual_rag", {}).get("enabled", False),
            "knowledge_graph": config.get("knowledge_graph", {}).get("enabled", False),
            "hierarchy": config.get("hierarchy", {}).get("enabled", False),
            "incremental_sync": config.get("sync", {}).get("enabled", False),
        },
    }


@app.get("/folders")
def list_folders():
    search_paths = []
    home = Path.home()
    for candidate in [
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        Path("C:/dev"),
        Path("C:/src"),
        Path("C:/projects"),
        Path("D:/repos"),
    ]:
        if candidate.exists():
            search_paths.append(candidate)

    folders = []
    for base in search_paths:
        try:
            for item in base.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    git_dir = item / ".git"
                    if git_dir.exists():
                        folders.append({
                            "name": item.name,
                            "path": str(item).replace("\\", "/"),
                            "type": "git",
                        })
        except PermissionError:
            continue

    configured_path = config.get("connectors", {}).get("github_files", {}).get("local_path", "")
    if configured_path:
        folders.insert(0, {
            "name": Path(configured_path).name or configured_path,
            "path": configured_path,
            "type": "configured",
        })

    return {"folders": folders}


@app.get("/repos")
def list_repos():
    return {"repos": store.list_repos(), "counts": store.count_by_repo()}


@app.get("/hierarchy")
def list_hierarchy(repo: str | None = None, request: Request = None):
    if request is not None:
        _require_auth(request)
    repos = [repo] if repo else store.list_repos()
    paths: list[str] = []
    for repo_name in repos:
        try:
            hierarchy = HierarchyIndex(repo_name, config.get("hierarchy", {}).get("max_depth", 10))
            paths.extend(hierarchy.get_all_paths())
        except Exception:
            continue
    return {"paths": sorted(set(paths))}


@app.post("/search")
def search(req: SearchRequest, _: None = Depends(_require_auth)):
    results = retrieve(
        req.q, req.k,
        source=req.source, repo=req.repo, hierarchy=req.hierarchy,
        hybrid=req.hybrid, rerank=req.rerank,
    )
    return {"results": [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "repo": h.get("repo", ""),
            "hierarchy": h.get("hierarchy_path", ""),
            "author": h.get("author"),
            "snippet": (h.get("text") or "")[:500],
            "summary": h.get("summary", ""),
            "score": h.get("combined_score") or h.get("rerank_score") or h.get("_distance"),
        }
        for h in results
    ]}


@app.post("/chat")
def chat(req: ChatRequest, _: None = Depends(_require_auth)):
    # Use the same hybrid + rerank pipeline as /search for higher-quality answers.
    hits = retrieve(req.q, req.k, source=req.source, repo=req.repo,
                    hybrid=True, rerank=True)

    sources = [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "repo": h.get("repo", ""),
            "summary": h.get("summary", ""),
            "text": h.get("text", ""),
        }
        for h in hits
    ]

    def stream():
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        for token in llm.answer(req.q, sources):
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/web/ask")
def web_ask(req: WebAskRequest, _: None = Depends(_require_auth)):
    """Live web Q&A: crawl the given URL(s), answer from them, store nothing."""
    website_cfg = config.get("connectors", {}).get("website", {})
    crawler_config = {
        "start_urls": req.urls or list(website_cfg.get("start_urls", [])),
        "sitemap_urls": list(website_cfg.get("sitemap_urls", [])),
        "label": website_cfg.get("label", ""),
        "same_domain_only": website_cfg.get("same_domain_only", True),
        "include_patterns": list(website_cfg.get("include_patterns", [])),
        "exclude_patterns": list(website_cfg.get("exclude_patterns", [])),
        "max_pages": req.max_pages if req.max_pages is not None else int(website_cfg.get("max_pages", 150)),
        "max_depth": req.max_depth if req.max_depth is not None else int(website_cfg.get("max_depth", 2)),
        "request_timeout_seconds": int(website_cfg.get("request_timeout_seconds", 15)),
        "delay_seconds": float(website_cfg.get("delay_seconds", 0.15)),
        "min_text_chars": int(website_cfg.get("min_text_chars", 250)),
        "max_page_size_kb": int(website_cfg.get("max_page_size_kb", 1024)),
        "respect_robots_txt": bool(website_cfg.get("respect_robots_txt", True)),
        "user_agent": website_cfg.get("user_agent", "KnowledgeHubBot/1.0 (+https://localhost)"),
    }

    emb_model = config["embedding"]["model"]
    emb_batch = int(config["embedding"].get("batch_size", 64))
    chunk_size = int(config["chunking"]["chunk_size"])
    chunk_overlap = int(config["chunking"]["chunk_overlap"])

    def stream():
        yield _sse({"type": "status", "text": "Crawling website..."})
        try:
            connector = WebsiteCrawlerConnector(crawler_config)
        except Exception as e:
            yield _sse({"type": "error", "error": f"crawler init failed: {e}"})
            return

        chunks: list[dict] = []
        try:
            for doc in connector.load_documents():
                pieces = chunk_text(doc.content, chunk_size=chunk_size, overlap=chunk_overlap)
                if not pieces:
                    continue
                vecs = embed([f"search_document: {p}" for p in pieces],
                             model_name=emb_model, batch_size=emb_batch)
                for piece, vec in zip(pieces, vecs):
                    chunks.append({"text": piece, "title": doc.title,
                                    "url": doc.url, "vector": vec})
        except Exception as e:
            yield _sse({"type": "error", "error": f"crawl failed: {e}"})
            return

        if not chunks:
            yield _sse({"type": "error", "error": "No web content found for the given URL(s)."})
            return

        yield _sse({"type": "status", "text": f"Pulled {len(chunks)} chunks from the web (not stored)."})

        qvec = embed_query(req.q, model_name=emb_model)
        for c in chunks:
            c["score"] = float(sum(a * b for a, b in zip(qvec, c["vector"])))
        top = sorted(chunks, key=lambda c: c["score"], reverse=True)[: max(req.k * 2, 20)]

        do_rerank = req.rerank if req.rerank is not None else config.get("search", {}).get("rerank", False)
        if do_rerank:
            try:
                from core.reranker import rerank as _rerank
                model = config.get("search", {}).get("rerank_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
                top = _rerank(req.q, top, top_k=req.k, model_name=model)
            except Exception:
                top = top[:req.k]
        else:
            top = top[:req.k]

        sources = [
            {"title": c.get("title"), "url": c.get("url"), "source": "website",
             "repo": "", "summary": "", "text": c.get("text", "")}
            for c in top
        ]
        yield _sse({"type": "sources", "sources": sources})

        try:
            for token in llm.answer(req.q, sources):
                yield _sse({"type": "token", "text": token})
        except Exception as e:
            yield _sse({"type": "error", "error": f"answer failed: {e}"})
            return
        yield _sse({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/sync/status")
def sync_status():
    return {
        "indexing": _indexing_in_progress,
        "stop_requested": _stop_event.is_set(),
        "repos": store.list_repos(),
        "repo_counts": store.count_by_repo(),
        "total_rows": store.count(),
        "last_result": _current_index_result,
    }


@app.post("/sync/start")
def sync_start(req: IndexRequest, _: None = Depends(_require_auth)):
    global _indexing_in_progress, _current_index_result

    if _indexing_in_progress:
        return {"error": "indexing already in progress"}

    _stop_event.clear()

    with _index_lock:
        if _indexing_in_progress:
            return {"error": "indexing already in progress"}
        _indexing_in_progress = True
        _current_index_result = None

    progress_q: queue.Queue = queue.Queue()

    def _progress_cb(event):
        progress_q.put(event)

    def _run():
        global _indexing_in_progress, _current_index_result
        try:
            result = run_indexing(
                progress_cb=_progress_cb,
                repo_path=req.repo_path if req.repo_path else None,
                force_full=req.force_full,
                stop_event=_stop_event,
            )
            _current_index_result = result
        except Exception as e:
            progress_q.put({"type": "error", "error": str(e)})
            _current_index_result = {"error": str(e)}
        finally:
            progress_q.put(None)
            with _index_lock:
                _indexing_in_progress = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    def stream():
        while True:
            event = progress_q.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/sync/stop")
def sync_stop(_: None = Depends(_require_auth)):
    if not _indexing_in_progress:
        return {"error": "no indexing in progress"}
    _stop_event.set()
    return {"status": "stopping"}


@app.post("/sync/clear")
def sync_clear(_: None = Depends(_require_auth)):
    if _indexing_in_progress:
        return {"error": "cannot clear while indexing"}
    store.clear()
    sync_state.clear_all()
    return {"status": "cleared"}


@app.get("/config")
def get_config():
    conn = config.get("connectors", {}).get("github_files", {})
    commits = config.get("connectors", {}).get("github_commits", {})
    website = config.get("connectors", {}).get("website", {})
    documents = config.get("connectors", {}).get("documents", {})
    arxiv = config.get("connectors", {}).get("arxiv", {})
    youtube = config.get("connectors", {}).get("youtube", {})
    return {
        "repo_path": conn.get("local_path", ""),
        "github": {
            "mode": conn.get("mode", "local"),
            "local_path": conn.get("local_path", ""),
            "repo": conn.get("repo", ""),
            "pat": "",
            "branch": conn.get("branch", ""),
            "commits_enabled": commits.get("enabled", False),
        },
        "website": {
            "enabled": website.get("enabled", False),
            "label": website.get("label", ""),
            "start_urls": website.get("start_urls", []),
            "sitemap_urls": website.get("sitemap_urls", []),
            "same_domain_only": website.get("same_domain_only", True),
            "include_patterns": website.get("include_patterns", []),
            "exclude_patterns": website.get("exclude_patterns", []),
            "max_pages": website.get("max_pages", 150),
            "max_depth": website.get("max_depth", 2),
            "delay_seconds": website.get("delay_seconds", 0.15),
            "min_text_chars": website.get("min_text_chars", 250),
            "respect_robots_txt": website.get("respect_robots_txt", True),
        },
        "documents": {
            "enabled": documents.get("enabled", False),
            "label": documents.get("label", "documents"),
            "paths": documents.get("paths", []),
            "recursive": documents.get("recursive", True),
            "max_file_size_kb": documents.get("max_file_size_kb", 10000),
            "min_text_chars": documents.get("min_text_chars", 100),
        },
        "arxiv": {
            "enabled": arxiv.get("enabled", False),
            "label": arxiv.get("label", "arxiv-papers"),
            "ids": arxiv.get("ids", []),
            "urls": arxiv.get("urls", []),
            "include_pdf_text": arxiv.get("include_pdf_text", True),
        },
        "youtube": {
            "enabled": youtube.get("enabled", False),
            "label": youtube.get("label", "youtube-transcripts"),
            "urls": youtube.get("urls", []),
            "video_ids": youtube.get("video_ids", []),
            "languages": youtube.get("languages", ["en"]),
            "include_timestamps": youtube.get("include_timestamps", True),
        },
        "llm": {
            "provider": config["llm"].get("provider", ""),
            "model": config["llm"].get("model", ""),
            "temperature": config["llm"].get("temperature", 0.2),
            "max_tokens": config["llm"].get("max_tokens", 2000),
        },
        "embedding": {
            "model": config["embedding"].get("model", ""),
            "dim": config["embedding"].get("dim", 768),
        },
        "chunking": {
            "chunk_size": config["chunking"].get("chunk_size", 512),
            "chunk_overlap": config["chunking"].get("chunk_overlap", 50),
        },
        "search": {
            "top_k": config.get("search", {}).get("top_k", 10),
            "rerank": config.get("search", {}).get("rerank", False),
        },
        "sync": {
            "enabled": config.get("sync", {}).get("enabled", True),
        },
    }


@app.post("/config")
def update_config(upd: ConfigUpdate, _: None = Depends(_require_auth)):
    global config

    conn = config.setdefault("connectors", {})
    gh = conn.setdefault("github_files", {})
    gh_commits = conn.setdefault("github_commits", {})
    website = conn.setdefault("website", {})
    documents = conn.setdefault("documents", {})
    arxiv = conn.setdefault("arxiv", {})
    youtube = conn.setdefault("youtube", {})

    gh.setdefault("enabled", True)
    gh_commits.setdefault("enabled", False)
    website.setdefault("enabled", False)
    documents.setdefault("enabled", False)
    arxiv.setdefault("enabled", False)
    youtube.setdefault("enabled", False)

    if upd.repo_path is not None:
        gh["local_path"] = upd.repo_path
    if upd.github_mode is not None:
        gh["mode"] = upd.github_mode
    if upd.github_repo is not None:
        gh["repo"] = upd.github_repo
        gh_commits["repo"] = upd.github_repo
    if upd.github_pat is not None:
        gh["pat"] = upd.github_pat
        gh_commits["pat"] = upd.github_pat
    if upd.github_branch is not None:
        gh["branch"] = upd.github_branch
    if upd.github_commits_enabled is not None:
        gh_commits["enabled"] = upd.github_commits_enabled

    if upd.github_files_enabled is not None:
        gh["enabled"] = upd.github_files_enabled

    if upd.website_enabled is not None:
        website["enabled"] = upd.website_enabled
    elif upd.github_mode is not None and upd.github_mode != "website":
        website["enabled"] = False
    if upd.website_label is not None:
        website["label"] = upd.website_label
    if upd.website_start_urls is not None:
        website["start_urls"] = upd.website_start_urls
    if upd.website_sitemap_urls is not None:
        website["sitemap_urls"] = upd.website_sitemap_urls
    if upd.website_same_domain_only is not None:
        website["same_domain_only"] = upd.website_same_domain_only
    if upd.website_include_patterns is not None:
        website["include_patterns"] = upd.website_include_patterns
    if upd.website_exclude_patterns is not None:
        website["exclude_patterns"] = upd.website_exclude_patterns
    if upd.website_max_pages is not None:
        website["max_pages"] = upd.website_max_pages
    if upd.website_max_depth is not None:
        website["max_depth"] = upd.website_max_depth
    if upd.website_delay_seconds is not None:
        website["delay_seconds"] = upd.website_delay_seconds
    if upd.website_min_text_chars is not None:
        website["min_text_chars"] = upd.website_min_text_chars
    if upd.website_respect_robots_txt is not None:
        website["respect_robots_txt"] = upd.website_respect_robots_txt

    if upd.documents_enabled is not None:
        documents["enabled"] = upd.documents_enabled
    elif upd.github_mode is not None and upd.github_mode != "zip":
        documents["enabled"] = False
    if upd.documents_label is not None:
        documents["label"] = upd.documents_label
    if upd.documents_paths is not None:
        documents["paths"] = upd.documents_paths
    if upd.documents_recursive is not None:
        documents["recursive"] = upd.documents_recursive
    if upd.documents_max_file_size_kb is not None:
        documents["max_file_size_kb"] = upd.documents_max_file_size_kb
    if upd.documents_min_text_chars is not None:
        documents["min_text_chars"] = upd.documents_min_text_chars

    if upd.arxiv_enabled is not None:
        arxiv["enabled"] = upd.arxiv_enabled
    elif upd.github_mode is not None and upd.github_mode != "arxiv":
        arxiv["enabled"] = False
    if upd.arxiv_label is not None:
        arxiv["label"] = upd.arxiv_label
    if upd.arxiv_ids is not None:
        arxiv["ids"] = upd.arxiv_ids
    if upd.arxiv_urls is not None:
        arxiv["urls"] = upd.arxiv_urls
    if upd.arxiv_include_pdf_text is not None:
        arxiv["include_pdf_text"] = upd.arxiv_include_pdf_text

    if upd.youtube_enabled is not None:
        youtube["enabled"] = upd.youtube_enabled
    elif upd.github_mode is not None and upd.github_mode != "youtube":
        youtube["enabled"] = False
    if upd.youtube_label is not None:
        youtube["label"] = upd.youtube_label
    if upd.youtube_urls is not None:
        youtube["urls"] = upd.youtube_urls
    if upd.youtube_video_ids is not None:
        youtube["video_ids"] = upd.youtube_video_ids
    if upd.youtube_languages is not None:
        youtube["languages"] = upd.youtube_languages
    if upd.youtube_include_timestamps is not None:
        youtube["include_timestamps"] = upd.youtube_include_timestamps

    if upd.llm_provider is not None:
        config["llm"]["provider"] = upd.llm_provider
    if upd.llm_model is not None:
        config["llm"]["model"] = upd.llm_model
    if upd.llm_temperature is not None:
        config["llm"]["temperature"] = upd.llm_temperature
    if upd.llm_max_tokens is not None:
        config["llm"]["max_tokens"] = upd.llm_max_tokens

    if upd.embedding_model is not None:
        config["embedding"]["model"] = upd.embedding_model
    if upd.chunk_size is not None:
        config["chunking"]["chunk_size"] = upd.chunk_size
    if upd.chunk_overlap is not None:
        config["chunking"]["chunk_overlap"] = upd.chunk_overlap

    search = config.setdefault("search", {})
    if upd.top_k is not None:
        search["top_k"] = upd.top_k
    if upd.rerank is not None:
        search["rerank"] = upd.rerank

    try:
        save_config(config)
        _recreate_runtime()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to save config: {e}")

    return {"status": "saved"}


@app.post("/uploads/zip")
async def upload_zip(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(default="zip-upload"),
):
    _require_auth(request)

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="please upload a .zip file")

    upload_dir = create_upload_dir("zip")
    zip_name = sanitize_name(Path(file.filename).stem or label or "zip-upload")
    zip_path = upload_dir / f"{zip_name}.zip"
    extract_dir = upload_dir / "extracted"

    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="uploaded zip is empty")
        if len(data) > 100 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="uploaded zip exceeds 100 MB limit")
        zip_path.write_bytes(data)
        extracted = extract_zip_safe(zip_path, extract_dir)
        if not extracted:
            raise HTTPException(status_code=400, detail="zip contained no supported files")
        return {
            "status": "ok",
            "label": sanitize_name(label or zip_name),
            "path": str(extract_dir).replace("\\", "/"),
            "files": len(extracted),
        }
    except HTTPException:
        cleanup_upload_dir(upload_dir)
        raise
    except Exception as e:
        cleanup_upload_dir(upload_dir)
        raise HTTPException(status_code=400, detail=f"zip upload failed: {e}")


@app.post("/graph/query")
def graph_query(req: GraphQueryRequest, _: None = Depends(_require_auth)):
    kg = get_kg()
    if not kg:
        return {"error": "knowledge graph not enabled"}
    return kg.query(req.repo, req.entity)


@app.get("/graph/{repo}")
def get_graph(repo: str, _: None = Depends(_require_auth)):
    kg = get_kg()
    if not kg:
        return {"error": "knowledge graph not enabled"}
    graph = kg.get_or_create(repo)
    return graph.to_dict()
