"""Admin API — system configuration, cache stats, and management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_store, get_research_store, get_llm
from core.config import load_config, save_config as _save_config
from core.vector_store import VectorStore

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdminConfigUpdate(BaseModel):
    embedding_model: str | None = None
    embedding_dim: int | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    chunk_size: int | None = Field(default=None, ge=64, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)
    search_rerank: bool | None = None


@router.get(":config")
def get_config(
    _auth: None = Depends(verify_api_key),
):
    """Get current system configuration."""
    config = load_config()
    return {
        "embedding": {
            "model": config.get("embedding", {}).get("model", ""),
            "dim": config.get("embedding", {}).get("dim", 768),
            "batch_size": config.get("embedding", {}).get("batch_size", 64),
        },
        "llm": {
            "provider": config.get("llm", {}).get("provider", ""),
            "model": config.get("llm", {}).get("model", ""),
        },
        "chunking": {
            "chunk_size": config.get("chunking", {}).get("chunk_size", 512),
            "chunk_overlap": config.get("chunking", {}).get("chunk_overlap", 50),
        },
        "search": {
            "rerank": config.get("search", {}).get("rerank", False),
        },
        "vector_store": {
            "path": config.get("vector_store", {}).get("path", ""),
            "table": config.get("vector_store", {}).get("table", ""),
        },
    }


@router.patch(":config")
def update_config(
    req: AdminConfigUpdate,
    _auth: None = Depends(verify_api_key),
):
    """Update system configuration."""
    config = load_config()

    if req.embedding_model is not None:
        config.setdefault("embedding", {})["model"] = req.embedding_model
    if req.embedding_dim is not None:
        config.setdefault("embedding", {})["dim"] = req.embedding_dim
    if req.llm_provider is not None:
        config.setdefault("llm", {})["provider"] = req.llm_provider
    if req.llm_model is not None:
        config.setdefault("llm", {})["model"] = req.llm_model
    if req.chunk_size is not None:
        config.setdefault("chunking", {})["chunk_size"] = req.chunk_size
    if req.chunk_overlap is not None:
        config.setdefault("chunking", {})["chunk_overlap"] = req.chunk_overlap
    if req.search_rerank is not None:
        config.setdefault("search", {})["rerank"] = req.search_rerank

    _save_config(config)
    return {"status": "ok", "message": "Configuration updated"}


@router.get(":cache-stats")
def cache_stats(
    _auth: None = Depends(verify_api_key),
):
    """Get cache performance statistics."""
    from core.cache import embedding_cache, search_cache
    return {
        "embedding": embedding_cache.stats,
        "search": search_cache.stats,
    }


@router.post(":cache-clear")
def clear_cache(
    prefix: str = "",
    _auth: None = Depends(verify_api_key),
):
    """Clear cache entries. Pass prefix to clear specific entries."""
    from core.cache import embedding_cache, search_cache
    emb_cleared = embedding_cache.invalidate(prefix)
    srch_cleared = search_cache.invalidate(prefix)
    return {
        "status": "ok",
        "embedding_cleared": emb_cleared,
        "search_cleared": srch_cleared,
    }


@router.get(":kg-stats")
def kg_stats(
    repo: str = "",
    _auth: None = Depends(verify_api_key),
):
    """Get knowledge graph statistics."""
    try:
        from core.knowledge_graph import KnowledgeGraphIndex
        kg_index = KnowledgeGraphIndex()
        if repo:
            return kg_index.stats(repo)
        # Aggregate stats across all repos
        total_entities = 0
        total_relations = 0
        entity_types = {}
        for r in kg_index.graphs:
            stats = kg_index.stats(r)
            total_entities += stats.get("total_entities", 0)
            total_relations += stats.get("total_relations", 0)
            for t, c in stats.get("entity_types", {}).items():
                entity_types[t] = entity_types.get(t, 0) + c
        return {
            "total_entities": total_entities,
            "total_relations": total_relations,
            "entity_types": entity_types,
            "repos": list(kg_index.graphs.keys()),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get(":kg-clusters")
def kg_clusters(
    repo: str,
    min_size: int = 2,
    _auth: None = Depends(verify_api_key),
):
    """Get entity clusters from the knowledge graph."""
    try:
        from core.knowledge_graph import KnowledgeGraphIndex
        kg_index = KnowledgeGraphIndex()
        return {"clusters": kg_index.clusters(repo, min_size=min_size)}
    except Exception as e:
        return {"error": str(e)}
