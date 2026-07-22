"""Agentic RAG API — LLM-driven multi-step reasoning with tool orchestration."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_llm, get_store, get_research_store
from core.agents.agent import AgenticRAG
from core.agents.tools import build_default_registry
from core.config import load_config
from core.llm import LLMClient
from core.vector_store import VectorStore

router = APIRouter(prefix="/v1/agent", tags=["agent"])


class AgentRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=5000)
    k: int = Field(default=8, ge=1, le=50)
    stream: bool = Field(default=True)


class AgentResponse(BaseModel):
    answer: str
    sources: list[dict] = []
    tool_calls: list[dict] = []
    rounds: int = 0
    duration_ms: float = 0


def _sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _get_agent(
    llm: LLMClient,
    store: VectorStore,
    research_store: VectorStore,
) -> AgenticRAG:
    config = load_config()
    kg_index = None
    try:
        if config.get("knowledge_graph", {}).get("enabled"):
            from core.knowledge_graph import KnowledgeGraphIndex
            kg_index = KnowledgeGraphIndex()
    except Exception:
        pass

    registry = build_default_registry(
        store=store,
        research_store=research_store,
        config=config,
        llm_client=llm,
        kg_index=kg_index,
    )
    return AgenticRAG(llm_client=llm, tool_registry=registry)


@router.post(":ask")
def agent_ask(
    req: AgentRequest,
    llm: LLMClient = Depends(get_llm),
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    agent = _get_agent(llm, store, research_store)

    if not req.stream:
        trace = agent.run(req.q, k=req.k)
        return AgentResponse(
            answer=trace.final_answer,
            sources=trace.sources_used[:req.k],
            tool_calls=[
                {"tool": tc.tool, "arguments": tc.arguments, "duration_ms": tc.duration_ms}
                for tc in trace.tool_calls
            ],
            rounds=trace.rounds,
            duration_ms=trace.total_duration_ms,
        )

    def stream():
        for event in agent.stream(req.q, k=req.k):
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get(":tools")
def list_tools(
    llm: LLMClient = Depends(get_llm),
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    agent = _get_agent(llm, store, research_store)
    return {
        "tools": [
            {"name": t.name, "description": t.description, "category": t.category}
            for t in agent.tools.list_tools()
        ]
    }
