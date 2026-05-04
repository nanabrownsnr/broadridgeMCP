from pydantic import BaseModel, Field


class ReadFilesRequest(BaseModel):
    paths: list[str]


class WriteFileItem(BaseModel):
    path: str
    content: str


class WriteFilesRequest(BaseModel):
    files: list[WriteFileItem]


class RunCommandRequest(BaseModel):
    cmd: str
    cwd: str | None = None


class ServeProjectRequest(BaseModel):
    cwd: str
    port: int = Field(default=4173, ge=1024, le=65535)


class DiffSummaryResponse(BaseModel):
    changed_files: list[str]
    summary: str

