"""Semantic Scholar connector — indexes 200M+ papers via the S2 Graph API.

Free, no API key required (unauthenticated is rate-limited to ~1 req/s; set an
optional S2_API_KEY to raise the limit). Returns metadata, abstract, a
generated TLDR, and citation counts. Best open substitute for broad
"Google Scholar-like" academic search across all fields.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Iterator
from urllib.parse import quote

import httpx

from connectors.base import BaseConnector, Document

S2_API = "https://api.semanticscholar.org/graph/v1"
USER_AGENT = "KnowledgeHubBot/1.0 (+https://localhost)"

FIELDS = "title,abstract,authors,year,venue,doi,url,externalIds,citationCount,tldr,publicationDate,openAccessPdf"


class SemanticScholarConnector(BaseConnector):
    name = "semantic_scholar"

    def __init__(self, config: dict):
        super().__init__(config)
        self.query = (config.get("query") or "").strip()
        self.ids = self._normalize_inputs(config.get("ids"))
        self.label = (config.get("label") or "semantic-scholar").strip() or "semantic-scholar"
        self.api_key = (config.get("api_key") or "").strip()
        self.max_results = int(config.get("max_results", 50))
        self.include_abstract = bool(config.get("include_abstract", True))
        self.timeout = float(config.get("request_timeout_seconds", 20))
        self.min_text_chars = int(config.get("min_text_chars", 50))
        # Unauthenticated S2 allows ~1 req/s; stay conservative.
        self.delay_seconds = float(config.get("delay_seconds", 1.0))

    def get_repo_name(self) -> str:
        return self.label

    def _normalize_inputs(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.replace(",", "\n").splitlines() if v.strip()]
        return [str(v).strip() for v in value if str(v).strip()]

    def _headers(self) -> dict:
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def search_papers(self, query: str, limit: int = 30) -> list[dict]:
        """Thin wrapper returning raw dicts for the research discover pipeline."""
        self.query = query
        self.max_results = limit
        return self._search()

    def _search(self) -> list[dict]:
        out: list[dict] = []
        offset = 0
        limit = min(100, max(1, self.max_results))
        while len(out) < self.max_results:
            resp = httpx.get(
                f"{S2_API}/paper/search",
                params={"query": self.query, "fields": FIELDS,
                        "limit": limit, "offset": offset},
                timeout=self.timeout,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", [])
            if not results:
                break
            out.extend(results)
            if len(results) < limit or not data.get("next"):
                break
            offset += limit
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
        return out[: self.max_results]

    def _fetch_by_ids(self) -> list[dict]:
        # S2 batch endpoint: up to 500 IDs per request.
        out: list[dict] = []
        for start in range(0, len(self.ids), 500):
            batch = self.ids[start:start + 500]
            if start > 0 and self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
            resp = httpx.post(
                f"{S2_API}/paper/batch",
                params={"fields": FIELDS},
                json={"ids": batch},
                timeout=self.timeout,
                headers=self._headers(),
            )
            resp.raise_for_status()
            out.extend([p for p in resp.json() if p])
        return out

    @staticmethod
    def _parse_year(value) -> datetime | None:
        if not value:
            return None
        try:
            return datetime(int(value), 1, 1)
        except Exception:
            return None

    def load_documents(self) -> Iterator[Document]:
        if self.ids:
            papers = self._fetch_by_ids()
        elif self.query:
            papers = self._search()
        else:
            raise ValueError("Provide a Semantic Scholar query or at least one ID/DOI")

        if not papers:
            raise ValueError("No Semantic Scholar papers found for the provided inputs")

        for paper in papers:
            title = (paper.get("title") or "").strip()
            abstract = (paper.get("abstract") or "").strip() if self.include_abstract else ""
            tldr = (paper.get("tldr") or {})
            if isinstance(tldr, dict):
                tldr = (tldr.get("text") or "").strip()
            else:
                tldr = ""
            authors = [
                (a.get("name") or "").strip()
                for a in paper.get("authors", []) if a.get("name")
            ]
            doi = paper.get("doi", "") or ""
            external = paper.get("externalIds", {}) or {}
            arxiv_id = external.get("ArXiv") or ""
            venue = (paper.get("venue") or "").strip()
            year = paper.get("year")
            citations = int(paper.get("citationCount", 0) or 0)
            pdf_url = ""
            oa = paper.get("openAccessPdf")
            if isinstance(oa, dict):
                pdf_url = oa.get("url", "") or ""
            url = paper.get("url") or (f"https://doi.org/{doi}" if doi else "")

            sections = []
            if title:
                sections.append(f"Title: {title}")
            if authors:
                sections.append(f"Authors: {', '.join(authors)}")
            if venue:
                sections.append(f"Venue: {venue}")
            if year:
                sections.append(f"Year: {year}")
            if citations:
                sections.append(f"Citations: {citations}")
            if arxiv_id:
                sections.append(f"arXiv ID: {arxiv_id}")
            if doi:
                sections.append(f"DOI: {doi}")
            if tldr:
                sections.append(f"TLDR: {tldr}")
            if abstract:
                sections.append(f"Abstract:\n{abstract}")
            content = "\n\n".join(section for section in sections if section).strip()
            if len(content) < self.min_text_chars:
                continue

            pid = (external.get("CorpusId") or doi or arxiv_id or
                   quote((title or "paper")[:80]))
            yield Document(
                id=f"semantic_scholar:{pid}",
                content=content,
                title=title or pid,
                source=self.name,
                url=url,
                author=", ".join(authors),
                created_at=self._parse_year(year),
                updated_at=self._parse_year(year),
                metadata={
                    "path": str(pid),
                    "paper_id": str(pid),
                    "abstract": abstract,
                    "tldr": tldr,
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "venue": venue,
                    "year": year,
                    "citation_count": citations,
                    "pdf_url": pdf_url,
                    "authors": authors,
                    "mode": "semantic_scholar",
                },
            )
