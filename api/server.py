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
_store_path = config["vector_store"]["path"]
if not Path(_store_path).is_absolute():
    _store_path = str(ROOT / _store_path)
store = VectorStore(
    path=_store_path,
    table=config["vector_store"]["table"],
    dim=config["embedding"]["dim"],
)

# Research store — same DB file, separate table
_research_cfg = config.get("research_store", {})
_research_store_path = _research_cfg.get("path", "./data/lancedb")
if not Path(_research_store_path).is_absolute():
    _research_store_path = str(ROOT / _research_store_path)
research_store = VectorStore(
    path=_research_store_path,
    table=_research_cfg.get("table", "research"),
    dim=config["embedding"]["dim"],
    schema_type="research",
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
    global config, store, research_store, llm, sync_state, _reranker, _kg_index, _reranker_config
    config = load_config()
    _store_path = config["vector_store"]["path"]
    if not Path(_store_path).is_absolute():
        _store_path = str(ROOT / _store_path)
    store = VectorStore(
        path=_store_path,
        table=config["vector_store"]["table"],
        dim=config["embedding"]["dim"],
    )
    _research_cfg = config.get("research_store", {})
    _research_store_path = _research_cfg.get("path", "./data/lancedb")
    if not Path(_research_store_path).is_absolute():
        _research_store_path = str(ROOT / _research_store_path)
    research_store = VectorStore(
        path=_research_store_path,
        table=_research_cfg.get("table", "research"),
        dim=config["embedding"]["dim"],
        schema_type="research",
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
        fts_hits = store.fts_search(query, k=max(k * 2, 20),
                                    source_filter=source, repo_filter=repo)
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
    scope: str | None = Field(default=None, pattern="^(main|research)$")


def retrieve_research(query: str, k: int, collection: str | None = None,
                      year_from: int | None = None,
                      hybrid: bool = True) -> list[dict]:
    """Retrieve from the research table with optional collection/year filters."""
    qvec = embed_query(query, model_name=config["embedding"]["model"])
    if hybrid:
        vector_hits = research_store.search(qvec, k=max(k * 2, 20))
        fts_hits = research_store.fts_search(query, k=max(k * 2, 20))
        results = hybrid_search(vector_hits, fts_hits,
                                vector_weight=0.7, fts_weight=0.3, top_k=k * 2)
    else:
        results = research_store.search(qvec, k=k)

    # Apply collection filter
    if collection:
        results = [r for r in results if (r.get("collection") or "default") == collection]

    # Apply year filter
    if year_from:
        results = [r for r in results if (r.get("year") or 0) >= year_from]

    return results[:k]


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
    arxiv_query: str | None = None
    arxiv_ids: list[str] | None = None
    arxiv_urls: list[str] | None = None
    arxiv_max_results: int | None = Field(default=None, ge=1, le=1000)
    arxiv_include_pdf_text: bool | None = None
    openalex_enabled: bool | None = None
    openalex_label: str | None = None
    openalex_query: str | None = None
    openalex_ids: list[str] | None = None
    openalex_api_key: str | None = None
    openalex_max_results: int | None = Field(default=None, ge=1, le=1000)
    s2_enabled: bool | None = None
    s2_label: str | None = None
    s2_query: str | None = None
    s2_ids: list[str] | None = None
    s2_api_key: str | None = None
    s2_max_results: int | None = Field(default=None, ge=1, le=1000)
    confluence_enabled: bool | None = None
    confluence_label: str | None = None
    confluence_base_url: str | None = None
    confluence_email: str | None = None
    confluence_api_token: str | None = None
    confluence_pat: str | None = None
    confluence_query: str | None = None
    confluence_spaces: list[str] | None = None
    confluence_max_results: int | None = Field(default=None, ge=1, le=1000)
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


import html as _html
import mimetypes

@app.get("/", response_class=HTMLResponse)
def root():
    index = UI_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h1>Knowledge Hub</h1><p>UI not built yet — POST to /search or /chat.</p>"


@app.get("/file", response_class=HTMLResponse)
def view_file(path: str = ""):
    """Serve a local file as a styled HTML page for viewing in the browser."""
    if not path:
        raise HTTPException(status_code=400, detail="path is required")

    # Resolve relative to the configured local_path
    local_path = config.get("connectors", {}).get("github_files", {}).get("local_path", "")
    if not local_path:
        raise HTTPException(status_code=400, detail="no local path configured")

    from core.config import ROOT as _ROOT
    base = Path(local_path)
    if not base.is_absolute():
        base = _ROOT / local_path
    base = base.resolve()

    # Prevent path traversal
    try:
        target = (base / path).resolve()
        if not str(target).startswith(str(base)):
            raise HTTPException(status_code=403, detail="access denied")
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = target.read_text(encoding="latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="cannot read file (binary?)")
    except OSError:
        raise HTTPException(status_code=500, detail="cannot read file")

    ext = target.suffix.lower()
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "jsx", ".tsx": "tsx", ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
        ".sh": "bash", ".bash": "bash", ".sql": "sql", ".go": "go",
        ".rs": "rust", ".java": "java", ".rb": "ruby", ".c": "c",
        ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".xml": "xml",
        ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    }
    lang = lang_map.get(ext, "")

    escaped = _html.escape(content)
    lines = escaped.split("\n")
    numbered = "\n".join(
        f'<span class="ln">{i+1}</span>{line}'
        for i, line in enumerate(lines)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html.escape(path)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #0f172a; color: #e2e8f0; }}
  .bar {{ background: #1e293b; padding: 12px 20px; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 10; }}
  .bar a {{ color: #94a3b8; text-decoration: none; font-size: 14px; }}
  .bar a:hover {{ color: #e2e8f0; }}
  .bar .path {{ color: #e2e8f0; font-size: 14px; font-weight: 500; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  pre {{ padding: 16px 0; overflow-x: auto; font-size: 13px; line-height: 1.7; }}
  code {{ display: block; }}
  .ln {{ display: inline-block; width: 4em; text-align: right; padding-right: 1em; color: #475569; user-select: none; }}
</style>
</head>
<body>
  <div class="bar">
    <a href="/">&larr; Back</a>
    <span class="path">{_html.escape(path)}</span>
  </div>
  <pre><code>{numbered}</code></pre>
</body>
</html>"""


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
    # Determine which store to retrieve from based on scope
    if req.scope == "research":
        hits = retrieve_research(req.q, req.k, hybrid=True)
    else:
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
    openalex = config.get("connectors", {}).get("openalex", {})
    semantic_scholar = config.get("connectors", {}).get("semantic_scholar", {})
    confluence = config.get("connectors", {}).get("confluence", {})
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
            "query": arxiv.get("query", ""),
            "ids": arxiv.get("ids", []),
            "urls": arxiv.get("urls", []),
            "max_results": arxiv.get("max_results", 50),
            "include_pdf_text": arxiv.get("include_pdf_text", True),
        },
        "openalex": {
            "enabled": openalex.get("enabled", False),
            "label": openalex.get("label", "openalex-papers"),
            "query": openalex.get("query", ""),
            "ids": openalex.get("ids", []),
            "api_key": "",
            "max_results": openalex.get("max_results", 50),
        },
        "semantic_scholar": {
            "enabled": semantic_scholar.get("enabled", False),
            "label": semantic_scholar.get("label", "semantic-scholar"),
            "query": semantic_scholar.get("query", ""),
            "ids": semantic_scholar.get("ids", []),
            "api_key": "",
            "max_results": semantic_scholar.get("max_results", 50),
        },
        "confluence": {
            "enabled": confluence.get("enabled", False),
            "label": confluence.get("label", "confluence"),
            "base_url": confluence.get("base_url", ""),
            "email": confluence.get("email", ""),
            "api_token": "",
            "pat": "",
            "query": confluence.get("query", ""),
            "spaces": confluence.get("spaces", []),
            "max_results": confluence.get("max_results", 200),
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
    openalex = conn.setdefault("openalex", {})
    semantic_scholar = conn.setdefault("semantic_scholar", {})
    confluence = conn.setdefault("confluence", {})
    youtube = conn.setdefault("youtube", {})

    gh.setdefault("enabled", True)
    gh_commits.setdefault("enabled", False)
    website.setdefault("enabled", False)
    documents.setdefault("enabled", False)
    arxiv.setdefault("enabled", False)
    openalex.setdefault("enabled", False)
    semantic_scholar.setdefault("enabled", False)
    confluence.setdefault("enabled", False)
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
    if upd.arxiv_query is not None:
        arxiv["query"] = upd.arxiv_query
    if upd.arxiv_ids is not None:
        arxiv["ids"] = upd.arxiv_ids
    if upd.arxiv_urls is not None:
        arxiv["urls"] = upd.arxiv_urls
    if upd.arxiv_max_results is not None:
        arxiv["max_results"] = upd.arxiv_max_results
    if upd.arxiv_include_pdf_text is not None:
        arxiv["include_pdf_text"] = upd.arxiv_include_pdf_text

    if upd.openalex_enabled is not None:
        openalex["enabled"] = upd.openalex_enabled
    elif upd.github_mode is not None and upd.github_mode != "openalex":
        openalex["enabled"] = False
    if upd.openalex_label is not None:
        openalex["label"] = upd.openalex_label
    if upd.openalex_query is not None:
        openalex["query"] = upd.openalex_query
    if upd.openalex_ids is not None:
        openalex["ids"] = upd.openalex_ids
    if upd.openalex_api_key is not None and upd.openalex_api_key:
        openalex["api_key"] = upd.openalex_api_key
    if upd.openalex_max_results is not None:
        openalex["max_results"] = upd.openalex_max_results

    if upd.s2_enabled is not None:
        semantic_scholar["enabled"] = upd.s2_enabled
    elif upd.github_mode is not None and upd.github_mode != "semantic_scholar":
        semantic_scholar["enabled"] = False
    if upd.s2_label is not None:
        semantic_scholar["label"] = upd.s2_label
    if upd.s2_query is not None:
        semantic_scholar["query"] = upd.s2_query
    if upd.s2_ids is not None:
        semantic_scholar["ids"] = upd.s2_ids
    if upd.s2_api_key is not None and upd.s2_api_key:
        semantic_scholar["api_key"] = upd.s2_api_key
    if upd.s2_max_results is not None:
        semantic_scholar["max_results"] = upd.s2_max_results

    if upd.confluence_enabled is not None:
        confluence["enabled"] = upd.confluence_enabled
    elif upd.github_mode is not None and upd.github_mode != "confluence":
        confluence["enabled"] = False
    if upd.confluence_label is not None:
        confluence["label"] = upd.confluence_label
    if upd.confluence_base_url is not None:
        confluence["base_url"] = upd.confluence_base_url
    if upd.confluence_email is not None:
        confluence["email"] = upd.confluence_email
    if upd.confluence_api_token is not None and upd.confluence_api_token:
        confluence["api_token"] = upd.confluence_api_token
    if upd.confluence_pat is not None and upd.confluence_pat:
        confluence["pat"] = upd.confluence_pat
    if upd.confluence_query is not None:
        confluence["query"] = upd.confluence_query
    if upd.confluence_spaces is not None:
        confluence["spaces"] = upd.confluence_spaces
    if upd.confluence_max_results is not None:
        confluence["max_results"] = upd.confluence_max_results

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


# ─── Research endpoints ────────────────────────────────────────────────

class DiscoverRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["arxiv", "semantic_scholar", "openalex"])
    limit_per_source: int = Field(default=30, ge=1, le=100)
    year_from: int | None = None
    year_to: int | None = None


class ResearchIndexRequest(BaseModel):
    paper_ids: list[str] = Field(..., min_length=1)
    papers: list[dict] = Field(default_factory=list)
    collection: str = Field(default="default", max_length=100)


class ResearchSearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=100)
    collection: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    hybrid: bool = True


class ResearchDeleteRequest(BaseModel):
    paper_ids: list[str] = Field(..., min_length=1)


@app.post("/research/discover")
def research_discover(req: DiscoverRequest, _: None = Depends(_require_auth)):
    """Discover papers from academic sources."""
    from core.research.discover import discover_papers
    from core.research.catalog import PaperCatalog
    from core.research.models import DiscoverRequest as DR, PaperCard

    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)

    discover_req = DR(
        q=req.q,
        sources=req.sources,
        limit_per_source=req.limit_per_source,
        year_from=req.year_from,
        year_to=req.year_to,
    )
    result = discover_papers(discover_req, catalog)
    return {
        "papers": [p.model_dump() for p in result.papers],
        "total_found": result.total_found,
        "already_indexed": result.already_indexed,
        "sources_queried": result.sources_queried,
    }


@app.post("/research/index")
def research_index(req: ResearchIndexRequest, _: None = Depends(_require_auth)):
    """Index selected papers into the research store."""
    from core.research.indexer import index_papers
    from core.research.models import PaperCard
    import queue as _queue

    # Convert dicts back to PaperCard objects
    papers = []
    for p in req.papers:
        if isinstance(p, dict):
            papers.append(PaperCard(**p))
        elif isinstance(p, PaperCard):
            papers.append(p)

    if not papers:
        raise HTTPException(status_code=400, detail="no papers to index")

    progress_q = _queue.Queue()

    def _progress_cb(event):
        progress_q.put(event)

    def _run():
        try:
            index_papers(papers, collection=req.collection, progress_cb=_progress_cb)
        except Exception as e:
            progress_q.put({"type": "error", "error": str(e)})
        finally:
            progress_q.put(None)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    def stream():
        while True:
            event = progress_q.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/research/search")
def research_search(req: ResearchSearchRequest, _: None = Depends(_require_auth)):
    """Search the research store."""
    results = retrieve_research(
        req.q, req.k,
        collection=req.collection,
        year_from=req.year_from,
        hybrid=req.hybrid,
    )
    return {"results": [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "collection": h.get("collection", "default"),
            "author": h.get("author"),
            "snippet": (h.get("text") or "")[:500],
            "summary": h.get("summary", ""),
            "score": h.get("combined_score") or h.get("rerank_score") or h.get("_distance"),
            "year": h.get("year"),
            "paper_id": h.get("paper_id", ""),
        }
        for h in results
    ]}


@app.get("/research/catalog")
def research_catalog(collection: str | None = None, _: None = Depends(_require_auth)):
    """List papers in the catalog, optionally filtered by collection."""
    from core.research.catalog import PaperCatalog
    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)

    if collection:
        ids = catalog.ids_by_collection(collection)
    else:
        ids = catalog.all_ids()

    return {
        "papers": ids,
        "count": len(ids),
        "collections": catalog.list_collections(),
    }


@app.post("/research/delete")
def research_delete(req: ResearchDeleteRequest, _: None = Depends(_require_auth)):
    """Delete papers from the research store by paper_id."""
    from core.research.catalog import PaperCatalog
    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)

    deleted = 0
    for pid in req.paper_ids:
        # Delete from LanceDB
        research_store.table.delete(f"paper_id = '{pid}'")
        # Remove from catalog
        catalog.unmark(pid)
        deleted += 1

    return {"deleted": deleted}


@app.get("/research/collections")
def research_collections(_: None = Depends(_require_auth)):
    """List all research collections."""
    from core.research.catalog import PaperCatalog
    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)

    collections = catalog.list_collections()
    counts = {}
    for c in collections:
        counts[c] = len(catalog.ids_by_collection(c))

    return {"collections": collections, "counts": counts}


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
