from __future__ import annotations

import re


def extract_highlights(text: str, query: str) -> list[dict[str, int]]:
    if not query or not text:
        return []
    terms = [t for t in re.split(r'\s+', query.strip().lower()) if len(t) > 2]
    if not terms:
        return []
    text_lower = text.lower()
    highlights: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for term in terms:
        for m in re.finditer(re.escape(term), text_lower):
            span = (m.start(), m.end())
            if span not in seen:
                seen.add(span)
                highlights.append({"char_start": m.start(), "char_end": m.end()})
    highlights.sort(key=lambda h: h["char_start"])
    return highlights


def build_snippet_with_highlights(text: str, query: str, max_len: int = 300) -> str:
    if not text:
        return ""
    highlights = extract_highlights(text, query)
    if not highlights:
        return text[:max_len]
    first_hl = highlights[0]["char_start"]
    start = max(0, first_hl - 80)
    snippet = text[start:start + max_len]
    return snippet
