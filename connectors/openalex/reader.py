"""OpenAlex connector — indexes 250M+ scholarly works via the OpenAlex API.

Requires a free API key (https://openalex.org/settings/api) as of Feb 2026.
Supports a keyword query and/or a list of DOIs/OpenAlex IDs. Abstracts are
reconstructed from OpenAlex's inverted index format when present.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator
from urllib.parse import quote

import httpx

from connectors.base import BaseConnector, Document
from core.resilience import get_breaker

OPENALEX_API = "https://api.openalex.org/works"
USER_AGENT = "KnowledgeHubBot/1.0 (+https://localhost)"


class OpenAlexConnector(BaseConnector):
    name = "openalex"

    def __init__(self, config: dict):
        super().__init__(config)
        self.query = (config.get("query") or "").strip()
        self.ids = self._normalize_inputs(config.get("ids"))
        self.label = (config.get("label") or "openalex-papers").strip() or "openalex-papers"
        self.api_key = (config.get("api_key") or "").strip()
        self.max_results = int(config.get("max_results", 50))
        self.include_abstract = bool(config.get("include_abstract", True))
        self.timeout = float(config.get("request_timeout_seconds", 20))
        self.min_text_chars = int(config.get("min_text_chars", 50))
        self.delay_seconds = float(config.get("delay_seconds", 0.1))

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
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict | None) -> str:
        if not inverted_index:
            return ""
        positions: list[tuple[int, str]] = []
        for word, idxs in inverted_index.items():
            for i in idxs:
                positions.append((i, word))
        positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in positions).strip()

    def search_papers(self, query: str, limit: int = 30) -> list[dict]:
        """Thin wrapper returning raw dicts for the research discover pipeline."""
        self.query = query
        self.max_results = limit
        params = {"search": self.query, "sort": "relevance_score:desc"}
        return self._fetch(params)

    def _fetch(self, params: dict) -> list[dict]:
        out: list[dict] = []
        page = 1
        per_page = min(200, max(1, self.max_results))
        breaker = get_breaker("openalex")
        while len(out) < self.max_results:
            params.update({"per-page": per_page, "page": page})
            def _do_fetch(p=params.copy()):
                resp = httpx.get(OPENALEX_API, params=p, timeout=self.timeout,
                                 headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            data = breaker.call(_do_fetch)
            results = data.get("results", [])
            if not results:
                break
            out.extend(results)
            if len(results) < per_page:
                break
            page += 1
            if self.delay_seconds > 0:
                import time
                time.sleep(self.delay_seconds)
        return out[: self.max_results]

    def _resolve_works(self) -> list[dict]:
        if self.ids:
            # Accept bare IDs (W123) or full URLs; OpenAlex accepts both.
            cleaned = [i.split("/")[-1] if "/" in i else i for i in self.ids]
            params = {"filter": f"openalex_id:{'|'.join(cleaned)}"}
            return self._fetch(params)
        if self.query:
            params = {"search": self.query, "sort": "relevance_score:desc"}
            return self._fetch(params)
        return []

    @staticmethod
    def _parse_iso(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def load_documents(self) -> Iterator[Document]:
        works = self._resolve_works()
        if not works:
            raise ValueError("Provide an OpenAlex query or at least one ID/DOI")

        for work in works:
            title = (work.get("title") or "").strip()
            display_name = work.get("display_name") or ""
            raw_abstract = work.get("abstract_inverted_index")
            abstract = self._reconstruct_abstract(raw_abstract) if self.include_abstract else ""
            doi = work.get("doi", "") or ""
            ids = work.get("ids", {})
            openalex_id = (ids.get("openalex") or work.get("id") or "").split("/")[-1]
            authors = [
                (a.get("author", {}).get("display_name") or "")
                for a in work.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]
            pub_year = (work.get("publication_year") or "")
            venue = ""
            host = work.get("primary_location", {}).get("source", {})
            if isinstance(host, dict):
                venue = host.get("display_name", "") or ""
            citation_count = int(work.get("cited_by_count", 0) or 0)
            pdf_url = ""
            loc = work.get("primary_location", {})
            if isinstance(loc, dict):
                pdf_url = loc.get("pdf_url", "") or ""
            if not pdf_url and work.get("open_access", {}).get("oa_url"):
                pdf_url = work["open_access"]["oa_url"]

            landing = doi or (ids.get("openalex") or work.get("id", ""))

            sections = []
            if title or display_name:
                sections.append(f"Title: {title or display_name}")
            if authors:
                sections.append(f"Authors: {', '.join(authors)}")
            if venue:
                sections.append(f"Venue: {venue}")
            if pub_year:
                sections.append(f"Year: {pub_year}")
            if citation_count:
                sections.append(f"Citations: {citation_count}")
            if doi:
                sections.append(f"DOI: {doi}")
            if abstract:
                sections.append(f"Abstract:\n{abstract}")
            content = "\n\n".join(section for section in sections if section).strip()
            if len(content) < self.min_text_chars:
                continue

            wid = openalex_id or quote((title or display_name or "work")[:80])
            yield Document(
                id=f"openalex:{wid}",
                content=content,
                title=title or display_name or wid,
                source=self.name,
                url=landing,
                author=", ".join(authors),
                created_at=self._parse_iso(work.get("publication_date", "")),
                updated_at=self._parse_iso(work.get("publication_date", "")),
                metadata={
                    "path": wid,
                    "work_id": wid,
                    "abstract": abstract,
                    "doi": doi,
                    "venue": venue,
                    "publication_year": pub_year,
                    "cited_by_count": citation_count,
                    "pdf_url": pdf_url,
                    "authors": authors,
                    "mode": "openalex",
                },
            )
