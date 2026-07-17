"""GitHub commits connector — fetches commit metadata plus changed-file lists."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterator

import httpx

from connectors.base import BaseConnector, Document


class GitHubCommitsConnector(BaseConnector):
    name = "github_commits"

    def __init__(self, config: dict):
        super().__init__(config)
        self.pat = (config.get("pat") or os.environ.get("GITHUB_PAT", "")).strip()
        self.repo = (config.get("repo") or os.environ.get("GITHUB_REPO", "")).strip()
        if not self.pat:
            raise ValueError("GitHub PAT required (set GITHUB_PAT or connectors.github_commits.pat)")
        if not self.repo:
            raise ValueError("GitHub repo required (set GITHUB_REPO or connectors.github_commits.repo)")
        self.skip_merges = config.get("skip_merge_commits", True)
        self.skip_authors = set(config.get("skip_authors", []))
        self.max_commits = int(config.get("max_commits", 5000))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _iter_commits(self) -> Iterator[dict]:
        owner_repo = self.repo.strip().lstrip("/")
        url = f"https://api.github.com/repos/{owner_repo}/commits"
        params = {"per_page": 100, "page": 1}
        seen = 0
        while seen < self.max_commits:
            resp = httpx.get(url, headers=self._headers(), params=params, timeout=30.0)
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            for c in batch:
                if seen >= self.max_commits:
                    return
                seen += 1
                yield c
            if len(batch) < 100:
                break
            params["page"] += 1

    def _get_commit_details(self, sha: str) -> dict:
        owner_repo = self.repo.strip().lstrip("/")
        url = f"https://api.github.com/repos/{owner_repo}/commits/{sha}"
        resp = httpx.get(url, headers=self._headers(), timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def load_documents(self) -> Iterator[Document]:
        for c in self._iter_commits():
            sha = c.get("sha", "")
            details = self._get_commit_details(sha) if sha else c
            raw = details.get("commit", {}) or c.get("commit", {})
            message = raw.get("message", "") or ""
            if self.skip_merges and message.startswith("Merge "):
                continue

            author = raw.get("author") or {}
            author_name = author.get("name", "") or ""
            author_email = author.get("email", "") or ""
            if author_name in self.skip_authors:
                continue

            files_changed = [f.get("filename") for f in (details.get("files") or []) if f.get("filename")]
            files_changed = files_changed[:30]

            parts = [message]
            if files_changed:
                parts.append("\nFiles changed:\n" + "\n".join(files_changed))
            content = "\n".join(parts).strip()
            if not content:
                continue

            sha_short = sha[:7]
            title_line = message.split("\n", 1)[0][:120]

            created = None
            date_str = author.get("date")
            if date_str:
                try:
                    created = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except Exception:
                    created = None

            yield Document(
                id=f"github_commit:{self.repo}:{sha}",
                content=content,
                title=f"{sha_short} — {title_line}",
                source=self.name,
                url=details.get("html_url", c.get("html_url", "")),
                author=f"{author_name} <{author_email}>".strip(),
                created_at=created,
                metadata={"sha": sha, "files_count": len(files_changed)},
            )
