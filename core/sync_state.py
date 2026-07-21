"""Incremental sync state tracker — remembers what was last indexed."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.config import resolve_data_path


class SyncState:
    def __init__(self, path: str = "./data/sync_state.json"):
        self.path = resolve_data_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2, default=str),
                             encoding="utf-8")

    def get_last_indexed(self, repo: str, connector: str) -> str | None:
        key = f"{repo}::{connector}"
        return self._state.get(key, {}).get("last_indexed")

    def set_last_indexed(self, repo: str, connector: str,
                         timestamp: datetime | None = None) -> None:
        key = f"{repo}::{connector}"
        ts = (timestamp or datetime.now()).isoformat()
        if key not in self._state:
            self._state[key] = {}
        self._state[key]["last_indexed"] = ts
        self._state[key]["last_sync"] = datetime.now().isoformat()
        self.save()

    def get_file_state(self, repo: str) -> dict[str, str]:
        key = f"{repo}::files"
        return self._state.get(key, {}).get("files", {})

    def set_file_state(self, repo: str, files: dict[str, str]) -> None:
        key = f"{repo}::files"
        if key not in self._state:
            self._state[key] = {}
        self._state[key]["files"] = files
        self._state[key]["last_sync"] = datetime.now().isoformat()
        self.save()

    def get_commit_state(self, repo: str) -> str | None:
        key = f"{repo}::github_commits"
        return self._state.get(key, {}).get("last_commit_sha")

    def set_commit_state(self, repo: str, sha: str) -> None:
        key = f"{repo}::github_commits"
        if key not in self._state:
            self._state[key] = {}
        self._state[key]["last_commit_sha"] = sha
        self._state[key]["last_sync"] = datetime.now().isoformat()
        self.save()

    def get_all_repos(self) -> list[str]:
        repos = set()
        for key in self._state:
            repo = key.split("::")[0]
            if repo:
                repos.add(repo)
        return sorted(repos)

    def clear_repo(self, repo: str) -> None:
        keys_to_remove = [k for k in self._state if k.startswith(f"{repo}::")]
        for key in keys_to_remove:
            del self._state[key]
        self.save()

    def clear_all(self) -> None:
        self._state = {}
        self.save()
