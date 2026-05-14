from pydantic import BaseModel, Field, model_validator


class ResumeInput(BaseModel):
    """One resume input item used by batch matching."""

    candidate_id: str = Field(..., description="Client-provided candidate identifier for ranking output.")
    resume_text: str | None = Field(default=None, description="Plain text resume content, if already extracted.")
    resume_url: str | None = Field(default=None, description="Public URL to resume file (pdf/image/txt/html).")

    @model_validator(mode="after")
    def validate_resume_source(self) -> "ResumeInput":
        if not self.resume_text and not self.resume_url:
            raise ValueError("Either resume_text or resume_url is required for each resume item.")
        return self


class MatchResumeToRoleRequest(BaseModel):
    """
    Match one resume to role requirements.

    Provide `resume_text` when possible for fastest results. Use `resume_url` when the resume
    needs to be downloaded and parsed by the tool.
    """

    role_requirements_text: str = Field(..., description="Complete role requirements text or JD excerpt.")
    candidate_id: str | None = Field(default=None, description="Optional candidate identifier for persistence/retrieval.")
    resume_text: str | None = Field(default=None, description="Plain text resume content.")
    resume_url: str | None = Field(default=None, description="Public URL to resume document.")

    @model_validator(mode="after")
    def validate_resume_source(self) -> "MatchResumeToRoleRequest":
        if not self.resume_text and not self.resume_url:
            raise ValueError("Either resume_text or resume_url is required.")
        return self


class BatchMatchResumesToRoleRequest(BaseModel):
    """
    Match many resumes to one role and return ranked results.
    """

    role_requirements_text: str = Field(..., description="Complete role requirements text or JD excerpt.")
    resumes: list[ResumeInput] = Field(..., description="Candidate list to evaluate against the same role.")


class GetCandidateAnalysisRequest(BaseModel):
    """Retrieve stored full analysis by candidate id."""

    candidate_id: str = Field(..., description="Candidate identifier used during match/batch call.")
