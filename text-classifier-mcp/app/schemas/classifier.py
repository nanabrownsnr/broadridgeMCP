from pydantic import BaseModel, Field


class ClassifyTextRequest(BaseModel):
    """Classify a single text payload."""

    text: str = Field(..., description="Required input text to classify.", examples=["API returns 500 when creating an instruction"])
    top_k: int = Field(default=3, ge=1, le=9, description="How many top labels to return.")


class BatchClassifyRequest(BaseModel):
    """Classify multiple text payloads in one request."""

    texts: list[str] = Field(..., description="Required batch of input texts.", examples=[["Button not clickable on mobile", "Need export CSV feature"]])
    top_k: int = Field(default=3, ge=1, le=9, description="How many top labels to return per item.")


class TrainingExample(BaseModel):
    """Single labeled training example."""

    text: str = Field(..., description="Training text.")
    label: str = Field(..., description="Target label for the text.")


class TrainExamplesRequest(BaseModel):
    """Incrementally train classifier with labeled examples."""

    examples: list[TrainingExample] = Field(..., description="Required labeled examples for incremental fitting.")

