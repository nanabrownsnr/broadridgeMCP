from datetime import datetime

import httpx
from core.authentication.auth_middleware import get_current_token, get_persona_id
from core.config import settings
from fastapi import Depends
from jose import jwt
from schemas.token import TokenData


class PlatformIntegrationClient:
    _client_auth_token: str | None = None
    _client_auth_token_expires_at: datetime | None = None

    def __init__(self, auth_token: str, persona_id: str | None = None):
        self.auth_token = auth_token
        self.persona_id = persona_id

    def _get_headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        if self.persona_id:
            headers["Authorization"] = f"Bearer {self.get_client_auth_token()}"
            headers[settings.PERSONA_ID_HEADER] = self.persona_id
        return headers

    def get_client_auth_token(self) -> str:
        if (
            PlatformIntegrationClient._client_auth_token
            and PlatformIntegrationClient._client_auth_token_expires_at
            and PlatformIntegrationClient._client_auth_token_expires_at > datetime.now()
        ):
            return PlatformIntegrationClient._client_auth_token

        data = {
            "client_id": settings.CLIENT_ID,
            "client_secret": settings.CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        response = httpx.post(
            f"{settings.ACCOUNT_SERVICE_URL.rstrip('/')}/api/v2/auth/login",
            data=data,
            timeout=60,
        )
        response.raise_for_status()
        access_token = response.json().get("access_token")
        if not access_token:
            raise RuntimeError("Unable to retrieve client auth token")

        PlatformIntegrationClient._client_auth_token = access_token
        exp = jwt.get_unverified_claims(access_token).get("exp")
        PlatformIntegrationClient._client_auth_token_expires_at = datetime.fromtimestamp(exp) if exp else None
        return access_token


def get_platform_client(
    current_token: TokenData = Depends(get_current_token),
    persona_id: str | None = Depends(get_persona_id),
) -> PlatformIntegrationClient:
    return PlatformIntegrationClient(current_token.access_token, persona_id)
