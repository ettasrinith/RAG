"""Agentic RAG — LLM-driven multi-step reasoning with tool orchestration.

The agent loop:
1. LLM receives the user question + available tools
2. LLM decides which tool(s) to call (or answers directly)
3. Tool results are fed back to the LLM
4. Loop continues until the LLM produces a final answer
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from core.agents.tools import ToolRegistry
from core.logging import get_logger

log = get_logger("agent")

AGENT_SYSTEM_PROMPT = """You are an intelligent research assistant with access to tools.

## Available Tools
You can call tools to search knowledge bases, find academic papers, run calculations,
query the knowledge graph, summarize text, and compare documents.

## How to Use Tools
- To call a tool, respond with a JSON block: {"tool": "tool_name", "arguments": {...}}
- You may call multiple tools in sequence
- After receiving tool results, analyze them and either call more tools or provide your final answer

## Rules
1. Always use tools to find facts before answering — don't guess
2. Cite sources using [1], [2] etc. matching the numbered source list
3. If a tool returns an error, try an alternative approach
4. For complex questions, break them into sub-questions and use tools for each
5. When you have enough information, provide a clear, concise final answer
6. For calculations, use the execute_python tool
7. For comparing things, gather info first with search, then use compare_texts

## Response Format
- When calling a tool: {"tool": "tool_name", "arguments": {"param": "value"}}
- When done: provide your final answer as plain text with [1], [2] citations
"""

MAX_TOOL_ROUNDS = 6
MAX_TOKENS_PER_ROUND = 4000


@dataclass
class ToolCall:
    tool: str
    arguments: dict
    result: Any = None
    error: str | None = None
    duration_ms: float = 0


@dataclass
class AgentTrace:
    """Full trace of an agentic reasoning session."""
    question: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: str = ""
    total_duration_ms: float = 0
    rounds: int = 0
    sources_used: list[dict] = field(default_factory=list)


class AgenticRAG:
    """Multi-step reasoning agent that orchestrates tools to answer questions."""

    def __init__(self, llm_client, tool_registry: ToolRegistry):
        self.llm = llm_client
        self.tools = tool_registry

    def run(self, question: str, k: int = 8) -> AgentTrace:
        """Run the full agentic loop and return a trace with the answer."""
        trace = AgentTrace(question=question)
        start = time.perf_counter()
        messages = self._init_messages(question)

        for round_num in range(MAX_TOOL_ROUNDS):
            trace.rounds = round_num + 1
            log.info("agent_round", extra={"round": round_num + 1, "question": question[:80]})

            # Get LLM response
            raw = self._llm_call(messages)
            parsed = self._parse_response(raw)

            if parsed.get("final_answer"):
                trace.final_answer = parsed["final_answer"]
                break

            if parsed.get("tool_call"):
                tc = self._execute_tool(parsed["tool_call"])
                trace.tool_calls.append(tc)

                if tc.result and isinstance(tc.result, dict):
                    for r in tc.result.get("results", []):
                        if r not in trace.sources_used:
                            trace.sources_used.append(r)

                # Feed tool result back to LLM
                tool_msg = self._format_tool_result(tc)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": tool_msg})
            else:
                # LLM gave a direct answer without tools
                trace.final_answer = parsed.get("text", raw)
                break
        else:
            # Max rounds reached — force a final answer
            messages.append({
                "role": "user",
                "content": "You've used enough tools. Now provide your final answer with citations.",
            })
            trace.final_answer = self._llm_call(messages)

        trace.total_duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "agent_complete",
            extra={
                "rounds": trace.rounds,
                "tool_calls": len(trace.tool_calls),
                "duration_ms": round(trace.total_duration_ms, 1),
            },
        )
        return trace

    def stream(self, question: str, k: int = 8) -> Iterator[dict]:
        """Stream the agentic process as SSE events."""
        trace = AgentTrace(question=question)
        start = time.perf_counter()
        messages = self._init_messages(question)

        for round_num in range(MAX_TOOL_ROUNDS):
            trace.rounds = round_num + 1

            # Stream the LLM response
            full_response = ""
            for chunk in self._llm_stream(messages):
                full_response += chunk
                yield {"type": "thinking", "text": chunk, "round": round_num + 1}

            parsed = self._parse_response(full_response)

            if parsed.get("final_answer"):
                trace.final_answer = parsed["final_answer"]
                yield {"type": "answer", "text": parsed["final_answer"]}
                break

            if parsed.get("tool_call"):
                tc = self._execute_tool(parsed["tool_call"])
                trace.tool_calls.append(tc)

                yield {
                    "type": "tool_call",
                    "tool": tc.tool,
                    "arguments": tc.arguments,
                    "duration_ms": round(tc.duration_ms, 1),
                }

                if tc.error:
                    yield {"type": "tool_error", "tool": tc.tool, "error": tc.error}
                else:
                    yield {"type": "tool_result", "tool": tc.tool, "result": tc.result}

                if tc.result and isinstance(tc.result, dict):
                    for r in tc.result.get("results", []):
                        if r not in trace.sources_used:
                            trace.sources_used.append(r)

                tool_msg = self._format_tool_result(tc)
                messages.append({"role": "assistant", "content": full_response})
                messages.append({"role": "user", "content": tool_msg})
            else:
                trace.final_answer = parsed.get("text", full_response)
                yield {"type": "answer", "text": trace.final_answer}
                break
        else:
            messages.append({
                "role": "user",
                "content": "Now provide your final answer with citations.",
            })
            answer = ""
            for chunk in self._llm_stream(messages):
                answer += chunk
                yield {"type": "answer", "text": chunk}
            trace.final_answer = answer

        trace.total_duration_ms = (time.perf_counter() - start) * 1000
        yield {
            "type": "done",
            "trace": {
                "rounds": trace.rounds,
                "tool_calls": len(trace.tool_calls),
                "sources": trace.sources_used,
                "duration_ms": round(trace.total_duration_ms, 1),
            },
        }

    def _init_messages(self, question: str) -> list[dict]:
        tool_schemas = json.dumps(self.tools.list_schemas(), indent=2)
        return [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Available tools:\n{tool_schemas}\n\nQuestion: {question}",
            },
        ]

    def _llm_call(self, messages: list[dict]) -> str:
        """Non-streaming LLM call."""
        prompt = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        return self.llm.complete(prompt, system_prompt=system)

    def _llm_stream(self, messages: list[dict]) -> Iterator[str]:
        """Streaming LLM call."""
        prompt = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        # Use the non-streaming complete for reliability, then yield
        result = self.llm.complete(prompt, system_prompt=system)
        yield result

    def _parse_response(self, text: str) -> dict:
        """Parse LLM response for tool calls or final answer."""
        text = text.strip()

        # Try to find a JSON tool call
        json_match = self._extract_json(text)
        if json_match and "tool" in json_match:
            return {"tool_call": json_match}

        # Check if it looks like a tool call pattern
        if '{"tool":' in text or '{"tool":' in text:
            json_match = self._extract_json(text)
            if json_match:
                return {"tool_call": json_match}

        # It's a direct answer
        return {"final_answer": text}

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try code block
        import re
        blocks = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        for block in blocks:
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

        # Try inline JSON
        start = text.find('{"tool":')
        if start == -1:
            start = text.find('{"tool":')
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    def _execute_tool(self, tool_call: dict) -> ToolCall:
        """Execute a tool and return the result."""
        name = tool_call.get("tool", "")
        args = tool_call.get("arguments", {})
        tc = ToolCall(tool=name, arguments=args)

        start = time.perf_counter()
        result = self.tools.execute(name, args)
        tc.duration_ms = (time.perf_counter() - start) * 1000

        if isinstance(result, dict) and "error" in result:
            tc.error = result["error"]
        else:
            tc.result = result

        return tc

    def _format_tool_result(self, tc: ToolCall) -> str:
        """Format a tool result for the LLM."""
        if tc.error:
            return f"Tool '{tc.tool}' returned an error: {tc.error}\nPlease try a different approach."

        result_str = json.dumps(tc.result, indent=2, default=str)
        if len(result_str) > 6000:
            result_str = result_str[:6000] + "\n... (truncated)"

        return f"Tool '{tc.tool}' result:\n{result_str}\n\nAnalyze these results and either call another tool or provide your final answer."
