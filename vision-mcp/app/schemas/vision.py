from pydantic import BaseModel, Field


class AnalyzeSourceRequest(BaseModel):
    """Request payload for analyzing a remote HTML, PDF, or image source."""

    source_url: str = Field(
        ...,
        description="Public or authenticated URL to analyze.",
        examples=["https://example.com/page-3.html"],
    )
    page_name: str | None = Field(
        default=None,
        description="Optional friendly page label used in the response.",
        examples=["login-page"],
    )
    target_page: int = Field(
        default=1,
        ge=1,
        description="PDF page number (1-based) to analyze when source is a PDF.",
        examples=[1],
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Optional HTTP headers for protected downloads (e.g. Authorization).",
        examples=[{"Authorization": "Bearer <token>"}],
    )


class VisionComponent(BaseModel):
    """Detected UI or document component."""

    type: str = Field(..., description="Component category, such as input, button, select, or link.")
    label: str | None = Field(default=None, description="Best-effort text label for the component.")
    x: int | None = Field(default=None, description="Optional x position in pixels.")
    y: int | None = Field(default=None, description="Optional y position in pixels.")
    w: int | None = Field(default=None, description="Optional width in pixels.")
    h: int | None = Field(default=None, description="Optional height in pixels.")


class VisionResponse(BaseModel):
    """Normalized response consumed by text-only LLMs for UI regeneration."""

    page_name: str = Field(..., description="Resolved page label for this analysis.")
    source_url: str = Field(..., description="Original analyzed source URL.")
    source_type: str = Field(..., description="Detected source type: html, pdf, or image.")
    text_blocks: list[dict] = Field(..., description="Extracted textual blocks with basic semantic roles.")
    layout: list[dict] = Field(..., description="High-level layout regions and geometry metadata.")
    components: list[VisionComponent] = Field(..., description="Detected interactive components.")
    style_tokens: dict = Field(..., description="Best-effort style hints (currently sparse).")
    summary: str = Field(..., description="Concise summary of the analyzed source.")

