"""Generic website crawler connector for indexing web content into RAG."""
from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from connectors.base import BaseConnector, Document


BLOCK_TAGS = {
    "script", "style", "noscript", "svg", "canvas", "iframe", "footer",
    "header", "nav", "aside", "form", "button", "input", "select",
    "textarea", "dialog", "template",
}

CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".content",
    ".post-content",
    ".entry-content",
    ".article-body",
    ".markdown-body",
]

TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref",
}


class WebsiteCrawlerConnector(BaseConnector):
    name = "website"

    def __init__(self, config: dict):
        super().__init__(config)
        self.label = (config.get("label") or "").strip()
        self.start_urls = self._as_list(config.get("start_urls"))
        self.sitemap_urls = self._as_list(config.get("sitemap_urls"))
        self.same_domain_only = bool(config.get("same_domain_only", True))
        self.include_patterns = [p.lower() for p in self._as_list(config.get("include_patterns")) if p.strip()]
        self.exclude_patterns = [p.lower() for p in self._as_list(config.get("exclude_patterns")) if p.strip()]
        self.max_pages = int(config.get("max_pages", 150))
        self.max_depth = int(config.get("max_depth", 2))
        self.timeout = int(config.get("request_timeout_seconds", 15))
        self.delay_seconds = float(config.get("delay_seconds", 0.15))
        self.min_text_chars = int(config.get("min_text_chars", 250))
        self.max_page_size_kb = int(config.get("max_page_size_kb", 1024))
        self.respect_robots_txt = bool(config.get("respect_robots_txt", True))
        self.user_agent = (config.get("user_agent") or "KnowledgeHubBot/1.0 (+https://localhost)").strip()
        self.allowed_domains = self._build_allowed_domains()
        self._robots: dict[str, RobotFileParser | None] = {}
        # Live, pull-only source: fetched content is answered on demand and
        # never written to the persistent vector store.
        self.persist = False

    def _as_list(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return [str(value).strip()]

    def _build_allowed_domains(self) -> set[str]:
        domains = set()
        for url in self.start_urls:
            host = urlparse(url).netloc.lower()
            if host:
                domains.add(host)
        return domains

    def get_repo_name(self) -> str:
        if self.label:
            return self.label
        if self.start_urls:
            host = urlparse(self.start_urls[0]).netloc.lower()
            if host:
                return f"web:{host}"
        return "web:crawl"

    def doc_id_for_path(self, path: str, repo_name: str = "") -> str | None:
        if not path:
            return None
        digest = hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"website:{repo_name or self.get_repo_name()}:{digest}"

    def _normalize_url(self, url: str, base: str | None = None) -> str | None:
        if not url:
            return None
        url = url.strip()
        if url.startswith(("mailto:", "tel:", "javascript:", "data:")):
            return None
        merged = urljoin(base, url) if base else url
        parsed = urlparse(merged)
        if parsed.scheme not in {"http", "https"}:
            return None

        clean_query = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_QUERY_KEYS
        ]
        normalized = parsed._replace(query=urlencode(clean_query, doseq=True), fragment="")
        url_out = urlunparse(normalized)
        if url_out.endswith("/") and normalized.path not in {"", "/"}:
            url_out = url_out[:-1]
        return url_out

    def _domain_allowed(self, url: str) -> bool:
        if not self.same_domain_only or not self.allowed_domains:
            return True
        host = urlparse(url).netloc.lower()
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_domains)

    def _matches_filters(self, url: str) -> bool:
        lower = url.lower()
        if self.include_patterns and not any(p in lower for p in self.include_patterns):
            return False
        if self.exclude_patterns and any(p in lower for p in self.exclude_patterns):
            return False
        return True

    def _get_robot_parser(self, url: str) -> RobotFileParser | None:
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if base in self._robots:
            return self._robots[base]
        parser = RobotFileParser()
        parser.set_url(urljoin(base, "/robots.txt"))
        try:
            parser.read()
        except Exception:
            parser = None
        self._robots[base] = parser
        return parser

    def _can_fetch(self, url: str) -> bool:
        if not self.respect_robots_txt:
            return True
        parser = self._get_robot_parser(url)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _iter_sitemap_links(self, client: httpx.Client) -> list[str]:
        sitemap_candidates = list(self.sitemap_urls)
        if not sitemap_candidates:
            for start_url in self.start_urls:
                parsed = urlparse(start_url)
                if parsed.scheme and parsed.netloc:
                    sitemap_candidates.append(f"{parsed.scheme}://{parsed.netloc}/sitemap.xml")

        discovered: list[str] = []
        seen: set[str] = set()
        queue = deque(sitemap_candidates)

        while queue and len(discovered) < self.max_pages:
            sitemap_url = queue.popleft()
            if sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            try:
                resp = client.get(sitemap_url)
                resp.raise_for_status()
            except Exception:
                continue

            try:
                root = ET.fromstring(resp.text)
            except Exception:
                continue

            tag = root.tag.lower()
            if tag.endswith("urlset"):
                for loc in root.iter():
                    if loc.tag.lower().endswith("loc") and loc.text:
                        normalized = self._normalize_url(loc.text)
                        if normalized and self._domain_allowed(normalized) and self._matches_filters(normalized):
                            discovered.append(normalized)
                            if len(discovered) >= self.max_pages:
                                break
            elif tag.endswith("sitemapindex"):
                for loc in root.iter():
                    if loc.tag.lower().endswith("loc") and loc.text:
                        normalized = self._normalize_url(loc.text)
                        if normalized:
                            queue.append(normalized)

        return discovered

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if title:
            return title[:240]
        parsed = urlparse(url)
        return (parsed.path.strip("/") or parsed.netloc or url)[:240]

    def _extract_text(self, soup: BeautifulSoup) -> str:
        for tag in soup.find_all(BLOCK_TAGS):
            tag.decompose()

        root = None
        for selector in CONTENT_SELECTORS:
            root = soup.select_one(selector)
            if root:
                break
        if root is None:
            root = soup.body or soup

        parts: list[str] = []
        seen = set()
        for element in root.select("h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,code,td"):
            text = " ".join(element.get_text(" ", strip=True).split())
            if not text:
                continue
            if len(text) < 20 and not element.name.startswith("h"):
                continue
            if text in seen:
                continue
            seen.add(text)
            parts.append(text)

        if not parts:
            fallback = "\n".join(line.strip() for line in root.get_text("\n", strip=True).splitlines() if line.strip())
            return fallback
        return "\n".join(parts)

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links: list[str] = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            normalized = self._normalize_url(anchor.get("href"), base=base_url)
            if not normalized or normalized in seen:
                continue
            if not self._domain_allowed(normalized) or not self._matches_filters(normalized):
                continue
            seen.add(normalized)
            links.append(normalized)
        return links

    def _parse_updated_at(self, response: httpx.Response) -> datetime | None:
        value = response.headers.get("last-modified")
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            return None

    def load_documents(self) -> Iterator[Document]:
        if not self.start_urls:
            raise ValueError("Website crawler needs at least one start URL")

        headers = {"User-Agent": self.user_agent}
        repo_name = self.get_repo_name()
        visited = set()
        queued = set()
        queue = deque()

        with httpx.Client(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
            for url in self._iter_sitemap_links(client):
                queue.append((url, 0))
                queued.add(url)

            for url in self.start_urls:
                normalized = self._normalize_url(url)
                if normalized and normalized not in queued:
                    queue.append((normalized, 0))
                    queued.add(normalized)

            count = 0
            while queue and count < self.max_pages:
                url, depth = queue.popleft()
                if url in visited or depth > self.max_depth:
                    continue
                if not self._domain_allowed(url) or not self._matches_filters(url) or not self._can_fetch(url):
                    continue

                visited.add(url)
                try:
                    response = client.get(url)
                    response.raise_for_status()
                except Exception:
                    continue

                content_type = (response.headers.get("content-type") or "").lower()
                if "html" not in content_type and "xml" not in content_type and response.text.lstrip()[:1] != "<":
                    continue
                if len(response.content) > self.max_page_size_kb * 1024:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                title = self._extract_title(soup, url)
                text = self._extract_text(soup)
                if not text or len(text) < self.min_text_chars:
                    for next_url in self._extract_links(soup, url):
                        if next_url not in queued and next_url not in visited:
                            queue.append((next_url, depth + 1))
                            queued.add(next_url)
                    continue

                count += 1
                yield Document(
                    id=self.doc_id_for_path(url, repo_name) or f"website:{repo_name}:{count}",
                    content=text,
                    title=title,
                    source=self.name,
                    url=url,
                    updated_at=self._parse_updated_at(response),
                    metadata={
                        "path": url,
                        "depth": depth,
                        "domain": urlparse(url).netloc.lower(),
                        "mode": "website",
                    },
                )

                for next_url in self._extract_links(soup, url):
                    if next_url not in queued and next_url not in visited:
                        queue.append((next_url, depth + 1))
                        queued.add(next_url)

                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)
