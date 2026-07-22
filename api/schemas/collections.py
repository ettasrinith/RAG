from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: str = Field(default="notes", pattern=r"^(github|notes|folder|papers|web_cache)$")
    source_config: dict[str, Any] = Field(default_factory=dict)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = Field(default=None, pattern=r"^(github|notes|folder|papers|web_cache)$")
    source_config: dict[str, Any] | None = None


class CollectionResponse(BaseModel):
    id: str
    name: str
    kind: str
    source_config: dict[str, Any]
    doc_count: int
    last_indexed_at: datetime | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class CollectionStats(BaseModel):
    id: str
    name: str
    doc_count: int
    last_indexed_at: datetime | None = None
    status: str
