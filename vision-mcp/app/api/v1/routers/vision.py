import imghdr
import tempfile
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from PIL import Image

from app.schemas.vision import AnalyzeSourceRequest

router = APIRouter(prefix="/vision", tags=["vision"])


def _detect_source_type(path: Path, content_type: str | None) -> str:
    if content_type:
        if "pdf" in content_type:
            return "pdf"
        if "html" in content_type:
            return "html"
        if "image" in content_type:
            return "image"
    ext = path.suffix.lower()
    if ext in {".pdf"}:
        return "pdf"
    if ext in {".html", ".htm"}:
        return "html"
    if imghdr.what(path):
        return "image"
    return "binary"


def _components_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    components: list[dict] = []
    for tag_name, component_type in [("input", "input"), ("button", "button"), ("select", "select"), ("a", "link")]:
        for tag in soup.find_all(tag_name):
            label = tag.get("aria-label") or tag.get_text(strip=True) or tag.get("name")
            components.append({"type": component_type, "label": label})
    return components[:200]


def _text_blocks_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for h in soup.find_all(["h1", "h2", "h3", "p", "span", "label", "button"]):
        text = h.get_text(" ", strip=True)
        if text:
            out.append({"text": text, "role": h.name})
    return out[:500]


def _pdf_page_to_text_blocks(pdf_path: Path, page_num: int) -> tuple[list[dict], tuple[int, int]]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    if page_num > len(pdf):
        raise HTTPException(status_code=400, detail=f"Requested page {page_num} out of range")
    page = pdf[page_num - 1]
    textpage = page.get_textpage()
    text = textpage.get_text_range()
    bitmap = page.render(scale=1)
    pil = bitmap.to_pil()
    return ([{"text": text[:10000], "role": "document"}] if text else []), pil.size


def _image_meta(image_path: Path) -> tuple[list[dict], tuple[int, int]]:
    with Image.open(image_path) as img:
        return [], img.size


@router.post("/analyze_source")
async def analyze_source(payload: AnalyzeSourceRequest) -> dict:
    """
    Analyze a remote source URL and normalize it into LLM-friendly UI context.

    Supported sources: HTML, PDF, and image files.
    Use this before page regeneration so a text-only LLM can reason over structure, text, and components.
    """
    headers = payload.headers or {}
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        response = await client.get(payload.source_url, headers=headers)
        response.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(response.content)
        temp_path = Path(tmp.name)

    source_type = _detect_source_type(temp_path, response.headers.get("content-type"))

    if source_type == "html":
        html = response.text
        components = _components_from_html(html)
        text_blocks = _text_blocks_from_html(html)
        layout = [{"role": "document", "order": 1}]
        style_tokens = {}
        summary = f"HTML page with {len(components)} detected interactive elements."
    elif source_type == "pdf":
        text_blocks, size = _pdf_page_to_text_blocks(temp_path, payload.target_page)
        components = []
        layout = [{"role": "pdf_page", "page": payload.target_page, "width": size[0], "height": size[1]}]
        style_tokens = {}
        summary = f"PDF page {payload.target_page} analyzed with extracted text content."
    elif source_type == "image":
        text_blocks, size = _image_meta(temp_path)
        components = []
        layout = [{"role": "image", "width": size[0], "height": size[1]}]
        style_tokens = {}
        summary = "Image metadata extracted. Add OCR later for richer component detection."
    else:
        raise HTTPException(status_code=400, detail="Unsupported source type")

    return {
        "page_name": payload.page_name or "unnamed-page",
        "source_url": payload.source_url,
        "source_type": source_type,
        "text_blocks": text_blocks,
        "layout": layout,
        "components": components,
        "style_tokens": style_tokens,
        "summary": summary,
    }

