from pydantic import BaseModel, Field


class ClassifyTextRequest(BaseModel):
    """Classify a single text payload."""

    text: str = Field(
        ...,
        description="Required input text to classify.",
        examples=["API returns 500 when creating an instruction"],
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=9,
        description="How many top labels to return (sorted by confidence).",
    )


class BatchClassifyRequest(BaseModel):
    """Classify multiple text payloads in one request."""

    texts: list[str] = Field(
        ...,
        description="Required batch of input texts.",
        examples=[["Button not clickable on mobile", "Need export CSV feature"]],
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=9,
        description="How many top labels to return per item (sorted by confidence).",
    )


class TrainingExample(BaseModel):
    """Single labeled training example."""

    text: str = Field(
        ...,
        description="Training text. Usually a previously triaged issue/ticket summary.",
    )
    label: str = Field(
        ...,
        description=(
            "Target label for the text. Use one of labels endpoint values. "
            "Common workflow: if classifier predicts `needs_review`, human picks final label and submits here."
        ),
    )


class TrainExamplesRequest(BaseModel):
    """Incrementally train classifier with labeled examples."""

    examples: list[TrainingExample] = Field(
        ...,
        description=(
            "Required labeled examples for incremental fitting. "
            "Use this continuously after human review to improve future predictions."
        ),
    )
