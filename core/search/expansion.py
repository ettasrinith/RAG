"""Query expansion — LLM-generated query variations for better recall.

Generates multiple query formulations from a single user query, then
fuses results from all variations to improve recall of semantically
related content that a single query might miss.
"""
from __future__ import annotations

import json
from typing import Iterator

from core.logging import get_logger

log = get_logger("expansion")

EXPANSION_PROMPT = """You are a search query expansion assistant. Given a user's question, generate {n} alternative search queries that capture different aspects and phrasings of the same topic.

Rules:
- Each query should be concise (3-15 words)
- Vary terminology: use synonyms, technical terms, and natural language phrasings
- Include related concepts the user might not have mentioned
- Keep queries focused and specific
- Do NOT include the original query in your variations

User question: {question}

Return ONLY a JSON array of strings, no other text. Example:
["query variation 1", "query variation 2", "query variation 3"]"""

REWRITE_PROMPT = """Rewrite this search query to be more effective for vector similarity search. Make it more specific, add relevant technical terms, and clarify intent. Return ONLY the rewritten query, nothing else.

Original query: {question}"""

HYPOTHETICAL_PROMPT = """Answer this question in 2-3 sentences as if you were writing a document that would contain the answer. This will be used for hypothetical document embedding (HyDE).

Question: {question}"""


class QueryExpander:
    """Generates query variations using LLM for improved search recall."""

    def __init__(self, llm_client):
        self.llm = llm_client

    def expand(self, query: str, n: int = 3) -> list[str]:
        """Generate n alternative query formulations."""
        prompt = EXPANSION_PROMPT.format(n=n, question=query)
        try:
            raw = self.llm.complete(prompt, system_prompt="You are a search query expansion assistant.")
            # Parse JSON array from response
            queries = self._parse_json_array(raw)
            if queries:
                log.info("query_expanded", extra={"original": query, "variations": len(queries)})
                return queries[:n]
        except Exception as e:
            log.warning("query_expansion_failed", extra={"error": str(e)})

        # Fallback: return the original query
        return [query]

    def rewrite(self, query: str) -> str:
        """Rewrite a query for better vector search performance."""
        prompt = REWRITE_PROMPT.format(question=query)
        try:
            result = self.llm.complete(prompt, system_prompt="You are a search query rewriter.")
            rewritten = result.strip().strip('"').strip("'")
            if rewritten and len(rewritten) > 5:
                log.info("query_rewritten", extra={"original": query, "rewritten": rewritten})
                return rewritten
        except Exception as e:
            log.warning("query_rewrite_failed", extra={"error": str(e)})
        return query

    def hypothetical_document(self, query: str) -> str:
        """Generate a hypothetical answer for HyDE (Hypothetical Document Embeddings)."""
        prompt = HYPOTHETICAL_PROMPT.format(question=query)
        try:
            result = self.llm.complete(prompt, system_prompt="Write factual, informative text.")
            if result.strip():
                log.info("hyde_generated", extra={"query": query[:50]})
                return result.strip()
        except Exception as e:
            log.warning("hyde_failed", extra={"error": str(e)})
        return query

    def expand_and_rewrite(self, query: str, n: int = 3) -> list[str]:
        """Expand a query into multiple variations, including a rewritten version."""
        variations = [query]

        # Add the rewritten query
        rewritten = self.rewrite(query)
        if rewritten != query:
            variations.append(rewritten)

        # Add LLM-generated variations
        expanded = self.expand(query, n=n)
        for eq in expanded:
            if eq.lower() not in [v.lower() for v in variations]:
                variations.append(eq)

        log.info(
            "query_expansion_complete",
            extra={"original": query, "total_variations": len(variations)},
        )
        return variations

    def _parse_json_array(self, text: str) -> list[str] | None:
        """Parse a JSON array from LLM response, handling markdown blocks."""
        import re
        # Try code block
        blocks = re.findall(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        for block in blocks:
            try:
                result = json.loads(block)
                if isinstance(result, list):
                    return [str(q) for q in result if q]
            except json.JSONDecodeError:
                continue

        # Try inline array
        start = text.find('[')
        end = text.rfind(']')
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return [str(q) for q in result if q]
            except json.JSONDecodeError:
                pass

        return None


def multi_query_search(
    query: str,
    store,
    embed_fn,
    search_fn,
    expander: QueryExpander | None = None,
    n_variations: int = 3,
    top_k: int = 10,
) -> list[dict]:
    """Search with multiple query variations and fuse results.

    Args:
        query: Original user query
        store: VectorStore instance
        embed_fn: Function to embed a query string -> vector
        search_fn: Function(vector, k) -> list[dict] for search
        expander: QueryExpander instance (if None, uses only original query)
        n_variations: Number of query variations to generate
        top_k: Final number of results to return

    Returns:
        Merged and deduplicated results sorted by score
    """
    from core.search.fusion import rrf_fuse

    # Generate query variations
    queries = [query]
    if expander:
        try:
            queries = expander.expand_and_rewrite(query, n=n_variations)
        except Exception as e:
            log.warning("multi_query_expansion_failed", extra={"error": str(e)})

    # Search with each variation
    all_results: list[dict] = []
    for q in queries:
        try:
            qvec = embed_fn(q)
            hits = search_fn(qvec, k=top_k * 2)
            for h in hits:
                h["_query_variant"] = q
            all_results.append(hits)
        except Exception as e:
            log.warning("multi_query_search_variant_failed", extra={"query": q, "error": str(e)})

    if not all_results:
        return []

    # Fuse results using RRF across all variations
    fused = all_results[0]
    for additional in all_results[1:]:
        fused = rrf_fuse(fused, additional, top_n=top_k * 2)

    return fused[:top_k]
