from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class AIPError(HTTPException):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(status_code=status_code, detail=self._body())

    def _body(self) -> dict:
        status_map = {
            400: "INVALID_ARGUMENT",
            401: "UNAUTHENTICATED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            409: "ALREADY_EXISTS",
            429: "RESOURCE_EXHAUSTED",
            500: "INTERNAL",
            501: "UNIMPLEMENTED",
            503: "UNAVAILABLE",
        }
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": status_map.get(self.status_code, "UNKNOWN"),
                "details": self.details or {},
            }
        }


def not_found(resource: str, id: str) -> AIPError:
    return AIPError(
        code="NOT_FOUND",
        message=f"{resource} '{id}' not found",
        status_code=404,
    )


def already_exists(resource: str, name: str) -> AIPError:
    return AIPError(
        code="ALREADY_EXISTS",
        message=f"{resource} '{name}' already exists",
        status_code=409,
    )


def invalid_argument(detail: str) -> AIPError:
    return AIPError(
        code="INVALID_ARGUMENT",
        message=detail,
        status_code=400,
    )


async def aip_error_handler(request, exc: AIPError):
    return JSONResponse(status_code=exc.status_code, content=exc._body())
