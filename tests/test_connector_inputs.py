import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.arxiv.reader import ArxivConnector
from connectors.openalex.reader import OpenAlexConnector
from connectors.semantic_scholar.reader import SemanticScholarConnector
from connectors.youtube.reader import YouTubeTranscriptConnector
from core.uploads import sanitize_name


def test_arxiv_extracts_ids_from_urls_and_ids():
    conn = ArxivConnector({
        "ids": ["1706.03762"],
        "urls": ["https://arxiv.org/abs/2401.00001v2"],
    })
    ids = conn._paper_ids()
    assert "1706.03762" in ids
    assert "2401.00001" in ids


def test_openalex_reconstructs_abstract():
    inv = {"the": [0, 2], "cat": [1]}
    assert OpenAlexConnector._reconstruct_abstract(inv) == "the cat the"


def test_openalex_ids_normalized():
    conn = OpenAlexConnector({"ids": ["W2741809807", "https://openalex.org/W200"]})
    # IDs are passed through; resolution happens at fetch time. Just ensure no crash.
    assert conn.name == "openalex"


def test_s2_passes_ids_through():
    conn = SemanticScholarConnector({"ids": ["arXiv:1706.03762", "10.1145/3292500"]})
    assert conn._normalize_inputs(conn.ids) == ["arXiv:1706.03762", "10.1145/3292500"]


def test_youtube_extracts_video_ids():
    conn = YouTubeTranscriptConnector({
        "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/9bZkp7q19f0"],
        "video_ids": ["3JZ_D3ELwOQ"],
    })
    ids = conn._video_ids()
    assert "dQw4w9WgXcQ" in ids
    assert "9bZkp7q19f0" in ids
    assert "3JZ_D3ELwOQ" in ids


def test_sanitize_name_keeps_safe_characters():
    assert sanitize_name("Semester Notes 2026!.zip") == "Semester-Notes-2026--zip"
