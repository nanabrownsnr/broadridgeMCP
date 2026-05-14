import httpx
from app.core.config import settings
from app.core.platform_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.wonder import WonderApiRequest, WonderAuthDiagnoseRequest
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/wonder", tags=["wonder"])


def _resolve_token(platform_client: PlatformIntegrationClient | None = None) -> str:
    if platform_client is not None:
        try:
            key = platform_client.get_access_key(settings.WONDER_KEY_SERVICE_NAME)
            if key:
                return key
        except Exception:
            pass

    if settings.WONDER_API_KEY:
        return settings.WONDER_API_KEY

    raise HTTPException(
        status_code=500,
        detail=(
            "Wonder credential not configured. Provide via Platform Integration "
            f"service='{settings.WONDER_KEY_SERVICE_NAME}' or WONDER_API_KEY env."
        ),
    )


def _build_headers(token: str) -> dict[str, str]:
    prefix = settings.WONDER_AUTH_SCHEME.strip()
    if not prefix:
        return {"Authorization": token, "Content-Type": "application/json"}
    return {"Authorization": f"{prefix} {token}", "Content-Type": "application/json"}


@router.post("/api_request", operation_id="wonder_api_request")
async def wonder_api_request(
    payload: WonderApiRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Call Wonder API with PIS->env credential fallback.

    Tool behavior:
    1) Resolve credential from Platform Integration using WONDER_KEY_SERVICE_NAME.
    2) If unavailable, fall back to WONDER_API_KEY in env.
    3) Execute request against WONDER_API_URL + path.

    Agents should ask for missing endpoint/path context only when it cannot be inferred.
    """
    token = _resolve_token(platform_client)
    method = payload.method.upper().strip()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise HTTPException(status_code=400, detail=f"Unsupported method: {method}")
    if not payload.path.startswith("/"):
        raise HTTPException(status_code=400, detail="path must start with '/'")

    url = f"{settings.WONDER_API_URL.rstrip('/')}{payload.path}"
    headers = _build_headers(token)

    async with httpx.AsyncClient(timeout=payload.timeout_seconds) as client:
        response = await client.request(
            method,
            url,
            params=payload.query,
            json=payload.json_body,
            headers=headers,
        )

    content_type = response.headers.get("content-type", "")
    body: dict | str
    if "application/json" in content_type:
        try:
            body = response.json()
        except Exception:
            body = response.text
    else:
        body = response.text

    return {
        "ok": response.status_code < 400,
        "status_code": response.status_code,
        "url": str(response.request.url),
        "method": method,
        "response": body,
    }


@router.post("/auth_diagnose", operation_id="wonder_auth_diagnose")
async def wonder_auth_diagnose(
    payload: WonderAuthDiagnoseRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Verify Wonder auth resolution order and optionally test an endpoint.
    """
    source = "env"
    token = ""
    try:
        token = platform_client.get_access_key(settings.WONDER_KEY_SERVICE_NAME)
        if token:
            source = "pis"
    except Exception:
        token = ""

    if not token:
        token = settings.WONDER_API_KEY
        source = "env" if token else "missing"

    if not token:
        return {
            "ok": False,
            "auth_source": "missing",
            "detail": "No token found in PIS or WONDER_API_KEY env",
        }

    method = payload.method.upper().strip()
    if not payload.test_path.startswith("/"):
        raise HTTPException(status_code=400, detail="test_path must start with '/'")

    url = f"{settings.WONDER_API_URL.rstrip('/')}{payload.test_path}"
    headers = _build_headers(token)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, url, headers=headers)

    return {
        "ok": response.status_code < 400,
        "auth_source": source,
        "status_code": response.status_code,
        "method": method,
        "url": url,
        "response_preview": response.text[:500],
    }


@router.get("/model_info", operation_id="wonder_model_info")
async def model_info() -> dict:
    """Return Wonder MCP configuration and credential resolution behavior."""
    return {
        "service": "wonder_mcp",
        "api_base": settings.WONDER_API_URL,
        "auth_resolution_order": [
            f"PlatformIntegration(service='{settings.WONDER_KEY_SERVICE_NAME}')",
            "WONDER_API_KEY env fallback",
        ],
        "auth_scheme": settings.WONDER_AUTH_SCHEME,
    }
