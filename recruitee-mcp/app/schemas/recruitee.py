from pydantic import BaseModel, Field


class CreateJobOfferRequest(BaseModel):
    """Create a mapped Recruitee job offer with structured role, requirements, and distribution settings."""

    title: str = Field(..., description="Job title")
    status: str = Field(default="draft", description="draft, internal, published, closed, archived")
    kind: str = Field(default="job", description="job or talent_pool")
    description: str | None = Field(default=None, description="Optional full description fallback.")
    role_summary: str | None = Field(default=None, description="Why this role exists and what it owns.")
    responsibilities: list[str] | None = Field(
        default=None,
        description="Day-to-day responsibilities as bullet items. Recommended 5-10.",
    )
    must_have_requirements: list[str] | None = Field(
        default=None,
        description="Non-negotiable requirements used later for resume matching.",
    )
    nice_to_have_requirements: list[str] | None = Field(
        default=None,
        description="Bonus requirements that are preferred but not mandatory.",
    )
    seniority: str | None = Field(default=None, description="e.g. Junior, Mid, Senior, Lead")
    location_type: str | None = Field(default=None, description="Remote, Hybrid, Onsite")
    employment_type: str | None = Field(default=None, description="e.g. Full-time, Contract")
    experience: str | None = Field(default=None, description="e.g. entry_level, mid_level, experienced, manager")
    education: str | None = Field(default=None, description="e.g. bachelor_degree, master_degree")
    team_name: str | None = Field(default=None, description="Team or department name shown in the role context.")
    interview_process: list[str] | None = Field(
        default=None,
        description="Ordered interview steps for candidate expectation-setting.",
    )
    pipeline_template_id: int | None = Field(default=None, description="Optional pipeline template id")
    department: str | None = Field(default=None)
    location: str | None = Field(default=None)
    location_ids: list[int] | None = Field(default=None, description="Preferred structured location IDs.")
    country_code: str | None = Field(default=None)
    state_code: str | None = Field(default=None)
    city: str | None = Field(default=None)
    remote: bool | None = Field(default=None)
    hybrid: bool | None = Field(default=None)
    on_site: bool | None = Field(default=None)
    number_of_openings: int | None = Field(default=None, ge=1)
    min_hours: int | None = Field(default=None, ge=1)
    max_hours: int | None = Field(default=None, ge=1)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, description="e.g. USD, EUR")
    salary_period: str | None = Field(default=None, description="e.g. yearly, monthly, hourly")
    offer_tags: list[str] | None = Field(default=None, description="Offer tags/labels.")
    visibility_options: list[str] | None = Field(default=None, description="e.g. linkedin, indeed, social_share, job_location")
    options_cv: str | None = Field(default=None, description="required, optional, off")
    options_phone: str | None = Field(default=None, description="required, optional, off")
    options_cover_letter: str | None = Field(default=None, description="required, optional, off")
    options_photo: str | None = Field(default=None, description="required, optional, off")


class PublishJobRequest(BaseModel):
    """Publish an existing role."""

    offer_id: int = Field(...)


class GetJobPublicUrlRequest(BaseModel):
    """Resolve a job's public URL."""

    offer_id: int = Field(...)
    include_raw_offer: bool = Field(default=False, description="Include full raw offer payload when true.")


class ListOfferStagesRequest(BaseModel):
    """List all workflow stages for a specific role/offer."""

    offer_id: int = Field(..., description="Offer ID returned by recruitee_list_job_openings or recruitee_create_job_offer")
    include_raw: bool = Field(default=False, description="Include full raw stages payload when true.")


class ListCandidatesRequest(BaseModel):
    """List candidates globally or scoped to an offer/stage."""

    offer_id: int | None = Field(default=None)
    stage_id: int | None = Field(default=None)
    limit: int = Field(default=50, ge=1, le=200)
    page: int = Field(default=1, ge=1)
    include_raw: bool = Field(default=False, description="Include full provider payload when true.")


class GetCandidateResumeSourceRequest(BaseModel):
    """Fetch one candidate profile and return resume source fields for downstream matching."""

    candidate_id: int = Field(..., description="Candidate ID from recruitee_list_candidates output.")
    include_raw_candidate: bool = Field(
        default=False,
        description="When true, include full raw candidate payload. Keep false for compact responses.",
    )


class GetCandidatesResumeSourcesRequest(BaseModel):
    """Batch version of resume source resolution for many candidates."""

    candidate_ids: list[int] = Field(
        ...,
        description="Candidate IDs from recruitee_list_candidates output. Recommended max 50 per request.",
    )
    include_raw_candidate: bool = Field(
        default=False,
        description="When true, include full raw candidate payload per result. Keep false for compact responses.",
    )


class MoveCandidateStageRequest(BaseModel):
    """Move a candidate to a pipeline stage."""

    candidate_id: int = Field(...)
    offer_id: int = Field(...)
    stage_id: int = Field(...)


class RegisterWebhookRequest(BaseModel):
    """Register a Recruitee webhook for event callbacks."""

    target_url: str = Field(..., description="HTTPS callback URL")
    event_type: str = Field(..., description="e.g. candidate_moved")

