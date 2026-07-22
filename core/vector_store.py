"""LanceDB wrapper — vector + full-text + hierarchy in one local table."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import lancedb
import pyarrow as pa
import pyarrow.compute as pc

from core.config import resolve_data_path
from core.logging import get_logger

log = get_logger("vector_store")


_SCHEMA_CACHE: dict[int, pa.Schema] = {}
_RESEARCH_SCHEMA_CACHE: dict[int, pa.Schema] = {}


def _schema(dim: int) -> pa.Schema:
    if dim not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[dim] = pa.schema([
            pa.field("id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("source", pa.string()),
            pa.field("repo", pa.string()),
            pa.field("title", pa.string()),
            pa.field("url", pa.string()),
            pa.field("author", pa.string()),
            pa.field("text", pa.string()),
            pa.field("summary", pa.string()),
            pa.field("hierarchy_path", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("created_at", pa.string()),
            pa.field("updated_at", pa.string()),
        ])
    return _SCHEMA_CACHE[dim]


def _research_schema(dim: int) -> pa.Schema:
    if dim not in _RESEARCH_SCHEMA_CACHE:
        base = _schema(dim)
        _RESEARCH_SCHEMA_CACHE[dim] = base.append(
            pa.field("paper_id", pa.string())
        ).append(
            pa.field("year", pa.int32())
        ).append(
            pa.field("venue", pa.string())
        ).append(
            pa.field("citation_count", pa.int32())
        ).append(
            pa.field("collection", pa.string())
        )
    return _RESEARCH_SCHEMA_CACHE[dim]


def _esc(val: str) -> str:
    """Escape a string value for safe use in LanceDB WHERE clauses.

    LanceDB uses a SQL-like WHERE clause; removing dangerous characters is
    far safer than trying to escape them because LanceDB's parser doesn't
    support standard SQL backslash escapes.
    """
    val = val.replace("\\", "\\\\")   # backslash
    val = val.replace("'", "''")      # single quote
    val = val.replace("\x00", "")     # null bytes
    val = val.replace(";", "")        # statement separator — just remove
    val = val.replace("--", "")       # SQL comment
    val = val.replace("/*", "")       # block comment start
    val = val.replace("*/", "")       # block comment end
    return val


class VectorStore:
    def __init__(self, path: str = "./data/lancedb", table: str = "knowledge",
                 dim: int = 768, schema_type: str = "default"):
        path = resolve_data_path(path)
        Path(path).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(path)
        self.table_name = table
        self.dim = dim
        self.schema_type = schema_type
        if table in self.db.table_names():
            self.table = self.db.open_table(table)
        else:
            schema = _research_schema(dim) if schema_type == "research" else _schema(dim)
            self.table = self.db.create_table(table, schema=schema)

    def upsert(self, rows: list[dict]) -> None:
        if not rows:
            return
        ids = [r["id"] for r in rows]
        placeholders = ",".join(f"'{_esc(i)}'" for i in ids)
        self.table.delete(f"id IN ({placeholders})")
        self.table.add(rows)

    def delete_by_doc(self, doc_id: str) -> None:
        self.table.delete(f"doc_id = '{_esc(doc_id)}'")

    def delete_by_source(self, source: str) -> None:
        self.table.delete(f"source = '{_esc(source)}'")

    def delete_by_repo(self, repo: str) -> None:
        self.table.delete(f"repo = '{_esc(repo)}'")

    def delete_docs(self, doc_ids: list[str]) -> None:
        if not doc_ids:
            return
        placeholders = ",".join(f"'{_esc(i)}'" for i in doc_ids)
        self.table.delete(f"doc_id IN ({placeholders})")

    def search(self, query_vector: list[float], k: int = 10,
               source_filter: str | None = None,
               repo_filter: str | None = None,
               hierarchy_filter: str | None = None) -> list[dict]:
        q = self.table.search(query_vector).limit(k)
        if source_filter:
            q = q.where(f"source = '{_esc(source_filter)}'")
        if repo_filter:
            q = q.where(f"repo = '{_esc(repo_filter)}'")
        if hierarchy_filter:
            q = q.where(f"hierarchy_path LIKE '{_esc(hierarchy_filter)}%'")
        return q.to_list()

    def fts_search(self, query: str, k: int = 10,
                   source_filter: str | None = None,
                   repo_filter: str | None = None) -> list[dict]:
        try:
            if self.count() == 0:
                return []
            self.ensure_fts()
            q = self.table.search(query, query_type="fts").limit(k)
            if source_filter:
                q = q.where(f"source = '{_esc(source_filter)}'")
            if repo_filter:
                q = q.where(f"repo = '{_esc(repo_filter)}'")
            return q.to_list()
        except Exception as e:
            log.warning("fts_search failed: %s", e)
            return []

    def list_repos(self) -> list[str]:
        try:
            tbl = self.table.to_arrow()
            repo_col = tbl.column("repo").combine_chunks()
            repo_col = pc.drop_null(repo_col)
            return sorted(set(repo_col.to_pylist()))
        except Exception as e:
            log.warning("list_repos failed: %s", e)
            return []

    def list_hierarchy_paths(self, repo: str | None = None) -> list[str]:
        try:
            tbl = self.table.to_arrow()
            path_col = pc.drop_null(tbl.column("hierarchy_path").combine_chunks())
            paths = sorted(set(path_col.to_pylist()))
            if repo:
                paths = [p for p in paths if isinstance(p, str) and p.startswith(repo)]
            return paths
        except Exception as e:
            log.warning("list_hierarchy_paths failed: %s", e)
            return []

    def count(self) -> int:
        return self.table.count_rows()

    def count_by_repo(self) -> dict[str, int]:
        try:
            tbl = self.table.to_arrow()
            repos = [r for r in tbl.column("repo").combine_chunks().to_pylist() if r]
            return dict(Counter(repos))
        except Exception as e:
            log.warning("count_by_repo failed: %s", e)
            return {}

    def clear(self) -> None:
        self.table.delete("true")

    def ensure_fts(self) -> None:
        """Ensure FTS index exists.

        Tries replace=True first (includes new data). On Windows this can fail
        with PermissionError because the old index directory is locked -- in
        that case falls back to replace=False (creates if absent, no-op
        otherwise).
        """
        try:
            self.table.create_fts_index("text", replace=True)
        except PermissionError:
            try:
                self.table.create_fts_index("text", replace=False)
            except Exception as e2:
                log.warning("ensure_fts fallback failed: %s", e2)
        except Exception as e:
            log.warning("ensure_fts failed: %s", e)
