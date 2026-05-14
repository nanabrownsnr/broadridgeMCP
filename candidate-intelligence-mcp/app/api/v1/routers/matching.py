import io
import json
import re
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from app.core.config import settings
from app.schemas.matching import BatchMatchResumesToRoleRequest, GetCandidateAnalysisRequest, MatchResumeToRoleRequest
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException

try:
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
except Exception:
    np = None
    Image = None
    RapidOCR = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


router = APIRouter(prefix="/candidate_intelligence", tags=["candidate_intelligence"])

_OCR_ENGINE = RapidOCR() if RapidOCR is not None else None
_STORE_DIR = Path(settings.ANALYSIS_STORE_DIR)
_STORE_DIR.mkdir(parents=True, exist_ok=True)
_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "to",
    "of",
    "in",
    "on",
    "with",
    "is",
    "are",
    "as",
    "by",
    "at",
    "from",
    "that",
    "this",
    "be",
    "will",
    "can",
    "must",
}


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9+#./-]+", text.lower()) if w not in _STOPWORDS and len(w) > 1]


def _split_requirements(role_text: str) -> list[dict[str, Any]]:
    lines = [x.strip("-* \t") for x in role_text.splitlines() if x.strip()]
    if not lines:
        lines = re.split(r"(?<=[.!?])\s+", role_text.strip())
    reqs: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        lower = line.lower()
        is_must = any(k in lower for k in ["must", "required", "minimum", "at least", "mandatory"])
        weight = 2.0 if is_must else 1.0
        reqs.append(
            {
                "requirement_id": f"R{idx}",
                "text": line,
                "type": "must_have" if is_must else "nice_to_have",
                "weight": weight,
                "tokens": set(_tokenize(line)),
            }
        )
    return reqs


def _resume_sentences(resume_text: str) -> list[str]:
    chunks = re.split(r"[\n\r]+|(?<=[.!?])\s+", resume_text)
    return [c.strip() for c in chunks if c and c.strip()]


def _match_requirement(requirement: dict[str, Any], evidence_lines: list[str]) -> dict[str, Any]:
    req_tokens = requirement["tokens"]
    if not req_tokens:
        return {"score": 0.0, "evidence": []}

    best = 0.0
    best_line = ""
    for line in evidence_lines:
        line_tokens = set(_tokenize(line))
        if not line_tokens:
            continue
        overlap = req_tokens.intersection(line_tokens)
        score = len(overlap) / max(1, len(req_tokens))
        if score > best:
            best = score
            best_line = line
    return {"score": round(best, 4), "evidence": [best_line] if best_line else []}


def _build_graph_score(role_text: str, resume_text: str) -> dict[str, Any]:
    requirements = _split_requirements(role_text)
    lines = _resume_sentences(resume_text)

    req_scores: list[dict[str, Any]] = []
    total_weight = sum(r["weight"] for r in requirements) or 1.0
    weighted_sum = 0.0
    must_have_sum = 0.0
    must_have_count = 0
    nice_sum = 0.0
    nice_count = 0
    missing = []
    evidence = []

    for req in requirements:
        res = _match_requirement(req, lines)
        node_score = res["score"]
        weighted_sum += node_score * req["weight"]
        req_scores.append(
            {
                "requirement_id": req["requirement_id"],
                "requirement_text": req["text"],
                "requirement_type": req["type"],
                "score": node_score,
                "matched": node_score >= 0.35,
                "evidence": res["evidence"],
            }
        )
        if req["type"] == "must_have":
            must_have_count += 1
            must_have_sum += node_score
        else:
            nice_count += 1
            nice_sum += node_score
        if node_score < 0.35:
            missing.append(req["text"])
        if res["evidence"]:
            evidence.append({"requirement": req["text"], "resume_evidence": res["evidence"][0], "score": node_score})

    overall = round((weighted_sum / total_weight) * 100, 2)
    must_score = round((must_have_sum / max(1, must_have_count)) * 100, 2)
    nice_score = round((nice_sum / max(1, nice_count)) * 100, 2)

    resume_tokens = _tokenize(resume_text)
    top_terms = [x for x, _ in Counter(resume_tokens).most_common(12)]

    return {
        "score_overall": overall,
        "must_have_score": must_score,
        "nice_to_have_score": nice_score,
        "requirement_scores": req_scores,
        "missing_requirements": missing[:10],
        "strengths": [x for x in req_scores if x["matched"]][:8],
        "reason_summary": (
            f"Matched {sum(1 for x in req_scores if x['matched'])}/{len(req_scores)} requirements. "
            f"Must-have strength {must_score:.1f}, overall match {overall:.1f}."
        ),
        "evidence": evidence[:12],
        "graph": {
            "role_nodes": [{"id": r["requirement_id"], "type": r["type"], "text": r["text"]} for r in requirements],
            "resume_nodes": [{"id": f"S{i+1}", "type": "resume_line", "text": ln} for i, ln in enumerate(lines[:40])],
            "top_resume_terms": top_terms,
        },
    }


def _analysis_path(candidate_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", candidate_id.strip())
    return _STORE_DIR / f"{safe}.json"


def _store_analysis(candidate_id: str, payload: dict[str, Any]) -> None:
    record = {
        "candidate_id": candidate_id,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    _analysis_path(candidate_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def _load_analysis(candidate_id: str) -> dict[str, Any] | None:
    path = _analysis_path(candidate_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_analysis(candidate_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
    strengths = analysis.get("strengths", [])
    missing = analysis.get("missing_requirements", [])
    return {
        "candidate_id": candidate_id,
        "score_overall": analysis.get("score_overall"),
        "must_have_score": analysis.get("must_have_score"),
        "nice_to_have_score": analysis.get("nice_to_have_score"),
        "reason_summary": analysis.get("reason_summary"),
        "top_strengths": [s.get("requirement_text") for s in strengths[:3] if s.get("requirement_text")],
        "top_gaps": missing[:3],
        "analysis_ref": candidate_id,
    }


async def _fetch_url_content(url: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Unable to fetch resume_url: {ex}")
    raw = response.content
    if len(raw) > settings.MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="resume_url file is too large")
    return raw, response.headers.get("content-type", "").lower()


def _parse_pdf(raw: bytes) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    except Exception:
        return ""


def _parse_html(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    return " ".join(soup.get_text(" ").split())


def _ocr_image(raw: bytes) -> str:
    if _OCR_ENGINE is None or Image is None or np is None:
        return ""
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        arr = np.array(img)
        out, _ = _OCR_ENGINE(arr)
        if not out:
            return ""
        return "\n".join(x[1] for x in out if len(x) >= 2)
    except Exception:
        return ""


async def _resolve_resume_text(resume_text: str | None, resume_url: str | None) -> tuple[str, dict[str, Any]]:
    if resume_text and resume_text.strip():
        return resume_text.strip(), {"source": "resume_text", "content_type": "text/plain"}
    if not resume_url:
        raise HTTPException(status_code=400, detail="Either resume_text or resume_url is required.")

    raw, content_type = await _fetch_url_content(resume_url)
    parsed = ""
    parser_used = "unknown"
    if "application/pdf" in content_type or resume_url.lower().endswith(".pdf"):
        parsed = _parse_pdf(raw)
        parser_used = "pdf"
    elif "text/html" in content_type or resume_url.lower().endswith(".html"):
        parsed = _parse_html(raw)
        parser_used = "html"
    elif content_type.startswith("text/") or resume_url.lower().endswith((".txt", ".md", ".rtf")):
        parsed = raw.decode("utf-8", errors="ignore")
        parser_used = "text"
    elif content_type.startswith("image/") or resume_url.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        parsed = _ocr_image(raw)
        parser_used = "ocr_image"
    else:
        maybe_text = raw.decode("utf-8", errors="ignore").strip()
        if len(maybe_text) > 100:
            parsed = maybe_text
            parser_used = "fallback_decode"
    if not parsed.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from resume_url. Provide resume_text or a parseable PDF/image/text URL.",
        )
    return parsed.strip(), {"source": "resume_url", "content_type": content_type, "parser_used": parser_used}


@router.post("/match_resume_to_role", operation_id="match_resume_to_role")
async def match_resume_to_role(payload: MatchResumeToRoleRequest) -> dict:
    """
    Match one candidate resume to role requirements using a built-in mini-graph scorer.

    Input:
    - `role_requirements_text`: role/JD requirements text
    - one of:
      - `resume_text`
      - `resume_url` (pdf/image/text/html)

    Output (compact):
    - `candidate_id`, `score_overall`, `must_have_score`, `nice_to_have_score`
    - `reason_summary`, `top_strengths`, `top_gaps`
    - `analysis_ref` for full retrieval via `get_candidate_full_analysis`
    """
    resume, meta = await _resolve_resume_text(payload.resume_text, payload.resume_url)
    analysis = _build_graph_score(payload.role_requirements_text, resume)
    candidate_id = payload.candidate_id or f"single_{int(datetime.now(timezone.utc).timestamp())}"
    _store_analysis(
        candidate_id,
        {"resume_source": meta, "analysis": analysis, "role_requirements_text": payload.role_requirements_text},
    )
    return {"resume_source": meta, "summary": _compact_analysis(candidate_id, analysis)}


@router.post("/batch_match_resumes_to_role", operation_id="batch_match_resumes_to_role")
async def batch_match_resumes_to_role(payload: BatchMatchResumesToRoleRequest) -> dict:
    """
    Match many resumes to one role and return a ranked shortlist.

    Input:
    - `role_requirements_text`
    - `resumes`: array of `{ candidate_id, resume_text | resume_url }`

    Output (compact):
    - `results`: ranked descending compact summaries
    - `top_candidates_summary`: short summary for the top 3 candidates
    - full details can be retrieved by `analysis_ref` using `get_candidate_full_analysis`
    """
    if not payload.resumes:
        raise HTTPException(status_code=400, detail="resumes must not be empty")

    full_results: list[dict[str, Any]] = []
    for item in payload.resumes:
        resume, meta = await _resolve_resume_text(item.resume_text, item.resume_url)
        analysis = _build_graph_score(payload.role_requirements_text, resume)
        _store_analysis(
            item.candidate_id,
            {"resume_source": meta, "analysis": analysis, "role_requirements_text": payload.role_requirements_text},
        )
        full_results.append({"candidate_id": item.candidate_id, "resume_source": meta, "analysis": analysis})

    ranked_full = sorted(full_results, key=lambda x: x["analysis"]["score_overall"], reverse=True)
    ranked = [_compact_analysis(x["candidate_id"], x["analysis"]) for x in ranked_full]
    top = ranked[:3]
    summary = [
        {
            "candidate_id": x["candidate_id"],
            "score_overall": x["score_overall"],
            "reason_summary": x["reason_summary"],
        }
        for x in top
    ]
    return {"count": len(ranked), "results": ranked, "top_candidates_summary": summary}


@router.post("/get_candidate_full_analysis", operation_id="get_candidate_full_analysis")
async def get_candidate_full_analysis(payload: GetCandidateAnalysisRequest) -> dict:
    """
    Retrieve previously stored full analysis by `candidate_id`.

    Use when:
    1. Compact match results indicate a promising candidate.
    2. You need full requirement-level evidence, graph details, and parsed source metadata.
    """
    record = _load_analysis(payload.candidate_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No stored analysis found for candidate_id={payload.candidate_id}")
    return record
