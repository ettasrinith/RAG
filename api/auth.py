"""Authentication and authorization middleware.

Provides timing-safe API key verification for both legacy and v1 endpoints.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader, APIKeyQuery

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="token", auto_error=False)


def get_api_key() -> str | None:
    """Get the configured API key (None = auth disabled)."""
    key = os.environ.get("KH_API_KEY", "").strip()
    return key or None


async def verify_api_key(
    request: Request,
    header_key: str | None = Security(API_KEY_HEADER),
    query_key: str | None = Security(API_KEY_QUERY),
) -> None:
    """Verify API key using timing-safe comparison.

    If KH_API_KEY is not set, all requests are allowed (auth disabled).
    """
    configured_key = get_api_key()
    if configured_key is None:
        return  # Auth disabled

    provided = header_key or query_key or ""

    # Timing-safe comparison to prevent timing attacks
    if not hmac.compare_digest(provided.encode(), configured_key.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
