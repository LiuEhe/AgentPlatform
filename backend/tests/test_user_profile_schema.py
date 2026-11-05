from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

import app.schemas.identity as identity
from app.schemas.identity import CreateUserRequest, ProfileRequest, RegisterRequest


def test_patch_distinguishes_omitted_and_clear():
    assert ProfileRequest.model_validate({}).model_dump(exclude_unset=True) == {}
    for key in ("email", "gender", "birthday", "phone_number", "address", "bio"):
        assert ProfileRequest.model_validate({key: "  "}).model_dump(exclude_unset=True) == {
            key: None,
        }
    for value in (None, "", "  "):
        with pytest.raises(ValidationError):
            ProfileRequest(display_name=value)


@pytest.mark.parametrize("key", ["email", "birthday", "role", "avatar_path", "has_avatar"])
def test_register_and_admin_create_reject_profile_fields(key):
    for model, secret in ((RegisterRequest, "password"), (CreateUserRequest, "temporary_password")):
        values = {"username": "alice", "display_name": "Alice", secret: "test-pass123"}
        assert model.model_validate(values).display_name == "Alice"
        with pytest.raises(ValidationError):
            model.model_validate({**values, key: "unexpected"})


@pytest.mark.parametrize("key,limit", [("bio", 200), ("address", 500), ("phone_number", 32)])
def test_profile_limits_and_controls(key, limit):
    value = "1" * limit if key == "phone_number" else "😀" * limit
    assert getattr(ProfileRequest(**{key: value}), key) == value
    for invalid in (value + "x", "bad\x00text", "bad\x1btext"):
        with pytest.raises(ValidationError):
            ProfileRequest(**{key: invalid})


def test_email_gender_phone_and_plain_text():
    assert ProfileRequest(email=" Alice@EXAMPLE.com ").email == "Alice@example.com"
    for gender in ("male", "female", "other", "undisclosed"):
        assert ProfileRequest(gender=gender).gender == gender
    phone = ProfileRequest(phone_number=" +86 (138) 0000-0000 ").phone_number
    assert phone == "+86 (138) 0000-0000"
    assert ProfileRequest(bio="<b>hello</b>\nnext").bio == "<b>hello</b>\nnext"
    for values in ({"email": "invalid"}, {"gender": "unknown"}, {"phone_number": "---"},
                   {"phone_number": "12+34"}, {"phone_number": "138abc"}, {"role": "admin"}):
        with pytest.raises(ValidationError):
            ProfileRequest(**values)


def test_birthday_uses_platform_day(monkeypatch):
    monkeypatch.setattr(identity, "profile_today", lambda: date(2026, 11, 5))
    assert ProfileRequest(birthday="2026-11-05").birthday == date(2026, 11, 5)
    assert ProfileRequest(birthday="2000-02-29").birthday == date(2000, 2, 29)
    for value in ("2026-11-06", "2000-02-30", "2026-11-05T00:00:00", 0, True):
        with pytest.raises(ValidationError):
            ProfileRequest(birthday=value)


def test_profile_today_at_business_midnight():
    assert identity.profile_today(datetime(2026, 11, 4, 15, 59, tzinfo=UTC)) == date(
        2026, 11, 4,
    )
    assert identity.profile_today(datetime(2026, 11, 4, 16, tzinfo=UTC)) == date(2026, 11, 5)
