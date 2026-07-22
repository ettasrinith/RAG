"""Hierarchy indexer — tracks folder structure for filtering."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.config import resolve_data_path
from core.logging import get_logger

log = get_logger("hierarchy")


@dataclass
class HierarchyNode:
    id: str
    repo: str
    path: str
    name: str
    parent_id: str | None = None
    depth: int = 0
    doc_count: int = 0
    children: list[str] = field(default_factory=list)


class HierarchyIndex:
    def __init__(self, repo: str, max_depth: int = 10, storage_path: str = "./data/hierarchy"):
        self.repo = repo
        self.max_depth = max_depth
        self.storage_path = resolve_data_path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.nodes: dict[str, HierarchyNode] = {}
        self._load()

    def _file_path(self) -> Path:
        return self.storage_path / f"{self.repo}.json"

    def _load(self) -> None:
        path = self._file_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data:
                    node = HierarchyNode(**item)
                    self.nodes[node.id] = node
            except Exception as e:
                log.warning("failed to load hierarchy: %s", e)

    def save(self) -> None:
        data = [
            {
                "id": n.id,
                "repo": n.repo,
                "path": n.path,
                "name": n.name,
                "parent_id": n.parent_id,
                "depth": n.depth,
                "doc_count": n.doc_count,
                "children": n.children,
            }
            for n in self.nodes.values()
        ]
        self._file_path().write_text(json.dumps(data, indent=2), encoding="utf-8")

    def build_from_files(self, file_paths: list[str]) -> None:
        folder_counts: dict[str, int] = {}

        for fp in file_paths:
            parts = Path(fp).parts
            for i in range(len(parts)):
                folder_path = "/".join(parts[:i])
                folder_name = parts[i] if i < len(parts) else ""
                key = f"{self.repo}::{folder_path}" if folder_path else f"{self.repo}::"

                if key not in self.nodes:
                    parent_path = "/".join(parts[:i-1]) if i > 0 else None
                    parent_id = f"{self.repo}::{parent_path}" if parent_path else None
                    self.nodes[key] = HierarchyNode(
                        id=key,
                        repo=self.repo,
                        path=folder_path,
                        name=folder_name,
                        parent_id=parent_id,
                        depth=i,
                    )

            if len(parts) > 1:
                parent_folder = "/".join(parts[:-1])
                parent_key = f"{self.repo}::{parent_folder}"
                if parent_key in self.nodes:
                    self.nodes[parent_key].doc_count += 1

        for node in self.nodes.values():
            if node.parent_id and node.parent_id in self.nodes:
                parent = self.nodes[node.parent_id]
                if node.id not in parent.children:
                    parent.children.append(node.id)

        self.save()

    def get_folder(self, path: str) -> HierarchyNode | None:
        key = f"{self.repo}::{path}"
        return self.nodes.get(key)

    def get_children(self, path: str) -> list[HierarchyNode]:
        key = f"{self.repo}::{path}"
        node = self.nodes.get(key)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_all_paths(self) -> list[str]:
        return sorted([n.path for n in self.nodes.values()], key=lambda p: p.count("/"))

    def to_list(self) -> list[dict]:
        return [
            {
                "id": n.id,
                "repo": n.repo,
                "path": n.path,
                "name": n.name,
                "parent_id": n.parent_id,
                "depth": n.depth,
                "doc_count": n.doc_count,
                "children": n.children,
            }
            for n in self.nodes.values()
        ]
