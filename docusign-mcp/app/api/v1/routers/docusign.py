import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from jose import jwt
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
_JWT_TOKEN_CACHE: dict[str, Any] = {"access_token": None, "expires_at": 0}


def _load_store() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"candidate_index": {}, "envelopes": {}}
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def _save_store(payload: dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _docusign_oauth_base() -> str:
    base = settings.DOCUSIGN_BASE_URL.lower()
    return "https://account-d.docusign.com" if "demo.docusign.net" in base else "https://account.docusign.com"


async def _mint_jwt_access_token() -> str:
    if not settings.DOCUSIGN_INTEGRATION_KEY or not settings.DOCUSIGN_USER_ID or not settings.DOCUSIGN_PRIVATE_KEY_PATH:
        raise HTTPException(
            status_code=500,
            detail=(
                "JWT mode requires DOCUSIGN_INTEGRATION_KEY, DOCUSIGN_USER_ID, "
                "and DOCUSIGN_PRIVATE_KEY_PATH."
            ),
        )

    now = int(time.time())
    cached = _JWT_TOKEN_CACHE.get("access_token")
    expires_at = int(_JWT_TOKEN_CACHE.get("expires_at", 0))
    if cached and expires_at - now > 120:
        return str(cached)

    private_key = Path(settings.DOCUSIGN_PRIVATE_KEY_PATH)
    if not private_key.exists():
        raise HTTPException(
            status_code=500,
            detail=f"DocuSign private key file not found at {settings.DOCUSIGN_PRIVATE_KEY_PATH}",
        )

    aud = _docusign_oauth_base()
    payload = {
        "iss": settings.DOCUSIGN_INTEGRATION_KEY,
        "sub": settings.DOCUSIGN_USER_ID,
        "aud": aud,
        "iat": now,
        "exp": now + 3600,
        "scope": settings.DOCUSIGN_JWT_SCOPES,
    }
    assertion = jwt.encode(payload, private_key.read_text(encoding="utf-8"), algorithm="RS256")

    token_url = f"{aud}/oauth/token"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])

    data = response.json()
    access_token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))
    if not access_token:
        raise HTTPException(status_code=500, detail="DocuSign JWT token response missing access_token.")

    _JWT_TOKEN_CACHE["access_token"] = access_token
    _JWT_TOKEN_CACHE["expires_at"] = now + expires_in
    return str(access_token)


async def _resolve_bearer_token(platform_client: PlatformIntegrationClient | None = None) -> str:
    if settings.DOCUSIGN_AUTH_MODE.strip().lower() == "jwt":
        return await _mint_jwt_access_token()

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
            "DocuSign token mode missing credentials. Provide via Platform Integration "
            f"service='{settings.DOCUSIGN_KEY_SERVICE_NAME}' or DOCUSIGN_ACCESS_TOKEN env."
        ),
    )


def _resolve_token_mode_candidates(platform_client: PlatformIntegrationClient | None = None) -> list[tuple[str, str]]:
    """
    Resolve token-mode auth candidates in priority order (`pis`, then `env`) and de-duplicate values.
    """
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    if platform_client is not None:
        try:
            token = platform_client.get_access_key(settings.DOCUSIGN_KEY_SERVICE_NAME)
            if token and token not in seen:
                candidates.append(("pis", token))
                seen.add(token)
        except Exception:
            pass
    if settings.DOCUSIGN_ACCESS_TOKEN and settings.DOCUSIGN_ACCESS_TOKEN not in seen:
        candidates.append(("env", settings.DOCUSIGN_ACCESS_TOKEN))
        seen.add(settings.DOCUSIGN_ACCESS_TOKEN)
    return candidates


def _base_rest_url() -> str:
    if not settings.DOCUSIGN_BASE_URL or not settings.DOCUSIGN_ACCOUNT_ID:
        raise HTTPException(status_code=500, detail="DOCUSIGN_BASE_URL and DOCUSIGN_ACCOUNT_ID are required")
    base = settings.DOCUSIGN_BASE_URL.rstrip("/")
    if not base.lower().endswith("/restapi"):
        base = f"{base}/restapi"
    return f"{base}/v2.1/accounts/{settings.DOCUSIGN_ACCOUNT_ID}"


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


async def _api_request_with_failover(
    method: str,
    path: str,
    platform_client: PlatformIntegrationClient | None = None,
    json_body: dict | None = None,
) -> dict:
    """
    Execute DocuSign API request with auth failover behavior.

    - JWT mode: uses minted JWT access token only.
    - Token mode: tries PIS token first, then env token on 401/403.
    """
    if settings.DOCUSIGN_AUTH_MODE.strip().lower() == "jwt":
        token = await _resolve_bearer_token(platform_client)
        return await _api_request(method, path, token, json_body=json_body)

    token_candidates = _resolve_token_mode_candidates(platform_client)
    if not token_candidates:
        raise HTTPException(
            status_code=500,
            detail=(
                "DocuSign token mode missing credentials. Provide via Platform Integration "
                f"service='{settings.DOCUSIGN_KEY_SERVICE_NAME}' or DOCUSIGN_ACCESS_TOKEN env."
            ),
        )

    failures: list[str] = []
    for idx, (source, token) in enumerate(token_candidates):
        try:
            return await _api_request(method, path, token, json_body=json_body)
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
    Send a DocuSign envelope from an existing template.

    Use when:
    1. Templates are managed in DocuSign UI.
    2. Caller has `template_id`, recipient email/name, and template `role_name`.
    3. Envelope must be indexed by `candidate_id` (and optional `client_id`) for later retrieval.
    """
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

    data = await _api_request_with_failover("POST", "/envelopes", platform_client, envelope_definition)
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
    """Get current envelope lifecycle status by `envelope_id`."""
    data = await _api_request_with_failover("GET", f"/envelopes/{payload.envelope_id}", platform_client)
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
    List envelopes linked to `candidate_id` from the local envelope index.

    Use this before status/document fetches to discover envelope IDs for a candidate.
    """
    store = _load_store()
    envelope_ids = store.get("candidate_index", {}).get(payload.candidate_id, [])
    results: list[dict[str, Any]] = []

    for envelope_id in envelope_ids:
        item = {"envelope_id": envelope_id, **store.get("envelopes", {}).get(envelope_id, {})}
        if payload.include_status_lookup:
            try:
                status = await _api_request_with_failover("GET", f"/envelopes/{envelope_id}", platform_client)
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
    Return completed-envelope document references for a candidate.

    Output contains DocuSign document API download paths (`document_download_path`)
    for each matched envelope document.
    """
    store = _load_store()
    envelope_ids = store.get("candidate_index", {}).get(payload.candidate_id, [])
    docs: list[dict[str, Any]] = []

    for envelope_id in envelope_ids:
        env = await _api_request_with_failover("GET", f"/envelopes/{envelope_id}", platform_client)
        status = (env.get("status") or "").lower()
        if payload.completed_only and status != "completed":
            continue
        listing = await _api_request_with_failover("GET", f"/envelopes/{envelope_id}/documents", platform_client)
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
    List templates in the connected DocuSign account.

    Use this tool first to discover `template_id` values for `docusign_send_envelope_from_template`.
    """
    qs: list[str] = [f"count={payload.count}"]
    if payload.search_text:
        qs.append(f"search_text={payload.search_text}")
    if payload.include_recipients:
        qs.append("include=recipients")
    query = "&".join(qs)
    data = await _api_request_with_failover("GET", f"/templates?{query}", platform_client)

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
    Fetch template metadata and optional recipients/documents for a specific `template_id`.

    Use to validate role names before sending from template.
    """
    include_parts: list[str] = []
    if payload.include_documents:
        include_parts.append("documents")
    if payload.include_recipients:
        include_parts.append("recipients")

    path = f"/templates/{payload.template_id}"
    if include_parts:
        path = f"{path}?include={','.join(include_parts)}"
    data = await _api_request_with_failover("GET", path, platform_client)
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
    """Return DocuSign MCP config/auth behavior for diagnostics."""
    return {
        "service": "docusign_mcp",
        "api_base": settings.DOCUSIGN_BASE_URL,
        "requires": ["DOCUSIGN_BASE_URL", "DOCUSIGN_ACCOUNT_ID"],
        "auth_mode": settings.DOCUSIGN_AUTH_MODE,
        "auth_resolution_order": [
            "DOCUSIGN_AUTH_MODE=jwt -> auto-minted JWT access token",
            f"PlatformIntegration(service='{settings.DOCUSIGN_KEY_SERVICE_NAME}')",
            "DOCUSIGN_ACCESS_TOKEN env fallback (token mode)",
        ],
        "store_path": settings.DOCUSIGN_STORE_PATH,
    }
