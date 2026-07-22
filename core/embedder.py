"""Embedding wrapper — single source of truth for vector creation.

Provides sync and async interfaces, with caching for repeated queries.
"""
from __future__ import annotations

import asyncio
import os

from sentence_transformers import SentenceTransformer

from core.cache import embedding_cache, cache_key
from core.logging import get_logger

log = get_logger("embedder")

_models: dict[str, SentenceTransformer] = {}


def get_model(model_name: str = "nomic-ai/nomic-embed-text-v1") -> SentenceTransformer:
    if model_name not in _models:
        log.info("Loading embedding model: %s", model_name)
        _models[model_name] = SentenceTransformer(model_name, trust_remote_code=True)
        log.info("Embedding model loaded: %s", model_name)
    return _models[model_name]


def _optimal_batch_size(model_name: str) -> int:
    """Determine optimal batch size based on hardware."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_mem = torch.cuda.get_device_properties(0).total_mem / (1024**3)
            if gpu_mem >= 8:
                return 256
            elif gpu_mem >= 4:
                return 128
            return 64
    except ImportError:
        pass
    # CPU: smaller batches to avoid memory pressure
    cpu_count = os.cpu_count() or 4
    return min(32, cpu_count * 4)


def embed(texts: list[str], model_name: str = "nomic-ai/nomic-embed-text-v1",
          batch_size: int | None = None) -> list[list[float]]:
    if not texts:
        return []
    model = get_model(model_name)
    if batch_size is None:
        batch_size = _optimal_batch_size(model_name)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return vectors.tolist()


def embed_query(text: str, model_name: str = "nomic-ai/nomic-embed-text-v1") -> list[float]:
    """Embed a single query, with caching."""
    ck = cache_key("query", model_name, text)
    cached = embedding_cache.get(ck)
    if cached is not None:
        return cached

    prefixed = f"search_query: {text}"
    result = embed([prefixed], model_name=model_name)[0]
    embedding_cache.set(ck, result)
    return result


# ── Async wrappers ────────────────────────────────────────────────

async def embed_async(texts: list[str], model_name: str = "nomic-ai/nomic-embed-text-v1",
                      batch_size: int | None = None) -> list[list[float]]:
    """Non-blocking embed using asyncio.to_thread()."""
    return await asyncio.to_thread(embed, texts, model_name, batch_size)


async def embed_query_async(text: str, model_name: str = "nomic-ai/nomic-embed-text-v1") -> list[float]:
    """Non-blocking embed_query using asyncio.to_thread()."""
    return await asyncio.to_thread(embed_query, text, model_name)
