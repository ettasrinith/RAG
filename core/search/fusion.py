from __future__ import annotations

import math
from datetime import datetime, timezone


# ── Recency bias ────────────────────────────────────────────────────
# Applies exponential decay to document scores based on age, so newer
# documents rank higher while preserving relevance ordering.

RECENCY_HALF_LIFE_DAYS = 365  # score halves every ~1 year by default


def _parse_timestamp(val) -> datetime | None:
    """Try to parse a value into a timezone-aware UTC datetime.

    Supports ISO strings (with or without timezone), unix epochs (int/float),
    and datetime objects (naive ones are treated as UTC).
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        # Epoch seconds — assume reasonable range
        if val > 1e12:  # milliseconds
            val = val / 1000
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except (OSError, ValueError):
            return None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        # Normalize trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None
        # Always return timezone-aware — treat naive strings as UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def apply_recency_bias(
    results: list[dict],
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> list[dict]:
    """Apply freshness decay to combined_score. Newer docs get a boost.

    Looks for a date field in each result (in order of priority):
      created_at, indexed_at, published_at, updated_at, year

    The boost is multiplicative: score *= decay_factor where
    decay_factor = 2^(-age_days / half_life_days).
    Documents with no parseable date get a neutral factor of 1.0.
    """
    now = datetime.now(timeout=timezone.utc) if hasattr(datetime, "timeout") else datetime.now(timezone.utc)
    decay_rate = math.log(2) / half_life_days

    for r in results:
        date_val = (
            r.get("created_at")
            or r.get("indexed_at")
            or r.get("published_at")
            or r.get("updated_at")
        )
        dt = _parse_timestamp(date_val)

        # Fallback: use integer year field (e.g. 2024)
        if dt is None:
            year = r.get("year")
            if isinstance(year, (int, float)) and 1900 < year < 2100:
                dt = datetime(int(year), 6, 15, tzinfo=timezone.utc)  # mid-year estimate

        if dt is not None:
            age_days = max((now - dt).total_seconds() / 86400, 0)
            decay = math.exp(-decay_rate * age_days)
        else:
            decay = 1.0  # no date = no penalty

        r["combined_score"] = r.get("combined_score", 0.0) * decay
        r.setdefault("score_breakdown", {})["recency_factor"] = round(decay, 4)

    results.sort(key=lambda x: x["combined_score"], reverse=True)
    return results


# ── RRF Fusion ──────────────────────────────────────────────────────

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
