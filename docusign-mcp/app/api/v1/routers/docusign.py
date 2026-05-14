import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from app.core.config import settings
from app.core.platform_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.docusign import (
    CompletedDocumentsRequest,
    EnvelopeStatusRequest,
    ListCandidateEnvelopesRequest,
    ListTemplatesRequest,
    SendEnvelopeFromTemplateRequest,
    TemplateDetailsRequest,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/docusign", tags=["docusign"])
STORE_PATH = Path(settings.DOCUSIGN_STORE_PATH)
STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"candidate_index": {}, "envelopes": {}}
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def _save_store(payload: dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _resolve_bearer_token(platform_client: PlatformIntegrationClient | None = None) -> str:
    if platform_client is not None:
        try:
            token = platform_client.get_access_key(settings.DOCUSIGN_KEY_SERVICE_NAME)
            if token:
                return token
        except Exception:
            pass
    if settings.DOCUSIGN_ACCESS_TOKEN:
        return settings.DOCUSIGN_ACCESS_TOKEN
    raise HTTPException(
        status_code=500,
        detail=(
            "DocuSign access token not configured. Provide via Platform Integration "
            f"service='{settings.DOCUSIGN_KEY_SERVICE_NAME}' or DOCUSIGN_ACCESS_TOKEN env."
        ),
    )


def _base_rest_url() -> str:
    if not settings.DOCUSIGN_BASE_URL or not settings.DOCUSIGN_ACCOUNT_ID:
        raise HTTPException(status_code=500, detail="DOCUSIGN_BASE_URL and DOCUSIGN_ACCOUNT_ID are required")
    return f"{settings.DOCUSIGN_BASE_URL.rstrip('/')}/v2.1/accounts/{settings.DOCUSIGN_ACCOUNT_ID}"


async def _api_request(method: str, path: str, token: str, json_body: dict | None = None) -> dict:
    url = f"{_base_rest_url()}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, url, headers=headers, json=json_body)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])
    if not response.text:
        return {}
    return response.json()


def _index_envelope(candidate_id: str, envelope_id: str, recipient_email: str, client_id: str | None) -> None:
    store = _load_store()
    idx = store["candidate_index"].setdefault(candidate_id, [])
    if envelope_id not in idx:
        idx.append(envelope_id)
    store["envelopes"][envelope_id] = {
        "candidate_id": candidate_id,
        "client_id": client_id,
        "recipient_email": recipient_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_store(store)


@router.post("/send_envelope_from_template", operation_id="docusign_send_envelope_from_template")
async def send_envelope_from_template(
    payload: SendEnvelopeFromTemplateRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Send an envelope from an existing DocuSign template.

    Use this for production flows where templates are managed in DocuSign UI and only template IDs are passed here.
    """
    token = _resolve_bearer_token(platform_client)
    text_custom_fields = [{"name": "candidate_id", "value": payload.candidate_id, "show": "false"}]
    if payload.client_id:
        text_custom_fields.append({"name": "client_id", "value": payload.client_id, "show": "false"})

    envelope_definition: dict[str, Any] = {
        "templateId": payload.template_id,
        "status": "sent",
        "customFields": {"textCustomFields": text_custom_fields},
        "templateRoles": [
            {
                "email": payload.recipient.email,
                "name": payload.recipient.name,
                "roleName": payload.role_name,
            }
        ],
    }
    if payload.subject:
        envelope_definition["emailSubject"] = payload.subject
    if payload.message:
        envelope_definition["emailBlurb"] = payload.message

    data = await _api_request("POST", "/envelopes", token, envelope_definition)
    envelope_id = data.get("envelopeId")
    if not envelope_id:
        raise HTTPException(status_code=500, detail="DocuSign response missing envelopeId")
    _index_envelope(payload.candidate_id, envelope_id, payload.recipient.email, payload.client_id)
    return {
        "candidate_id": payload.candidate_id,
        "template_id": payload.template_id,
        "envelope_id": envelope_id,
        "status": data.get("status"),
        "uri": data.get("uri"),
    }


@router.post("/get_envelope_status", operation_id="docusign_get_envelope_status")
async def get_envelope_status(
    payload: EnvelopeStatusRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """Get current envelope status by envelope id."""
    token = _resolve_bearer_token(platform_client)
    data = await _api_request("GET", f"/envelopes/{payload.envelope_id}", token)
    return {
        "envelope_id": payload.envelope_id,
        "status": data.get("status"),
        "completed_date_time": data.get("completedDateTime"),
        "created_date_time": data.get("createdDateTime"),
        "recipients_uri": data.get("recipientsUri"),
    }


@router.post("/list_candidate_envelopes", operation_id="docusign_list_candidate_envelopes")
async def list_candidate_envelopes(
    payload: ListCandidateEnvelopesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    List envelopes previously sent for a candidate/client identifier.
    """
    store = _load_store()
    envelope_ids = store.get("candidate_index", {}).get(payload.candidate_id, [])
    results: list[dict[str, Any]] = []

    token = _resolve_bearer_token(platform_client) if payload.include_status_lookup else None
    for envelope_id in envelope_ids:
        item = {"envelope_id": envelope_id, **store.get("envelopes", {}).get(envelope_id, {})}
        if payload.include_status_lookup and token:
            try:
                status = await _api_request("GET", f"/envelopes/{envelope_id}", token)
                item["status"] = status.get("status")
                item["completed_date_time"] = status.get("completedDateTime")
            except Exception as ex:
                item["status_error"] = str(ex)
        results.append(item)
    return {"candidate_id": payload.candidate_id, "count": len(results), "envelopes": results}


@router.post("/get_completed_documents", operation_id="docusign_get_completed_documents")
async def get_completed_documents(
    payload: CompletedDocumentsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Return completed envelope document references by candidate/client.

    Response returns DocuSign API document endpoints (`document_download_path`) for each completed envelope doc.
    """
    store = _load_store()
    envelope_ids = store.get("candidate_index", {}).get(payload.candidate_id, [])
    token = _resolve_bearer_token(platform_client)
    docs: list[dict[str, Any]] = []

    for envelope_id in envelope_ids:
        env = await _api_request("GET", f"/envelopes/{envelope_id}", token)
        status = (env.get("status") or "").lower()
        if payload.completed_only and status != "completed":
            continue
        listing = await _api_request("GET", f"/envelopes/{envelope_id}/documents", token)
        for d in listing.get("envelopeDocuments", []):
            doc_id = d.get("documentId")
            if not doc_id:
                continue
            docs.append(
                {
                    "candidate_id": payload.candidate_id,
                    "envelope_id": envelope_id,
                    "envelope_status": status,
                    "document_id": doc_id,
                    "document_name": d.get("name"),
                    "document_type": d.get("type"),
                    "document_download_path": f"/envelopes/{envelope_id}/documents/{doc_id}",
                }
            )

    return {"candidate_id": payload.candidate_id, "count": len(docs), "documents": docs}


@router.post("/list_templates", operation_id="docusign_list_templates")
async def list_templates(
    payload: ListTemplatesRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    List available DocuSign templates so agents can discover valid template IDs before sending.
    """
    token = _resolve_bearer_token(platform_client)
    qs: list[str] = [f"count={payload.count}"]
    if payload.search_text:
        qs.append(f"search_text={payload.search_text}")
    if payload.include_recipients:
        qs.append("include=recipients")
    query = "&".join(qs)
    data = await _api_request("GET", f"/templates?{query}", token)

    items: list[dict[str, Any]] = []
    for t in data.get("envelopeTemplates", []):
        row = {
            "template_id": t.get("templateId") or t.get("template_id") or t.get("id"),
            "name": t.get("name"),
            "description": t.get("description"),
            "created": t.get("created"),
            "last_modified": t.get("lastModified"),
            "shared": t.get("shared"),
            "folder_id": t.get("folderId"),
        }
        if payload.include_recipients:
            row["recipients"] = t.get("recipients")
        items.append(row)
    return {"count": len(items), "templates": items}


@router.post("/get_template_details", operation_id="docusign_get_template_details")
async def get_template_details(
    payload: TemplateDetailsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Get detailed metadata for a single DocuSign template, including recipients/documents when requested.
    """
    token = _resolve_bearer_token(platform_client)
    include_parts: list[str] = []
    if payload.include_documents:
        include_parts.append("documents")
    if payload.include_recipients:
        include_parts.append("recipients")

    path = f"/templates/{payload.template_id}"
    if include_parts:
        path = f"{path}?include={','.join(include_parts)}"
    data = await _api_request("GET", path, token)
    return {
        "template_id": data.get("templateId") or payload.template_id,
        "name": data.get("name"),
        "description": data.get("description"),
        "email_subject": data.get("emailSubject"),
        "email_blurb": data.get("emailBlurb"),
        "created": data.get("created"),
        "last_modified": data.get("lastModified"),
        "shared": data.get("shared"),
        "documents": data.get("documents") if payload.include_documents else None,
        "recipients": data.get("recipients") if payload.include_recipients else None,
        "raw_template": data,
    }


@router.get("/model_info", operation_id="docusign_model_info")
async def model_info() -> dict:
    """Return DocuSign MCP auth and storage config behavior."""
    return {
        "service": "docusign_mcp",
        "api_base": settings.DOCUSIGN_BASE_URL,
        "requires": ["DOCUSIGN_BASE_URL", "DOCUSIGN_ACCOUNT_ID"],
        "auth_resolution_order": [
            f"PlatformIntegration(service='{settings.DOCUSIGN_KEY_SERVICE_NAME}')",
            "DOCUSIGN_ACCESS_TOKEN env fallback",
        ],
        "store_path": settings.DOCUSIGN_STORE_PATH,
    }
