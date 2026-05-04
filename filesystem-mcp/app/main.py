from api.v1.routers.filesystem import router as filesystem_router
from core.config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP
from system.license_server import monitor_license_server
import asyncio

app = FastAPI(title=settings.APP_TITLE, version=settings.VERSION, root_path=settings.ROOT_PATH)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(filesystem_router, prefix=settings.API_V1_STR)

mcp = FastApiMCP(app)
mcp.mount()


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(monitor_license_server())


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": settings.SERVICE_ID}
