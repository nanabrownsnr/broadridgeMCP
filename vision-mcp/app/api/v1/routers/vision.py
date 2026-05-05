import imghdr
import tempfile
from pathlib import Path
from collections import Counter

import httpx
import numpy as np
import pypdfium2 as pdfium
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from app.schemas.vision import AnalyzeSourceRequest, CompareImagesRequest

router = APIRouter(prefix="/vision", tags=["vision"])
OCR_ENGINE = RapidOCR()


async def _download_to_temp_file(source_url: str, headers: dict[str, str] | None = None) -> tuple[Path, str | None, str]:
    req_headers = headers or {}
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        response = await client.get(source_url, headers=req_headers)
        response.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(response.content)
        temp_path = Path(tmp.name)
    return temp_path, response.headers.get("content-type"), response.text


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
    temp_path, content_type, response_text = await _download_to_temp_file(payload.source_url, payload.headers)
    source_type = _detect_source_type(temp_path, content_type)

    if source_type == "html":
        html = response_text
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


def _image_to_array(path: Path, size: tuple[int, int] | None = None) -> tuple[np.ndarray, tuple[int, int]]:
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        original_size = rgb.size
        if size is not None:
            rgb = rgb.resize(size, Image.Resampling.BILINEAR)
        arr = np.asarray(rgb).astype(np.float32) / 255.0
    return arr, original_size


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union else 0.0


@router.post("/compare_images")
async def compare_images(payload: CompareImagesRequest) -> dict:
    """
    Compare source and generated page images and return fidelity metrics plus correction hints.

    Use this in redesign mode after each generation pass to drive auto-correction.
    """
    source_path, source_content_type, _ = await _download_to_temp_file(payload.source_url, payload.headers)
    gen_path, gen_content_type, _ = await _download_to_temp_file(payload.generated_url, payload.headers)

    source_type = _detect_source_type(source_path, source_content_type)
    generated_type = _detect_source_type(gen_path, gen_content_type)
    if source_type != "image" or generated_type != "image":
        raise HTTPException(status_code=400, detail="compare_images currently supports image-to-image comparisons only")

    src_arr, src_size = _image_to_array(source_path)
    gen_arr, gen_size = _image_to_array(gen_path, size=src_size)

    mae = float(np.mean(np.abs(src_arr - gen_arr)))
    similarity_score = max(0.0, 1.0 - mae)

    src_text_blocks = _ocr_blocks_from_image(source_path)
    gen_text_blocks = _ocr_blocks_from_image(gen_path)
    src_text = {b["text"].strip().lower() for b in src_text_blocks if b.get("text")}
    gen_text = {b["text"].strip().lower() for b in gen_text_blocks if b.get("text")}
    text_similarity = _jaccard_similarity(src_text, gen_text)

    src_components = _infer_components_from_ocr(src_text_blocks)
    gen_components = _infer_components_from_ocr(gen_text_blocks)
    src_comp = {f'{c.get("type")}::{(c.get("label") or "").strip().lower()}' for c in src_components}
    gen_comp = {f'{c.get("type")}::{(c.get("label") or "").strip().lower()}' for c in gen_components}
    comp_similarity = _jaccard_similarity(src_comp, gen_comp)

    src_tokens = _extract_style_tokens(source_path)
    gen_tokens = _extract_style_tokens(gen_path)
    src_palette = src_tokens.get("dominant_colors", [])
    gen_palette = gen_tokens.get("dominant_colors", [])
    palette_overlap = _jaccard_similarity(set(src_palette), set(gen_palette))

    hints: list[str] = []
    if similarity_score < 0.90:
        hints.append("Tighten overall layout spacing and element positioning to match the source image.")
    if text_similarity < 0.85:
        hints.append("Review text content, copy hierarchy, and missing labels to improve OCR text overlap.")
    if comp_similarity < 0.80:
        hints.append("Adjust interactive components (inputs/buttons/links) count and placement to match the source.")
    if palette_overlap < 0.60:
        hints.append("Align dominant colors and contrast levels with the reference palette.")
    if abs(src_size[0] - gen_size[0]) > 8 or abs(src_size[1] - gen_size[1]) > 8:
        hints.append("Match viewport/canvas dimensions to the source before rendering.")
    if not hints:
        hints.append("Visual match is strong; proceed with feature-specific refinements only.")

    source_path.unlink(missing_ok=True)
    gen_path.unlink(missing_ok=True)

    return {
        "similarity_score": round(similarity_score, 4),
        "mae_score": round(mae, 4),
        "text_similarity_score": round(text_similarity, 4),
        "component_similarity_score": round(comp_similarity, 4),
        "source_size": {"width": src_size[0], "height": src_size[1]},
        "generated_size": {"width": gen_size[0], "height": gen_size[1]},
        "correction_hints": hints,
    }

