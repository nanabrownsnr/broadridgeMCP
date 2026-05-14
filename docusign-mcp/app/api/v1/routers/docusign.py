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
    SendEnvelopeRequest,
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


@router.post("/send_envelope_for_signature", operation_id="docusign_send_envelope_for_signature")
async def send_envelope_for_signature(
    payload: SendEnvelopeRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Send an envelope for signature and tag it with `candidate_id` so retrieval by client/candidate is reliable.
    """
    token = _resolve_bearer_token(platform_client)
    text_custom_fields = [{"name": "candidate_id", "value": payload.candidate_id, "show": "false"}]
    if payload.client_id:
        text_custom_fields.append({"name": "client_id", "value": payload.client_id, "show": "false"})

    envelope_definition: dict[str, Any] = {
        "emailSubject": payload.subject,
        "status": "sent",
        "customFields": {"textCustomFields": text_custom_fields},
    }
    if payload.message:
        envelope_definition["emailBlurb"] = payload.message

    if payload.template_id:
        envelope_definition["templateId"] = payload.template_id
        envelope_definition["templateRoles"] = [
            {"email": payload.recipient.email, "name": payload.recipient.name, "roleName": "signer"}
        ]
    else:
        envelope_definition["documents"] = [
            {
                "documentBase64": payload.document_base64,
                "name": payload.document_name,
                "fileExtension": payload.file_extension,
                "documentId": "1",
            }
        ]
        envelope_definition["recipients"] = {
            "signers": [
                {
                    "email": payload.recipient.email,
                    "name": payload.recipient.name,
                    "recipientId": "1",
                    "routingOrder": "1",
                }
            ]
        }

    data = await _api_request("POST", "/envelopes", token, envelope_definition)
    envelope_id = data.get("envelopeId")
    if not envelope_id:
        raise HTTPException(status_code=500, detail="DocuSign response missing envelopeId")
    _index_envelope(payload.candidate_id, envelope_id, payload.recipient.email, payload.client_id)
    return {
        "candidate_id": payload.candidate_id,
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
