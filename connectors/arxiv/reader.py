"""arXiv connector — indexes paper metadata, abstract, and PDF-extracted text."""
from __future__ import annotations

import io
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Iterator
from urllib.parse import parse_qs, quote, urlparse

import httpx

from connectors.base import BaseConnector, Document
from core.resilience import get_breaker, with_retry

ARXIV_API = "https://export.arxiv.org/api/query"
PDF_URL_RE = re.compile(r"/pdf/([0-9]{4}\.[0-9]{4,5})(?:\.pdf)?$")
ABS_URL_RE = re.compile(r"/abs/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?$")

USER_AGENT = "KnowledgeHubBot/1.0 (+https://localhost)"


class ArxivConnector(BaseConnector):
    name = "arxiv"

    def __init__(self, config: dict):
        super().__init__(config)
        self.query = (config.get("query") or "").strip()
        self.ids = self._normalize_inputs(config.get("ids"))
        self.urls = self._normalize_inputs(config.get("urls"))
        self.label = (config.get("label") or "arxiv-papers").strip() or "arxiv-papers"
        self.max_results = int(config.get("max_results", 50))
        self.include_pdf_text = bool(config.get("include_pdf_text", True))
        self.timeout = float(config.get("request_timeout_seconds", 20))
        self.min_text_chars = int(config.get("min_text_chars", 50))
        self.max_pdf_bytes = int(config.get("max_pdf_size_mb", 25)) * 1024 * 1024
        # arXiv asks clients to space requests ~3s apart under load.
        self.delay_seconds = float(config.get("delay_seconds", 3.0))

    def get_repo_name(self) -> str:
        return self.label

    def _normalize_inputs(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return [str(v).strip() for v in value if str(v).strip()]

    def _extract_id(self, raw: str) -> str | None:
        text = (raw or "").strip()
        if not text:
            return None
        if re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}(?:v\d+)?", text):
            return text.split("v", 1)[0]
        parsed = urlparse(text)
        if parsed.netloc.endswith("arxiv.org"):
            for pattern in (ABS_URL_RE, PDF_URL_RE):
                match = pattern.search(parsed.path)
                if match:
                    return match.group(1)
            query_id = parse_qs(parsed.query).get("id_list")
            if query_id:
                return query_id[0].split(",", 1)[0].strip()
        return None

    def _paper_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for raw in [*self.ids, *self.urls]:
            pid = self._extract_id(raw)
            if pid and pid not in seen:
                ids.append(pid)
                seen.add(pid)
        return ids

    def _fetch_feed(self, params: dict) -> str:
        breaker = get_breaker("arxiv")
        def _do_fetch():
            resp = httpx.get(ARXIV_API, params=params, timeout=self.timeout,
                             headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text
        return breaker.call(_do_fetch)

    def search_papers(self, query: str, limit: int = 30) -> list[dict]:
        """Thin wrapper returning raw dicts for the research discover pipeline."""
        self.query = query
        self.max_results = limit
        return self._search()

    def _search(self) -> list[dict]:
        out: list[dict] = []
        start = 0
        limit = min(100, max(1, self.max_results))
        while len(out) < self.max_results:
            params = {
                "search_query": f"all:{self.query}",
                "start": start,
                "max_results": limit,
            }
            feed = self._fetch_feed(params)
            papers = self._parse_feed(feed)
            if not papers:
                break
            out.extend(papers)
            if len(papers) < limit:
                break
            start += limit
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
        return out[: self.max_results]

    def _parse_feed(self, xml_text: str) -> list[dict]:
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        root = ET.fromstring(xml_text)
        items: list[dict] = []
        for entry in root.findall("atom:entry", ns):
            paper_id_url = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
            pid = self._extract_id(paper_id_url) or ""
            title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
            summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
            published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
            updated = (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip()
            primary_category = ""
            cat = entry.find("arxiv:primary_category", ns)
            if cat is not None:
                primary_category = cat.attrib.get("term", "")
            categories = [c.attrib.get("term", "") for c in entry.findall("atom:category", ns) if c.attrib.get("term")]
            authors = [
                (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
                for author in entry.findall("atom:author", ns)
            ]
            comment = (entry.findtext("arxiv:comment", default="", namespaces=ns) or "").strip()
            journal_ref = (entry.findtext("arxiv:journal_ref", default="", namespaces=ns) or "").strip()
            doi = (entry.findtext("arxiv:doi", default="", namespaces=ns) or "").strip()
            pdf_url = f"https://arxiv.org/pdf/{pid}.pdf" if pid else ""
            abs_url = f"https://arxiv.org/abs/{pid}" if pid else paper_id_url
            for link in entry.findall("atom:link", ns):
                href = link.attrib.get("href", "")
                if link.attrib.get("title") == "pdf" and href:
                    pdf_url = href
            items.append({
                "id": pid,
                "title": title,
                "summary": summary,
                "published": published,
                "updated": updated,
                "primary_category": primary_category,
                "categories": categories,
                "authors": authors,
                "comment": comment,
                "journal_ref": journal_ref,
                "doi": doi,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            })
        return items

    def _parse_iso(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def _read_pdf_text(self, pdf_url: str) -> str:
        if not pdf_url:
            return ""
        try:
            resp = httpx.get(pdf_url, timeout=self.timeout, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.content
            if len(data) > self.max_pdf_bytes:
                return ""
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except Exception:
            return ""

    def load_documents(self) -> Iterator[Document]:
        if self.query:
            papers = self._search()
        else:
            paper_ids = self._paper_ids()
            if not paper_ids:
                raise ValueError("Provide an arXiv query, or at least one ID/URL")
            params = {"id_list": ",".join(paper_ids), "max_results": len(paper_ids)}
            feed = self._fetch_feed(params)
            papers = self._parse_feed(feed)

        if not papers:
            raise ValueError("No arXiv papers found for the provided inputs")

        for idx, paper in enumerate(papers):
            if idx > 0 and self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

            abstract = (paper.get("summary") or "").strip()
            pdf_text = self._read_pdf_text(paper.get("pdf_url", "")) if self.include_pdf_text else ""
            sections = []
            if paper.get("title"):
                sections.append(f"Title: {paper['title']}")
            if paper.get("authors"):
                sections.append(f"Authors: {', '.join(paper['authors'])}")
            if paper.get("primary_category"):
                sections.append(f"Primary category: {paper['primary_category']}")
            if paper.get("categories"):
                sections.append(f"Categories: {', '.join(paper['categories'])}")
            if paper.get("comment"):
                sections.append(f"Comment: {paper['comment']}")
            if paper.get("journal_ref"):
                sections.append(f"Journal reference: {paper['journal_ref']}")
            if paper.get("doi"):
                sections.append(f"DOI: {paper['doi']}")
            if abstract:
                sections.append(f"Abstract:\n{abstract}")
            if pdf_text:
                sections.append(f"Full text:\n{pdf_text}")
            content = "\n\n".join(section for section in sections if section).strip()
            if len(content) < self.min_text_chars:
                continue

            pid = paper.get("id") or quote((paper.get('title') or 'paper')[:80])
            yield Document(
                id=f"arxiv:{pid}",
                content=content,
                title=paper.get("title") or pid,
                source=self.name,
                url=paper.get("abs_url") or paper.get("pdf_url") or "",
                author=", ".join(paper.get("authors") or []),
                created_at=self._parse_iso(paper.get("published", "")),
                updated_at=self._parse_iso(paper.get("updated", "")),
                metadata={
                    "path": pid,
                    "paper_id": pid,
                    "abstract": abstract,
                    "pdf_url": paper.get("pdf_url", ""),
                    "abs_url": paper.get("abs_url", ""),
                    "primary_category": paper.get("primary_category", ""),
                    "categories": paper.get("categories", []),
                    "comment": paper.get("comment", ""),
                    "journal_ref": paper.get("journal_ref", ""),
                    "doi": paper.get("doi", ""),
                    "authors": paper.get("authors", []),
                    "mode": "arxiv",
                },
            )
