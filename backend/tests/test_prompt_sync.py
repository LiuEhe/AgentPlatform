from types import SimpleNamespace

import pytest


def test_sync_is_read_only_without_apply():
    from scripts.sync_langfuse_prompts import sync_prompts

    class Missing(Exception):
        status_code = 404

    class Client:
        def get_prompt(self, *a, **kw):
            raise Missing()

        def create_prompt(self, **kwargs):
            raise AssertionError("dry run wrote data")

    result = sync_prompts(client=Client(), apply=False)
    assert result == {"created": 0, "missing": 8, "unchanged": 0, "conflict": 0}


def test_sync_conflict_never_moves_production_label():
    from scripts.sync_langfuse_prompts import sync_prompts

    class Client:
        def get_prompt(self, *a, **kw):
            return SimpleNamespace(get_langchain_prompt=lambda: [("system", "different")])

        def create_prompt(self, **kw):
            pytest.fail("must not overwrite conflict")

    assert sync_prompts(client=Client(), apply=True)["conflict"] == 8


def test_sync_same_content_does_not_create_version():
    from scripts.sync_langfuse_prompts import prompt_specs, sync_prompts

    specs = {s.name: s for s in prompt_specs()}

    class Client:
        def get_prompt(self, name, **kwargs):
            return SimpleNamespace(get_langchain_prompt=lambda: specs[name].messages)

        def create_prompt(self, **kwargs):
            pytest.fail("unchanged prompt must not create a version")

    assert sync_prompts(client=Client(), apply=True)["unchanged"] == 8


def test_sync_creates_missing_with_public_sdk_signature():
    from scripts.sync_langfuse_prompts import sync_prompts

    class Missing(Exception):
        status_code = 404

    created = []

    class Client:
        def get_prompt(self, *a, **kw):
            raise Missing()

        def create_prompt(self, *, name, prompt, type, labels):
            created.append((name, prompt, labels))

    assert sync_prompts(client=Client(), apply=True)["created"] == 8
    assert all(labels == [] for _, _, labels in created)
