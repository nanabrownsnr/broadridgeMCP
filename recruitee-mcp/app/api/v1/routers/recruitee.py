from typing import Any

import httpx
from app.core.config import settings
from app.core.platfom_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.recruitee import (
    CreateJobRequest,
    GetCandidateResumeSourceRequest,
    GetCandidatesResumeSourcesRequest,
    GetJobPublicUrlRequest,
    ListOfferStagesRequest,
    ListCandidatesRequest,
    MoveCandidateStageRequest,
    PublishJobRequest,
    RegisterWebhookRequest,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/recruitee", tags=["recruitee"])


def _resolve_api_key(platform_client: PlatformIntegrationClient | None = None) -> str:
    # Preferred: Platform Integration key
    if platform_client is not None:
        try:
            key = platform_client.get_access_key(settings.RECRUITEE_KEY_SERVICE_NAME)
            if key:
                return key
        except Exception:
            pass
    # Fallback: static env key
    if settings.RECRUITEE_API_KEY:
        return settings.RECRUITEE_API_KEY
    raise HTTPException(
        status_code=500,
        detail=(
            "Recruitee API key not configured. Provide via Platform Integration "
            f"service='{settings.RECRUITEE_KEY_SERVICE_NAME}' or RECRUITEE_API_KEY env."
        ),
    )


def _company_id() -> str:
    if not settings.RECRUITEE_COMPANY_ID:
        raise HTTPException(status_code=500, detail="RECRUITEE_COMPANY_ID is required")
    return settings.RECRUITEE_COMPANY_ID


async def _api_request(method: str, path: str, api_key: str, json: dict | None = None, params: dict | None = None) -> Any:
    base = settings.RECRUITEE_API_URL.rstrip("/")
    url = f"{base}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, url, headers=headers, json=json, params=params)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])
    if not response.text:
        return {}
    return response.json()


def _resume_source_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_obj = candidate.get("candidate", candidate)
    cv_original_file = candidate_obj.get("cv_original_file") or candidate_obj.get("cv_original_url")
    cv_url = candidate_obj.get("cv_url")
    resume_text = candidate_obj.get("cv") or candidate_obj.get("resume_text")
    preferred_resume_url = cv_original_file or cv_url
    return {
        "candidate_id": candidate_obj.get("id"),
        "candidate_name": candidate_obj.get("name"),
        "emails": candidate_obj.get("emails", []),
        "cv_original_file": cv_original_file,
        "cv_url": cv_url,
        "resume_url": preferred_resume_url,
        "resume_text": resume_text,
        "has_resume_url": bool(preferred_resume_url),
        "has_resume_text": bool(resume_text),
    }


def _build_structured_description(payload: CreateJobRequest) -> str | None:
    sections: list[str] = []

    context_lines: list[str] = []
    if payload.seniority:
        context_lines.append(f"- Seniority: {payload.seniority}")
    if payload.employment_type:
        context_lines.append(f"- Employment type: {payload.employment_type}")
    if payload.location_type:
        context_lines.append(f"- Work model: {payload.location_type}")
    if payload.team_name:
        context_lines.append(f"- Team: {payload.team_name}")
    if context_lines:
        sections.append("Role Context\n" + "\n".join(context_lines))

    if payload.role_summary:
        sections.append("Role Summary\n" + payload.role_summary.strip())

    if payload.responsibilities:
        resp = "\n".join([f"- {x.strip()}" for x in payload.responsibilities if x and x.strip()])
        if resp:
            sections.append("Responsibilities\n" + resp)

    if payload.must_have_requirements:
        must = "\n".join([f"- {x.strip()}" for x in payload.must_have_requirements if x and x.strip()])
        if must:
            sections.append("Must-Have Requirements\n" + must)

    if payload.nice_to_have_requirements:
        nice = "\n".join([f"- {x.strip()}" for x in payload.nice_to_have_requirements if x and x.strip()])
        if nice:
            sections.append("Nice-to-Have Requirements\n" + nice)

    if payload.interview_process:
        steps = [
            f"{idx + 1}. {step.strip()}"
            for idx, step in enumerate(payload.interview_process)
            if step and step.strip()
        ]
        if steps:
            sections.append("Interview Process\n" + "\n".join(steps))

    if sections:
        return "\n\n".join(sections)
    if payload.description and payload.description.strip():
        return payload.description.strip()
    return None


@router.post("/create_job", operation_id="recruitee_create_job")
async def create_job(payload: CreateJobRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Create a new Recruitee role (offer).

    Use this when the hiring agent receives a request like
    "open a new backend role" and must create the job shell first.

    Required input:
    - `title`

    Optional input:
    - Structured JD fields: `role_summary`, `responsibilities`, `must_have_requirements`, `nice_to_have_requirements`
    - Role metadata: `seniority`, `location_type`, `employment_type`, `team_name`, `interview_process`
    - Legacy fallback: `description`
    - Routing: `pipeline_template_id`, `department`, `location`, `status`

    Agent behavior guidance:
    - The agent should try to infer structured fields from the user's natural-language request first.
    - If the user provides a JD document/text, parse it and map content into the structured fields.
    - If required role context is still unclear, ask concise follow-up questions for missing high-value fields
      (especially `role_summary`, `responsibilities`, and `must_have_requirements`).
    - Do not block on perfect completeness; proceed with best available details and keep remaining fields optional.

    Output:
    - `{ "offer": { ... } }`
    - Use `offer.id` as `offer_id` in other tools.

    Auth resolution order:
    1. Platform Integration key for service `RECRUITEE_KEY_SERVICE_NAME`
    2. `RECRUITEE_API_KEY` from env fallback
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()

    body: dict[str, Any] = {
        "title": payload.title,
        "status": payload.status,
    }
    description_text = _build_structured_description(payload)
    if description_text is not None:
        body["description"] = description_text
    if payload.pipeline_template_id is not None:
        body["pipeline_template_id"] = payload.pipeline_template_id
    if payload.department is not None:
        body["department"] = payload.department
    if payload.location is not None:
        body["location"] = payload.location

    data = await _api_request("POST", f"/c/{company_id}/offers", key, json=body)
    return {"offer": data}


@router.get("/list_job_openings", operation_id="recruitee_list_job_openings")
async def list_job_openings(
    include_raw: bool = False,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Return all job openings with a compact list for tool chaining.

    Use this as the first discovery step when the user asks:
    - "show all roles"
    - "how many openings do we have"
    - "find offer id for role X"

    Output:
    - `total_count`: number of offers
    - `openings`: list of `{ offer_id, title, status, slug, published_at }`
    - `raw`: full provider payload when `include_raw=true`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    data = await _api_request("GET", f"/c/{company_id}/offers", key, params={"limit": 1000, "page": 1})
    offers = data.get("offers", [])
    openings = [
        {
            "offer_id": offer.get("id"),
            "title": offer.get("title"),
            "status": offer.get("status"),
            "slug": offer.get("slug"),
            "published_at": offer.get("published_at"),
        }
        for offer in offers
    ]
    result = {
        "total_count": data.get("meta", {}).get("total_count", len(openings)),
        "openings": openings,
    }
    if include_raw:
        result["raw"] = data
    return result


@router.post("/publish_job", operation_id="recruitee_publish_job")
async def publish_job(payload: PublishJobRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Publish an existing Recruitee role so it becomes publicly visible.

    Required input:
    - `offer_id` returned from `recruitee_create_job`

    Output:
    - `{ "offer": { ... } }` with updated status.
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    data = await _api_request(
        "PATCH",
        f"/c/{company_id}/offers/{payload.offer_id}",
        key,
        json={"status": "published"},
    )
    return {"offer": data}


@router.post("/get_job_public_url", operation_id="recruitee_get_job_public_url")
async def get_job_public_url(payload: GetJobPublicUrlRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Resolve the best public application link for a published role.

    Required input:
    - `offer_id`

    Output:
    - `best_url` (primary URL to post)
    - `url_candidates` (alternatives if multiple URL fields exist)
    - `raw_offer` (full offer object)
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    data = await _api_request("GET", f"/c/{company_id}/offers/{payload.offer_id}", key)

    # Recruitee APIs can expose URL fields differently; return best available candidates.
    url_candidates = []
    for field in ["careers_url", "public_url", "url", "hosted_url"]:
        val = data.get(field)
        if val:
            url_candidates.append(val)

    slug = data.get("slug")
    if slug:
        # conventional careers pattern fallback
        url_candidates.append(f"https://{company_id}.recruitee.com/o/{slug}")

    return {
        "offer_id": payload.offer_id,
        "title": data.get("title"),
        "slug": slug,
        "url_candidates": url_candidates,
        "best_url": url_candidates[0] if url_candidates else None,
        **({"raw_offer": data} if payload.include_raw_offer else {}),
    }


@router.post("/list_offer_stages", operation_id="recruitee_list_offer_stages")
async def list_offer_stages(payload: ListOfferStagesRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Return pipeline stages for a specific offer, so agents can use stage names instead of guessing stage IDs.

    Required input:
    - `offer_id`

    Output:
    - `stages`: list of `{ stage_id, stage_name, position, kind }`
    - `offer_id`
    - `raw`: full provider payload when `include_raw=true`

    Recommended flow:
    1. call `recruitee_list_job_openings` to get `offer_id`
    2. call this tool to map stage names -> stage IDs
    3. call `recruitee_move_candidate_stage` with the selected `stage_id`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    data = await _api_request("GET", f"/c/{company_id}/offers/{payload.offer_id}/stages", key)

    # Recruitee responses can vary by plan/version; normalize common shapes.
    stage_items = data.get("stages", data if isinstance(data, list) else [])
    stages = []
    for item in stage_items:
        stages.append(
            {
                "stage_id": item.get("id"),
                "stage_name": item.get("name") or item.get("title"),
                "position": item.get("position"),
                "kind": item.get("kind") or item.get("type"),
            }
        )
    result: dict[str, Any] = {"offer_id": payload.offer_id, "stages": stages}
    if payload.include_raw:
        result["raw"] = data
    return result


@router.post("/list_candidates", operation_id="recruitee_list_candidates")
async def list_candidates(
    payload: ListCandidatesRequest | None = None,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    List candidates, optionally scoped by role (`offer_id`) and stage.

    Required input:
    - none (body is optional; if omitted, defaults are used)

    Optional input:
    - `offer_id`, `stage_id`, `limit`, `page`

    Typical usage:
    - "how many applied to role X"
    - "show candidates in Offer Accepted stage"

    Output:
    - Compact default: `{ "count", "candidates": [ {candidate_id, name, emails, placements} ] }`
    - Raw payload only when `include_raw=true`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    payload = payload or ListCandidatesRequest()

    params: dict[str, Any] = {"limit": payload.limit, "page": payload.page}
    if payload.offer_id is not None:
        params["offer_id"] = payload.offer_id
    if payload.stage_id is not None:
        params["stage_id"] = payload.stage_id

    data = await _api_request("GET", f"/c/{company_id}/candidates", key, params=params)
    candidate_rows = data.get("candidates", [])
    compact = []
    for c in candidate_rows:
        compact.append(
            {
                "candidate_id": c.get("id"),
                "name": c.get("name"),
                "emails": c.get("emails", []),
                "placements": [
                    {
                        "offer_id": p.get("offer_id"),
                        "stage_id": p.get("stage_id"),
                        "talent_pool_id": p.get("talent_pool_id"),
                    }
                    for p in c.get("placements", [])
                ],
            }
        )
    result: dict[str, Any] = {"count": len(compact), "candidates": compact}
    if payload.include_raw:
        result["raw"] = data
    return result


@router.post("/get_candidate_resume_source", operation_id="recruitee_get_candidate_resume_source")
async def get_candidate_resume_source(
    payload: GetCandidateResumeSourceRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Resolve resume source fields for one candidate so downstream matching MCP can consume URL or text.

    Required input:
    - `candidate_id` from `recruitee_list_candidates`

    Output (compact by default):
    - `resume_source` with:
      - `resume_url` (preferred CV URL if available)
      - `resume_text` (if present in provider response)
      - `cv_original_file`, `cv_url`, `has_resume_url`, `has_resume_text`
    - `raw_candidate` only when `include_raw_candidate=true`

    Cross-MCP usage:
    1. call `recruitee_get_candidate_resume_source`
    2. if `resume_source.resume_text` exists, pass it to Candidate Intelligence `match_resume_to_role.resume_text`
    3. else pass `resume_source.resume_url` to Candidate Intelligence `match_resume_to_role.resume_url`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    candidate = await _api_request("GET", f"/c/{company_id}/candidates/{payload.candidate_id}", key)
    resume_source = _resume_source_from_candidate(candidate)
    result: dict[str, Any] = {"resume_source": resume_source}
    if payload.include_raw_candidate:
        result["raw_candidate"] = candidate
    return result


@router.post("/get_candidates_resume_sources", operation_id="recruitee_get_candidates_resume_sources")
async def get_candidates_resume_sources(
    payload: GetCandidatesResumeSourcesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Batch-resolve resume source fields for many candidates.

    Required input:
    - `candidate_ids`: list of candidate IDs from `recruitee_list_candidates`

    Output (compact by default):
    - `results`: list of `{ candidate_id, resume_source, error? }`
    - each result includes `raw_candidate` only when `include_raw_candidate=true`
    - `count`

    Cross-MCP usage:
    - Convert this output into `batch_match_resumes_to_role.resumes[]` by mapping each item:
      - `candidate_id` as-is
      - use `resume_text` when available, otherwise `resume_url`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    candidate_ids = payload.candidate_ids[:50]

    results: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        try:
            candidate = await _api_request("GET", f"/c/{company_id}/candidates/{candidate_id}", key)
            item = {"candidate_id": candidate_id, "resume_source": _resume_source_from_candidate(candidate)}
            if payload.include_raw_candidate:
                item["raw_candidate"] = candidate
            results.append(item)
        except Exception as ex:
            results.append({"candidate_id": candidate_id, "error": str(ex)})
    return {"count": len(results), "results": results}


@router.post("/build_batch_matching_input", operation_id="recruitee_build_batch_matching_input")
async def build_batch_matching_input(
    payload: GetCandidatesResumeSourcesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Build a ready-to-use payload fragment for Candidate Intelligence MCP batch matching.

    Required input:
    - `candidate_ids`: list of candidate IDs from `recruitee_list_candidates`

    Output:
    - `resumes`: array formatted exactly for
      Candidate Intelligence `batch_match_resumes_to_role.resumes[]`
      with each item as:
      - `{ "candidate_id": "...", "resume_text": "..." }` when text is available
      - `{ "candidate_id": "...", "resume_url": "..." }` otherwise
    - `skipped`: candidates with no usable resume source
    - `count`

    Usage:
    1. call this tool
    2. call Candidate Intelligence `batch_match_resumes_to_role` with:
       - your `role_requirements_text`
       - returned `resumes` array
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    candidate_ids = payload.candidate_ids[:50]

    resumes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate_id in candidate_ids:
        try:
            candidate = await _api_request("GET", f"/c/{company_id}/candidates/{candidate_id}", key)
            source = _resume_source_from_candidate(candidate)
            if source.get("resume_text"):
                resumes.append({"candidate_id": str(candidate_id), "resume_text": source["resume_text"]})
            elif source.get("resume_url"):
                resumes.append({"candidate_id": str(candidate_id), "resume_url": source["resume_url"]})
            else:
                skipped.append({"candidate_id": candidate_id, "reason": "No resume_text or resume_url in candidate profile"})
        except Exception as ex:
            skipped.append({"candidate_id": candidate_id, "reason": str(ex)})

    return {"count": len(resumes), "resumes": resumes, "skipped": skipped}


@router.post("/move_candidate_stage", operation_id="recruitee_move_candidate_stage")
async def move_candidate_stage(payload: MoveCandidateStageRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Move a candidate to a specific stage in an offer pipeline.

    Required input:
    - `candidate_id`
    - `offer_id`
    - `stage_id`

    Output:
    - `{ "result": { ... } }`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()

    # endpoint may vary by account version; this is common move action pattern.
    body = {
        "offer_id": payload.offer_id,
        "stage_id": payload.stage_id,
    }
    data = await _api_request(
        "POST",
        f"/c/{company_id}/candidates/{payload.candidate_id}/move",
        key,
        json=body,
    )
    return {"result": data}


@router.post("/register_webhook", operation_id="recruitee_register_webhook")
async def register_webhook(payload: RegisterWebhookRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Register a Recruitee webhook for hiring workflow events.

    Required input:
    - `target_url`: HTTPS callback endpoint you control
    - `event_type`: Recruitee event name (for example `candidate_moved`)

    Output:
    - `{ "webhook": { ... } }`
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()
    body = {
        "target_url": payload.target_url,
        "event_type": payload.event_type,
    }
    data = await _api_request("POST", f"/c/{company_id}/webhooks", key, json=body)
    return {"webhook": data}


@router.get("/model_info", operation_id="recruitee_model_info")
async def model_info() -> dict:
    """
    Return service configuration behavior for debugging MCP setup.

    Use this to confirm:
    - API base URL
    - required env fields
    - key resolution order (Platform Integration first, env fallback second)
    """
    return {
        "service": "recruitee_mcp",
        "api_base": settings.RECRUITEE_API_URL,
        "requires": ["RECRUITEE_COMPANY_ID"],
        "auth_resolution_order": [
            f"PlatformIntegration(service='{settings.RECRUITEE_KEY_SERVICE_NAME}')",
            "RECRUITEE_API_KEY env fallback",
        ],
    }
