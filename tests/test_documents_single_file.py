import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.documents.reader import DocumentsConnector


def test_documents_connector_single_file(tmp_path: Path):
    f = tmp_path / 'notes.txt'
    f.write_text('hello world from a single document file' * 10, encoding='utf-8')
    conn = DocumentsConnector({
        'paths': [str(f)],
        'label': 'single-file',
        'min_text_chars': 5,
    })
    docs = list(conn.load_documents())
    assert len(docs) == 1
    assert docs[0].title == 'notes.txt'
