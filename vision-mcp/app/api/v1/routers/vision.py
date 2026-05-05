import imghdr
import tempfile
from pathlib import Path
from collections import Counter

import httpx
import pypdfium2 as pdfium
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from app.schemas.vision import AnalyzeSourceRequest

router = APIRouter(prefix="/vision", tags=["vision"])
OCR_ENGINE = RapidOCR()


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


def _extract_style_tokens(image_path: Path) -> dict:
    with Image.open(image_path) as img:
        rgb = img.convert("RGB").resize((256, 256))
        pixels = list(rgb.getdata())
        top = Counter(pixels).most_common(5)
        palette = [f"#{r:02X}{g:02X}{b:02X}" for (r, g, b), _ in top]
        return {"dominant_colors": palette}


def _ocr_blocks_from_image(image_path: Path) -> list[dict]:
    ocr_result, _ = OCR_ENGINE(str(image_path))
    if not ocr_result:
        return []

    blocks: list[dict] = []
    for item in ocr_result:
        points = item[0]
        text = (item[1] or "").strip()
        conf = float(item[2]) if len(item) > 2 and item[2] is not None else None
        if not text:
            continue
        xs = [int(p[0]) for p in points]
        ys = [int(p[1]) for p in points]
        blocks.append(
            {
                "text": text,
                "role": "ocr_text",
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
                "confidence": conf,
            }
        )
    return blocks


def _infer_components_from_ocr(text_blocks: list[dict]) -> list[dict]:
    components: list[dict] = []
    input_keywords = {"email", "password", "username", "search", "phone", "name"}
    button_keywords = {"login", "sign in", "submit", "continue", "save", "next", "send"}

    for block in text_blocks:
        text = block.get("text", "").strip()
        lower = text.lower()
        x = block.get("x")
        y = block.get("y")
        w = block.get("w")
        h = block.get("h")

        if any(k in lower for k in input_keywords):
            components.append({"type": "input", "label": text, "x": x, "y": y, "w": w, "h": h})
        elif any(k in lower for k in button_keywords):
            components.append({"type": "button", "label": text, "x": x, "y": y, "w": w, "h": h})

    return components[:200]


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
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
            image_tmp = Path(tmp_img.name)
        pdf = pdfium.PdfDocument(str(temp_path))
        page = pdf[payload.target_page - 1]
        bitmap = page.render(scale=2)
        bitmap.to_pil().save(image_tmp)
        ocr_blocks = _ocr_blocks_from_image(image_tmp)
        text_blocks.extend(ocr_blocks)
        components = _infer_components_from_ocr(ocr_blocks)
        style_tokens = _extract_style_tokens(image_tmp)
        image_tmp.unlink(missing_ok=True)
        layout = [{"role": "pdf_page", "page": payload.target_page, "width": size[0], "height": size[1]}]
        summary = f"PDF page {payload.target_page} analyzed with extracted text content."
    elif source_type == "image":
        _, size = _image_meta(temp_path)
        text_blocks = _ocr_blocks_from_image(temp_path)
        components = _infer_components_from_ocr(text_blocks)
        layout = [{"role": "image", "width": size[0], "height": size[1]}]
        style_tokens = _extract_style_tokens(temp_path)
        summary = f"Image analyzed with OCR text blocks ({len(text_blocks)}) and inferred components ({len(components)})."
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

