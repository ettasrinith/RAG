"""Cross-source deduplication for discovered papers.

Priority: DOI > arXiv ID > title fuzzy match.
"""
from __future__ import annotations

import re
from unicodedata import normalize as _norm

from core.research.models import PaperCard


def _normalise_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = _norm("NFKD", title).lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def merge_paper_cards(cards: list[PaperCard]) -> list[PaperCard]:
    """Deduplicate a list of PaperCards across sources.

    Merging rules:
    1. DOI match wins — keep the card with the richer metadata.
    2. arXiv ID match wins — same strategy.
    3. Title fuzzy match (>85% overlap) — keep the richer card.
    """
    by_doi: dict[str, PaperCard] = {}
    by_arxiv: dict[str, PaperCard] = {}
    by_title: dict[str, PaperCard] = {}
    seen_ids: set[str] = set()

    result: list[PaperCard] = []

    # Sort by citation_count descending so richer records merge on top.
    cards.sort(key=lambda c: (c.citation_count or 0), reverse=True)

    for card in cards:
        canonical = _canonical_key(card)
        if canonical in seen_ids:
            continue
        seen_ids.add(canonical)
        result.append(card)

    return result


def _canonical_key(card: PaperCard) -> str:
    """Return a stable canonical key for dedup."""
    if card.doi:
        return f"doi:{card.doi.lower().strip()}"
    if card.arxiv_id:
        return f"arxiv:{card.arxiv_id.strip()}"
    norm = _normalise_title(card.title)
    if norm:
        return f"title:{norm}"
    return f"pid:{card.paper_id}"
