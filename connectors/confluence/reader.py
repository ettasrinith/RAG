"""Confluence connector — indexes pages from an Atlassian Confluence instance.

Authenticates with an email + API token (Confluence Cloud) or a personal
access token (Confluence Server/Data Center). Pages are fetched via CQL search
or by space, and their storage-format body is converted to plain text for
indexing. Use this for internal company / team knowledge wikis.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from connectors.base import BaseConnector, Document


class ConfluenceConnector(BaseConnector):
    name = "confluence"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = (config.get("base_url") or "").strip().rstrip("/")
        self.email = (config.get("email") or "").strip()
        self.api_token = (config.get("api_token") or "").strip()
        self.pat = (config.get("pat") or "").strip()
        self.query = (config.get("query") or "").strip()
        self.spaces = self._normalize_inputs(config.get("spaces"))
        self.label = (config.get("label") or "confluence").strip() or "confluence"
        self.limit = int(config.get("max_results", 200))
        self.timeout = float(config.get("request_timeout_seconds", 20))
        self.min_text_chars = int(config.get("min_text_chars", 50))
        self.include_body = bool(config.get("include_body", True))

    def get_repo_name(self) -> str:
        return self.label

    def _normalize_inputs(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.replace(",", "\n").splitlines() if v.strip()]
        return [str(v).strip() for v in value if str(v).strip()]

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.pat:
            headers["Authorization"] = f"Bearer {self.pat}"
        elif self.email and self.api_token:
            raw = f"{self.email}:{self.api_token}".encode()
            token = base64.b64encode(raw).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _cql(self) -> str:
        clauses: list[str] = []
        if self.query:
            clauses.append(f'(text ~ "{self.query}" OR title ~ "{self.query}")')
        if self.spaces:
            space_clause = " OR ".join(f'space = "{s}"' for s in self.spaces)
            clauses.append(f"({space_clause})")
        if not clauses:
            clauses.append("type = page")
        return " AND ".join(clauses)

    def _fetch_pages(self) -> list[dict]:
        if not self.base_url:
            raise ValueError("Confluence base_url is required")
        out: list[dict] = []
        start = 0
        limit = min(25, max(1, self.limit))
        while len(out) < self.limit:
            resp = httpx.get(
                urljoin(f"{self.base_url}/", "rest/api/content/search"),
                params={"cql": self._cql(), "limit": limit, "start": start,
                        "expand": "body.storage,version"},
                timeout=self.timeout,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            out.extend(results)
            if len(results) < limit:
                break
            start += limit
        return out[: self.limit]

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines).strip()

    @staticmethod
    def _parse_iso(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def load_documents(self) -> Iterator[Document]:
        pages = self._fetch_pages()
        if not pages:
            raise ValueError("No Confluence pages found for the provided query/spaces")

        for page in pages:
            title = (page.get("title") or "").strip()
            page_id = str(page.get("id", ""))
            space = (page.get("space", {}) or {}).get("key", "")
            links = page.get("_links", {}) or {}
            webui = links.get("webui", "")
            url = urljoin(f"{self.base_url}/", webui.lstrip("/")) if webui else f"{self.base_url}/pages/viewpage.action?pageId={page_id}"
            version = page.get("version", {}) or {}
            updated = self._parse_iso(version.get("when", ""))
            body_html = ""
            if self.include_body:
                body_html = (page.get("body", {}) or {}).get("storage", {}).get("value", "")
            text = self._html_to_text(body_html) if self.include_body else ""

            sections = []
            if title:
                sections.append(f"Title: {title}")
            if space:
                sections.append(f"Space: {space}")
            if text:
                sections.append(text)
            content = "\n\n".join(sections).strip()
            if len(content) < self.min_text_chars:
                continue

            path = f"{space}/{page_id}" if space else page_id
            yield Document(
                id=f"confluence:{page_id}",
                content=content,
                title=title or page_id,
                source=self.name,
                url=url,
                author=(version.get("by", {}) or {}).get("displayName", ""),
                created_at=None,
                updated_at=updated or datetime.now(timezone.utc),
                metadata={
                    "path": path,
                    "page_id": page_id,
                    "space": space,
                    "version": version.get("number", ""),
                    "webui": webui,
                    "mode": "confluence",
                },
            )
