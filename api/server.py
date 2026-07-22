from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.errors import AIPError, aip_error_handler
from api.routers import collections, search, documents, papers, jobs, chat, web, legacy

app = FastAPI(
    title="Knowledge Hub",
    version="2.0.0",
    description="Production-grade RAG platform with resource-oriented API",
)

app.add_exception_handler(AIPError, aip_error_handler)

app.include_router(collections.router)
app.include_router(search.router)
app.include_router(documents.router)
app.include_router(papers.router)
app.include_router(jobs.router)
app.include_router(chat.router)
app.include_router(web.router)
app.include_router(legacy.router)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    index = UI_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h1>Knowledge Hub</h1><p>API ready — see /docs for OpenAPI.</p>"
