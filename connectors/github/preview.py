"""Preview which files would be indexed and their importance scores.

Usage:
    python -m connectors.github.preview
    python -m connectors.github.preview --top 100
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from core.config import load_config
from connectors.github.importance import git_change_counts, importance_score
from connectors.github.files import TEXT_EXTENSIONS

console = Console()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=50, help="how many top-scoring files to show")
    parser.add_argument("--threshold", type=float, default=None,
                        help="override threshold from config")
    args = parser.parse_args()

    config = load_config()
    cfg = config["connectors"]["github_files"]
    local_path = Path(cfg["local_path"])
    threshold = args.threshold if args.threshold is not None else cfg["importance_threshold"]
    skip_dirs = set(cfg.get("skip_dirs", []))
    skip_ext = set(cfg.get("skip_extensions", []))
    max_bytes = int(cfg.get("max_file_size_kb", 500)) * 1024

    console.print(f"[cyan]scanning {local_path}...[/cyan]")
    counts = git_change_counts(str(local_path))

    scored = []
    skipped_ext = skipped_size = skipped_binary = 0

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        rp = Path(root)
        for f in files:
            p = rp / f
            ext = p.suffix.lower()
            if ext in skip_ext:
                skipped_ext += 1
                continue
            if ext and ext not in TEXT_EXTENSIONS:
                skipped_binary += 1
                continue
            try:
                if p.stat().st_size > max_bytes:
                    skipped_size += 1
                    continue
            except OSError:
                continue
            rel = str(p.relative_to(local_path)).replace("\\", "/")
            score = importance_score(rel, counts.get(rel, 0))
            scored.append((score, rel, counts.get(rel, 0)))

    scored.sort(reverse=True)
    above = [s for s in scored if s[0] >= threshold]

    console.print(f"\n[bold]Total scanned:[/bold] {len(scored) + skipped_ext + skipped_binary + skipped_size}")
    console.print(f"  skipped (extension blocklist): {skipped_ext}")
    console.print(f"  skipped (binary/unknown ext):  {skipped_binary}")
    console.print(f"  skipped (too large):           {skipped_size}")
    console.print(f"[bold green]Would index:[/bold green] {len(above)} (threshold={threshold})")

    table = Table(title=f"Top {args.top} files by importance")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Git changes", justify="right")
    table.add_column("Path")
    for score, path, changes in scored[: args.top]:
        table.add_row(f"{score:.0f}", str(changes), path)
    console.print(table)


if __name__ == "__main__":
    main()
