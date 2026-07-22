from __future__ import annotations

import logging
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)

from core.logging import get_logger

log = get_logger("reranker")

_reranker_instance = None
_reranker_lock = threading.Lock()


def get_reranker(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
    global _reranker_instance
    if _reranker_instance is None:
        with _reranker_lock:
            if _reranker_instance is None:
                try:
                    from sentence_transformers import CrossEncoder
                    _reranker_instance = CrossEncoder(model_name)
                except Exception as e:
                    logger.warning("Failed to load reranker %s: %s", model_name, e)
                    return None
    return _reranker_instance


@lru_cache(maxsize=512)
def _cached_rerank_score(query: str, passage: str) -> float:
    reranker = get_reranker()
    if reranker is None:
        return 0.0
    try:
        return float(reranker.predict([(query, passage)])[0])
    except Exception as e:
        log.warning("reranker score failed: %s", e)
        return 0.0


def rerank(
    query: str,
    results: list[dict],
    top_k: int = 10,
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> list[dict]:
    if not results:
        return []

    reranker = get_reranker(model_name)
    if reranker is None:
        return results[:top_k]

    pairs = [(query, r.get("text", r.get("snippet", ""))[:512]) for r in results]
    try:
        scores = reranker.predict(pairs)
    except Exception as e:
        logger.warning("Rerank predict failed: %s", e)
        return results[:top_k]

    for r, score in zip(results, scores):
        r["rerank_score"] = float(score)
        breakdown = r.get("score_breakdown", {})
        breakdown["rerank_score"] = float(score)
        r["score_breakdown"] = breakdown

    results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    return results[:top_k]
