from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.auth import verify_api_key
from api.deps import get_session, get_store
from api.schemas.documents import (
    IngestRequest,
    IngestResponse,
    UploadResponse,
    GitHubLookupRequest,
    GitHubLookupResponse,
)
from core.config import resolve_data_path
from core.vector_store import VectorStore
from services.ingest_service import IngestService

UPLOAD_ROOT = resolve_data_path("./data/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def _sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@router.post(":upload")
def upload_documents(
    collection_name: str = Form(...),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
    store: VectorStore = Depends(get_store),
    _auth: None = Depends(verify_api_key),
):
    """Upload files and start an indexing job."""
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")

    # Create a temporary directory for this upload batch
    job_dir = Path(tempfile.mkdtemp(prefix="upload-", dir=str(UPLOAD_ROOT)))
    saved_paths = []

    for f in files:
        if not f.filename:
            continue
        # Sanitize filename
        safe_name = re.sub(r'[^\w\-_. ]', '_', f.filename)
        dest = job_dir / safe_name
        try:
            content = f.file.read()
            dest.write_bytes(content)
            saved_paths.append(str(dest))
        except Exception as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Failed to save {f.filename}: {str(e)}")

    if not saved_paths:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No files could be saved")

    # Start an indexing job for these files
    svc = IngestService(session, store)
    job_id = svc.start_ingest(
        source="upload",
        source_config={
            "repo_path": str(job_dir),
            "label": collection_name,
        },
        collection_name=collection_name,
    )

    return UploadResponse(
        job_id=job_id,
        collection_id=job_id,
        collection_name=collection_name,
        file_count=len(saved_paths),
    )


@router.post(":github-lookup")
def github_lookup(
    req: GitHubLookupRequest,
    _auth: None = Depends(verify_api_key),
) -> GitHubLookupResponse:
    """Parse a GitHub URL and return repo information."""
    url = req.url.strip().rstrip("/")
    # Match patterns: https://github.com/owner/repo, github.com/owner/repo
    m = re.match(r"(?:https?://)?github\.com/([^/]+)/([^/?#]+)", url)
    if not m:
        return GitHubLookupResponse(
            owner="",
            repo="",
            error="Invalid GitHub URL. Expected format: https://github.com/owner/repo",
        )

    owner, repo = m.group(1), m.group(2)
    # Remove .git suffix if present
    repo = re.sub(r"\.git$", "", repo)

    # Try GitHub API for rich info
    try:
        import urllib.request
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        req_gh = urllib.request.Request(api_url, headers={"User-Agent": "KnowledgeHub/1.0"})
        with urllib.request.urlopen(req_gh, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return GitHubLookupResponse(
                owner=owner,
                repo=repo,
                full_name=data.get("full_name"),
                description=data.get("description"),
                stars=data.get("stargazers_count"),
                default_branch=data.get("default_branch", "main"),
            )
    except Exception:
        # Fallback: return just the name
        return GitHubLookupResponse(
            owner=owner,
            repo=repo,
            full_name=f"{owner}/{repo}",
            default_branch="main",
        )


@router.post(":ingest")
def ingest_documents(
    req: IngestRequest,
    session: Session = Depends(get_session),
    store: VectorStore = Depends(get_store),
    _auth: None = Depends(verify_api_key),
):
    svc = IngestService(session, store)
    job_id = svc.start_ingest(
        source=req.source,
        source_config=req.source_config,
        collection_id=req.collection_id,
        collection_name=req.collection_name,
    )

    progress_q = svc.get_progress_queue(job_id)

    def stream():
        if progress_q is None:
            yield _sse({"type": "error", "error": "Job queue not found"})
            return
        yield _sse({"type": "started", "job_id": job_id})
        while True:
            try:
                event = progress_q.get(timeout=30)
            except Exception:
                yield _sse({"type": "heartbeat"})
                continue
            if event is None:
                yield _sse({"type": "done", "job_id": job_id})
                break
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")
