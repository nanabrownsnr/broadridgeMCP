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


def _resolve_bearer_token(platform_client: PlatformIntegrationClient | None = None) -> str:
    if platform_client is not None:
        try:
            token = platform_client.get_access_key(settings.PANDADOC_KEY_SERVICE_NAME)
            if token:
                return token
        except Exception:
            pass

    if settings.PANDADOC_API_KEY:
        return settings.PANDADOC_API_KEY

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


@router.post("/list_templates", operation_id="pandadoc_list_templates")
async def list_templates(
    payload: ListTemplatesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """List PandaDoc templates with optional query/tag filters."""
    token = _resolve_bearer_token(platform_client)
    params: dict = {"count": payload.count, "page": payload.page}
    if payload.q:
        params["q"] = payload.q
    if payload.tag:
        params["tag"] = payload.tag
    data = await _request("GET", "/public/v1/templates", token, params=params)

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
    token = _resolve_bearer_token(platform_client)
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

    data = await _request("POST", "/public/v1/documents", token, json_body=body)
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
    token = _resolve_bearer_token(platform_client)
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
            data = await _request("GET", path, token)
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
    """Get PandaDoc document details and status."""
    token = _resolve_bearer_token(platform_client)
    data = await _request("GET", f"/public/v1/documents/{payload.document_id}", token)
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
        "raw": data,
    }


@router.post("/send_document", operation_id="pandadoc_send_document")
async def send_document(
    payload: SendDocumentRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """Send a PandaDoc document for signing."""
    token = _resolve_bearer_token(platform_client)
    body: dict = {"silent": payload.silent}
    if payload.subject:
        body["subject"] = payload.subject
    if payload.message:
        body["message"] = payload.message
    data = await _request("POST", f"/public/v1/documents/{payload.document_id}/send", token, json_body=body)
    return {"document_id": payload.document_id, "result": data}


@router.post("/list_documents", operation_id="pandadoc_list_documents")
async def list_documents(
    payload: ListDocumentsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """List PandaDoc documents with optional search/status filters."""
    token = _resolve_bearer_token(platform_client)
    params: dict = {"count": payload.count, "page": payload.page}
    if payload.q:
        params["q"] = payload.q
    if payload.status:
        params["status"] = payload.status

    data = await _request("GET", "/public/v1/documents", token, params=params)
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
