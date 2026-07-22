"""Discover papers from academic sources with caching."""
from __future__ import annotations

import time
import concurrent.futures
from typing import Any

from core.config import load_config
from core.research.models import PaperCard, DiscoverRequest, DiscoverResponse
from core.research.merge import merge_paper_cards
from core.research.catalog import PaperCatalog
from core.logging import get_logger

log = get_logger("discover")

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------
_discover_cache: dict[str, tuple[float, list[PaperCard]]] = {}
CACHE_TTL = 300  # 5 minutes


def _cache_key(req: DiscoverRequest) -> str:
    return f"{req.q}:{','.join(sorted(req.sources))}:{req.limit_per_source}"


def _get_cached(key: str) -> list[PaperCard] | None:
    if key in _discover_cache:
        ts, results = _discover_cache[key]
        if time.time() - ts < CACHE_TTL:
            return results
    return None


def _set_cached(key: str, results: list[PaperCard]) -> None:
    _discover_cache[key] = (time.time(), results)


# ---------------------------------------------------------------------------
# Connector wrappers — thin adapters that call search_papers()
# ---------------------------------------------------------------------------

def _fetch_arxiv(req: DiscoverRequest) -> list[PaperCard]:
    from connectors.arxiv.reader import ArxivConnector
    cfg = {
        "query": req.q,
        "max_results": req.limit_per_source,
        "include_pdf_text": False,
        "delay_seconds": 0,
    }
    connector = ArxivConnector(cfg)
    raw = connector.search_papers(req.q, req.limit_per_source)
    cards: list[PaperCard] = []
    for r in raw:
        year = None
        pub = r.get("published", "")
        if pub and len(pub) >= 4:
            try:
                year = int(pub[:4])
            except ValueError:
                pass
        if req.year_from and year and year < req.year_from:
            continue
        if req.year_to and year and year > req.year_to:
            continue
        cards.append(PaperCard(
            paper_id=r.get("id", ""),
            title=r.get("title", ""),
            authors=r.get("authors", []),
            abstract=r.get("summary", ""),
            year=year,
            venue=r.get("primary_category", ""),
            doi=r.get("doi", ""),
            arxiv_id=r.get("id", ""),
            pdf_url=r.get("pdf_url", ""),
            abs_url=r.get("abs_url", ""),
            source="arxiv",
        ))
    return cards


def _fetch_s2(req: DiscoverRequest) -> list[PaperCard]:
    from connectors.semantic_scholar.reader import SemanticScholarConnector
    cfg = {
        "query": req.q,
        "max_results": req.limit_per_source,
        "include_abstract": True,
        "delay_seconds": 0,
    }
    connector = SemanticScholarConnector(cfg)
    raw = connector.search_papers(req.q, req.limit_per_source)
    cards: list[PaperCard] = []
    for r in raw:
        year = r.get("year")
        if isinstance(year, str):
            try:
                year = int(year)
            except ValueError:
                year = None
        if req.year_from and year and year < req.year_from:
            continue
        if req.year_to and year and year > req.year_to:
            continue
        authors = []
        for a in r.get("authors", []):
            if isinstance(a, dict):
                authors.append(a.get("name", ""))
            else:
                authors.append(str(a))
        external = r.get("externalIds", {}) or {}
        cards.append(PaperCard(
            paper_id=str(external.get("CorpusId", r.get("paperId", ""))),
            title=r.get("title", ""),
            authors=authors,
            abstract=r.get("abstract", "") or "",
            year=year,
            venue=r.get("venue", ""),
            citation_count=r.get("citationCount"),
            doi=r.get("doi", "") or external.get("DOI", ""),
            arxiv_id=external.get("ArXiv", ""),
            pdf_url=(r.get("openAccessPdf") or {}).get("url", ""),
            abs_url=r.get("url", ""),
            source="semantic_scholar",
        ))
    return cards


def _fetch_openalex(req: DiscoverRequest) -> list[PaperCard]:
    from connectors.openalex.reader import OpenAlexConnector
    cfg = {
        "query": req.q,
        "max_results": req.limit_per_source,
        "include_abstract": True,
        "delay_seconds": 0,
    }
    connector = OpenAlexConnector(cfg)
    raw = connector.search_papers(req.q, req.limit_per_source)
    cards: list[PaperCard] = []
    for r in raw:
        year = r.get("publication_year")
        if isinstance(year, str):
            try:
                year = int(year)
            except ValueError:
                year = None
        if req.year_from and year and year < req.year_from:
            continue
        if req.year_to and year and year > req.year_to:
            continue
        authors = []
        for a in r.get("authorships", []):
            name = (a.get("author") or {}).get("display_name", "")
            if name:
                authors.append(name)
        ids = r.get("ids", {})
        doi = r.get("doi", "") or ""
        oa = r.get("open_access", {}) or {}
        pdf_url = oa.get("oa_url", "")
        if not pdf_url:
            loc = r.get("primary_location") or {}
            pdf_url = loc.get("pdf_url", "") or ""
        cards.append(PaperCard(
            paper_id=ids.get("openalex", r.get("id", "")).split("/")[-1],
            title=r.get("title", ""),
            authors=authors,
            abstract=OpenAlexConnector._reconstruct_abstract(r.get("abstract_inverted_index")),
            year=year,
            venue=(r.get("primary_location") or {}).get("source", {}).get("display_name", ""),
            citation_count=r.get("cited_by_count"),
            doi=doi,
            pdf_url=pdf_url,
            abs_url=doi or ids.get("openalex", ""),
            source="openalex",
        ))
    return cards


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_FETCH_MAP = {
    "arxiv": _fetch_arxiv,
    "semantic_scholar": _fetch_s2,
    "openalex": _fetch_openalex,
}


def discover_papers(req: DiscoverRequest, catalog: PaperCatalog) -> DiscoverResponse:
    """Fetch papers from multiple sources in parallel, merge, and mark already-indexed."""
    key = _cache_key(req)
    cached = _get_cached(key)
    if cached is not None:
        return _build_response(cached, req.sources, catalog)

    fetchers = [_FETCH_MAP[s] for s in req.sources if s in _FETCH_MAP]
    all_cards: list[PaperCard] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(f, req): f.__name__ for f in fetchers}
        for fut in concurrent.futures.as_completed(futures):
            try:
                all_cards.extend(fut.result())
            except Exception as e:
                log.warning("source fetch %s failed: %s", futures[fut], e)

    merged = merge_paper_cards(all_cards)
    _set_cached(key, merged)
    return _build_response(merged, req.sources, catalog)


def _build_response(
    cards: list[PaperCard],
    sources: list[str],
    catalog: PaperCatalog,
) -> DiscoverResponse:
    already = 0
    for c in cards:
        if catalog.is_indexed(c.paper_id):
            c.already_indexed = True
            already += 1
    return DiscoverResponse(
        papers=cards,
        total_found=len(cards),
        already_indexed=already,
        sources_queried=sources,
    )
