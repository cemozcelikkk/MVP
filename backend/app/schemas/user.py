"""Kullanıcı / Auth Pydantic şemaları."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    # API sözleşmesinde "username" olarak sunulur; DB'de mevcut
    # `display_name` kolonuna yazılır (bkz. app.models.user.User).
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Şifre UTF-8 kodlamasında en fazla 72 bayt olabilir.")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    trust_score: int
    is_active: bool
    email_verified: bool = False
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class PasswordResetRequest(TokenRequest):
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Şifre UTF-8 kodlamasında en fazla 72 bayt olabilir.")
        return value


class AccountDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=72)
    confirmation: str
