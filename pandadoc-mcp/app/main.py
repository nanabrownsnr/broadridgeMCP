import asyncio
import logging
import time

from app.api.v1.routers.pandadoc import router as pandadoc_router
from app.core.config import settings
from app.system.license_server import monitor_license_server
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP

logger = logging.getLogger("mcp")

app = FastAPI(title=settings.APP_TITLE, version=settings.VERSION, root_path=settings.ROOT_PATH)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_mcp_requests(request: Request, call_next):
    start = time.time()
    path = request.url.path
    method = request.method
    if "/mcp" in path or "/api/v1" in path:
        body = await request.body()
        logger.info(f"[MCP-IN] {method} {path} | Body: {body.decode('utf-8', errors='ignore')[:500] if body else 'No body'}")
    response = await call_next(request)
    if "/mcp" in path or "/api/v1" in path:
        logger.info(f"[MCP-OUT] {method} {path} | Status: {response.status_code} | Time: {time.time() - start:.3f}s")
    return response


app.include_router(pandadoc_router, prefix=settings.API_V1_STR)

mcp = FastApiMCP(app)
mcp.mount_http(mount_path="/mcp")
mcp.mount_sse(mount_path="/sse")


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(monitor_license_server())


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": settings.SERVICE_ID}
