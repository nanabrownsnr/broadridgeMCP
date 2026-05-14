from pydantic import BaseModel, EmailStr, Field


class RecipientInput(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1)


class ListTemplatesRequest(BaseModel):
    """
    List templates in the current DocuSign account.
    """

    search_text: str | None = Field(
        default=None,
        description="Optional template name search text to filter results.",
    )
    include_recipients: bool = Field(
        default=False,
        description="Include template recipient summaries when true.",
    )
    count: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum templates to return (1-100).",
    )


class TemplateDetailsRequest(BaseModel):
    template_id: str = Field(..., description="DocuSign template ID.")
    include_documents: bool = Field(
        default=False,
        description="Include template document metadata when true.",
    )
    include_recipients: bool = Field(
        default=True,
        description="Include template recipient metadata when true.",
    )


class SendEnvelopeFromTemplateRequest(BaseModel):
    """
    Send envelope from an existing DocuSign template.
    """

    candidate_id: str = Field(..., description="Internal candidate/client identifier for retrieval.")
    template_id: str = Field(..., description="DocuSign template ID to use.")
    subject: str | None = Field(default=None, description="Optional email subject override.")
    message: str | None = Field(default=None, description="Optional email blurb/message.")
    recipient: RecipientInput
    role_name: str = Field(
        default="signer",
        description="Template role name configured in DocuSign (for example signer).",
    )
    client_id: str | None = Field(default=None, description="Optional secondary grouping key.")


class EnvelopeStatusRequest(BaseModel):
    envelope_id: str


class ListCandidateEnvelopesRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate/client identifier set at envelope creation.")
    include_status_lookup: bool = Field(default=True, description="Fetch current status per envelope when true.")


class CompletedDocumentsRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate/client identifier set at envelope creation.")
    completed_only: bool = Field(default=True, description="Filter to completed envelopes only.")
