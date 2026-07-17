import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.hierarchy import HierarchyIndex


def test_hierarchy_builds_paths(tmp_path: Path):
    h = HierarchyIndex('repo1', storage_path=str(tmp_path))
    h.build_from_files(['src/app/main.py', 'src/lib/util.py'])
    paths = h.get_all_paths()
    assert 'src' in paths
    assert 'src/app' in paths
    assert 'src/lib' in paths
