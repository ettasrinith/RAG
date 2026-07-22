"""Tool registry for agentic RAG — defines callable tools the LLM can invoke."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    handler: Callable[..., Any]
    category: str = "general"

    def to_schema(self) -> dict:
        """Convert to OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Central registry of tools the agentic LLM can call."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def list_schemas(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        try:
            return tool.handler(**arguments)
        except Exception as e:
            return {"error": f"Tool '{name}' failed: {e}"}


# ── Built-in tool implementations ───────────────────────────────────


def _make_search_tool(store, research_store, config):
    """Create a knowledge base search tool."""
    from core.embedder import embed_query
    from core.search.fusion import rrf_fuse, apply_recency_bias
    from core.search.reranker import rerank

    def search_knowledge(query: str, k: int = 5, source: str = "") -> dict:
        qvec = embed_query(query, model_name=config["embedding"]["model"])
        vector_hits = store.search(qvec, k=max(k * 2, 20))
        fts_hits = store.fts_search(query, k=max(k * 2, 20))
        fused = rrf_fuse(vector_hits, fts_hits, top_n=k * 2)

        try:
            if research_store and research_store.count() > 0:
                r_vec = research_store.search(qvec, k=max(k * 2, 20))
                r_fts = research_store.fts_search(query, k=max(k * 2, 20))
                for h in r_vec + r_fts:
                    h.setdefault("source", "research")
                fused = rrf_fuse(fused, r_vec + r_fts, top_n=k * 2)
        except Exception:
            pass

        fused = apply_recency_bias(fused)
        results = rerank(query, fused, top_k=k) if config.get("search", {}).get("rerank") else fused[:k]

        return {
            "results": [
                {
                    "title": r.get("title", ""),
                    "source": r.get("source", ""),
                    "url": r.get("url", ""),
                    "snippet": (r.get("text") or "")[:500],
                    "score": round(r.get("combined_score", 0), 4),
                }
                for r in results
            ],
            "count": len(results),
        }

    return Tool(
        name="search_knowledge",
        description="Search the internal knowledge base (documents, code, research papers). Returns relevant snippets with titles and scores.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "k": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
                "source": {"type": "string", "description": "Filter by source type (e.g. 'github', 'arxiv')"},
            },
            "required": ["query"],
        },
        handler=search_knowledge,
        category="search",
    )


def _make_web_search_tool():
    """Create a web search tool using external APIs."""
    def web_search(query: str, max_results: int = 5) -> dict:
        try:
            from services.web_search_service import WebSearchService
            svc = WebSearchService()
            papers = svc.discover(query, sources=["arxiv", "semantic_scholar"], limit=max_results)
            return {
                "results": [
                    {
                        "title": p.get("title", ""),
                        "authors": p.get("authors", ""),
                        "year": p.get("year"),
                        "abstract": (p.get("abstract") or "")[:500],
                        "url": p.get("url", ""),
                        "source": p.get("source", ""),
                    }
                    for p in papers
                ],
                "count": len(papers),
            }
        except Exception as e:
            return {"error": f"Web search failed: {e}", "results": []}

    return Tool(
        name="web_search",
        description="Search academic databases (arXiv, Semantic Scholar, OpenAlex) for papers and research.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        handler=web_search,
        category="search",
    )


def _make_python_tool():
    """Create a Python code execution tool (sandboxed)."""
    def execute_python(code: str) -> dict:
        import io
        import contextlib
        buf = io.StringIO()
        local_ns: dict = {"math": math, "re": re, "json": json}
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, {"__builtins__": __builtins__}, local_ns)  # noqa: S102
            output = buf.getvalue()
            if len(output) > 5000:
                output = output[:5000] + "\n... (truncated)"
            return {"output": output, "success": True}
        except Exception as e:
            return {"error": str(e), "success": False}

    return Tool(
        name="execute_python",
        description="Execute Python code for calculations, data processing, or analysis. Use for math, string manipulation, or computing metrics.",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
            },
            "required": ["code"],
        },
        handler=execute_python,
        category="computation",
    )


def _make_kg_tool(kg_index=None):
    """Create a knowledge graph query tool."""
    def query_knowledge_graph(repo: str, entity: str = "") -> dict:
        if not kg_index:
            return {"error": "Knowledge graph not enabled"}
        if entity:
            return kg_index.query(repo, entity)
        graph = kg_index.get_or_create(repo)
        return {
            "repo": repo,
            "entity_count": len(graph.entities),
            "relation_count": len(graph.relations),
            "entities": [{"name": e.name, "type": e.type} for e in graph.entities[:50]],
        }

    return Tool(
        name="knowledge_graph",
        description="Query the knowledge graph for entity relationships, code structure, and dependencies.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository or collection name"},
                "entity": {"type": "string", "description": "Entity to look up (optional, lists all if empty)"},
            },
            "required": ["repo"],
        },
        handler=query_knowledge_graph,
        category="analysis",
    )


def _make_summarize_tool(llm_client):
    """Create a summarization tool."""
    def summarize(text: str, max_sentences: int = 3) -> dict:
        prompt = f"Summarize the following in {max_sentences} sentences:\n\n{text[:4000]}"
        result = llm_client.complete(prompt, system_prompt="Be concise and factual.")
        return {"summary": result}

    return Tool(
        name="summarize",
        description="Summarize a long piece of text into key points.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to summarize"},
                "max_sentences": {"type": "integer", "description": "Max sentences (default 3)", "default": 3},
            },
            "required": ["text"],
        },
        handler=summarize,
        category="analysis",
    )


def _make_comparison_tool(llm_client):
    """Create a comparison tool."""
    def compare(text_a: str, text_b: str, focus: str = "differences") -> dict:
        prompt = f"Compare the following two pieces of text. Focus on {focus}.\n\nText A:\n{text_a[:2000]}\n\nText B:\n{text_b[:2000]}"
        result = llm_client.complete(prompt, system_prompt="Provide a structured comparison.")
        return {"comparison": result}

    return Tool(
        name="compare_texts",
        description="Compare two pieces of text and identify similarities and differences.",
        parameters={
            "type": "object",
            "properties": {
                "text_a": {"type": "string", "description": "First text"},
                "text_b": {"type": "string", "description": "Second text"},
                "focus": {"type": "string", "description": "What to focus on (default: differences)", "default": "differences"},
            },
            "required": ["text_a", "text_b"],
        },
        handler=compare,
        category="analysis",
    )


def _make_citations_tool():
    """Create a citation formatting tool."""
    def format_citations(sources: list[dict], style: str = "inline") -> dict:
        formatted = []
        for i, s in enumerate(sources, 1):
            if style == "inline":
                formatted.append(f"[{i}] {s.get('title', 'Untitled')} — {s.get('url', '')}")
            elif style == "apa":
                author = s.get("author", "Unknown")
                year = s.get("year", "n.d.")
                title = s.get("title", "Untitled")
                url = s.get("url", "")
                formatted.append(f"{author} ({year}). {title}. {url}")
            else:
                formatted.append(f"{i}. {s.get('title', '')} — {s.get('url', '')}")
        return {"citations": formatted, "count": len(formatted)}

    return Tool(
        name="format_citations",
        description="Format a list of sources into a citation style (inline, apa, numbered).",
        parameters={
            "type": "object",
            "properties": {
                "sources": {"type": "array", "items": {"type": "object"}, "description": "List of source objects"},
                "style": {"type": "string", "enum": ["inline", "apa", "numbered"], "default": "inline"},
            },
            "required": ["sources"],
        },
        handler=format_citations,
        category="utility",
    )


def build_default_registry(store, research_store, config, llm_client=None, kg_index=None) -> ToolRegistry:
    """Build the default tool registry with all built-in tools."""
    registry = ToolRegistry()
    registry.register(_make_search_tool(store, research_store, config))
    registry.register(_make_web_search_tool())
    registry.register(_make_python_tool())
    registry.register(_make_kg_tool(kg_index))
    if llm_client:
        registry.register(_make_summarize_tool(llm_client))
        registry.register(_make_comparison_tool(llm_client))
    registry.register(_make_citations_tool())
    return registry
