"""Token-aware text chunker."""
from __future__ import annotations

import tiktoken

# cl100k is OpenAI's tokenizer, close enough for any modern embedding model
_ENC = tiktoken.get_encoding("cl100k_base")


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """Split text into ~chunk_size token chunks with token overlap."""
    if not text or not text.strip():
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    tokens = _ENC.encode(text, disallowed_special=())
    if len(tokens) <= chunk_size:
        return [text]

    chunks = []
    step = chunk_size - overlap
    for start in range(0, len(tokens), step):
        end = start + chunk_size
        piece = _ENC.decode(tokens[start:end])
        if piece.strip():
            chunks.append(piece)
        if end >= len(tokens):
            break
    return chunks
