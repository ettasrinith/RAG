"""Live smoke tests for research connectors — hit the real APIs.

These are skipped automatically when there is no network access or when a
required API key is missing from the environment. Run with:
    pytest tests/test_live_connectors.py -v
"""
import os
import sys
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.openalex.reader import OpenAlexConnector
from connectors.semantic_scholar.reader import SemanticScholarConnector


def _online() -> bool:
    try:
        import httpx
        resp = httpx.get("https://api.openalex.org/works?search=test&per-page=1",
                         timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _online(), reason="no network access")


def test_openalex_query_returns_documents():
    key = os.environ.get("OPENALEX_API_KEY", "")
    conn = OpenAlexConnector({"query": "attention is all you need", "max_results": 2,
                              "api_key": key})
    docs = list(conn.load_documents())
    assert docs, "OpenAlex returned no documents"
    assert docs[0].source == "openalex"
    assert "Title:" in docs[0].content
    assert docs[0].url


def test_semantic_scholar_query_returns_documents():
    key = os.environ.get("S2_API_KEY", "")
    conn = SemanticScholarConnector({"query": "attention is all you need", "max_results": 2,
                                     "api_key": key})
    try:
        docs = list(conn.load_documents())
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            pytest.skip("Semantic Scholar rate-limited (set S2_API_KEY to raise limit)")
        raise
    assert docs, "Semantic Scholar returned no documents"
    assert docs[0].source == "semantic_scholar"
    assert "Title:" in docs[0].content
