from pydantic import BaseModel, EmailStr, Field


class ListTemplatesRequest(BaseModel):
    q: str | None = Field(default=None, description="Optional template name search query.")
    count: int = Field(default=50, ge=1, le=100, description="Templates per page.")
    page: int = Field(default=1, ge=1, description="Page number.")
    tag: list[str] | None = Field(default=None, description="Optional tags filter.")


class RecipientInput(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1, description="Template role name, e.g. Signer")


class CreateDocumentFromTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="New document display name.")
    template_uuid: str = Field(..., min_length=1, description="PandaDoc template UUID.")
    recipients: list[RecipientInput] = Field(..., min_length=1)
    tokens: dict[str, str] | None = Field(default=None, description="Optional template tokens.")
    fields: dict | None = Field(default=None, description="Optional prefilled fields payload.")
    metadata: dict[str, str] | None = Field(default=None, description="Optional metadata tags/keys.")
    parse_form_fields: bool | None = Field(default=None, description="Optional parse form fields behavior.")


class DocumentDetailsRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    include_review_session: bool = Field(
        default=False,
        description="If true, also request an embedded editing session for draft review.",
    )
    review_session_email: EmailStr | None = Field(
        default=None,
        description="Email to bind editing session to when include_review_session=true.",
    )
    review_session_lifetime: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Embedded editing session lifetime in seconds.",
    )
    include_signing_session: bool = Field(
        default=False,
        description="If true, also request embedded signing session URL.",
    )
    signing_recipient_email: EmailStr | None = Field(
        default=None,
        description="Recipient email used to generate signing session URL.",
    )
    signing_session_lifetime: int = Field(
        default=3600,
        ge=60,
        le=31535999,
        description="Embedded signing session lifetime in seconds.",
    )


class SendDocumentRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    subject: str | None = Field(default=None, description="Optional email subject override.")
    message: str | None = Field(default=None, description="Optional custom email message.")
    silent: bool = Field(default=False, description="Set true to skip notification emails.")


class ListDocumentsRequest(BaseModel):
    q: str | None = Field(default=None, description="Optional document search query.")
    status: str | None = Field(default=None, description="Optional status filter.")
    count: int = Field(default=50, ge=1, le=100)
    page: int = Field(default=1, ge=1)


class TemplateDetailsRequest(BaseModel):
    template_uuid: str = Field(..., min_length=1, description="PandaDoc template UUID.")
