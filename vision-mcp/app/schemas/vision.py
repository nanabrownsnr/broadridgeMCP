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


class CompareImagesRequest(BaseModel):
    """Request payload for visual similarity scoring between source and generated pages."""

    source_url: str = Field(
        ...,
        description="Reference/source image URL representing the original page.",
        examples=["https://example.com/source-page.png"],
    )
    generated_url: str = Field(
        ...,
        description="Generated page screenshot URL to compare against the source.",
        examples=["https://example.com/generated-page.png"],
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Optional HTTP headers used for both downloads.",
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


class ImageComparisonResponse(BaseModel):
    """Visual QA response used to guide auto-correction loops."""

    similarity_score: float = Field(..., description="Overall 0-1 similarity score (higher is better).")
    mae_score: float = Field(..., description="Mean absolute pixel error normalized to 0-1 (lower is better).")
    text_similarity_score: float = Field(
        ..., description="OCR text overlap score 0-1 between source and generated images."
    )
    component_similarity_score: float = Field(
        ..., description="Inferred component overlap score 0-1 between source and generated images."
    )
    source_size: dict = Field(..., description="Original source image dimensions.")
    generated_size: dict = Field(..., description="Generated image dimensions.")
    correction_hints: list[str] = Field(
        ..., description="Actionable hints for the renderer to improve visual fidelity in the next pass."
    )

