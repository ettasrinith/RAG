from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.auth import verify_api_key
from api.deps import get_llm, get_store, get_research_store
from api.schemas.chat import ChatRequest
from core.config import load_config
from core.embedder import embed_query
from core.llm import LLMClient
from core.search.fusion import rrf_fuse, apply_recency_bias
from core.search.reranker import rerank
from core.vector_store import VectorStore

router = APIRouter(prefix="/v1/chat", tags=["chat"])


def _sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@router.post(":ask")
def chat_ask(
    req: ChatRequest,
    llm: LLMClient = Depends(get_llm),
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    config = load_config()
    qvec = embed_query(req.q, model_name=config["embedding"]["model"])

    k = req.k * 3
    vector_hits = store.search(qvec, k=max(k * 2, 20))
    fts_hits = store.fts_search(req.q, k=max(k * 2, 20))

    fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

    # Also search research store so indexed papers appear in chat
    try:
        if research_store.count() > 0:
            r_vec = research_store.search(qvec, k=max(k * 2, 20))
            r_fts = research_store.fts_search(req.q, k=max(k * 2, 20))
            for h in r_vec:
                h.setdefault("source", "research")
                h.setdefault("repo", h.get("collection", "research"))
            for h in r_fts:
                h.setdefault("source", "research")
                h.setdefault("repo", h.get("collection", "research"))
            fused = rrf_fuse(fused, r_vec + r_fts, top_n=k)
    except Exception:
        pass  # Research store may not have data yet

    # Apply recency bias so newer documents rank higher
    fused = apply_recency_bias(fused)

    reranked = rerank(req.q, fused, top_k=req.k)

    sources = [
        {
            "title": h.get("title"),
            "url": h.get("url"),
            "source": h.get("source"),
            "repo": h.get("repo", ""),
            "snippet": (h.get("text") or "")[:300],
            "score": h.get("combined_score", 0.0),
        }
        for h in reranked
    ]

    if not req.stream:
        return {"sources": sources, "answer": "Streaming only supported via SSE"}

    def stream():
        yield _sse({"type": "sources", "sources": sources})
        for token in llm.answer(req.q, sources):
            yield _sse({"type": "token", "text": token})
        yield _sse({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")
