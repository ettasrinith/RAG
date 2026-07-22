"""LanceDB backend implementing the DocumentIndex interface.

Follows Onyx's capability-mixin pattern. Supports hybrid search
with FTS version tracking and set-based ACLs.
"""
from __future__ import annotations

import gc
import re
import shutil
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
import pyarrow.compute as pc

from core.config import resolve_data_path
from core.interfaces import (
    Chunk,
    Clearable,
    Countable,
    Deletable,
    DocumentAccess,
    DocumentIndex,
    HybridCapable,
    Indexable,
    SchemaVerifiable,
    SearchResult,
    Updatable,
)
from core.logging import get_logger

log = get_logger("lancedb_backend")


def _esc(val: str) -> str:
    """Escape a string value for safe use in LanceDB WHERE clauses."""
    val = val.replace("\x00", "")
    val = val.replace("'", "''")
    val = val.replace(";", "")
    val = val.replace("--", "")
    val = val.replace("/*", "")
    val = val.replace("*/", "")
    return val


def _validate_identifier(name: str) -> str:
    """Validate a column/field name to prevent injection."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(f"Invalid identifier: {name}")
    return name


# ── Schema ─────────────────────────────────────────────────────────────

_SCHEMA_CACHE: dict[int, pa.Schema] = {}


def _schema(embedding_dim: int, acl_columns: bool = False) -> pa.Schema:
    """Build the Arrow schema for a knowledge table."""
    if embedding_dim not in _SCHEMA_CACHE:
        fields = [
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
            pa.field("vector", pa.list_(pa.float32(), embedding_dim)),
            pa.field("created_at", pa.string()),
            pa.field("updated_at", pa.string()),
        ]
        _SCHEMA_CACHE[embedding_dim] = pa.schema(fields)
    return _SCHEMA_CACHE[embedding_dim]


def _research_schema(embedding_dim: int) -> pa.Schema:
    """Build the Arrow schema for the research table."""
    base = _schema(embedding_dim)
    return base.append(pa.field("paper_id", pa.string())).append(
        pa.field("year", pa.int32())
    ).append(pa.field("venue", pa.string())).append(
        pa.field("citation_count", pa.int32())
    ).append(pa.field("collection", pa.string()))


# ── Backend Implementation ─────────────────────────────────────────────


class LanceDBDocumentIndex(DocumentIndex):
    """LanceDB-backed document index with FTS version tracking.

    Uses Onyx's capability-mixin pattern: implements SchemaVerifiable,
    Indexable, Deletable, Updatable, HybridCapable, Countable, Clearable.
    """

    def __init__(
        self,
        path: str = "./data/lancedb",
        table: str = "knowledge",
        embedding_dim: int = 768,
        schema_type: str = "default",
    ):
        path = resolve_data_path(path)
        Path(path).mkdir(parents=True, exist_ok=True)
        self._db_path = path
        self._table_name = table
        self._embedding_dim = embedding_dim
        self._schema_type = schema_type
        self._db = lancedb.connect(path)

        # FTS version tracking — monotonic counters
        self._data_version: int = 0
        self._fts_version: int = -1
        self._fts_lock = threading.Lock()

        if table in self._db.table_names():
            self._table = self._db.open_table(table)
        else:
            schema = _research_schema(embedding_dim) if schema_type == "research" else _schema(embedding_dim)
            self._table = self._db.create_table(table, schema=schema)

    # ── SchemaVerifiable ──────────────────────────────────────────────

    def verify_and_create_index_if_necessary(self, embedding_dim: int) -> None:
        """Verify the schema — the table is created in __init__."""
        if self._table is None or embedding_dim != self._embedding_dim:
            self._embedding_dim = embedding_dim
            schema = _research_schema(embedding_dim) if self._schema_type == "research" else _schema(embedding_dim)
            if self._table_name in self._db.table_names():
                self._db.drop_table(self._table_name)
            self._table = self._db.create_table(self._table_name, schema=schema)

    # ── Indexable ─────────────────────────────────────────────────────

    def index(self, chunks: list[Chunk]) -> int:
        """Index a batch of chunks."""
        if not chunks:
            return 0

        # Auto-create ACL columns if any chunk carries access control data
        has_acl = any(
            c.access_read is not None or c.access_write is not None or c.access_owner
            for c in chunks
        )
        if has_acl:
            self.ensure_columns({
                "acl_read": pa.list_(pa.string()),
                "acl_write": pa.list_(pa.string()),
                "acl_owner": pa.string(),
            })

        # Delete existing chunks for these doc IDs first (upsert semantics)
        doc_ids = {c.doc_id for c in chunks}
        for did in doc_ids:
            self._table.delete(f"doc_id = '{_esc(did)}'")

        rows = [_chunk_to_row(c) for c in chunks]
        # Pad rows with defaults for any table columns not present (e.g. acl_*
        # after schema migration) so LanceDB doesn't reject the batch.
        if rows:
            rows = self._pad_rows_to_schema(rows)
        self._table.add(rows)
        self._mark_fts_dirty()
        return len(chunks)

    # ── Deletable ─────────────────────────────────────────────────────

    def delete(self, doc_id: str) -> int:
        """Delete all chunks for a document."""
        before = self.count()
        self._table.delete(f"doc_id = '{_esc(doc_id)}'")
        self._mark_fts_dirty()
        return before - self.count()

    # ── Updatable ─────────────────────────────────────────────────────

    def update_access(self, doc_id: str, access: DocumentAccess) -> bool:
        """Update ACLs for a document without re-embedding.

        Uses additive migration: creates a new table with updated ACL
        column, then swaps it in — never deletes rows in-place.

        Note: ACL columns must exist on the table first (call ensure_columns).
        """
        acl = access.to_acl()
        tbl = self._table.to_arrow()
        doc_ids_list = tbl.column("doc_id").combine_chunks().to_pylist()

        # Check if acl_read column exists; if not, add it first
        has_acl = "acl_read" in {f.name for f in tbl.schema}
        if not has_acl:
            default_acl = pa.array([[] for _ in range(len(tbl))], type=pa.list_(pa.string()))
            tbl = tbl.append_column("acl_read", default_acl)

        acl_sorted = sorted(acl)
        acl_col = tbl.column("acl_read").combine_chunks()

        new_acl_vals = []
        any_updated = False
        for i, did in enumerate(doc_ids_list):
            if did == doc_id:
                new_acl_vals.append(acl_sorted)
                any_updated = True
            else:
                val = acl_col[i].as_py() if acl_col[i] is not None else []
                new_acl_vals.append(val)

        if not any_updated:
            return False

        new_tbl = tbl.set_column(
            tbl.schema.get_field_index("acl_read"), "acl_read",
            pa.array(new_acl_vals, type=pa.list_(pa.string()))
        )

        # Additive migration: create new table, drop old, rename
        migrated_name = f"{self._table_name}_migrated"
        self._db.create_table(migrated_name, new_tbl, mode="overwrite")
        self._db.drop_table(self._table_name)
        self._table = self._db.open_table(migrated_name)
        self._table_name = migrated_name
        self._mark_fts_dirty()
        return True

    # ── HybridCapable ─────────────────────────────────────────────────

    def hybrid_search(
        self,
        query: str,
        vector: list[float],
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Hybrid search: vector + keyword fused via RRF."""
        from core.search.fusion import rrf_fuse, apply_recency_bias

        vector_results = self.vector_search(vector, filters=filters, user_acl=user_acl, k=k * 2)
        keyword_results = self.keyword_search(query, filters=filters, user_acl=user_acl, k=k * 2)

        # Convert to dict format for fusion
        v_dicts = [sr_to_dict(r) for r in vector_results]
        k_dicts = [sr_to_dict(r) for r in keyword_results]

        fused = rrf_fuse(v_dicts, k_dicts, top_n=k)
        fused = apply_recency_bias(fused)

        return [dict_to_sr(r) for r in fused]

    def keyword_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Keyword-only search via LanceDB FTS."""
        try:
            if self.count() == 0:
                return []
            self._ensure_fts_fresh()
            q = self._table.search(query, query_type="fts").limit(k)
            for key, val in (filters or {}).items():
                if val is not None:
                    q = q.where(f"{_validate_identifier(key)} = '{_esc(str(val))}'")
            results = q.to_list()
            if user_acl is not None and results:
                results = self._filter_by_acl(results, user_acl)
            return [self._row_to_search_result(r, rank=i) for i, r in enumerate(results)]
        except Exception as e:
            log.warning("keyword_search failed: %s", e)
            return []

    def vector_search(
        self,
        vector: list[float],
        filters: dict[str, Any] | None = None,
        user_acl: set[str] | None = None,
        k: int = 10,
    ) -> list[SearchResult]:
        """Vector-only search."""
        try:
            if self.count() == 0:
                return []
            q = self._table.search(vector).limit(k)
            for key, val in (filters or {}).items():
                if val is not None:
                    q = q.where(f"{_validate_identifier(key)} = '{_esc(str(val))}'")
            results = q.to_list()
            if user_acl is not None and results:
                results = self._filter_by_acl(results, user_acl)
            return [self._row_to_search_result(r, rank=i) for i, r in enumerate(results)]
        except Exception as e:
            log.warning("vector_search failed: %s", e)
            return []

    # ── Countable ─────────────────────────────────────────────────────

    def count(self) -> int:
        return self._table.count_rows()

    def count_by_repo(self) -> dict[str, int]:
        try:
            tbl = self._table.to_arrow()
            repos = [r for r in tbl.column("repo").combine_chunks().to_pylist() if r]
            return dict(Counter(repos))
        except Exception as e:
            log.warning("count_by_repo failed: %s", e)
            return {}

    # ── Clearable ─────────────────────────────────────────────────────

    def clear(self) -> None:
        self._table.delete("true")
        self._mark_fts_dirty()

    # ── Schema helpers (additive migration) ───────────────────────────

    def ensure_columns(self, new_columns: dict[str, pa.DataType]) -> None:
        """Add columns without deleting data (additive-only migration)."""
        existing_fields = {f.name for f in self._table.schema}
        missing = {n: t for n, t in new_columns.items() if n not in existing_fields}
        if not missing:
            return

        log.info("Adding %d columns: %s", len(missing), list(missing.keys()))
        data = self._table.to_arrow()

        for col_name, col_type in missing.items():
            if pa.types.is_string(col_type) or pa.types.is_large_string(col_type):
                default = ""
            elif pa.types.is_integer(col_type) or pa.types.is_int32(col_type) or pa.types.is_int64(col_type):
                default = 0
            elif pa.types.is_floating(col_type) or pa.types.is_float32(col_type) or pa.types.is_float64(col_type):
                default = 0.0
            elif pa.types.is_boolean(col_type):
                default = False
            elif pa.types.is_list(col_type):
                default = []
            else:
                default = None
            data = data.append_column(col_name, pa.array([default] * len(data), type=col_type))

        migrated_name = f"{self._table_name}_migrated"
        self._db.create_table(migrated_name, data, mode="overwrite")
        self._db.drop_table(self._table_name)
        self._table = self._db.open_table(migrated_name)
        self._table_name = migrated_name
        self._mark_fts_dirty()
        log.info("Migration complete: %d rows preserved", len(data))

    def list_repos(self) -> list[str]:
        try:
            tbl = self._table.to_arrow()
            repo_col = pc.drop_null(tbl.column("repo").combine_chunks())
            return sorted(set(repo_col.to_pylist()))
        except Exception:
            return []

    # ── Internal: Schema helpers ──────────────────────────────────────────

    @staticmethod
    def _default_for_type(col_type: pa.DataType) -> Any:
        """Return a sensible default value for a given Arrow type."""
        if pa.types.is_string(col_type) or pa.types.is_large_string(col_type):
            return ""
        elif pa.types.is_integer(col_type) or pa.types.is_int32(col_type) or pa.types.is_int64(col_type):
            return 0
        elif pa.types.is_floating(col_type) or pa.types.is_float32(col_type) or pa.types.is_float64(col_type):
            return 0.0
        elif pa.types.is_boolean(col_type):
            return False
        elif pa.types.is_list(col_type):
            return []
        return None

    def _pad_rows_to_schema(self, rows: list[dict]) -> list[dict]:
        """Fill in defaults for any table-schema columns missing from rows."""
        schema_fields = {f.name for f in self._table.schema}
        for row in rows:
            missing = schema_fields - set(row.keys())
            for col_name in missing:
                col_type = self._table.schema.field(col_name).type
                row[col_name] = self._default_for_type(col_type)
        return rows

    # ── Internal: FTS version tracking ─────────────────────────────────

    def _mark_fts_dirty(self) -> None:
        self._data_version += 1

    def _ensure_fts_fresh(self) -> None:
        with self._fts_lock:
            if self._fts_version >= self._data_version:
                return
            self._rebuild_fts()

    def _rebuild_fts(self) -> None:
        """Force rebuild FTS index, handling Windows file-lock bugs.

        On Windows ``replace=True`` can report success while producing a
        corrupted index (row indices out of sync), so we skip it and
        always use the close/reopen + ``replace=False`` path.
        """
        import sys as _sys

        # Strategy 1: In-place replace (reliable on Linux/macOS)
        if _sys.platform != "win32":
            try:
                self._table.create_fts_index("text", replace=True)
                self._fts_version = self._data_version
                log.info("FTS rebuilt — version %d", self._fts_version)
                return
            except PermissionError:
                log.info("FTS replace blocked — using close/reopen")
            except Exception as e:
                log.warning("FTS replace failed: %s — trying close/reopen", e)
        else:
            log.info("Windows detected — using close/reopen strategy for FTS")

        # Strategy 2: Close, delete, reopen (required on Windows)
        try:
            db_path = str(self._db_path)
            tbl_name = self._table_name
            lance_dir = Path(db_path) / f"{tbl_name}.lance"
            index_dir = lance_dir / "_indices"
            self._table = None
            self._db = None
            gc.collect()
            if index_dir.exists():
                shutil.rmtree(index_dir, ignore_errors=True)
            self._db = lancedb.connect(db_path)
            self._table = self._db.open_table(tbl_name)
            self._table.create_fts_index("text", replace=False)
            self._fts_version = self._data_version
            log.info("FTS rebuilt (close/reopen) — version %d", self._fts_version)
        except Exception as e:
            log.error("FTS rebuild failed: %s", e)

    # ── Internal: ACL filtering ───────────────────────────────────────

    def _has_acl_column(self) -> bool:
        try:
            return "acl_read" in {f.name for f in self._table.schema}
        except Exception:
            return False

    def _filter_by_acl(self, results: list[dict], user_acl: set[str]) -> list[dict]:
        """Filter results in-memory using set-based ACL (Onyx pattern)."""
        if not self._has_acl_column():
            return results  # No ACL column = all public
        filtered = []
        for r in results:
            doc_acl = r.get("acl_read")
            if not doc_acl:
                filtered.append(r)  # No ACL = public
            elif not user_acl.isdisjoint(set(doc_acl)):
                filtered.append(r)  # Intersection = access granted
        return filtered

    # ── Helpers ───────────────────────────────────────────────────────

    def _row_to_search_result(self, row: dict, rank: int = 0) -> SearchResult:
        return SearchResult(
            id=row.get("id", ""),
            doc_id=row.get("doc_id", ""),
            title=row.get("title", ""),
            text=row.get("text", ""),
            source=row.get("source", ""),
            repo=row.get("repo", ""),
            url=row.get("url", ""),
            author=row.get("author", ""),
            summary=row.get("summary", ""),
            score=row.get("_distance", 0.0) or row.get("combined_score", 0.0),
            rank=rank,
        )


# ── Module-level helpers ────────────────────────────────────────────────


def _chunk_to_row(c: Chunk) -> dict:
    row = {
        "id": c.id,
        "doc_id": c.doc_id,
        "source": c.source,
        "repo": c.repo,
        "title": c.title,
        "url": c.url,
        "author": c.author,
        "text": c.text,
        "summary": c.summary,
        "hierarchy_path": c.hierarchy_path,
        "vector": c.vector or [],
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }
    # Include ACL fields if populated (maps Chunk.access_read → acl_read)
    if c.access_read is not None:
        row["acl_read"] = c.access_read
    if c.access_write is not None:
        row["acl_write"] = c.access_write
    if c.access_owner:
        row["acl_owner"] = c.access_owner
    return row


def sr_to_dict(sr: SearchResult) -> dict:
    """Convert SearchResult to flat dict for fusion functions."""
    return {
        "id": sr.id,
        "doc_id": sr.doc_id,
        "title": sr.title,
        "text": sr.text,
        "source": sr.source,
        "repo": sr.repo,
        "url": sr.url,
        "author": sr.author,
        "summary": sr.summary,
        "combined_score": sr.score,
    }


def dict_to_sr(d: dict) -> SearchResult:
    """Convert flat dict back to SearchResult."""
    return SearchResult(
        id=d.get("id", ""),
        doc_id=d.get("doc_id", ""),
        title=d.get("title", ""),
        text=d.get("text", ""),
        source=d.get("source", ""),
        repo=d.get("repo", ""),
        url=d.get("url", ""),
        author=d.get("author", ""),
        summary=d.get("summary", ""),
        score=d.get("combined_score", 0.0),
    )
