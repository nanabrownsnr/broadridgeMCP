from pydantic import BaseModel, Field


class AnalyzeSourceRequest(BaseModel):
    source_url: str
    page_name: str | None = None
    target_page: int = Field(default=1, ge=1)
    headers: dict[str, str] | None = None


class VisionComponent(BaseModel):
    type: str
    label: str | None = None
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None


class VisionResponse(BaseModel):
    page_name: str
    source_url: str
    source_type: str
    text_blocks: list[dict]
    layout: list[dict]
    components: list[VisionComponent]
    style_tokens: dict
    summary: str
