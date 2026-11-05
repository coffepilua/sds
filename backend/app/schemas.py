from typing import Literal

from pydantic import BaseModel, Field, model_validator

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
DATE = r"^\d{4}-\d{2}-\d{2}$"


class Register(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field("", max_length=50)


class Login(BaseModel):
    email: str
    password: str


class ProfilePatch(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    phone: str | None = Field(None, max_length=50)


class CaseIn(BaseModel):
    specialty_id: int
    description: str = Field(min_length=1)
    target_country: str | None = Field(None, max_length=100)
    budget_usd: int | None = Field(None, ge=0)


class CasePatch(BaseModel):
    specialty_id: int | None = None
    description: str | None = Field(None, min_length=1)
    target_country: str | None = Field(None, max_length=100)
    budget_usd: int | None = Field(None, ge=0)


class StatusIn(BaseModel):
    status: str
    note: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class ShareIn(BaseModel):
    clinic_id: int


class ConsentIn(BaseModel):
    approved: bool


class QuoteIn(BaseModel):
    share_id: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_min: int = Field(ge=0)
    price_max: int = Field(ge=0)
    details: str = Field(min_length=1)
    valid_until: str = Field(pattern=DATE)

    @model_validator(mode="after")
    def _range(self):
        if self.price_min > self.price_max:
            raise ValueError("price_min must be <= price_max")
        return self


class QuotePatch(BaseModel):
    price_min: int | None = Field(None, ge=0)
    price_max: int | None = Field(None, ge=0)
    details: str | None = Field(None, min_length=1)
    valid_until: str | None = Field(None, pattern=DATE)


class MsgIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class StaffIn(BaseModel):
    email: str = Field(pattern=EMAIL)
    full_name: str = Field(min_length=1)
    role: Literal["coordinator", "clinic"]
    clinic_id: int | None = None
    password: str | None = Field(None, min_length=8)


class ClinicIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    description: str = ""
    specialty_ids: list[int] = []
    image_url: str | None = None


class ClinicPatch(BaseModel):
    name: str | None = None
    country: str | None = None
    city: str | None = None
    description: str | None = None
    verification_status: Literal["pending", "verified", "rejected"] | None = None
    specialty_ids: list[int] | None = None
    image_url: str | None = None


class ActiveIn(BaseModel):
    is_active: bool
