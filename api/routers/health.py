"""Comprehensive health check endpoints for each subsystem."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.deps import get_store, get_research_store
from core.vector_store import VectorStore

router = APIRouter(prefix="/v1", tags=["health"])

_start_time = time.time()


class ComponentHealth(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    latency_ms: float | None = None
    detail: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str = "2.0.0"
    uptime_s: float
    components: dict[str, ComponentHealth]


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Full health check — probes all subsystems."""
    components: dict[str, ComponentHealth] = {}

    # Vector store (knowledge)
    try:
        store = get_store()
        t0 = time.perf_counter()
        count = store.count()
        components["vector_store"] = ComponentHealth(
            status="healthy",
            latency_ms=(time.perf_counter() - t0) * 1000,
            detail=f"{count} rows",
        )
    except Exception as e:
        components["vector_store"] = ComponentHealth(status="unhealthy", detail=str(e))

    # Research store
    try:
        rstore = get_research_store()
        t0 = time.perf_counter()
        count = rstore.count()
        components["research_store"] = ComponentHealth(
            status="healthy",
            latency_ms=(time.perf_counter() - t0) * 1000,
            detail=f"{count} rows",
        )
    except Exception as e:
        components["research_store"] = ComponentHealth(status="degraded", detail=str(e))

    # Database
    try:
        from core.registry.database import get_session
        session = get_session()
        t0 = time.perf_counter()
        session.execute("SELECT 1")
        session.close()
        components["database"] = ComponentHealth(
            status="healthy",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        components["database"] = ComponentHealth(status="unhealthy", detail=str(e))

    # Embedding model
    try:
        from core.embedder import get_model
        t0 = time.perf_counter()
        get_model()
        components["embedding_model"] = ComponentHealth(
            status="healthy",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        components["embedding_model"] = ComponentHealth(status="degraded", detail=str(e))

    overall = "healthy"
    if any(c.status == "unhealthy" for c in components.values()):
        overall = "unhealthy"
    elif any(c.status == "degraded" for c in components.values()):
        overall = "degraded"

    return HealthResponse(
        status=overall,
        uptime_s=round(time.time() - _start_time, 1),
        components=components,
    )


@router.get("/health/ready")
async def readiness():
    """Kubernetes-style readiness probe."""
    try:
        store = get_store()
        store.count()
        return {"ready": True}
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False})


@router.get("/health/live")
async def liveness():
    """Kubernetes-style liveness probe."""
    return {"alive": True}
