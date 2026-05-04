import asyncio
import os
import subprocess
from pathlib import Path

from app.core.config import settings
from fastapi import APIRouter, HTTPException
from app.schemas.filesystem import ReadFilesRequest, RunCommandRequest, ServeProjectRequest, WriteFilesRequest

router = APIRouter(prefix="/filesystem", tags=["filesystem"])


SERVE_PROCESSES: dict[int, subprocess.Popen] = {}


def _safe_path(path: str) -> Path:
    root = Path(settings.WORKSPACE_ROOT).resolve()
    candidate = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail=f"Path escapes WORKSPACE_ROOT: {path}")
    return candidate


@router.post("/read_files")
async def read_files(payload: ReadFilesRequest) -> dict:
    output: dict[str, str] = {}
    for raw_path in payload.paths:
        path = _safe_path(raw_path)
        if not path.exists() or not path.is_file():
            output[raw_path] = ""
            continue
        output[raw_path] = path.read_text(encoding="utf-8", errors="ignore")
    return {"files": output}


@router.post("/write_files")
async def write_files(payload: WriteFilesRequest) -> dict:
    written: list[str] = []
    for file_item in payload.files:
        path = _safe_path(file_item.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_item.content, encoding="utf-8")
        written.append(str(path))
    return {"written_files": written}


@router.post("/run_command")
async def run_command(payload: RunCommandRequest) -> dict:
    cwd = _safe_path(payload.cwd) if payload.cwd else Path(settings.WORKSPACE_ROOT).resolve()
    proc = await asyncio.create_subprocess_shell(
        payload.cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "return_code": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="ignore"),
        "stderr": stderr.decode("utf-8", errors="ignore"),
    }


@router.post("/serve_project")
async def serve_project(payload: ServeProjectRequest) -> dict:
    cwd = _safe_path(payload.cwd)

    existing = SERVE_PROCESSES.get(payload.port)
    if existing and existing.poll() is None:
        return {"url": f"http://localhost:{payload.port}", "status": "already_running"}

    proc = subprocess.Popen(
        ["python", "-m", "http.server", str(payload.port)],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SERVE_PROCESSES[payload.port] = proc
    return {"url": f"http://localhost:{payload.port}", "status": "started"}


@router.get("/snapshot_diff")
async def snapshot_diff() -> dict:
    root = Path(settings.WORKSPACE_ROOT).resolve()
    changed: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full_path = Path(dirpath) / name
            changed.append(str(full_path))
    return {"changed_files": changed, "summary": "Filesystem snapshot generated"}

