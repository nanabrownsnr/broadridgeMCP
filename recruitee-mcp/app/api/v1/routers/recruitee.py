from typing import Any

import httpx
from app.core.config import settings
from app.core.platfom_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.recruitee import (
    CreateJobRequest,
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
async def list_job_openings(platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Return all job openings with a compact list for tool chaining.

    Use this as the first discovery step when the user asks:
    - "show all roles"
    - "how many openings do we have"
    - "find offer id for role X"

    Output:
    - `total_count`: number of offers
    - `openings`: list of `{ offer_id, title, status, slug, published_at }`
    - `raw`: full provider payload for advanced logic
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
    return {
        "total_count": data.get("meta", {}).get("total_count", len(openings)),
        "openings": openings,
        "raw": data,
    }


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
        "raw_offer": data,
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
    - `raw`: full provider payload

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
    return {"offer_id": payload.offer_id, "stages": stages, "raw": data}


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
    - `{ "candidates": { "meta": { ... }, "candidates": [ ... ] } }`
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
    return {"candidates": data}


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
