from enum import StrEnum

from pydantic import BaseModel


class ClientIdentifier(StrEnum):
    QUEST_AI = "quest_ai"


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    id: str
    email: str
    role: str
    type: str
    client_id: str
    username: str
    access_token: str


class EmailVerificationToken(BaseModel):
    verification_token: str
