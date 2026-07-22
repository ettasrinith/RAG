"""LanceDB wrapper — vector + full-text + hierarchy in one local table."""
from __future__ import annotations

import re
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

    Uses a whitelist-ish approach: remove characters that could break out of
    a string literal or inject SQL-like statements.
    """
    # Remove null bytes
    val = val.replace("\x00", "")
    # Double single quotes (standard SQL string escaping)
    val = val.replace("'", "''")
    # Remove statement terminators and comment sequences
    val = val.replace(";", "")
    val = val.replace("--", "")
    val = val.replace("/*", "")
    val = val.replace("*/", "")
    return val


def _esc_like(val: str) -> str:
    """Escape a value for use in LIKE patterns (also escapes wildcards)."""
    val = _esc(val)
    val = val.replace("%", "\\%")
    val = val.replace("_", "\\_")
    return val


def _validate_identifier(name: str) -> str:
    """Validate a column/field name to prevent injection via identifiers."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(f"Invalid identifier: {name}")
    return name


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
               hierarchy_filter: str | None = None,
               user_groups: list[str] | None = None) -> list[dict]:
        q = self.table.search(query_vector).limit(k)
        if source_filter:
            q = q.where(f"source = '{_esc(source_filter)}'")
        if repo_filter:
            q = q.where(f"repo = '{_esc(repo_filter)}'")
        if hierarchy_filter:
            q = q.where(f"hierarchy_path LIKE '{_esc(hierarchy_filter)}%'")
        # ACL filtering: applied in-memory if acl_read column exists
        results = q.to_list()
        if user_groups is not None and results:
            results = self._filter_by_acl(results, user_groups)
        return results

    def fts_search(self, query: str, k: int = 10,
                   source_filter: str | None = None,
                   repo_filter: str | None = None,
                   user_groups: list[str] | None = None) -> list[dict]:
        try:
            if self.count() == 0:
                return []
            self.ensure_fts()
            q = self.table.search(query, query_type="fts").limit(k)
            if source_filter:
                q = q.where(f"source = '{_esc(source_filter)}'")
            if repo_filter:
                q = q.where(f"repo = '{_esc(repo_filter)}'")
            results = q.to_list()
            if user_groups is not None and results:
                results = self._filter_by_acl(results, user_groups)
            return results
        except Exception as e:
            log.warning("fts_search failed for query=%r: %s", query[:50], e)
            return []

    # ── ACL Management ──────────────────────────────────────────────

    def _has_acl_column(self) -> bool:
        """Check if the table has acl_read column (for backward compatibility)."""
        try:
            fields = [f.name for f in self.table.schema]
            return "acl_read" in fields
        except Exception:
            return False

    def _filter_by_acl(self, results: list[dict], user_groups: list[str]) -> list[dict]:
        """Filter results by ACL in memory. Chunks with empty/no acl_read are public."""
        if not self._has_acl_column():
            return results  # No ACL column — all chunks are public
        filtered = []
        for r in results:
            acl = r.get("acl_read")
            if not acl:
                filtered.append(r)  # No ACL set = public
            elif any(g in acl for g in user_groups):
                filtered.append(r)  # User has access
        return filtered

    def ensure_acl_columns(self) -> bool:
        """Add ACL columns to an existing table if they don't exist."""
        if self._has_acl_column():
            return True
        try:
            import pyarrow as pa
            tbl = self.table.to_arrow()
            n = tbl.num_rows
            # Add nullable ACL columns
            acl_read_default = pa.array([[] for _ in range(n)], type=pa.list_(pa.string()))
            acl_write_default = pa.array([[] for _ in range(n)], type=pa.list_(pa.string()))
            acl_owner_default = pa.array(["" for _ in range(n)], type=pa.string())
            tbl = tbl.append_column("acl_read", acl_read_default)
            tbl = tbl.append_column("acl_write", acl_write_default)
            tbl = tbl.append_column("acl_owner", acl_owner_default)
            self.table.delete("true")
            self.table.add(tbl)
            log.info("acl_columns_added", extra={"rows": n})
            return True
        except Exception as e:
            log.warning("ensure_acl_columns failed: %s", e)
            return False

    def set_chunk_acl(
        self,
        chunk_ids: list[str],
        acl_read: list[str] | None = None,
        acl_write: list[str] | None = None,
        acl_owner: str | None = None,
    ) -> int:
        """Update ACL fields on specific chunks. Returns count updated."""
        if not chunk_ids:
            return 0
        if not self._has_acl_column():
            self.ensure_acl_columns()

        tbl = self.table.to_arrow()
        ids_array = tbl.column("id").combine_chunks().to_pylist()
        id_set = set(chunk_ids)
        update_mask = [i in id_set for i in ids_array]

        if not any(update_mask):
            return 0

        import pyarrow as pa
        acl_read_col = tbl.column("acl_read").combine_chunks()
        acl_write_col = tbl.column("acl_write").combine_chunks()
        acl_owner_col = tbl.column("acl_owner").combine_chunks()

        new_read = []
        new_write = []
        new_owner = []
        updated = 0

        for idx, mask in enumerate(update_mask):
            old_r = acl_read_col[idx].as_py() if acl_read_col[idx] else []
            old_w = acl_write_col[idx].as_py() if acl_write_col[idx] else []
            old_o = acl_owner_col[idx].as_py() if acl_owner_col[idx] else ""
            if mask:
                new_read.append(acl_read if acl_read is not None else old_r)
                new_write.append(acl_write if acl_write is not None else old_w)
                new_owner.append(acl_owner if acl_owner is not None else old_o)
                updated += 1
            else:
                new_read.append(old_r)
                new_write.append(old_w)
                new_owner.append(old_o)

        new_tbl = tbl.set_column(
            tbl.schema.get_field_index("acl_read"), "acl_read",
            pa.array(new_read, type=pa.list_(pa.string()))
        )
        new_tbl = new_tbl.set_column(
            new_tbl.schema.get_field_index("acl_write"), "acl_write",
            pa.array(new_write, type=pa.list_(pa.string()))
        )
        new_tbl = new_tbl.set_column(
            new_tbl.schema.get_field_index("acl_owner"), "acl_owner",
            pa.array(new_owner, type=pa.string())
        )

        self.table.delete("true")
        self.table.add(new_tbl)
        log.info("acl_updated", extra={"chunk_ids": len(chunk_ids), "updated": updated})
        return updated

    def set_repo_acl(self, repo: str, acl_read: list[str]) -> int:
        """Set ACL on all chunks in a repository."""
        if not self._has_acl_column():
            self.ensure_acl_columns()
        tbl = self.table.to_arrow()
        repo_col = tbl.column("repo").combine_chunks().to_pylist()
        chunk_ids = [
            tbl.column("id").combine_chunks().to_pylist()[i]
            for i, r in enumerate(repo_col)
            if r == repo
        ]
        return self.set_chunk_acl(chunk_ids, acl_read=acl_read)

    def get_chunk_acl(self, chunk_id: str) -> dict | None:
        """Get ACL for a specific chunk."""
        if not self._has_acl_column():
            return None
        tbl = self.table.to_arrow()
        ids = tbl.column("id").combine_chunks().to_pylist()
        for i, cid in enumerate(ids):
            if cid == chunk_id:
                return {
                    "id": chunk_id,
                    "acl_read": (tbl.column("acl_read").combine_chunks()[i].as_py()
                                 if tbl.column("acl_read").combine_chunks()[i] else []),
                    "acl_write": (tbl.column("acl_write").combine_chunks()[i].as_py()
                                  if tbl.column("acl_write").combine_chunks()[i] else []),
                    "acl_owner": (tbl.column("acl_owner").combine_chunks()[i].as_py()
                                  if tbl.column("acl_owner").combine_chunks()[i] else ""),
                }
        return None

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
