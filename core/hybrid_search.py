"""Hybrid search — merges vector + keyword (FTS) results."""
from __future__ import annotations

_DISTANCE_FIELD = "_distance"
_SCORE_FIELD = "_score"


def hybrid_search(
    vector_results: list[dict],
    fts_results: list[dict],
    vector_weight: float = 0.7,
    fts_weight: float = 0.3,
    top_k: int = 10,
) -> list[dict]:
    if vector_results:
        max_dist = max(r.get(_DISTANCE_FIELD, 1.0) for r in vector_results) or 1.0
        for r in vector_results:
            dist = r.get(_DISTANCE_FIELD, max_dist)
            r["_norm_score"] = 1.0 - (dist / max_dist)

    if fts_results:
        max_score = max(r.get(_SCORE_FIELD, 1.0) for r in fts_results) or 1.0
        for r in fts_results:
            score = r.get(_SCORE_FIELD, 0)
            r["_norm_score"] = score / max_score

    merged: dict[str, dict] = {}

    for r in vector_results:
        row_id = r.get("id") or r.get("doc_id", "")
        if row_id not in merged:
            merged[row_id] = {**r, "_vector_score": r["_norm_score"], "_fts_score": 0.0}
        else:
            merged[row_id]["_vector_score"] = max(merged[row_id].get("_vector_score", 0.0), r["_norm_score"])

    for r in fts_results:
        row_id = r.get("id") or r.get("doc_id", "")
        if row_id not in merged:
            merged[row_id] = {**r, "_fts_score": r["_norm_score"], "_vector_score": 0.0}
        else:
            merged[row_id]["_fts_score"] = max(merged[row_id].get("_fts_score", 0.0), r["_norm_score"])

    for row_id, r in merged.items():
        r["combined_score"] = (
            vector_weight * r.get("_vector_score", 0) +
            fts_weight * r.get("_fts_score", 0)
        )

    results = sorted(merged.values(), key=lambda x: x["combined_score"], reverse=True)

    for r in results:
        r.pop("_norm_score", None)
        r.pop("_vector_score", None)
        r.pop("_fts_score", None)

    return results[:top_k]
