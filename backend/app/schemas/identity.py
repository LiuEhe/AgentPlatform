"""中立身份记录与账号输入，秘密字段不参与repr。"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    has_avatar: bool
    created_at: datetime
    updated_at: datetime


Gender = Literal["male", "female", "other", "undisclosed"]
PROFILE_FIELDS = frozenset({
    "display_name", "email", "gender", "birthday", "phone_number", "address", "bio",
})


class UserProfile(UserIdentity):
    email: str | None = None
    gender: Gender | None = None
    birthday: date | None = None
    phone_number: str | None = None
    address: str | None = None
    bio: str | None = None


@dataclass
class AvatarWriteState:
    commit_started: bool = False


@dataclass(frozen=True)
class AvatarChange:
    profile: UserProfile
    previous_path: str | None = field(repr=False)


def profile_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(timezone(timedelta(hours=8))).date()


def validate_display_name(value):
    if not isinstance(value, str):
        raise ValueError("显示名称须为1–50个字符")
    value = value.strip()
    if not 1 <= len(value) <= 50 or any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("显示名称须为1–50个字符，不能包含控制字符")
    return value


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


class DisplayNameInput(IdentityInput):
    display_name: str

    _name = field_validator("display_name", mode="before")(validate_display_name)


class ProfileRequest(IdentityInput):
    display_name: str | None = None
    email: EmailStr | None = Field(default=None, max_length=254)
    gender: Gender | None = None
    birthday: date | None = None
    phone_number: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=200)

    _name = field_validator("display_name", mode="before")(validate_display_name)

    @field_validator("email", "gender", "birthday", "phone_number", "address", "bio",
                     mode="before")
    @classmethod
    def optional_text(cls, value, info):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            allowed = "\n\r\t" if info.field_name in {"address", "bio"} else ""
            if any(unicodedata.category(c) == "Cc" and c not in allowed for c in value):
                raise ValueError("资料不能包含非法控制字符")
        return value

    @field_validator("birthday", mode="before")
    @classmethod
    def birthday_date(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("生日须为YYYY-MM-DD格式")
        parsed = date.fromisoformat(value)
        if parsed > profile_today():
            raise ValueError("生日不能晚于今天")
        return parsed

    @field_validator("phone_number")
    @classmethod
    def phone(cls, value):
        if value is not None and (
            not re.fullmatch(r"\+?[0-9 ()-]+", value) or not re.search(r"[0-9]", value)
        ):
            raise ValueError("手机号格式无效")
        return value


class RegisterRequest(DisplayNameInput):
    username: str
    password: str = Field(repr=False)

    _username = field_validator("username")(normalize_username)
    _password = field_validator("password")(validate_password)


class CreateUserRequest(DisplayNameInput):
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
