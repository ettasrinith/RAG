from __future__ import annotations


def rrf_fuse(
    vector_results: list[dict],
    fts_results: list[dict],
    k: int = 60,
    top_n: int = 20,
) -> list[dict]:
    merged: dict[str, dict] = {}
    seen_ids: dict[str, int] = {}

    for rank, r in enumerate(vector_results):
        rid = r.get("id") or r.get("doc_id", "")
        if rid not in seen_ids:
            seen_ids[rid] = len(seen_ids)
            merged[rid] = {**r, "_rrf_score": 0.0}
        merged[rid]["_rrf_score"] += 1.0 / (k + rank + 1)
        merged[rid].setdefault("_vector_rank", rank + 1)
        merged[rid]["_fts_rank"] = merged[rid].get("_fts_rank", len(fts_results) + 1)

    for rank, r in enumerate(fts_results):
        rid = r.get("id") or r.get("doc_id", "")
        if rid not in seen_ids:
            seen_ids[rid] = len(seen_ids)
            merged[rid] = {**r, "_rrf_score": 0.0}
        merged[rid]["_rrf_score"] += 1.0 / (k + rank + 1)
        merged[rid].setdefault("_fts_rank", rank + 1)
        merged[rid]["_vector_rank"] = merged[rid].get("_vector_rank", len(vector_results) + 1)

    results = sorted(merged.values(), key=lambda x: x["_rrf_score"], reverse=True)

    for r in results:
        r["combined_score"] = r["_rrf_score"]
        r["score_breakdown"] = {
            "vector_rank": r.get("_vector_rank", 0),
            "fts_rank": r.get("_fts_rank", 0),
            "rrf_score": r["_rrf_score"],
        }
        for key in ("_rrf_score", "_vector_rank", "_fts_rank"):
            r.pop(key, None)

    return results[:top_n]


def hybrid_search_v2(
    vector_results: list[dict],
    fts_results: list[dict],
    vector_weight: float | None = None,
    fts_weight: float | None = None,
    top_k: int = 20,
) -> list[dict]:
    return rrf_fuse(vector_results, fts_results, k=60, top_n=top_k)
