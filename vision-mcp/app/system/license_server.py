import asyncio
import sys
import uuid
import logging

import httpx
from app.core.config import settings
from jose import jwt

LICENSE_SERVER_URL = settings.LICENSE_SERVER_BASE_URL.rstrip("/")
JWKS_URL = f"{LICENSE_SERVER_URL}/{settings.LICENSE_SERVER_JWKS_ENDPOINT.lstrip('/')}" if settings.LICENSE_SERVER_BASE_URL else ""
LICENSE_ACTIVATION_URL = (
    f"{LICENSE_SERVER_URL}/{settings.LICENSE_SERVER_ACTIVATION_ENDPOINT.lstrip('/')}"
    if settings.LICENSE_SERVER_BASE_URL
    else ""
)
logger = logging.getLogger(__name__)


def get_device_id() -> str:
    return f"{uuid.getnode():012x}"


async def validate_license_or_exit() -> None:
    if not (settings.LICENSE_SERVER_BASE_URL and settings.LICENSE_KEY):
        return

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            LICENSE_ACTIVATION_URL,
            json={"license_key": settings.LICENSE_KEY, "device_id": get_device_id(), "service_id": settings.SERVICE_ID},
        )
        if response.is_error:
            body = response.text[:1000]
            raise RuntimeError(f"License activation failed: {response.status_code} body={body}")


async def monitor_license_server() -> None:
    while True:
        try:
            await validate_license_or_exit()
        except Exception as exc:
            logger.error("License validation error: %s", exc)
            sys.exit(1)
        await asyncio.sleep(86400)

