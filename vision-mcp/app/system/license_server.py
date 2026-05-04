import asyncio
import sys
import uuid

import httpx
from core.config import settings
from jose import jwt

LICENSE_SERVER_URL = settings.LICENSE_SERVER_BASE_URL.rstrip("/")
JWKS_URL = f"{LICENSE_SERVER_URL}/{settings.LICENSE_SERVER_JWKS_ENDPOINT.lstrip('/')}" if settings.LICENSE_SERVER_BASE_URL else ""
LICENSE_ACTIVATION_URL = (
    f"{LICENSE_SERVER_URL}/{settings.LICENSE_SERVER_ACTIVATION_ENDPOINT.lstrip('/')}"
    if settings.LICENSE_SERVER_BASE_URL
    else ""
)


def get_device_id() -> str:
    return f"{uuid.getnode():012x}"


async def validate_license_or_exit() -> None:
    if not (settings.LICENSE_SERVER_BASE_URL and settings.LICENSE_KEY):
        return

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            LICENSE_ACTIVATION_URL,
            json={"license_key": settings.LICENSE_KEY, "device_id": get_device_id()},
        )
        response.raise_for_status()


async def monitor_license_server() -> None:
    while True:
        try:
            await validate_license_or_exit()
        except Exception:
            sys.exit(1)
        await asyncio.sleep(86400)
