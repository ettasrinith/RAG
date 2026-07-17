"""GitHub files connector — indexes either a local folder or a GitHub repo via token."""
from __future__ import annotations

import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from github import Auth, Github

from connectors.base import BaseConnector, Document
from connectors.github.importance import (
    git_change_counts,
    importance_score,
)
from core.sync_state import SyncState


TEXT_EXTENSIONS = {
    ".md", ".rst", ".txt", ".adoc",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".scala",
    ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".sh", ".bash", ".bat", ".ps1", ".zsh",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".sql", ".graphql", ".proto",
    ".html", ".css", ".scss",
    ".json", ".xml",
}


class GitHubFilesConnector(BaseConnector):
    name = "github_files"

    def __init__(self, config: dict):
        super().__init__(config)
        self.mode = (config.get("mode") or "").strip().lower()
        self.local_path = Path(config.get("local_path") or "")
        self.repo = (config.get("repo") or "").strip()
        self.pat = (config.get("pat") or "").strip()
        self.branch = (config.get("branch") or "").strip()
        self.skip_extensions = set(config.get("skip_extensions", []))
        self.skip_dirs = set(config.get("skip_dirs", []))
        self.max_size_bytes = int(config.get("max_file_size_kb", 500)) * 1024
        self.threshold = float(config.get("importance_threshold", 25))
        self.max_api_files = int(config.get("max_api_files", 3000))

    def _repo_label(self) -> str:
        if self.repo:
            return self.repo
        if str(self.local_path):
            return self.local_path.name
        return ""

    def _effective_mode(self) -> str:
        if self.mode in {"local", "github"}:
            return self.mode
        if self.repo and self.pat and not self.local_path.exists():
            return "github"
        return "local"

    def _should_skip_dir(self, dir_name: str) -> bool:
        return dir_name in self.skip_dirs or dir_name.startswith(".")

    def _should_consider(self, path: Path) -> bool:
        if path.name.startswith("."):
            return False
        ext = path.suffix.lower()
        if ext in self.skip_extensions:
            return False
        if ext and ext not in TEXT_EXTENSIONS:
            return False
        try:
            if path.stat().st_size > self.max_size_bytes:
                return False
        except OSError:
            return False
        return True

    def _should_consider_remote(self, rel_path: str, size: int | None = None) -> bool:
        path = Path(rel_path)
        if path.name.startswith("."):
            return False
        if any(self._should_skip_dir(part) for part in path.parts[:-1]):
            return False
        ext = path.suffix.lower()
        if ext in self.skip_extensions:
            return False
        if ext and ext not in TEXT_EXTENSIONS:
            return False
        if size is not None and size > self.max_size_bytes:
            return False
        return True

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="latin-1")
            except Exception:
                return None
        except OSError:
            return None

    def _decode_blob(self, blob) -> str | None:
        try:
            if getattr(blob, "encoding", "") == "base64":
                raw = base64.b64decode(blob.content)
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw.decode("latin-1")
            content = blob.content or ""
            if isinstance(content, bytes):
                try:
                    return content.decode("utf-8")
                except UnicodeDecodeError:
                    return content.decode("latin-1")
            return str(content)
        except Exception:
            return None

    def get_changed_files(self, repo_path: str, sync_state: SyncState, repo_name: str) -> set[str] | None:
        if self._effective_mode() != "local":
            return None

        local_path = Path(repo_path)
        if not local_path.exists():
            return None

        file_state = sync_state.get_file_state(repo_name)
        current_files: dict[str, str] = {}

        for root, dirs, files in os.walk(local_path):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]
            for fname in files:
                fpath = Path(root) / fname
                if not self._should_consider(fpath):
                    continue
                rel = str(fpath.relative_to(local_path)).replace("\\", "/")
                try:
                    mtime = datetime.fromtimestamp(fpath.stat().st_mtime).isoformat()
                    current_files[rel] = mtime
                except OSError:
                    continue

        changed = set()
        for rel, mtime in current_files.items():
            if rel not in file_state or file_state[rel] != mtime:
                changed.add(rel)

        for rel in file_state:
            if rel not in current_files:
                changed.add(rel)

        return changed if file_state else None

    def _load_local_documents(self) -> Iterator[Document]:
        if not self.local_path.exists():
            raise FileNotFoundError(f"local_path does not exist: {self.local_path}")

        repo_label = self._repo_label()
        change_counts = git_change_counts(str(self.local_path))

        for root, dirs, files in os.walk(self.local_path):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

            root_path = Path(root)
            for fname in files:
                fpath = root_path / fname
                if not self._should_consider(fpath):
                    continue

                rel_path = str(fpath.relative_to(self.local_path)).replace("\\", "/")
                score = importance_score(rel_path, change_counts.get(rel_path, 0))
                if score < self.threshold:
                    continue

                content = self._read_text(fpath)
                if not content or not content.strip():
                    continue

                try:
                    mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
                except OSError:
                    mtime = None

                url = (
                    f"https://github.com/{self.repo}/blob/{self.branch or 'main'}/{rel_path}"
                    if self.repo else ""
                )

                yield Document(
                    id=f"github_file:{repo_label}:{rel_path}",
                    content=content,
                    title=rel_path,
                    source=self.name,
                    url=url,
                    updated_at=mtime,
                    metadata={
                        "path": rel_path,
                        "ext": fpath.suffix.lower(),
                        "importance": round(score, 1),
                        "git_changes": change_counts.get(rel_path, 0),
                        "mode": "local",
                    },
                )

    def _load_remote_documents(self) -> Iterator[Document]:
        if not self.pat:
            raise ValueError("GitHub token is required to index a repo via GitHub API")
        if not self.repo:
            raise ValueError("GitHub repo is required in owner/repo format")

        client = Github(auth=Auth.Token(self.pat))
        repo = client.get_repo(self.repo)
        branch = self.branch or repo.default_branch
        tree = repo.get_git_tree(branch, recursive=True).tree
        pushed_at = getattr(repo, "pushed_at", None)
        indexed = 0

        for item in tree:
            if indexed >= self.max_api_files:
                break
            if getattr(item, "type", "") != "blob":
                continue
            rel_path = item.path
            if not self._should_consider_remote(rel_path, getattr(item, "size", None)):
                continue

            score = importance_score(rel_path, 0)
            if score < self.threshold:
                continue

            blob = repo.get_git_blob(item.sha)
            content = self._decode_blob(blob)
            if not content or not content.strip():
                continue

            indexed += 1
            yield Document(
                id=f"github_file:{self.repo}:{rel_path}",
                content=content,
                title=rel_path,
                source=self.name,
                url=f"https://github.com/{self.repo}/blob/{branch}/{rel_path}",
                updated_at=pushed_at,
                metadata={
                    "path": rel_path,
                    "ext": Path(rel_path).suffix.lower(),
                    "importance": round(score, 1),
                    "git_changes": 0,
                    "branch": branch,
                    "mode": "github",
                },
            )

    def load_documents(self) -> Iterator[Document]:
        if self._effective_mode() == "github":
            yield from self._load_remote_documents()
            return
        yield from self._load_local_documents()
