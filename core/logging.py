"""Simple structured logging for Knowledge Hub."""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once."""
    logger = logging.getLogger("kh")
    if logger.handlers:
        return  # already configured

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("lancedb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger of the 'kh' namespace, e.g. kh.indexer."""
    return logging.getLogger(f"kh.{name}")
