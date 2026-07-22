from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class JobResponse(BaseModel):
    id: str
    collection_id: str
    collection_name: str = ""
    state: str
    items_done: int = 0
    items_total: int = 0
    progress: float = 0.0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class CancelJobResponse(BaseModel):
    status: str = "cancelled"
    job_id: str
