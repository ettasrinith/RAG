"""Smoke tests for the pure-Python core pieces (no LanceDB / model downloads)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.chunker import chunk_text
from core.config import _resolve_env


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
