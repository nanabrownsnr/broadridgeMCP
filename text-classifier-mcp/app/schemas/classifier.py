from pydantic import BaseModel, Field


class TaxonomyDefinition(BaseModel):
    """Taxonomy definition used to lock allowed labels for a use case."""

    taxonomy_id: str = Field(..., description="Stable taxonomy ID (e.g. twynity_tickets, hr_tickets).")
    display_name: str = Field(..., description="Human-readable taxonomy name.")
    labels: list[str] = Field(..., min_length=2, description="Allowed label set for this taxonomy.")
    description: str | None = Field(default=None, description="Optional description.")
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Default high-confidence threshold.")


class CreateTaxonomyRequest(BaseModel):
    """Create a new taxonomy with locked labels."""

    taxonomy: TaxonomyDefinition


class UpdateTaxonomyRequest(BaseModel):
    """Update an existing taxonomy definition."""

    taxonomy_id: str
    display_name: str | None = None
    labels: list[str] | None = None
    description: str | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class ClassifyTextRequest(BaseModel):
    """Classify one text using a selected taxonomy."""

    taxonomy_id: str = Field(default="twynity_tickets", description="Target taxonomy to use for classification.")
    text: str = Field(..., description="Required input text to classify.")
    top_k: int = Field(default=3, ge=1, le=20, description="How many top labels to return.")


class BatchClassifyRequest(BaseModel):
    """Classify multiple texts using a selected taxonomy."""

    taxonomy_id: str = Field(default="twynity_tickets", description="Target taxonomy to use for classification.")
    texts: list[str] = Field(..., description="Required batch of texts.")
    top_k: int = Field(default=3, ge=1, le=20, description="How many top labels to return per item.")


class TrainingExample(BaseModel):
    """Single labeled training example for classifier feedback loop."""

    text: str = Field(..., description="Training text from real ticket/request.")
    label: str = Field(..., description="Final human-approved label from the selected taxonomy.")


class TrainExamplesRequest(BaseModel):
    """Incrementally train a taxonomy classifier."""

    taxonomy_id: str = Field(default="twynity_tickets", description="Target taxonomy to update.")
    examples: list[TrainingExample] = Field(
        ...,
        description="Labeled examples. Main workflow: if predicted label is `needs_review`, human picks label and submit here.",
    )

