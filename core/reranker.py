"""Cross-encoder reranker — re-sorts search results by actual relevance."""
from __future__ import annotations

from sentence_transformers import CrossEncoder

_model: CrossEncoder | None = None
_model_name: str = ""


def get_reranker(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> CrossEncoder:
    global _model, _model_name
    if _model is None or _model_name != model_name:
        _model = CrossEncoder(model_name)
        _model_name = model_name
    return _model


def rerank(query: str, results: list[dict], top_k: int = 5,
           model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> list[dict]:
    """Rerank results using cross-encoder. Returns top_k results."""
    if not results:
        return []

    model = get_reranker(model_name)

    # Build query-document pairs
    pairs = []
    for r in results:
        text = r.get("text", "") or r.get("snippet", "") or r.get("title", "")
        pairs.append([query, text[:512]])  # truncate for cross-encoder

    # Score and sort
    scores = model.predict(pairs)
    for i, score in enumerate(scores):
        results[i]["rerank_score"] = float(score)

    results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return results[:top_k]
