"""Contextual RAG — generates per-chunk LLM summaries and embeds them *with* the
chunk so retrieval actually benefits (Anthropic-style contextual retrieval).

The summary is emitted per chunk (not once per document) and concatenated with
the chunk text before embedding, which is what makes similarity search surface
the right chunks.
"""
from __future__ import annotations

import re

from core.llm import LLMClient
from core.logging import get_logger

log = get_logger("contextual_rag")


DEFAULT_SUMMARY_PROMPT = (
    "Summarize what the following code/document snippet does in one concise sentence."
)


class ContextualRAG:
    def __init__(self, llm_config: dict, prompt: str | None = None,
                 batch_size: int = 10):
        self.llm = LLMClient(llm_config)
        self.prompt = prompt or DEFAULT_SUMMARY_PROMPT
        self.batch_size = batch_size

    def summarize_chunk(self, chunk_text: str) -> str:
        summaries = self.summarize_batch([chunk_text])
        return summaries[0] if summaries else (chunk_text[:200] if chunk_text else "")

    def summarize_batch(self, chunks: list[str]) -> list[str]:
        if not chunks:
            return []
        results: list[str] = []
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i:i + self.batch_size]
            numbered = "\n".join(f"{j + 1}. {t[:800]}" for j, t in enumerate(batch))
            prompt_text = (
                f"{self.prompt}\n"
                "Reply with exactly one short sentence per snippet, prefixed by its "
                f"number (e.g. '1. ...'). Do not add extra commentary.\n\n{numbered}"
            )
            try:
                response = self.llm.complete(prompt_text, system_prompt=self.prompt)
            except Exception as e:
                log.warning("LLM completion failed: %s", e)
                response = ""
            results.extend(self._parse_numbered(response, len(batch)))
        return results

    @staticmethod
    def _parse_numbered(text: str, n: int) -> list[str]:
        out: list[str] = ["" for _ in range(n)]
        # Try structured numbered format first (e.g. "1. summary", "2) summary")
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)[.)]\s*(.*)", line)
            if not m:
                continue
            idx = int(m.group(1)) - 1
            val = m.group(2).strip()
            if 0 <= idx < n and val:
                out[idx] = val[:200]
        # Fallback: if numbered parsing yielded nothing, try heuristics
        if not any(out) and text.strip():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            # One line per chunk (bullet list or plain list)
            if len(lines) >= n:
                for i in range(min(n, len(lines))):
                    candidate = re.sub(r"^[-*\d.)\s]+", "", lines[i]).strip()
                    if candidate:
                        out[i] = candidate[:200]
            # Single block of text — fall back to placing it as first summary
            if not any(out):
                out[0] = text.strip()[:200]
        return out

    def enrich_chunks(self, chunks: list[dict]) -> list[dict]:
        texts = [c.get("text", "") for c in chunks]
        summaries = self.summarize_batch(texts)
        enriched = []
        for chunk, summary in zip(chunks, summaries):
            chunk["summary"] = summary
            enriched.append(chunk)
        return enriched
