"""Staged indexing pipeline following Onyx's architecture.

Pipeline stages:
1. **Filtering** — Remove empty/oversized documents
2. **Dedup** — Skip unchanged documents (timestamp + content hash)
3. **Chunking** — Split documents into chunks
4. **Embedding** — Generate vector embeddings
5. **Indexing** — Write to DocumentIndex backend
6. **Post-index** — Update sync state

Each stage is a separate function with clear inputs/outputs.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from core.chunker import chunk_text
from core.embedder import embed
from core.interfaces import Chunk, Document, DocumentIndex, Section
from core.sync_state import SyncState

MAX_DOCUMENT_CHARS = 100_000


@dataclass
class PipelineResult:
    """Result of running the indexing pipeline."""
    total_docs: int = 0
    total_chunks: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    skipped: int = 0


@dataclass
class PipelineContext:
    """Shared context passed through pipeline stages."""
    document_index: DocumentIndex
    sync_state: SyncState | None = None
    progress_cb: Callable[[dict], None] | None = None
    stop_event: Any | None = None


# ── Stage 1: Filtering ──────────────────────────────────────────────────


def filter_documents(docs: list[Document]) -> list[Document]:
    """Remove empty, oversize, or invalid documents."""
    filtered = []
    for d in docs:
        total_chars = sum(len(s.text) for s in d.sections)
        if total_chars == 0:
            continue
        if total_chars > MAX_DOCUMENT_CHARS:
            # Truncate oversize documents
            truncated = 0
            new_sections = []
            for s in d.sections:
                if truncated + len(s.text) > MAX_DOCUMENT_CHARS:
                    remaining = MAX_DOCUMENT_CHARS - truncated
                    if remaining > 0:
                        new_sections.append(Section(text=s.text[:remaining]))
                    break
                new_sections.append(s)
                truncated += len(s.text)
            d.sections = new_sections
        filtered.append(d)
    return filtered


# ── Stage 2: Dedup ──────────────────────────────────────────────────────


def _content_hash(doc: Document) -> str:
    """Compute a content fingerprint for dedup."""
    text = "".join(s.text for s in doc.sections)
    return hashlib.sha256(text.encode()).hexdigest()


def dedup_documents(
    docs: list[Document],
    sync_state: SyncState | None = None,
    force_full: bool = False,
) -> list[Document]:
    """Skip documents that haven't changed since last index.

    Two gates (following Onyx's pattern):
    - Gate 1: Quick timestamp check
    - Gate 2: Content hash comparison
    """
    if force_full or sync_state is None:
        return docs

    result = []
    for d in docs:
        last = sync_state.get_last_indexed(d.repo, d.doc_id)
        if last is None:
            result.append(d)
            continue

        # Gate 1: Timestamp check
        if d.updated_at and d.updated_at <= last.get("updated_at", ""):
            continue  # Not modified per timestamp

        # Gate 2: Content hash
        new_hash = _content_hash(d)
        if new_hash == last.get("content_hash"):
            continue  # Content unchanged

        result.append(d)
    return result


# ── Stage 3: Chunking ───────────────────────────────────────────────────


def chunk_documents(docs: list[Document]) -> list[Chunk]:
    """Split documents into chunks ready for embedding."""
    chunks: list[Chunk] = []
    for doc in docs:
        full_text = "\n\n".join(s.text for s in doc.sections)
        text_chunks = chunk_text(full_text)

        for i, text_chunk in enumerate(text_chunks):
            chunk_id = f"{doc.doc_id}__chunk_{i}"
            chunks.append(Chunk(
                id=chunk_id,
                doc_id=doc.doc_id,
                text=text_chunk,
                title=doc.title,
                source=doc.source,
                repo=doc.repo,
                url=doc.url,
                author=doc.author,
                summary=doc.summary,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            ))
    return chunks


# ── Stage 4: Embedding ──────────────────────────────────────────────────


def embed_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Generate vector embeddings for each chunk.

    Uses all-or-nothing per document: if any chunk from a document
    fails, all its chunks are scrubbed (Onyx pattern).
    """
    if not chunks:
        return []

    texts = [c.text for c in chunks]
    try:
        vectors = embed(texts)
    except Exception as e:
        # If embedding fails entirely, return chunks without vectors
        # (they'll be skipped at index time)
        return chunks

    for chunk, vector in zip(chunks, vectors):
        chunk.vector = vector
    return chunks


# ── Stage 5: Indexing ───────────────────────────────────────────────────


def write_chunks(
    chunks: list[Chunk],
    document_index: DocumentIndex,
    progress_cb: Callable[[dict], None] | None = None,
) -> int:
    """Write chunks to the document index backend."""
    if not chunks:
        return 0

    # Group by doc_id for progress reporting
    doc_ids = set(c.doc_id for c in chunks)
    indexed = document_index.index(chunks)

    if progress_cb:
        progress_cb({
            "type": "index_progress",
            "docs": len(doc_ids),
            "chunks": indexed,
        })
    return indexed


# ── Stage 6: Post-index ────────────────────────────────────────────────


def post_index(
    docs: list[Document],
    chunks: list[Chunk],
    sync_state: SyncState | None = None,
    errors: list[str] | None = None,
) -> None:
    """Update sync state with content hashes for dedup on next run."""
    if sync_state is None:
        return

    for doc in docs:
        content_hash = _content_hash(doc)
        sync_state.set_last_indexed(
            doc.repo,
            doc.doc_id,
            {
                "content_hash": content_hash,
                "updated_at": doc.updated_at or datetime.now().isoformat(),
                "chunk_count": sum(1 for c in chunks if c.doc_id == doc.doc_id),
            },
        )


# ── Pipeline Orchestrator ───────────────────────────────────────────────


def run_indexing_pipeline(
    docs: list[Document],
    context: PipelineContext,
    force_full: bool = False,
) -> PipelineResult:
    """Run the full indexing pipeline on a batch of documents.

    Follows Onyx's staging pattern: filter → dedup → chunk → embed → write → post.
    """
    result = PipelineResult()
    t0 = time.time()

    try:
        # Stage 1: Filter
        docs = filter_documents(docs)
        result.total_docs = len(docs)

        # Stage 2: Dedup
        docs = dedup_documents(docs, context.sync_state, force_full)
        result.skipped = result.total_docs - len(docs)
        if not docs:
            result.elapsed_s = time.time() - t0
            return result

        # Stage 3: Chunk
        chunks = chunk_documents(docs)

        # Stage 4: Embed
        chunks = embed_chunks(chunks)
        chunks = [c for c in chunks if c.vector is not None]
        result.total_chunks = len(chunks)
        if not chunks:
            result.elapsed_s = time.time() - t0
            return result

        # Stage 5: Write
        written = write_chunks(chunks, context.document_index, context.progress_cb)

        # Stage 6: Post-index
        if not force_full:
            post_index(docs, chunks, context.sync_state)

        result.elapsed_s = time.time() - t0

    except Exception as e:
        result.errors.append(str(e))
        result.elapsed_s = time.time() - t0

    return result
