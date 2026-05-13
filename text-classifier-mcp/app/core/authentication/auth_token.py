import asyncio
from datetime import datetime, timedelta

import httpx
from app.core.config import settings
from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from app.schemas.token import TokenData

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class CachedJWKSHelper:
    jwks: list[dict] | None = None
    last_updated: datetime | None = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_jwks(cls) -> list[dict]:
        async with cls._lock:
            if (
                cls.jwks is not None
                and cls.last_updated is not None
                and datetime.now() < cls.last_updated + timedelta(seconds=settings.ACCOUNT_SERVICE_JWKS_CACHE_TTL)
            ):
                return cls.jwks

            if not settings.ACCOUNT_SERVICE_URL:
                raise HTTPException(status_code=500, detail="ACCOUNT_SERVICE_URL is not configured")

            jwks_url = (
                f"{settings.ACCOUNT_SERVICE_URL.rstrip('/')}"
                f"/{settings.ACCOUNT_SERVICE_JWKS_ENDPOINT.lstrip('/')}"
            )
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                cls.jwks = response.json()["keys"]
                cls.last_updated = datetime.now()
                return cls.jwks

    @classmethod
    async def get_public_key(cls, kid: str) -> dict:
        jwks = await cls.get_jwks()
        for jwk in jwks:
            if jwk["kid"] == kid:
                return jwk
        raise HTTPException(status_code=401, detail="Key not found")


async def verify_access_token(token: str, audience: str | None = settings.SERVICE_ID) -> TokenData:
    try:
        header = jwt.get_unverified_header(token)
        key = await CachedJWKSHelper.get_public_key(header["kid"])
        payload = jwt.decode(token, key, algorithms=["RS256"], audience=audience)

        return TokenData(
            email=payload.get("sub"),
            id=payload.get("id"),
            type=payload.get("type"),
            role=payload.get("role"),
            client_id=payload.get("client_id"),
            username=payload.get("username"),
            access_token=token,
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Access token expired") from exc
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc

