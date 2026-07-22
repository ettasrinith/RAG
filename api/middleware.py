"""Production middleware stack for Knowledge Hub.

Provides CORS, request ID tracking, security headers, and optional rate limiting.
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging import get_logger

log = get_logger("middleware")


def setup_middleware(app: FastAPI, config: dict) -> None:
    """Install all middleware in correct order (outermost first)."""

    # 1. CORS (must be outermost)
    cors_config = config.get("cors", {})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config.get("origins", ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )

    # 2. Request ID + Logging
    app.add_middleware(RequestContextMiddleware)

    # 3. Security Headers
    app.add_middleware(SecurityHeadersMiddleware)

    # 4. Rate Limiting (opt-in)
    rate_config = config.get("rate_limit", {})
    if rate_config.get("enabled", False):
        app.add_middleware(RateLimitMiddleware, config=rate_config)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds X-Request-ID, logs request/response, tracks timing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request.state.request_id = request_id
        start = time.perf_counter()

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

        log.info(
            "request %s %s -> %s (%.1fms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter."""

    def __init__(self, app, config: dict):
        super().__init__(app)
        self.requests_per_minute = config.get("requests_per_minute", 120)
        self._windows: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ("/v1/health", "/health", "/v1/health/live"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = self._windows.setdefault(client_ip, [])

        # Remove entries older than 60s
        cutoff = now - 60.0
        self._windows[client_ip] = [t for t in window if t > cutoff]
        window = self._windows[client_ip]

        if len(window) >= self.requests_per_minute:
            return Response(
                content='{"error":{"code":"RATE_LIMITED","message":"Too many requests"}}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        window.append(now)
        return await call_next(request)
