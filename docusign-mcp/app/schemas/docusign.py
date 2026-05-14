from pydantic import BaseModel, EmailStr, Field, model_validator


class RecipientInput(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1)


class SendEnvelopeRequest(BaseModel):
    """
    Send a DocuSign envelope for signature and tag it with client/candidate metadata for later retrieval.
    """

    candidate_id: str = Field(..., description="Internal candidate/client identifier used for later retrieval.")
    subject: str = Field(..., description="Envelope email subject.")
    message: str | None = Field(default=None, description="Optional envelope message/email blurb.")
    recipient: RecipientInput
    template_id: str | None = Field(default=None, description="DocuSign template ID to use.")
    document_name: str | None = Field(default=None, description="Required when using document_base64.")
    document_base64: str | None = Field(default=None, description="Base64-encoded file content when not using template.")
    file_extension: str | None = Field(default=None, description="e.g. pdf, docx")
    client_id: str | None = Field(default=None, description="Optional secondary grouping key.")

    @model_validator(mode="after")
    def validate_template_or_document(self) -> "SendEnvelopeRequest":
        if not self.template_id and not self.document_base64:
            raise ValueError("Provide either template_id or document_base64.")
        if self.document_base64 and (not self.document_name or not self.file_extension):
            raise ValueError("document_name and file_extension are required with document_base64.")
        return self


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
