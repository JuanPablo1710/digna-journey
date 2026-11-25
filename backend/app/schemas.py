from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InteractionRequest(BaseModel):
    identifier: str = Field(min_length=1)
    identifier_type: Literal["session", "phone", "account"]
    idempotency_key: str = Field(min_length=1)
    kind: Literal["message", "action", "call_started", "call_ended"]
    action: str | None = None
    content: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class PersonInput(BaseModel):
    full_name: str = Field(min_length=2)
    birth_date: date
    email: str | None = None
    phone: str | None = None

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value: Any) -> Any:
        if isinstance(value, str) and "/" in value:
            return datetime.strptime(value, "%d/%m/%Y").date()
        return value


Relationship = Literal["self", "hijo_a", "madre_padre", "pareja", "otro"]


class PreregisterData(BaseModel):
    requester: PersonInput
    relationship: Relationship
    patient: PersonInput | None = None
    study_id: str | None = None


class DraftPersonInput(BaseModel):
    full_name: str | None = None
    birth_date: str | None = None
    email: str | None = None
    phone: str | None = None


class DraftData(BaseModel):
    requester: DraftPersonInput | None = None
    relationship: Relationship | None = None
    patient: DraftPersonInput | None = None
    study_id: str | None = None


class CaseActionData(BaseModel):
    case_id: str
    expected_version: int = Field(ge=1)
    study_id: str | None = None
    clinic_id: str | None = None
    slot_id: str | None = None


class VerificationRequestData(BaseModel):
    channel: Literal["web", "app", "whatsapp", "callcenter"]
    identifier: str = Field(min_length=1)
    method: Literal["email_otp", "dob_check"]
    birth_date: date | None = None

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_optional_birth_date(cls, value: Any) -> Any:
        if isinstance(value, str) and "/" in value:
            return datetime.strptime(value, "%d/%m/%Y").date()
        return value


class VerificationConfirmData(BaseModel):
    channel: Literal["web", "app", "whatsapp", "callcenter"]
    identifier: str = Field(min_length=1)
    code: str = Field(pattern=r"^\d{6}$")

