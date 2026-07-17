"""Smoke tests for the pure-Python core pieces (no LanceDB / model downloads)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.hybrid_search import hybrid_search
from core.chunker import chunk_text
from core.config import _resolve_env


def test_hybrid_merges_and_ranks():
    vector = [
        {"id": "a::chunk0", "doc_id": "a", "_distance": 0.1},
        {"id": "b::chunk0", "doc_id": "b", "_distance": 0.5},
    ]
    fts = [
        {"id": "b::chunk0", "doc_id": "b", "_score": 2.0},
        {"id": "c::chunk0", "doc_id": "c", "_score": 1.0},
    ]
    out = hybrid_search(vector, fts, vector_weight=0.7, fts_weight=0.3, top_k=3)
    ids = [r["id"] for r in out]
    assert {"a::chunk0", "b::chunk0", "c::chunk0"} <= set(ids)
    assert out[0]["id"] == "b::chunk0"


def test_hybrid_empty():
    assert hybrid_search([], [], top_k=5) == []


def test_resolve_env_var(monkeypatch):
    monkeypatch.setenv("KH_TEST_VAR", "hello")
    assert _resolve_env("${KH_TEST_VAR}") == "hello"


def test_resolve_env_dict_key(monkeypatch):
    monkeypatch.setenv("KH_TEST_TOKEN", "secret")
    assert _resolve_env({"pat_env": "KH_TEST_TOKEN"}) == {"pat": "secret"}


def test_chunk_text_returns_single_when_small():
    assert chunk_text("short text", chunk_size=512) == ["short text"]


def test_chunk_text_splits_long():
    pieces = chunk_text("word " * 2000, chunk_size=50, overlap=10)
    assert len(pieces) > 1


def test_chunk_text_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_text("abc def ghi", chunk_size=10, overlap=10)
