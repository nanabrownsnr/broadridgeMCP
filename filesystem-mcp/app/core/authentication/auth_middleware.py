from typing import List

from app.core.authentication.auth_token import verify_access_token
from app.core.config import settings
from app.schemas.token import TokenData
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


def get_persona_id(persona_id: str | None = Header(default=None, alias=settings.PERSONA_ID_HEADER)) -> str | None:
    return persona_id


def _local_token() -> TokenData:
    return TokenData(
        id="local",
        email="local@local",
        role="admin",
        type="bearer",
        client_id="local",
        username="local",
        access_token="local",
    )


async def get_current_token(credentials: HTTPAuthorizationCredentials | None = Security(security)) -> TokenData:
    # No Authorization header: run in local mode.
    if credentials is None:
        return _local_token()

    # Invalid/expired Authorization header: gracefully degrade to local mode so
    # endpoint-level credential failover (PIS -> env) can still execute.
    try:
        token_data = await verify_access_token(credentials.credentials)
    except HTTPException:
        return _local_token()

    if token_data.type != "bearer":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token type")
    return token_data


def get_effective_owner_id(
    token_data: TokenData = Depends(get_current_token),
    persona_id: str | None = Depends(get_persona_id),
) -> str:
    return persona_id or token_data.id


class RoleBasedAccessControl:
    def __init__(self, roles: List[str]) -> None:
        self.allowed_roles = roles

    def __call__(self, current_token: TokenData = Depends(get_current_token)) -> None:
        if current_token.role not in self.allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User role not permitted")
