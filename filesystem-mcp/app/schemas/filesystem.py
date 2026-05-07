from pydantic import BaseModel, Field


class ReadFilesRequest(BaseModel):
    """Request payload for reading multiple files."""

    paths: list[str] = Field(
        ...,
        description="List of file paths to read. Relative paths are resolved from WORKSPACE_ROOT.",
        examples=[["src/index.html", "styles/page.css"]],
    )


class WriteFileItem(BaseModel):
    """Single file write instruction."""

    path: str = Field(
        ...,
        description="Target file path. Relative paths are resolved from WORKSPACE_ROOT.",
        examples=["prototype/page-3.html"],
    )
    content: str = Field(
        ...,
        description="Full UTF-8 file content to write at `path`.",
        examples=["<html><body><h1>Prototype</h1></body></html>"],
    )


class WriteFilesRequest(BaseModel):
    """Request payload for writing one or more files."""

    files: list[WriteFileItem] = Field(
        ...,
        description="List of file write operations.",
    )
    project: str | None = Field(
        default=None,
        description="Optional project namespace. Relative write paths are rooted under WORKSPACE_ROOT/projects/{project}.",
        examples=["twynity_joinwaitlist_v2"],
    )


class RunCommandRequest(BaseModel):
    """Request payload for running a shell command in the workspace."""

    cmd: str = Field(
        ...,
        description="Shell command to execute.",
        examples=["npm run build"],
    )
    cwd: str | None = Field(
        default=None,
        description="Optional working directory. Defaults to WORKSPACE_ROOT.",
        examples=["prototype-app"],
    )


class ServeProjectRequest(BaseModel):
    """Request payload for starting a static file server for preview."""

    cwd: str | None = Field(
        default=None,
        description="Directory to serve over HTTP. If omitted, uses WORKSPACE_ROOT/projects/{project}.",
        examples=["prototype-app/dist"],
    )
    project: str | None = Field(
        default=None,
        description="Optional project namespace used when `cwd` is not provided.",
        examples=["twynity_joinwaitlist_v2"],
    )
    port: int | None = Field(
        default=None,
        ge=1024,
        le=65535,
        description="Optional preferred port. If omitted, an available port in 9000-9100 is selected.",
        examples=[9000],
    )
    auto_port: bool = Field(
        default=True,
        description="When true, choose the first available port in 9000-9100 if `port` is omitted or unavailable.",
    )
    file: str | None = Field(
        default=None,
        description="Optional file path to append to the URL (e.g., 'index.html').",
        examples=["join-waitlist.html"],
    )
    base_url: str | None = Field(
        default=None,
        description="Optional public base URL override, e.g. 'http://178.194.34.219'.",
        examples=["http://178.194.34.219"],
    )


class DiffSummaryResponse(BaseModel):
    """Response model for snapshot_diff results."""

    changed_files: list[str] = Field(
        ...,
        description="List of discovered files in the workspace snapshot.",
    )
    summary: str = Field(
        ...,
        description="Human-readable summary of the snapshot operation.",
    )

