from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    collections: list[str] = Field(default_factory=lambda: ["*"])
    k: int = Field(default=8, ge=1, le=50)
    filter: str | None = None
    stream: bool = True


class ChatSource(BaseModel):
    title: str
    url: str
    source: str
    snippet: str
    score: float | None = None
