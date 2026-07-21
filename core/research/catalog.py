"""JSON-file paper ID registry for dedup tracking."""
from __future__ import annotations

import json
import threading
from pathlib import Path


class PaperCatalog:
    """Thread-safe JSON-file registry of indexed paper IDs."""

    def __init__(self, path: str = "./data/research_catalog.json"):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # -- public API --------------------------------------------------------

    def is_indexed(self, paper_id: str) -> bool:
        with self._lock:
            return paper_id in self._data

    def mark_indexed(self, paper_id: str, meta: dict | None = None) -> None:
        with self._lock:
            self._data[paper_id] = meta or {}
            self._save()

    def unmark(self, paper_id: str) -> None:
        with self._lock:
            self._data.pop(paper_id, None)
            self._save()

    def all_ids(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def list_collections(self) -> list[str]:
        """Return unique collection values across all entries."""
        with self._lock:
            return sorted({v.get("collection", "default") for v in self._data.values()})

    def ids_by_collection(self, collection: str) -> list[str]:
        with self._lock:
            return [pid for pid, meta in self._data.items()
                    if meta.get("collection", "default") == collection]
