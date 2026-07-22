from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    status: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PaginationResponse(BaseModel):
    page_size: int
    page_token: str | None = None
    next_page_token: str | None = None


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    pagination: PaginationResponse | None = None


class OperationResponse(BaseModel):
    status: str = "ok"
    message: str | None = None
