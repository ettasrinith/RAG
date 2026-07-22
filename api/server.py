from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.errors import AIPError, aip_error_handler
from api.routers import collections, search, documents, papers, jobs, chat, web, legacy
from api.routers import health, sessions, agent, admin
from api.middleware import setup_middleware
from core.config import load_config
from core.logging import setup_logging, get_logger

# Initialize logging
setup_logging(level="INFO")
log = get_logger("server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    log.info("Knowledge Hub starting (v2.0.0)")
    yield
    # Graceful shutdown
    log.info("Knowledge Hub shutting down gracefully...")
    try:
        from api.routers.legacy import _stop_event
        _stop_event.set()
    except Exception:
        pass
    await asyncio.sleep(1)
    log.info("Shutdown complete")


app = FastAPI(
    title="Knowledge Hub",
    version="2.0.0",
    description="Production-grade RAG platform with resource-oriented API",
    lifespan=lifespan,
)

app.add_exception_handler(AIPError, aip_error_handler)

# ── Middleware (order matters: outermost first) ──────────────
config = load_config()
setup_middleware(app, config)

# ── Routers ─────────────────────────────────────────────────
app.include_router(collections.router)
app.include_router(search.router)
app.include_router(documents.router)
app.include_router(papers.router)
app.include_router(jobs.router)
app.include_router(chat.router)
app.include_router(web.router)
app.include_router(legacy.router)
app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(agent.router)
app.include_router(admin.router)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    index = UI_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h1>Knowledge Hub</h1><p>API ready — see /docs for OpenAPI.</p>"
