import asyncio
import logging
import os
import subprocess
from pathlib import Path

from app.core.config import settings
from fastapi import APIRouter, HTTPException
from app.schemas.filesystem import ReadFilesRequest, RunCommandRequest, ServeProjectRequest, WriteFilesRequest

router = APIRouter(prefix="/filesystem", tags=["filesystem"])

logger = logging.getLogger(__name__)

SERVE_PROCESSES: dict[int, subprocess.Popen] = {}


def _safe_path(path: str) -> Path:
    root = Path(settings.WORKSPACE_ROOT).resolve()
    candidate = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail=f"Path escapes WORKSPACE_ROOT: {path}")
    return candidate


@router.post("/read_files")
async def read_files(payload: ReadFilesRequest) -> dict:
    """
    Read one or more text files from the allowed workspace.

    Use this tool when the agent needs project context before editing.
    Returns a map of requested paths to UTF-8 content. Missing files return an empty string.
    """
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
    """
    Write one or more files into the allowed workspace.

    Use this after planning code changes. Parent directories are created automatically.
    Returns absolute paths of files written.
    """
    logger.info(f"[WRITE_FILES] REQUEST - {len(payload.files)} files")
    for i, f in enumerate(payload.files):
        logger.info(f"[WRITE_FILES] File {i+1}: path={f.path}, size={len(f.content)} chars")
    
    written: list[str] = []
    for file_item in payload.files:
        path = _safe_path(file_item.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_item.content, encoding="utf-8")
        written.append(str(path))
    
    response = {"written_files": written}
    logger.info(f"[WRITE_FILES] RESPONSE - {response}")
    return response


@router.post("/run_command")
async def run_command(payload: RunCommandRequest) -> dict:
    """
    Execute a shell command inside the workspace and capture output.

    Use for build, lint, test, and other project commands.
    Returns `return_code`, `stdout`, and `stderr`.
    """
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
    """
    Start or reuse a static HTTP server for previewing generated pages.

    Use this to get a preview URL after writing HTML/CSS/JS files.
    Only ports 9000-9100 are exposed externally.
    Returns `url` and `status` (`started` or `already_running`).
    """
    cwd = _safe_path(payload.cwd)
    port = payload.port
    
    # Force ports to exposed range 9000-9100
    if port < 9000 or port > 9100:
        logger.warning(f"[SERVE_PROJECT] Port {port} outside exposed range, using 9000")
        port = 9000
    
    logger.info(f"[SERVE_PROJECT] REQUEST - cwd={cwd}, port={port}")

    existing = SERVE_PROCESSES.get(port)
    if existing and existing.poll() is None:
        response = {"url": f"http://178.194.34.219:{port}", "status": "already_running"}
        logger.info(f"[SERVE_PROJECT] RESPONSE - {response}")
        return response

    proc = subprocess.Popen(
        ["python", "-m", "http.server", str(port)],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SERVE_PROCESSES[port] = proc
    response = {"url": f"http://178.194.34.219:{port}", "status": "started"}
    logger.info(f"[SERVE_PROJECT] RESPONSE - {response}")
    return response


@router.get("/snapshot_diff")
async def snapshot_diff() -> dict:
    """
    Return a simple workspace file snapshot.

    Use this as a lightweight way to enumerate generated artifacts after tool execution.
    """
    root = Path(settings.WORKSPACE_ROOT).resolve()
    changed: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full_path = Path(dirpath) / name
            changed.append(str(full_path))
    return {"changed_files": changed, "summary": "Filesystem snapshot generated"}

