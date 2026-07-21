from __future__ import annotations

"""Legacy endpoints — kept for backward compatibility, delegates to new services."""

import html as _html
import json
import os
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import load_config, ROOT
from core.indexer import run_indexing
from core.sync_state import SyncState
from core.hierarchy import HierarchyIndex
from core.uploads import create_upload_dir, cleanup_upload_dir, extract_zip_safe, sanitize_name
from connectors.website.crawler import WebsiteCrawlerConnector
from core.chunker import chunk_text
from core.embedder import embed, embed_query
from core.search.fusion import rrf_fuse
from core.search.reranker import rerank
from api.deps import get_llm, get_store, get_research_store, get_session

router = APIRouter(tags=["legacy"])

config = load_config()
_stop_event = threading.Event()
_index_lock = threading.Lock()
_indexing_in_progress = False
_current_index_result = None

API_KEY = os.environ.get("KH_API_KEY", "")


def _require_auth(request: Request):
    if not API_KEY:
        return
    provided = request.headers.get("X-API-Key") or request.query_params.get("token", "")
    if provided != API_KEY:
        raise HTTPException(status_code=401, detail="missing or invalid API key")


@router.get("/health")
def health(store=Depends(get_store)):
    return {
        "ok": True,
        "rows": store.count(),
        "repos": store.list_repos(),
        "repo_counts": store.count_by_repo(),
        "embedding_model": config["embedding"]["model"],
        "llm_model": config["llm"]["model"],
        "indexing": _indexing_in_progress,
    }


@router.post("/search")
def search(req: dict, store=Depends(get_store)):
    q = req.get("q", "")
    k = req.get("k", 10)
    source = req.get("source")
    repo = req.get("repo")

    qvec = embed_query(q, model_name=config["embedding"]["model"])
    vector_hits = store.search(qvec, k=max(k * 2, 20), source_filter=source, repo_filter=repo)
    fts_hits = store.fts_search(q, k=max(k * 2, 20), source_filter=source, repo_filter=repo)
    fused = rrf_fuse(vector_hits, fts_hits, top_n=k * 2)
    reranked = rerank(q, fused, top_k=k) if config.get("search", {}).get("rerank", False) else fused[:k]

    return {"results": [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "repo": h.get("repo", ""),
            "snippet": (h.get("text") or "")[:500],
            "summary": h.get("summary", ""),
            "score": h.get("combined_score") or h.get("rerank_score") or h.get("_distance"),
        }
        for h in reranked
    ]}


@router.post("/chat")
def chat(req: dict, llm=Depends(get_llm), store=Depends(get_store)):
    q = req.get("q", "")
    k = req.get("k", 8)
    qvec = embed_query(q, model_name=config["embedding"]["model"])
    vector_hits = store.search(qvec, k=max(k * 2, 20))
    fts_hits = store.fts_search(q, k=max(k * 2, 20))
    fused = rrf_fuse(vector_hits, fts_hits, top_n=k * 2)
    reranked = rerank(q, fused, top_k=k)

    sources = [
        {"title": h.get("title"), "url": h.get("url"), "source": h.get("source"),
         "summary": h.get("summary", ""), "text": h.get("text", "")}
        for h in reranked
    ]

    def stream():
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        for token in llm.answer(q, sources):
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/sync/start")
def sync_start(req: dict):
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
            result = run_indexing(progress_cb=_progress_cb, stop_event=_stop_event)
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


@router.get("/sync/status")
def sync_status(store=Depends(get_store)):
    return {
        "indexing": _indexing_in_progress,
        "stop_requested": _stop_event.is_set(),
        "repos": store.list_repos(),
        "repo_counts": store.count_by_repo(),
        "total_rows": store.count(),
        "last_result": _current_index_result,
    }


@router.post("/sync/stop")
def sync_stop():
    global _indexing_in_progress
    if not _indexing_in_progress:
        return {"error": "no indexing in progress"}
    _stop_event.set()
    return {"status": "stopping"}


@router.post("/sync/clear")
def sync_clear(store=Depends(get_store)):
    if _indexing_in_progress:
        return {"error": "cannot clear while indexing"}
    store.clear()
    return {"status": "cleared"}


@router.get("/repos")
def list_repos(store=Depends(get_store)):
    return {"repos": store.list_repos(), "counts": store.count_by_repo()}


@router.get("/file", response_class=HTMLResponse)
def view_file(path: str = ""):
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    local_path = config.get("connectors", {}).get("github_files", {}).get("local_path", "")
    if not local_path:
        raise HTTPException(status_code=400, detail="no local path configured")
    base = Path(local_path)
    if not base.is_absolute():
        base = ROOT / local_path
    base = base.resolve()
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
        f'<span class="ln">{i+1}</span>{line}' for i, line in enumerate(lines)
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


@router.get("/folders")
def list_folders():
    search_paths = []
    home = Path.home()
    for candidate in [home / "Documents", home / "Desktop", home / "Downloads",
                      Path("C:/dev"), Path("C:/src"), Path("C:/projects"), Path("D:/repos")]:
        if candidate.exists():
            search_paths.append(candidate)
    folders = []
    for base in search_paths:
        try:
            for item in base.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    git_dir = item / ".git"
                    if git_dir.exists():
                        folders.append({"name": item.name, "path": str(item).replace("\\", "/"), "type": "git"})
        except PermissionError:
            continue
    configured_path = config.get("connectors", {}).get("github_files", {}).get("local_path", "")
    if configured_path:
        folders.insert(0, {"name": Path(configured_path).name or configured_path, "path": configured_path, "type": "configured"})
    return {"folders": folders}


@router.get("/hierarchy")
def list_hierarchy(repo: str | None = None):
    store = __import__("api.deps", fromlist=["get_store"]).get_store()
    repos = [repo] if repo else store.list_repos()
    paths: list[str] = []
    for repo_name in repos:
        try:
            hierarchy = HierarchyIndex(repo_name, config.get("hierarchy", {}).get("max_depth", 10))
            paths.extend(hierarchy.get_all_paths())
        except Exception:
            continue
    return {"paths": sorted(set(paths))}


@router.post("/web/ask")
def web_ask(req: dict, llm=Depends(get_llm)):
    website_cfg = config.get("connectors", {}).get("website", {})
    urls = req.get("urls") or list(website_cfg.get("start_urls", []))
    query = req.get("q", "")
    k = req.get("k", 8)
    crawler_config = {
        "start_urls": urls,
        "sitemap_urls": list(website_cfg.get("sitemap_urls", [])),
        "label": website_cfg.get("label", ""),
        "same_domain_only": website_cfg.get("same_domain_only", True),
        "include_patterns": list(website_cfg.get("include_patterns", [])),
        "exclude_patterns": list(website_cfg.get("exclude_patterns", [])),
        "max_pages": req.get("max_pages") or int(website_cfg.get("max_pages", 150)),
        "max_depth": req.get("max_depth") or int(website_cfg.get("max_depth", 2)),
        "request_timeout_seconds": int(website_cfg.get("request_timeout_seconds", 15)),
        "delay_seconds": float(website_cfg.get("delay_seconds", 0.15)),
        "min_text_chars": int(website_cfg.get("min_text_chars", 250)),
        "max_page_size_kb": int(website_cfg.get("max_page_size_kb", 1024)),
        "respect_robots_txt": bool(website_cfg.get("respect_robots_txt", True)),
        "user_agent": website_cfg.get("user_agent", "KnowledgeHubBot/1.0"),
    }
    emb_model = config["embedding"]["model"]
    emb_batch = int(config["embedding"].get("batch_size", 64))
    chunk_size = int(config["chunking"]["chunk_size"])
    chunk_overlap = int(config["chunking"]["chunk_overlap"])

    def stream():
        yield f"data: {json.dumps({'type': 'status', 'text': 'Crawling...'})}\n\n"
        try:
            connector = WebsiteCrawlerConnector(crawler_config)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'crawler init failed: {e}'})}\n\n"
            return
        chunks: list[dict] = []
        try:
            for doc in connector.load_documents():
                pieces = chunk_text(doc.content, chunk_size=chunk_size, overlap=chunk_overlap)
                if not pieces:
                    continue
                vecs = embed([f"search_document: {p}" for p in pieces], model_name=emb_model, batch_size=emb_batch)
                for piece, vec in zip(pieces, vecs):
                    chunks.append({"text": piece, "title": doc.title, "url": doc.url, "vector": vec})
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'crawl failed: {e}'})}\n\n"
            return
        if not chunks:
            yield f"data: {json.dumps({'type': 'error', 'error': 'No web content found.'})}\n\n"
            return
        yield f"data: {json.dumps({'type': 'status', 'text': f'Pulled {len(chunks)} chunks.'})}\n\n"
        qvec = embed_query(query, model_name=emb_model)
        for c in chunks:
            c["score"] = float(sum(a * b for a, b in zip(qvec, c["vector"])))
        top = sorted(chunks, key=lambda c: c["score"], reverse=True)[:max(k * 2, 20)]
        if config.get("search", {}).get("rerank", False):
            top = rerank(query, top, top_k=k)
        else:
            top = top[:k]
        sources = [{"title": c.get("title"), "url": c.get("url"), "source": "website", "text": c.get("text", "")} for c in top]
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        for token in llm.answer(query, sources):
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


class GraphQueryRequest(BaseModel):
    repo: str
    entity: str


def get_kg():
    global _kg_index
    if _kg_index is None and config.get("knowledge_graph", {}).get("enabled"):
        with _index_lock:
            if _kg_index is None:
                try:
                    from core.knowledge_graph import KnowledgeGraphIndex
                    _kg_index = KnowledgeGraphIndex()
                except Exception:
                    pass
    return _kg_index


_kg_index = None

# ─── Research endpoints ──────────────────────────────────────────────

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


@router.post("/research/discover")
def research_discover(req: DiscoverRequest):
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


@router.post("/research/index")
def research_index(req: ResearchIndexRequest, session: Session = Depends(get_session)):
    from core.research.indexer import index_papers
    from core.research.models import PaperCard
    from core.registry.models import CollectionModel
    from services.job_service import JobService
    from sqlalchemy.orm import Session
    import queue as _queue

    papers = []
    for p in req.papers:
        if isinstance(p, dict):
            papers.append(PaperCard(**p))
        elif isinstance(p, PaperCard):
            papers.append(p)

    if not papers:
        raise HTTPException(status_code=400, detail="no papers to index")

    # Resolve collection by id, then by name, or create one
    coll = session.query(CollectionModel).filter(
        CollectionModel.id == req.collection
    ).first()
    if not coll:
        coll = session.query(CollectionModel).filter(
            CollectionModel.name == req.collection
        ).first()
    if not coll:
        coll = CollectionModel(
            name=req.collection,
            kind="research",
            source_config={"paper_ids": [p.paper_id for p in papers]},
        )
        session.add(coll)
        session.commit()
        session.refresh(coll)

    job_svc = JobService(session)
    job = job_svc.create(collection_id=coll.id, items_total=len(papers))
    job_id = job.id
    session.commit()

    progress_q = _queue.Queue()

    def _progress_cb(event):
        progress_q.put(event)

    def _run():
        from core.registry.database import get_session as _get_db_session
        local_session = _get_db_session()
        local_job_svc = JobService(local_session)
        try:
            index_papers(papers, collection=req.collection, progress_cb=_progress_cb)
            local_job_svc.update_progress(job_id, items_done=len(papers), state="done")
            local_session.commit()
        except Exception as e:
            local_job_svc.update_progress(job_id, items_done=0, state="failed")
            local_session.commit()
            progress_q.put({"type": "error", "error": str(e)})
        finally:
            local_session.close()
            progress_q.put(None)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'started', 'job_id': job_id})}\n\n"
        while True:
            event = progress_q.get()
            if event is None:
                yield f"data: {json.dumps({'type': 'done', 'job_id': job_id})}\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/research/search")
def research_search(req: ResearchSearchRequest, store=Depends(get_research_store)):
    from core.embedder import embed_query
    from core.search.fusion import rrf_fuse

    qvec = embed_query(req.q, model_name=config["embedding"]["model"])
    if req.hybrid:
        vector_hits = store.search(qvec, k=max(req.k * 2, 20))
        fts_hits = store.fts_search(req.q, k=max(req.k * 2, 20))
        results = rrf_fuse(vector_hits, fts_hits, top_n=req.k * 2)
    else:
        results = store.search(qvec, k=req.k)

    if req.collection:
        results = [r for r in results if (r.get("collection") or "default") == req.collection]
    if req.year_from:
        results = [r for r in results if (r.get("year") or 0) >= req.year_from]

    return {"results": [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "collection": h.get("collection", "default"),
            "author": h.get("author"),
            "snippet": (h.get("text") or "")[:500],
            "summary": h.get("summary", ""),
            "score": h.get("combined_score") or h.get("_distance"),
            "year": h.get("year"),
            "paper_id": h.get("paper_id", ""),
        }
        for h in results[:req.k]
    ]}


@router.get("/research/catalog")
def research_catalog(collection: str | None = None):
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


@router.post("/research/delete")
def research_delete(req: ResearchDeleteRequest, store=Depends(get_research_store)):
    from core.research.catalog import PaperCatalog
    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)
    deleted = 0
    for pid in req.paper_ids:
        try:
            store.table.delete(f"paper_id = '{pid}'")
        except Exception:
            pass
        try:
            catalog.unmark(pid)
        except Exception:
            pass
        deleted += 1
    return {"deleted": deleted}


@router.get("/research/collections")
def research_collections():
    from core.research.catalog import PaperCatalog
    catalog_path = config.get("research", {}).get("catalog_path", "./data/research_catalog.json")
    catalog = PaperCatalog(catalog_path)
    collections = catalog.list_collections()
    counts = {}
    for c in collections:
        counts[c] = len(catalog.ids_by_collection(c))
    return {"collections": collections, "counts": counts}


@router.post("/graph/query")
def graph_query(req: GraphQueryRequest):
    kg = get_kg()
    if not kg:
        return {"error": "knowledge graph not enabled"}
    return kg.query(req.repo, req.entity)


@router.get("/graph/{repo}")
def get_graph(repo: str):
    kg = get_kg()
    if not kg:
        return {"error": "knowledge graph not enabled"}
    graph = kg.get_or_create(repo)
    return graph.to_dict()
