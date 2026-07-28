"""Deep Document Parsing — OCR, table extraction, and structured PDF parsing.

Extracts text, tables, figures, and metadata from PDFs and images using
multiple strategies: pdfplumber for tables, pytesseract for OCR fallback,
and LLM-assisted structuring for complex layouts.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging import get_logger

log = get_logger("parsing_service")


@dataclass
class ParsedTable:
    """A table extracted from a document."""
    page: int
    rows: list[list[str]]
    headers: list[str] = field(default_factory=list)
    caption: str = ""

    def to_markdown(self) -> str:
        if not self.rows:
            return ""
        headers = self.headers or self.rows[0]
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in self.rows[1:] if self.headers else self.rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "headers": self.headers,
            "rows": self.rows,
            "caption": self.caption,
            "markdown": self.to_markdown(),
        }


@dataclass
class ParsedFigure:
    """A figure/image extracted from a document."""
    page: int
    caption: str = ""
    image_path: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "caption": self.caption,
            "image_path": self.image_path,
            "description": self.description,
        }


@dataclass
class ParsedDocument:
    """Full structured result of document parsing."""
    source_path: str
    pages: int = 0
    full_text: str = ""
    tables: list[ParsedTable] = field(default_factory=list)
    figures: list[ParsedFigure] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    ocr_applied: bool = False
    parse_method: str = "standard"

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "pages": self.pages,
            "full_text": self.full_text[:10000],
            "text_length": len(self.full_text),
            "tables": [t.to_dict() for t in self.tables],
            "figures": [f.to_dict() for f in self.figures],
            "metadata": self.metadata,
            "ocr_applied": self.ocr_applied,
            "parse_method": self.parse_method,
            "table_count": len(self.tables),
            "figure_count": len(self.figures),
        }


class DeepParsingService:
    """Service for deep document understanding — OCR, tables, figures."""

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self._pdfplumber = None
        self._pytesseract = None

    def parse_document(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        """Parse a document with deep understanding (tables, OCR, figures)."""
        options = options or {}
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._parse_pdf(path, options)
        elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            return self._parse_image(path, options)
        elif suffix in (".md", ".txt", ".rst"):
            return self._parse_text(path, options)
        else:
            return self._parse_generic(path, options)

    def parse_content(self, content: str, filename: str = "document") -> ParsedDocument:
        """Parse raw text content and extract structure (tables, sections)."""
        doc = ParsedDocument(source_path=filename, parse_method="content")
        doc.full_text = content
        doc.pages = max(1, len(content) // 3000)

        # Extract markdown tables
        doc.tables = self._extract_markdown_tables(content)

        # Extract metadata
        doc.metadata = self._extract_metadata(content)

        return doc

    def extract_tables_from_text(self, text: str) -> list[ParsedTable]:
        """Extract tabular data from plain text using heuristics."""
        tables = []

        # Pattern 1: Markdown tables
        tables.extend(self._extract_markdown_tables(text))

        # Pattern 2: Tab/space-separated columns
        tables.extend(self._extract_column_tables(text))

        return tables

    def structure_with_llm(self, text: str, instruction: str = "") -> dict:
        """Use LLM to extract structured information from text."""
        if not self.llm:
            return {"error": "LLM not configured"}

        prompt = f"""Extract structured information from the following document text.
Return a JSON object with these fields:
- title: document title
- sections: list of section headings
- key_findings: list of key findings or conclusions
- methodology: description of methodology (if academic)
- tables_data: any tabular data found (as arrays)
- entities: important named entities
{f'- instruction: {instruction}' if instruction else ''}

Document text:
{text[:6000]}

Respond with valid JSON only."""

        try:
            result = self.llm.complete(prompt, system_prompt="You are a document analysis expert. Return valid JSON.")
            import json
            # Try to parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                return json.loads(json_match.group())
            return {"raw": result}
        except Exception as e:
            log.warning("LLM structuring failed: %s", e)
            return {"error": str(e), "raw": text[:500]}

    # ── Private methods ─────────────────────────────────────────

    def _parse_pdf(self, path: Path, options: dict) -> ParsedDocument:
        """Parse PDF with table extraction and OCR fallback."""
        doc = ParsedDocument(source_path=str(path), parse_method="pdf_deep")

        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                doc.pages = len(pdf.pages)
                text_parts = []

                for i, page in enumerate(pdf.pages):
                    # Extract text
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)

                    # Extract tables
                    if options.get("extract_tables", True):
                        raw_tables = page.extract_tables() or []
                        for rt in raw_tables:
                            if rt and len(rt) > 1:
                                headers = [str(c or "") for c in rt[0]]
                                rows = [[str(c or "") for c in row] for row in rt[1:]]
                                doc.tables.append(ParsedTable(
                                    page=i + 1,
                                    headers=headers,
                                    rows=rows,
                                ))

                    # Extract figures info
                    if options.get("extract_figures", True):
                        for img in (page.images or []):
                            doc.figures.append(ParsedFigure(
                                page=i + 1,
                                caption=f"Figure on page {i + 1}",
                            ))

                doc.full_text = "\n\n".join(text_parts)

                # OCR fallback if text is sparse
                if len(doc.full_text.strip()) < 100 and options.get("ocr_fallback", True):
                    doc.ocr_applied = True
                    doc.full_text = self._ocr_pdf(path)

                # Metadata
                doc.metadata = {
                    "title": pdf.metadata.get("Title", ""),
                    "author": pdf.metadata.get("Author", ""),
                    "creator": pdf.metadata.get("Creator", ""),
                    "pages": doc.pages,
                }

        except ImportError:
            log.warning("pdfplumber not installed, falling back to basic parsing")
            doc = self._parse_pdf_basic(path, doc)
        except Exception as e:
            log.warning("PDF parsing error: %s", e)
            doc.parse_method = "fallback"
            doc.full_text = f"Error parsing PDF: {e}"

        return doc

    def _parse_pdf_basic(self, path: Path, doc: ParsedDocument) -> ParsedDocument:
        """Fallback PDF parsing without pdfplumber."""
        try:
            import fitz  # PyMuPDF
            with fitz.open(str(path)) as pdf_doc:
                doc.pages = len(pdf_doc)
                text_parts = []
                for page in pdf_doc:
                    text_parts.append(page.get_text())
                doc.full_text = "\n\n".join(text_parts)
                doc.parse_method = "pymupdf"
        except ImportError:
            doc.full_text = path.read_text(encoding="utf-8", errors="ignore")
            doc.parse_method = "raw_text"
        return doc

    def _parse_image(self, path: Path, options: dict) -> ParsedDocument:
        """Parse image with OCR."""
        doc = ParsedDocument(source_path=str(path), parse_method="ocr", ocr_applied=True)
        doc.pages = 1

        try:
            import pytesseract
            from PIL import Image
            img = Image.open(str(path))
            doc.full_text = pytesseract.image_to_string(img)
            doc.metadata = {"format": img.format, "size": img.size}
        except ImportError:
            doc.full_text = f"[OCR unavailable — pytesseract not installed] Image: {path.name}"
            doc.parse_method = "no_ocr"
        except Exception as e:
            doc.full_text = f"OCR failed: {e}"

        return doc

    def _parse_text(self, path: Path, options: dict) -> ParsedDocument:
        """Parse text/markdown files."""
        doc = ParsedDocument(source_path=str(path), parse_method="text")
        doc.full_text = path.read_text(encoding="utf-8", errors="ignore")
        doc.pages = max(1, len(doc.full_text) // 3000)
        doc.tables = self._extract_markdown_tables(doc.full_text)
        doc.metadata = self._extract_metadata(doc.full_text)
        return doc

    def _parse_generic(self, path: Path, options: dict) -> ParsedDocument:
        """Generic file parsing."""
        doc = ParsedDocument(source_path=str(path), parse_method="generic")
        try:
            doc.full_text = path.read_text(encoding="utf-8", errors="ignore")
        except UnicodeDecodeError:
            doc.full_text = f"[Binary file: {path.name}, {path.stat().st_size} bytes]"
        doc.pages = 1
        return doc

    def _ocr_pdf(self, path: Path) -> str:
        """OCR a scanned PDF page by page."""
        try:
            import pytesseract
            from pdf2image import convert_from_path
            images = convert_from_path(str(path), dpi=200)
            texts = []
            for img in images:
                texts.append(pytesseract.image_to_string(img))
            return "\n\n".join(texts)
        except ImportError:
            return "[OCR unavailable — install pytesseract and pdf2image]"
        except Exception as e:
            return f"[OCR failed: {e}]"

    def _extract_markdown_tables(self, text: str) -> list[ParsedTable]:
        """Extract markdown-formatted tables from text."""
        tables = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if "|" in line and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1].strip()):
                # Found a table header
                headers = [c.strip() for c in line.split("|") if c.strip()]
                rows = []
                i += 2  # Skip separator
                while i < len(lines) and "|" in lines[i]:
                    row = [c.strip() for c in lines[i].split("|") if c.strip()]
                    if row:
                        rows.append(row)
                    i += 1
                tables.append(ParsedTable(page=1, headers=headers, rows=rows))
            else:
                i += 1
        return tables

    def _extract_column_tables(self, text: str) -> list[ParsedTable]:
        """Extract space/tab-separated column data."""
        tables = []
        lines = text.split("\n")
        block: list[str] = []

        for line in lines:
            # Detect lines with multiple tabs or 3+ spaces separating columns
            if "\t" in line or re.search(r'\S\s{3,}\S', line):
                block.append(line)
            else:
                if len(block) >= 3:
                    table = self._block_to_table(block)
                    if table:
                        tables.append(table)
                block = []

        if len(block) >= 3:
            table = self._block_to_table(block)
            if table:
                tables.append(table)

        return tables

    def _block_to_table(self, block: list[str]) -> ParsedTable | None:
        """Convert a block of aligned text lines into a table."""
        rows = []
        for line in block:
            if "\t" in line:
                cells = [c.strip() for c in line.split("\t") if c.strip()]
            else:
                cells = [c.strip() for c in re.split(r'\s{3,}', line) if c.strip()]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            return None

        # Check column consistency
        col_counts = [len(r) for r in rows]
        if max(col_counts) - min(col_counts) > 1:
            return None

        headers = rows[0]
        return ParsedTable(page=1, headers=headers, rows=rows[1:])

    def _extract_metadata(self, text: str) -> dict:
        """Extract document metadata from content."""
        meta: dict[str, Any] = {}

        # Title (first heading)
        title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if title_match:
            meta["title"] = title_match.group(1).strip()

        # DOI
        doi_match = re.search(r'10\.\d{4,}/[^\s]+', text)
        if doi_match:
            meta["doi"] = doi_match.group()

        # Email / author
        emails = re.findall(r'[\w.-]+@[\w.-]+\.\w+', text)
        if emails:
            meta["emails"] = emails[:5]

        return meta
