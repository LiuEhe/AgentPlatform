"""Profile SQL artifact parity and non-destructive scope; never executes SQL."""

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
    "users_profile_avatar_path_check",
    "users_profile_email_length_check",
    "users_profile_gender_check",
    "users_profile_phone_length_check",
    "users_profile_address_length_check",
    "users_profile_bio_length_check",
}


def assets():
    initializer = (SQL_ROOT / "schema_v4.sql").read_text(encoding="utf-8")
    migration_path = SQL_ROOT / "add_user_profile_fields.sql"
    assert migration_path.exists(), "The reviewed profile increment SQL must be delivered"
    increment = migration_path.read_text(encoding="utf-8")
    return initializer, increment


def without_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def test_profile_sql_assets_have_matching_nullable_columns():
    initializer, increment = assets()
    users = initializer.split("CREATE TABLE users (", 1)[1].split("\n);", 1)[0]
    for name, data_type in PROFILE_COLUMNS.items():
        initial = re.search(rf"^\s*{name}\s+{data_type}\b([^\n]*)", users, re.M)
        added = re.search(rf"ADD COLUMN\s+{name}\s+{data_type}\b([^\n]*)", increment, re.I)
        assert initial is not None, f"Initializer missing profile column {name}"
        assert added is not None, f"Increment missing profile column {name}"
        for declaration in (initial[1], added[1]):
            assert "NOT NULL" not in declaration.upper()
            assert "DEFAULT" not in declaration.upper()


def test_profile_sql_assets_share_static_constraints():
    initializer, increment = assets()
    pattern = r"CONSTRAINT\s+(users_profile_\w+)\s+CHECK\s*\(([^\n]+)\)"
    initial = dict(re.findall(pattern, initializer, re.I))
    added = dict(re.findall(pattern, increment, re.I))
    assert set(initial) == CONSTRAINTS
    assert set(added) == CONSTRAINTS
    def normalize(value):
        return re.sub(r"\s+", "", value).rstrip(",")
    assert {key: normalize(value) for key, value in initial.items()} == {
        key: normalize(value) for key, value in added.items()
    }
    assert "CURRENT_DATE" not in without_comments(initializer + increment).upper()


def test_increment_only_alters_users_and_never_mutates_user_data():
    initializer, increment = assets()
    sql = without_comments(increment)
    assert re.search(r"^\s*BEGIN\s*;", sql, re.I)
    assert re.search(r"COMMIT\s*;\s*$", sql, re.I)
    assert set(re.findall(r"ALTER\s+TABLE\s+(\w+)", sql, re.I)) == {"users"}
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE|INSERT|UPDATE)\b", sql, re.I)
    assert not re.search(r"\bCREATE\s+(TABLE|INDEX|SCHEMA)\b", sql, re.I)
    assert "IF NOT EXISTS" not in sql.upper()
    assert "INSERT INTO chat_schema_version VALUES (true, 4);" in initializer


def test_increment_checks_existing_structure_before_adding_columns():
    _, increment = assets()
    preflight, _ = without_comments(increment).split("ALTER TABLE users", 1)
    assert "current_schema()" in preflight
    assert "information_schema.columns" in preflight
    assert "pg_constraint" in preflight
    assert "RAISE EXCEPTION" in preflight
    for column in PROFILE_COLUMNS:
        assert f"'{column}'" in preflight
    for name in CONSTRAINTS:
        assert f"'{name}'" in preflight
