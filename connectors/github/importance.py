"""Score files by importance — combines git history + name signals + depth."""
from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

HIGH_VALUE_NAMES = {
    "README", "SETUP", "INSTALL", "CONTRIBUTING", "ARCHITECTURE",
    "DEPLOYMENT", "DEPLOY", "RUNBOOK", "ONBOARDING", "GETTING_STARTED",
    "CHANGELOG", "CONFIG", "ENVIRONMENT", "ENV", "MAKEFILE", "DOCKERFILE",
}

HIGH_VALUE_FRAGMENTS = (
    "Controller", "Service", "API", "Gateway", "Router", "Main",
    "App", "Config", "Settings", "Constants", "index", "main",
)


def git_change_counts(repo_path: str) -> dict[str, int]:
    """Returns {relative_path: number_of_commits_touching_it}."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--pretty=format:", "--name-only"],
            cwd=repo_path,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    counter = Counter(line.strip() for line in out.splitlines() if line.strip())
    return dict(counter)


def importance_score(rel_path: str, change_count: int = 0) -> float:
    """0–100ish — combine git activity, depth, name, and extension."""
    p = Path(rel_path)
    score = 0.0

    # git frequency (capped)
    score += min(change_count * 2, 40)

    # shallower paths matter more
    depth = len(p.parts)
    score += max(0, 20 - depth * 2)

    stem_upper = p.stem.upper()
    if any(name in stem_upper for name in HIGH_VALUE_NAMES):
        score += 30
    if any(frag in p.name for frag in HIGH_VALUE_FRAGMENTS):
        score += 10

    ext = p.suffix.lower()
    if ext in {".md", ".rst", ".txt"}:
        score += 25
    elif ext in {".sh", ".bat", ".ps1"}:
        score += 15
    elif ext in {".yml", ".yaml", ".toml", ".ini"}:
        score += 10

    return score
