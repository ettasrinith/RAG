"""Base connector interface — every source plugs in by implementing this."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass
class Document:
    id: str
    content: str
    title: str
    source: str
    url: str = ""
    author: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


class BaseConnector:
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        # Whether documents from this connector should be persisted to the
        # vector store during indexing. Pull-only sources (e.g. live web) set
        # this to False and are consumed on demand instead.
        self.persist: bool = True

    def load_documents(self) -> Iterator[Document]:
        raise NotImplementedError

    def is_enabled(self) -> bool:
        return self.config.get("enabled", False)

    def get_repo_name(self) -> str:
        label = self.config.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
        return ""

    def get_changed_files(self, repo_path: str, sync_state=None, repo_name: str = "") -> set[str] | None:
        """Return set of changed file paths, or None for full index.

        Override in connectors that support incremental sync.
        """
        return None
