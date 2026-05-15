import httpx
from app.core.config import settings
from app.core.platform_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.pandadoc import (
    CreateDocumentFromTemplateRequest,
    DocumentDetailsRequest,
    ListDocumentsRequest,
    ListTemplatesRequest,
    SendDocumentRequest,
    TemplateDetailsRequest,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/pandadoc", tags=["pandadoc"])


def _resolve_bearer_token_candidates(platform_client: PlatformIntegrationClient | None = None) -> list[tuple[str, str]]:
    """
    Resolve auth token candidates in priority order and de-duplicate values.
    """
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    if platform_client is not None:
        try:
            token = platform_client.get_access_key(settings.PANDADOC_KEY_SERVICE_NAME)
            if token and token not in seen:
                candidates.append(("pis", token))
                seen.add(token)
        except Exception:
            pass

    if settings.PANDADOC_API_KEY and settings.PANDADOC_API_KEY not in seen:
        candidates.append(("env", settings.PANDADOC_API_KEY))
        seen.add(settings.PANDADOC_API_KEY)

    if candidates:
        return candidates

    raise HTTPException(
        status_code=500,
        detail=(
            "PandaDoc credential not configured. Provide via Platform Integration "
            f"service='{settings.PANDADOC_KEY_SERVICE_NAME}' or PANDADOC_API_KEY env."
        ),
    )


def _base_url() -> str:
    return settings.PANDADOC_API_URL.rstrip("/")


async def _request(
    method: str,
    path: str,
    token: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict:
    url = f"{_base_url()}{path}"
    headers = {
        "Authorization": f"API-Key {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, url, headers=headers, json=json_body, params=params)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])
    if not response.text:
        return {}
    return response.json()


async def _request_with_failover(
    method: str,
    path: str,
    token_candidates: list[tuple[str, str]],
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict:
    """
    Execute PandaDoc request with auth failover.

    If the PIS token yields 401/403, retries with env token when available.
    """
    failures: list[str] = []
    for idx, (source, token) in enumerate(token_candidates):
        try:
            return await _request(method, path, token, json_body=json_body, params=params)
        except HTTPException as ex:
            if ex.status_code in (401, 403) and idx < len(token_candidates) - 1:
                failures.append(f"{source}:{ex.status_code}")
                continue
            if failures:
                raise HTTPException(
                    status_code=ex.status_code,
                    detail=f"{ex.detail} | auth_attempts={','.join(failures + [f'{source}:{ex.status_code}'])}",
                )
            raise


@router.post("/list_templates", operation_id="pandadoc_list_templates")
async def list_templates(
    payload: ListTemplatesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """List PandaDoc templates with optional query/tag filters."""
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    params: dict = {"count": payload.count, "page": payload.page}
    if payload.q:
        params["q"] = payload.q
    if payload.tag:
        params["tag"] = payload.tag
    data = await _request_with_failover("GET", "/public/v1/templates", token_candidates, params=params)

    results = []
    for t in data.get("results", []):
        results.append(
            {
                "template_uuid": t.get("id") or t.get("uuid"),
                "name": t.get("name"),
                "date_created": t.get("date_created"),
                "date_modified": t.get("date_modified"),
                "folder_uuid": t.get("folder_uuid"),
                "tags": t.get("tags", []),
            }
        )

    return {
        "count": len(results),
        "next": data.get("next"),
        "previous": data.get("previous"),
        "templates": results,
    }


@router.post("/create_document_from_template", operation_id="pandadoc_create_document_from_template")
async def create_document_from_template(
    payload: CreateDocumentFromTemplateRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Create a PandaDoc document from a template.

    Note: creation is asynchronous; use get_document_details until status reaches document.draft.
    """
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    body: dict = {
        "name": payload.name,
        "template_uuid": payload.template_uuid,
        "recipients": [r.model_dump() for r in payload.recipients],
    }
    if payload.tokens:
        body["tokens"] = [{"name": k, "value": v} for k, v in payload.tokens.items()]
    if payload.fields:
        body["fields"] = payload.fields
    if payload.metadata:
        body["metadata"] = payload.metadata
    if payload.parse_form_fields is not None:
        body["parse_form_fields"] = payload.parse_form_fields

    data = await _request_with_failover("POST", "/public/v1/documents", token_candidates, json_body=body)
    return {
        "document_id": data.get("id") or data.get("uuid"),
        "name": data.get("name"),
        "status": data.get("status"),
        "date_created": data.get("date_created"),
        "raw": data,
    }


@router.post("/get_template_details", operation_id="pandadoc_get_template_details")
async def get_template_details(
    payload: TemplateDetailsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Get template details to discover recipient roles and available template structure before document creation.

    The router tries a couple of PandaDoc template detail endpoints for compatibility across API variants.
    """
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    tried: list[str] = []
    data: dict | None = None

    candidates = [
        f"/public/v1/templates/{payload.template_uuid}/details",
        f"/public/v1/templates/{payload.template_uuid}",
    ]
    last_error: HTTPException | None = None
    for path in candidates:
        tried.append(path)
        try:
            data = await _request_with_failover("GET", path, token_candidates)
            break
        except HTTPException as ex:
            last_error = ex
            if ex.status_code != 404:
                raise

    if data is None:
        if last_error is not None:
            raise last_error
        raise HTTPException(status_code=404, detail=f"Template not found. Tried: {tried}")

    recipients = data.get("recipients") or data.get("roles") or []
    tokens = data.get("tokens") or data.get("fields") or data.get("variables") or []
    return {
        "template_uuid": data.get("id") or data.get("uuid") or payload.template_uuid,
        "name": data.get("name"),
        "description": data.get("description"),
        "date_created": data.get("date_created"),
        "date_modified": data.get("date_modified"),
        "recipients": recipients,
        "tokens_or_fields": tokens,
        "detected_endpoints": tried,
        "raw": data,
    }


@router.post("/get_document_details", operation_id="pandadoc_get_document_details")
async def get_document_details(
    payload: DocumentDetailsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """Get PandaDoc rich document details and optionally generate review/signing session URLs."""
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    data = await _request_with_failover("GET", f"/public/v1/documents/{payload.document_id}/details", token_candidates)
    # Surface common URLs when present in PandaDoc response variants.
    document_url = data.get("document_url") or data.get("url")
    preview_url = None
    signing_url = None
    embedded = data.get("embedded")
    if isinstance(embedded, dict):
        preview_url = embedded.get("preview_url") or embedded.get("document_url")
        signing_url = embedded.get("recipient_view_url") or embedded.get("signing_url")

    links = data.get("links")
    if isinstance(links, dict):
        preview_url = preview_url or links.get("preview") or links.get("document")
        signing_url = signing_url or links.get("recipient_view") or links.get("sign")

    review_session: dict | None = None
    review_session_email_used: str | None = None
    review_session_error: str | None = None
    if payload.include_review_session:
        derived_email = payload.review_session_email
        if not derived_email:
            recs = data.get("recipients")
            if isinstance(recs, list):
                for rec in recs:
                    if isinstance(rec, dict) and rec.get("email"):
                        derived_email = rec["email"]
                        break
        if not derived_email:
            review_session_error = (
                "include_review_session=true but no email could be derived. "
                "Pass review_session_email explicitly."
            )
        else:
            review_session_email_used = derived_email
            review_session = await _request_with_failover(
                "POST",
                f"/public/v1/documents/{payload.document_id}/editing-sessions",
                token_candidates,
                json_body={
                    "email": derived_email,
                    "lifetime": payload.review_session_lifetime,
                },
            )

    signing_session: dict | None = None
    if payload.include_signing_session:
        if not payload.signing_recipient_email:
            raise HTTPException(
                status_code=400,
                detail="signing_recipient_email is required when include_signing_session=true",
            )
        signing_session = await _request_with_failover(
            "POST",
            f"/public/v1/documents/{payload.document_id}/session",
            token_candidates,
            json_body={
                "recipient": payload.signing_recipient_email,
                "lifetime": payload.signing_session_lifetime,
            },
        )
        if isinstance(signing_session, dict):
            signing_url = (
                signing_url
                or signing_session.get("session_url")
                or signing_session.get("url")
                or signing_session.get("recipient_view_url")
            )

    return {
        "document_id": payload.document_id,
        "name": data.get("name"),
        "status": data.get("status"),
        "date_created": data.get("date_created"),
        "date_modified": data.get("date_modified"),
        "recipients": data.get("recipients"),
        "document_url": document_url,
        "preview_url": preview_url,
        "signing_url": signing_url,
        "review_session": review_session,
        "review_session_email_used": review_session_email_used,
        "review_session_error": review_session_error,
        "signing_session": signing_session,
        "raw": data,
    }


@router.post("/send_document", operation_id="pandadoc_send_document")
async def send_document(
    payload: SendDocumentRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """Send a PandaDoc document for signing."""
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    body: dict = {"silent": payload.silent}
    if payload.subject:
        body["subject"] = payload.subject
    if payload.message:
        body["message"] = payload.message
    data = await _request_with_failover("POST", f"/public/v1/documents/{payload.document_id}/send", token_candidates, json_body=body)
    return {"document_id": payload.document_id, "result": data}


@router.post("/list_documents", operation_id="pandadoc_list_documents")
async def list_documents(
    payload: ListDocumentsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """List PandaDoc documents with optional search/status filters."""
    token_candidates = _resolve_bearer_token_candidates(platform_client)
    params: dict = {"count": payload.count, "page": payload.page}
    if payload.q:
        params["q"] = payload.q
    if payload.status:
        params["status"] = payload.status

    data = await _request_with_failover("GET", "/public/v1/documents", token_candidates, params=params)
    rows = []
    for d in data.get("results", []):
        rows.append(
            {
                "document_id": d.get("id") or d.get("uuid"),
                "name": d.get("name"),
                "status": d.get("status"),
                "date_created": d.get("date_created"),
                "date_modified": d.get("date_modified"),
            }
        )
    return {"count": len(rows), "next": data.get("next"), "previous": data.get("previous"), "documents": rows}


@router.get("/model_info", operation_id="pandadoc_model_info")
async def model_info() -> dict:
    """Return PandaDoc MCP auth/config behavior."""
    return {
        "service": "pandadoc_mcp",
        "api_base": settings.PANDADOC_API_URL,
        "auth_resolution_order": [
            f"PlatformIntegration(service='{settings.PANDADOC_KEY_SERVICE_NAME}')",
            "PANDADOC_API_KEY env fallback",
        ],
        "auth_scheme": "Authorization: API-Key <token>",
    }
