"""Re-index endpoint — rebuild the knowledge table from all configured sources."""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_store
from core.indexer import run_indexing
from core.logging import get_logger
from core.vector_store import VectorStore

log = get_logger("reindex")

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_reindex_lock = threading.Lock()
_reindex_in_progress = False


class ReindexRequest(BaseModel):
    """Request body for re-indexing."""

    force_full: bool = Field(
        default=True,
        description="If True, ignore incremental sync state and re-index everything.",
    )
    rebuild_fts: bool = Field(
        default=True,
        description="If True, rebuild FTS index after re-indexing.",
    )


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _run():
    """Generator for the SSE stream."""
    global _reindex_in_progress
    _reindex_in_progress = True
    try:
        yield _sse({"type": "start", "message": "Starting re-index..."})

        progress_events: list[dict] = []

        def progress_cb(event: dict):
            progress_events.append(event)

        result = run_indexing(
            progress_cb=progress_cb,
            stop_event=None,
        )

        for event in progress_events:
            yield _sse({"type": "progress", **event})

        if result.get("errors"):
            yield _sse({
                "type": "warning",
                "message": f"Indexing completed with {len(result['errors'])} errors",
                "errors": result["errors"],
            })

        yield _sse({
            "type": "index_done",
            "total_chunks": result.get("total_chunks", 0),
            "total_docs": result.get("total_docs", 0),
            "elapsed": result.get("elapsed", 0),
        })
    except Exception as e:
        log.error("Re-index failed: %s", e, exc_info=True)
        yield _sse({"type": "error", "message": str(e)})
    finally:
        _reindex_in_progress = False
        _reindex_lock.release()


@router.post(":reindex")
def reindex(
    req: ReindexRequest,
    store: VectorStore = Depends(get_store),
    _auth: None = Depends(verify_api_key),
):
    """Trigger full re-indexing from all configured sources.

    Returns an SSE stream with progress events:
    - ``{"type": "start", "message": "..."}``
    - ``{"type": "progress", ...}``
    - ``{"type": "index_done", "total_chunks": N}``
    - ``{"type": "done", "message": "..."}``
    - ``{"type": "error", "message": "..."}``
    """
    if not _reindex_lock.acquire(blocking=False):
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "Re-index already in progress"})]),
            media_type="text/event-stream",
        )

    def stream():
        yield from _run()

        # Rebuild FTS
        yield _sse({"type": "fts_rebuild", "message": "Rebuilding FTS index..."})
        try:
            store._ensure_fts_fresh()
            yield _sse({"type": "fts_rebuild", "message": "FTS index rebuilt."})
        except Exception as e:
            log.warning("FTS rebuild after re-index failed: %s", e)
            yield _sse({"type": "fts_rebuild", "message": f"FTS rebuild failed: {e}"})

        total_chunks = store.count()
        yield _sse({
            "type": "done",
            "total_chunks": total_chunks,
            "message": f"Re-index complete: {total_chunks} chunks in store.",
        })

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get(":reindex-status")
def reindex_status(_auth: None = Depends(verify_api_key)):
    """Check if re-indexing is in progress."""
    return {"in_progress": _reindex_in_progress}
