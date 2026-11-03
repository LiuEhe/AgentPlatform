"""中立身份记录与账号输入，秘密字段不参与repr。"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_username(value: str) -> str:
    value = value.strip(" \t\n\r\v\f").lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", value):
        raise ValueError("用户名须为3–32位字母、数字或下划线，以字母开头")
    return value


def validate_password(value: str) -> str:
    if not 6 <= len(value) <= 20 or "\x00" in value:
        raise ValueError("密码须为6–20个字符，不能包含空字符")
    return value


class UserIdentity(BaseModel):
    user_id: UUID
    username: str
    display_name: str
    role: Literal["admin", "user"]
    status: Literal["active", "disabled"]
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserRecord:
    identity: UserIdentity
    password_hash: str = field(repr=False)


@dataclass(frozen=True)
class AuthContext:
    user: UserIdentity
    auth_session_id: UUID
    csrf_token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class LoginGrant:
    context: AuthContext
    cookie_token: str = field(repr=False)


@dataclass(frozen=True)
class HashVerification:
    valid: bool
    replacement_hash: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class UserPage:
    items: list[UserIdentity]
    next_cursor: str | None


class IdentityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(IdentityInput):
    username: str
    password: str = Field(repr=False)

    _username = field_validator("username")(normalize_username)
    _password = field_validator("password")(validate_password)


class ProfileRequest(IdentityInput):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 50 or "\x00" in value:
            raise ValueError("显示名称须为1–50个字符")
        return value


class RegisterRequest(ProfileRequest):
    username: str
    password: str = Field(repr=False)

    _username = field_validator("username")(normalize_username)
    _password = field_validator("password")(validate_password)


class CreateUserRequest(ProfileRequest):
    username: str
    temporary_password: str = Field(repr=False)

    _username = field_validator("username")(normalize_username)
    _password = field_validator("temporary_password")(validate_password)


class PasswordRequest(IdentityInput):
    current_password: str = Field(repr=False)
    new_password: str = Field(repr=False)

    _password = field_validator("current_password", "new_password")(validate_password)


class ResetPasswordRequest(IdentityInput):
    temporary_password: str = Field(repr=False)

    _password = field_validator("temporary_password")(validate_password)


class StatusRequest(IdentityInput):
    status: Literal["active", "disabled"]
