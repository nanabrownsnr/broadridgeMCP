from typing import Any

import httpx
from app.core.config import settings
from app.core.platfom_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.recruitee import (
    CreateJobRequest,
    GetJobPublicUrlRequest,
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


@router.post("/create_job", operation_id="recruitee_create_job")
async def create_job(payload: CreateJobRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Create a new Recruitee role (offer).

    Use this when the hiring agent receives a request like
    "open a new backend role" and must create the job shell first.

    Required input:
    - `title`

    Optional input:
    - `description`, `pipeline_template_id`, `department`, `location`, `status`

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
    if payload.description is not None:
        body["description"] = payload.description
    if payload.pipeline_template_id is not None:
        body["pipeline_template_id"] = payload.pipeline_template_id
    if payload.department is not None:
        body["department"] = payload.department
    if payload.location is not None:
        body["location"] = payload.location

    data = await _api_request("POST", f"/c/{company_id}/offers", key, json=body)
    return {"offer": data}


@router.post("/publish_job", operation_id="recruitee_publish_job")
async def publish_job(payload: PublishJobRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Publish an existing Recruitee role so it becomes publicly visible.

    Required input:
    - `offer_id` returned from `recruitee_create_job`
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


@router.post("/list_candidates", operation_id="recruitee_list_candidates")
async def list_candidates(payload: ListCandidatesRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    List candidates, optionally scoped by role (`offer_id`) and stage.

    Required input:
    - none

    Optional input:
    - `offer_id`, `stage_id`, `limit`, `page`

    Typical usage:
    - "how many applied to role X"
    - "show candidates in Offer Accepted stage"
    """
    key = _resolve_api_key(platform_client)
    company_id = _company_id()

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
