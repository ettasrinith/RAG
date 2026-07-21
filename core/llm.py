"""LLM provider abstraction — Claude / OpenAI / LiteLLM."""
from __future__ import annotations

import os
import time
from typing import Iterator

SYSTEM_PROMPT = """You are a knowledge assistant for a software team. Answer the
user's question using ONLY the provided sources. Cite sources inline as [1], [2]
matching the numbered list. If the answer isn't in the sources, say so plainly —
don't make things up. Keep answers focused and link the user to the source for
deeper reading."""

GENERIC_COMPLETION_PROMPT = "You are a concise assistant. Follow the user's instructions exactly."

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_TIMEOUT = 60.0


def _format_sources(sources: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        header = f"[{i}] {s.get('title', '')} · {s.get('source', '')}"
        url = s.get("url") or ""
        if url:
            header += f" · {url}"
        blocks.append(f"{header}\n{s.get('text', '')}")
    return "\n\n---\n\n".join(blocks)


class LLMClient:
    def __init__(self, config: dict):
        self.provider = config.get("provider", "anthropic")
        self.model = config.get("model", "claude-sonnet-latest")
        self.max_tokens = int(config.get("max_tokens", 2000))
        self.temperature = float(config.get("temperature", 0.2))
        self.base_url = config.get("base_url", "")
        self.api_key = (config.get("api_key") or "").strip()

    def answer(self, question: str, sources: list[dict]) -> Iterator[str]:
        context = _format_sources(sources)
        user_msg = f"""Sources:

{context}

Question: {question}

Answer with inline citations like [1], [2]."""

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                if self.provider == "anthropic":
                    yield from self._anthropic_stream(user_msg)
                elif self.provider in ("openai", "litellm", "ollama"):
                    yield from self._openai_stream(user_msg)
                else:
                    raise ValueError(f"unknown LLM provider: {self.provider}")
                return
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                    continue
                raise last_error

    def answer_sync(self, question: str, sources: list[dict]) -> str:
        result = ""
        for token in self.answer(question, sources):
            result += token
        return result

    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        system_prompt = system_prompt or GENERIC_COMPLETION_PROMPT
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                if self.provider == "anthropic":
                    return self._anthropic_complete(prompt, system_prompt)
                if self.provider in ("openai", "litellm", "ollama"):
                    return self._openai_complete(prompt, system_prompt)
                raise ValueError(f"unknown LLM provider: {self.provider}")
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                    continue
                raise last_error

    def _anthropic_stream(self, user_msg: str) -> Iterator[str]:
        import anthropic

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            timeout=_TIMEOUT,
        )
        with client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    def _anthropic_complete(self, prompt: str, system_prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            timeout=_TIMEOUT,
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for block in getattr(resp, "content", []) or []:
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
        return "".join(parts).strip()

    def _openai_stream(self, user_msg: str) -> Iterator[str]:
        from openai import OpenAI

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY") or \
            os.environ.get("LITELLM_API_KEY") or os.environ.get("OLLAMA_API_KEY", "dummy")
        kwargs: dict = {"api_key": api_key, "timeout": _TIMEOUT}
        base = self.base_url or os.environ.get("LITELLM_BASE_URL") or os.environ.get("OLLAMA_BASE_URL")
        if base:
            kwargs["base_url"] = base

        client = OpenAI(**kwargs)
        stream = client.chat.completions.create(
            model=self.model,
            max_completion_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=True,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def _openai_complete(self, prompt: str, system_prompt: str) -> str:
        from openai import OpenAI

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY") or \
            os.environ.get("LITELLM_API_KEY") or os.environ.get("OLLAMA_API_KEY", "dummy")
        kwargs: dict = {"api_key": api_key, "timeout": _TIMEOUT}
        base = self.base_url or os.environ.get("LITELLM_BASE_URL") or os.environ.get("OLLAMA_BASE_URL")
        if base:
            kwargs["base_url"] = base

        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=self.model,
            max_completion_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip() if resp.choices else ""
