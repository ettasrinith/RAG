import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.knowledge_graph import KnowledgeGraphIndex


def test_knowledge_graph_dedupes_relations(tmp_path: Path):
    kg = KnowledgeGraphIndex(storage_path=str(tmp_path))
    text = "import foo\nimport foo\nclass MyClass {}"
    kg.build_from_doc('repo1', 'a.py', text)
    kg.build_from_doc('repo1', 'a.py', text)
    graph = kg.get_or_create('repo1')
    unique = {(r.source, r.target, r.relation_type, r.context) for r in graph.relations}
    assert len(graph.relations) == len(unique)
