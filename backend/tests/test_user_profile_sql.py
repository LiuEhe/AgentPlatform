"""Profile fields and constraints in the new-environment initializer; never executes SQL."""

import re
from pathlib import Path

SQL_ROOT = Path(__file__).resolve().parents[1] / "database"
PROFILE_COLUMNS = {
    "avatar_path": "text",
    "email": "text",
    "gender": "text",
    "birthday": "date",
    "phone_number": "text",
    "address": "text",
    "bio": "text",
}
CONSTRAINTS = {
    "users_profile_avatar_path_check": "avatar_path IS NULL OR char_length(btrim(avatar_path)) > 0",
    "users_profile_email_length_check": "email IS NULL OR char_length(email) BETWEEN 1 AND 254",
    "users_profile_gender_check": (
        "gender IS NULL OR gender IN ('male','female','other','undisclosed')"
    ),
    "users_profile_phone_length_check": (
        "phone_number IS NULL OR char_length(phone_number) BETWEEN 1 AND 32"
    ),
    "users_profile_address_length_check": (
        "address IS NULL OR char_length(address) BETWEEN 1 AND 500"
    ),
    "users_profile_bio_length_check": "bio IS NULL OR char_length(bio) BETWEEN 1 AND 200",
}


def initializer():
    return (SQL_ROOT / "schema_v4.sql").read_text(encoding="utf-8")


def without_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def test_initializer_has_nullable_profile_columns():
    users = without_comments(initializer()).split("CREATE TABLE users (", 1)[1].split("\n);", 1)[0]
    for name, data_type in PROFILE_COLUMNS.items():
        initial = re.search(rf"^\s*{name}\s+{data_type}\b([^\n]*)", users, re.M)
        assert initial is not None, f"Initializer missing profile column {name}"
        assert "NOT NULL" not in initial[1].upper()
        assert "DEFAULT" not in initial[1].upper()


def test_initializer_has_expected_profile_constraints():
    pattern = r"CONSTRAINT\s+(users_profile_\w+)\s+CHECK\s*\(([^\n]+)\)"
    users = without_comments(initializer()).split("CREATE TABLE users (", 1)[1].split("\n);", 1)[0]
    initial = dict(re.findall(pattern, users, re.I))

    def normalize(value):
        return re.sub(r"\s+", "", value).rstrip(",")

    assert {key: normalize(value) for key, value in initial.items()} == {
        key: normalize(value) for key, value in CONSTRAINTS.items()
    }


def test_initializer_constraints_do_not_depend_on_current_date():
    assert "CURRENT_DATE" not in without_comments(initializer()).upper()


def test_initializer_records_current_schema_version():
    assert "INSERT INTO chat_schema_version VALUES (true, 4);" in without_comments(initializer())
