"""Dead letter queue for failed indexing operations.

Persists failed items to disk so they can be retried or investigated later.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict

from core.config import ROOT
from core.logging import get_logger

log = get_logger("dead_letter")

DLQ_PATH = ROOT / "data" / "dead_letter_queue.jsonl"


@dataclass
class DeadLetter:
    job_id: str
    doc_id: str
    source: str
    error: str
    timestamp: float
    retry_count: int = 0
    payload: dict | None = None


def enqueue(letter: DeadLetter) -> None:
    """Append a failed item to the dead letter queue."""
    DLQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DLQ_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(letter)) + "\n")
    log.info("DLQ enqueue: %s/%s — %s", letter.source, letter.doc_id, letter.error)


def list_failed(limit: int = 100) -> list[DeadLetter]:
    """Read recent failures from the DLQ."""
    if not DLQ_PATH.exists():
        return []
    letters = []
    with open(DLQ_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                letters.append(DeadLetter(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
    return letters[-limit:]


def clear() -> int:
    """Clear the DLQ, return count of items removed."""
    if not DLQ_PATH.exists():
        return 0
    count = sum(1 for _ in open(DLQ_PATH))
    DLQ_PATH.unlink()
    log.info("DLQ cleared: %d items removed", count)
    return count
