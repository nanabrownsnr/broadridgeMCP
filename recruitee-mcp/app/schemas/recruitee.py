from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    """Create a draft role in Recruitee."""

    title: str = Field(..., description="Job title")
    description: str | None = Field(default=None, description="Optional rich text job description")
    pipeline_template_id: int | None = Field(default=None, description="Optional pipeline template id")
    department: str | None = Field(default=None)
    location: str | None = Field(default=None)
    status: str = Field(default="draft", description="draft or published")


class PublishJobRequest(BaseModel):
    """Publish an existing role."""

    offer_id: int = Field(...)


class GetJobPublicUrlRequest(BaseModel):
    """Resolve a job's public URL."""

    offer_id: int = Field(...)


class ListCandidatesRequest(BaseModel):
    """List candidates globally or scoped to an offer/stage."""

    offer_id: int | None = Field(default=None)
    stage_id: int | None = Field(default=None)
    limit: int = Field(default=50, ge=1, le=200)
    page: int = Field(default=1, ge=1)


class MoveCandidateStageRequest(BaseModel):
    """Move a candidate to a pipeline stage."""

    candidate_id: int = Field(...)
    offer_id: int = Field(...)
    stage_id: int = Field(...)


class RegisterWebhookRequest(BaseModel):
    """Register a Recruitee webhook for event callbacks."""

    target_url: str = Field(..., description="HTTPS callback URL")
    event_type: str = Field(..., description="e.g. candidate_moved")

