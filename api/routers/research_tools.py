"""Research Tools API — Deep parsing, deep research, lit review, recommendations."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_llm, get_store, get_research_store
from core.config import load_config
from core.llm import LLMClient
from core.vector_store import VectorStore

router = APIRouter(prefix="/v1/research-tools", tags=["research-tools"])


# ── Request/Response schemas ────────────────────────────────────

class ParseRequest(BaseModel):
    content: str = Field(default="", description="Raw text content to parse")
    filename: str = Field(default="document", description="Filename for context")
    extract_tables: bool = Field(default=True)
    structure_with_llm: bool = Field(default=False)
    llm_instruction: str = Field(default="", description="Custom instruction for LLM structuring")


class DeepResearchRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=2000)
    depth: int = Field(default=3, ge=1, le=5, description="Research depth (sub-queries)")
    stream: bool = Field(default=True)


class LiteratureReviewRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=1000)
    max_papers: int = Field(default=15, ge=3, le=50)
    length: str = Field(default="800-1200", description="Target word count range")
    focus: str = Field(default="", description="Custom focus/instructions")
    include_external: bool = Field(default=True)
    stream: bool = Field(default=True)


class RecommendationRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    abstract: str = Field(default="")
    authors: str = Field(default="")
    k: int = Field(default=10, ge=1, le=50)
    strategy: str = Field(default="hybrid", description="hybrid, semantic, author, topic")


class TopicRecommendationRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    k: int = Field(default=10, ge=1, le=50)


class ReadingPathRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    depth: int = Field(default=3, ge=1, le=7)


# ── Helpers ─────────────────────────────────────────────────────

def _sse(obj) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def _get_config():
    return load_config()


# ── Deep Document Parsing ───────────────────────────────────────

@router.post(":parse")
def parse_document(
    req: ParseRequest,
    llm: LLMClient = Depends(get_llm),
    _auth: None = Depends(verify_api_key),
):
    """Parse document content with deep understanding (tables, structure, metadata)."""
    from services.parsing_service import DeepParsingService

    svc = DeepParsingService(llm_client=llm if req.structure_with_llm else None)

    if req.content:
        doc = svc.parse_content(req.content, req.filename)
    else:
        return {"error": "No content provided"}

    result = doc.to_dict()

    # Optional LLM structuring
    if req.structure_with_llm and llm:
        structured = svc.structure_with_llm(doc.full_text, req.llm_instruction)
        result["structured"] = structured

    return result


@router.post(":parse-file")
async def parse_uploaded_file(
    file: UploadFile = File(...),
    extract_tables: bool = Form(default=True),
    ocr_fallback: bool = Form(default=True),
    llm: LLMClient = Depends(get_llm),
    _auth: None = Depends(verify_api_key),
):
    """Upload and parse a file (PDF, image, text) with deep understanding."""
    import tempfile
    import os
    from services.parsing_service import DeepParsingService

    # Save uploaded file temporarily
    suffix = os.path.splitext(file.filename or "doc.pdf")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        svc = DeepParsingService(llm_client=llm)
        doc = svc.parse_document(tmp_path, {
            "extract_tables": extract_tables,
            "ocr_fallback": ocr_fallback,
            "extract_figures": True,
        })
        return doc.to_dict()
    finally:
        os.unlink(tmp_path)


@router.post(":extract-tables")
def extract_tables(
    req: ParseRequest,
    _auth: None = Depends(verify_api_key),
):
    """Extract tables from text content."""
    from services.parsing_service import DeepParsingService

    svc = DeepParsingService()
    tables = svc.extract_tables_from_text(req.content)
    return {
        "tables": [t.to_dict() for t in tables],
        "count": len(tables),
    }


# ── Deep Research Mode ──────────────────────────────────────────

@router.post(":deep-research")
def deep_research(
    req: DeepResearchRequest,
    llm: LLMClient = Depends(get_llm),
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    """Multi-step agentic research: decompose → search → cross-reference → synthesize."""
    from services.deep_research_service import DeepResearchService

    config = _get_config()
    svc = DeepResearchService(llm, store, research_store, config)

    if not req.stream:
        result = svc.run(req.question, depth=req.depth)
        return result.to_dict()

    def stream():
        for event in svc.stream(req.question, depth=req.depth):
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Literature Review Generator ─────────────────────────────────

@router.post(":literature-review")
def literature_review(
    req: LiteratureReviewRequest,
    llm: LLMClient = Depends(get_llm),
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    """Generate a structured literature review / related work section."""
    from services.literature_review_service import LiteratureReviewService

    config = _get_config()
    svc = LiteratureReviewService(llm, store, research_store, config)

    if not req.stream:
        result = svc.generate(
            topic=req.topic,
            max_papers=req.max_papers,
            length=req.length,
            focus=req.focus,
            include_external=req.include_external,
        )
        return result.to_dict()

    def stream():
        for event in svc.stream(
            topic=req.topic,
            max_papers=req.max_papers,
            length=req.length,
            focus=req.focus,
            include_external=req.include_external,
        ):
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Paper Recommendations ───────────────────────────────────────

@router.post(":recommend")
def recommend_papers(
    req: RecommendationRequest,
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    """Get paper recommendations based on a seed paper."""
    from services.recommendation_service import RecommendationService

    config = _get_config()
    svc = RecommendationService(store, research_store, config)
    result = svc.recommend_for_paper(
        title=req.title,
        abstract=req.abstract,
        authors=req.authors,
        k=req.k,
        strategy=req.strategy,
    )
    return result.to_dict()


@router.post(":recommend-topic")
def recommend_for_topic(
    req: TopicRecommendationRequest,
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    """Get paper recommendations based on a research topic."""
    from services.recommendation_service import RecommendationService

    config = _get_config()
    svc = RecommendationService(store, research_store, config)
    result = svc.recommend_for_topic(topic=req.topic, k=req.k)
    return result.to_dict()


@router.post(":reading-path")
def reading_path(
    req: ReadingPathRequest,
    store: VectorStore = Depends(get_store),
    research_store: VectorStore = Depends(get_research_store),
    _auth: None = Depends(verify_api_key),
):
    """Generate a suggested reading path starting from a paper."""
    from services.recommendation_service import RecommendationService

    config = _get_config()
    svc = RecommendationService(store, research_store, config)
    return svc.get_reading_path(title=req.title, depth=req.depth)
