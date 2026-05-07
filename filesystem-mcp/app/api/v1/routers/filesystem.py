import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path

from app.core.config import settings
from fastapi import APIRouter, HTTPException
from app.schemas.filesystem import ReadFilesRequest, RunCommandRequest, ServeProjectRequest, WriteFilesRequest

router = APIRouter(prefix="/filesystem", tags=["filesystem"])

logger = logging.getLogger(__name__)

SERVE_PROCESSES: dict[int, dict] = {}
DEFAULT_PROJECT = "default"


def _safe_path(path: str) -> Path:
    root = Path(settings.WORKSPACE_ROOT).resolve()
    candidate = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail=f"Path escapes WORKSPACE_ROOT: {path}")
    return candidate


def _sanitize_project_name(project: str | None) -> str:
    raw = (project or DEFAULT_PROJECT).strip().lower()
    clean = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")
    return clean or DEFAULT_PROJECT


def _resolve_project_root(project: str | None) -> Path:
    root = Path(settings.WORKSPACE_ROOT).resolve()
    return (root / "projects" / _sanitize_project_name(project)).resolve()


def _find_available_port(start: int = 9000, end: int = 9100) -> int:
    for p in range(start, end + 1):
        existing = SERVE_PROCESSES.get(p)
        if existing and existing["process"].poll() is None:
            continue
        return p
    raise HTTPException(status_code=503, detail="No available preview ports in range 9000-9100")


@router.post("/read_files", operation_id="read_files")
async def read_files(payload: ReadFilesRequest) -> dict:
    """
    Read one or more text files from the allowed workspace.

    Use when:
    1. You need existing code/context before edits.
    2. You need to verify generated files after writes.

    Input expectations:
    1. `paths` is required.
    2. Relative paths are resolved from WORKSPACE_ROOT.
    3. Absolute paths are allowed if still inside WORKSPACE_ROOT.

    Behavior:
    1. Missing files return an empty string in the response map.
    2. Does not create or modify files.
    """
    output: dict[str, str] = {}
    for raw_path in payload.paths:
        path = _safe_path(raw_path)
        if not path.exists() or not path.is_file():
            output[raw_path] = ""
            continue
        output[raw_path] = path.read_text(encoding="utf-8", errors="ignore")
    return {"files": output}


@router.post("/write_files", operation_id="write_files")
async def write_files(payload: WriteFilesRequest) -> dict:
    """
    Write one or more files into the allowed workspace.

    Use when:
    1. Creating/updating HTML/CSS/JS or support files.
    2. Writing feature-specific changes in a project namespace.

    Input expectations:
    1. `files` is required.
    2. `project` is optional. If omitted, defaults to project namespace `default`.
    3. Relative file paths are rooted at WORKSPACE_ROOT/projects/{project}.
    4. Absolute file paths are allowed only within WORKSPACE_ROOT.

    Behavior:
    1. Parent directories are auto-created.
    2. Returns `written_files` and resolved `project_root`.
    3. This endpoint does not serve URLs; call `serve_project` after writing.
    """
    logger.info(f"[WRITE_FILES] REQUEST - {len(payload.files)} files")
    for i, f in enumerate(payload.files):
        logger.info(f"[WRITE_FILES] File {i+1}: path={f.path}, size={len(f.content)} chars")
    
    project_root = _resolve_project_root(payload.project)
    project_root.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for file_item in payload.files:
        if Path(file_item.path).is_absolute():
            path = _safe_path(file_item.path)
        else:
            path = _safe_path(str(project_root / file_item.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_item.content, encoding="utf-8")
        written.append(str(path))
    
    response = {"written_files": written, "project_root": str(project_root)}
    logger.info(f"[WRITE_FILES] RESPONSE - {response}")
    return response


@router.post("/run_command", operation_id="run_command")
async def run_command(payload: RunCommandRequest) -> dict:
    """
    Execute a shell command inside the workspace and capture output.

    Use when:
    1. Running build/lint/test steps.
    2. Running local tooling required before preview.

    Input expectations:
    1. `cmd` is required.
    2. `cwd` is optional; defaults to WORKSPACE_ROOT.

    Behavior:
    1. Returns `return_code`, `stdout`, and `stderr`.
    2. Non-zero return code does not throw HTTP error; caller should inspect `return_code`.
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


@router.post("/serve_project", operation_id="serve_project")
async def serve_project(payload: ServeProjectRequest) -> dict:
    """
    Start or reuse a static HTTP preview server for generated pages.

    Use when:
    1. You need a live URL for user review.
    2. You want per-project isolation and dynamic ports.

    Input expectations:
    1. Provide either `cwd` or `project`.
    2. If `project` is provided and `cwd` is omitted, serves WORKSPACE_ROOT/projects/{project}.
    3. `port` is optional. If omitted, a free port in 9000-9100 is auto-selected.
    4. `auto_port=true` allows reassignment when requested port is in use by another directory.
    5. `file` is optional; if omitted, latest modified HTML file is auto-detected recursively.
    6. `base_url` is optional; if omitted, service default URL is used.

    Behavior:
    1. Restarts server on same port if `cwd` changed and `auto_port` is false.
    2. Returns `url`, `status`, `project_root`, and `port`.
    3. Raises 400 if no HTML file can be resolved.
    """
    project_root = _resolve_project_root(payload.project)
    project_root.mkdir(parents=True, exist_ok=True)
    cwd = _safe_path(payload.cwd) if payload.cwd else project_root

    if payload.port is not None:
        port = payload.port
        if port < 9000 or port > 9100:
            logger.warning(f"[SERVE_PROJECT] Port {port} outside exposed range, forcing auto port")
            port = _find_available_port()
    else:
        port = _find_available_port()

    # If requested port is busy with another cwd and auto_port is enabled, allocate new.
    existing_for_port = SERVE_PROCESSES.get(port)
    if (
        existing_for_port
        and existing_for_port["process"].poll() is None
        and Path(existing_for_port["cwd"]) != cwd
        and payload.auto_port
    ):
        port = _find_available_port()
    
    # Find HTML file in directory (recursive to support nested outputs).
    file_path = ""
    if payload.file:
        candidate_file = (cwd / payload.file).resolve()
        if not candidate_file.exists() or not candidate_file.is_file():
            raise HTTPException(status_code=400, detail=f"Requested file not found: {payload.file}")
        try:
            rel = candidate_file.relative_to(cwd)
            rel_str = str(rel).replace('\\', '/')
            file_path = f"/{rel_str}"
        except Exception:
            file_path = f"/{payload.file}"
    else:
        # Auto-detect latest HTML file recursively.
        html_files = list(cwd.rglob("*.html"))
        if html_files:
            html_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            selected = html_files[0]
            rel = selected.relative_to(cwd)
            rel_str = str(rel).replace('\\', '/')
            file_path = f"/{rel_str}"
            logger.info(f"[SERVE_PROJECT] Auto-detected HTML file: {rel}")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"No HTML file found under directory: {cwd}. Provide `file` explicitly.",
            )
    
    logger.info(f"[SERVE_PROJECT] REQUEST - cwd={cwd}, port={port}, file={file_path}")

    existing_meta = SERVE_PROCESSES.get(port)
    if existing_meta and existing_meta["process"].poll() is None:
        existing_cwd = Path(existing_meta["cwd"])
        # Restart server if directory changed, otherwise reuse process and update URL.
        if existing_cwd != cwd:
            logger.info(f"[SERVE_PROJECT] CWD changed for port {port}: {existing_cwd} -> {cwd}. Restarting server.")
            existing_meta["process"].terminate()
            try:
                existing_meta["process"].wait(timeout=5)
            except Exception:
                existing_meta["process"].kill()
        else:
            existing_meta["last_file_path"] = file_path
            base_url = (payload.base_url or "http://178.194.34.219").rstrip("/")
            response = {"url": f"{base_url}:{port}{file_path}", "status": "already_running", "project_root": str(project_root)}
            logger.info(f"[SERVE_PROJECT] RESPONSE - {response}")
            return response

    if existing_meta and existing_meta["process"].poll() is not None:
        SERVE_PROCESSES.pop(port, None)

    proc = subprocess.Popen(
        ["python", "-m", "http.server", str(port)],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SERVE_PROCESSES[port] = {"process": proc, "cwd": str(cwd), "last_file_path": file_path}
    base_url = (payload.base_url or "http://178.194.34.219").rstrip("/")
    response = {
        "url": f"{base_url}:{port}{file_path}",
        "status": "started",
        "project_root": str(project_root),
        "port": port,
    }
    logger.info(f"[SERVE_PROJECT] RESPONSE - {response}")
    return response


@router.get("/snapshot_diff", operation_id="snapshot_diff")
async def snapshot_diff() -> dict:
    """
    Return a simple workspace file snapshot.

    Use when:
    1. You need quick visibility into generated artifacts.
    2. You need a lightweight post-write inspection pass.
    """
    root = Path(settings.WORKSPACE_ROOT).resolve()
    changed: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full_path = Path(dirpath) / name
            changed.append(str(full_path))
    return {"changed_files": changed, "summary": "Filesystem snapshot generated"}

