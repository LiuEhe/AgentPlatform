import asyncio
from types import SimpleNamespace

import pytest


def test_remote_label_cache_and_fallback():
    from app.infrastructure.langfuse.prompts import LangfusePromptResolver
    from app.nodes.llm.prompts import PromptSpec

    class Client:
        calls = 0

        def get_prompt(self, name, **kwargs):
            self.calls += 1
            assert kwargs["label"] == "production"
            return SimpleNamespace(
                version=self.calls,
                get_langchain_prompt=lambda: [
                    ("system", "system"),
                    ("human", "{content}"),
                ],
            )

    async def run():
        client = Client()
        resolver = LangfusePromptResolver(client)
        spec = PromptSpec("test", (("system", "system"), ("human", "{content}")))
        async with resolver.session():
            results = await asyncio.gather(*(resolver.resolve(spec) for _ in range(5)))
            assert [r.version for r in results] == [1] * 5
        async with resolver.session():
            assert (await resolver.resolve(spec)).version == 2

    asyncio.run(run())


def test_strict_version_missing_fails():
    from app.infrastructure.langfuse.prompts import LangfusePromptResolver
    from app.nodes.llm.prompts import PromptSpec

    class BrokenClient:
        def get_prompt(self, *args, **kwargs):
            raise RuntimeError("not found")

    async def run():
        resolver = LangfusePromptResolver(BrokenClient())
        spec = PromptSpec("test", (("human", "{content}"),))
        async with resolver.session():
            assert (await resolver.resolve(spec)).fallback is True
        async with resolver.session(versions={"test": 7}, strict=True):
            with pytest.raises(ValueError, match="PROMPT_VERSION_UNAVAILABLE"):
                await resolver.resolve(spec)

    asyncio.run(run())


def test_template_variable_mismatch_falls_back_without_latest():
    from app.infrastructure.langfuse.prompts import LangfusePromptResolver
    from app.nodes.llm.prompts import PromptSpec

    client = SimpleNamespace(
        get_prompt=lambda *a, **k: SimpleNamespace(
            version=1,
            get_langchain_prompt=lambda: [("human", "{wrong}")],
        )
    )

    async def run():
        resolver = LangfusePromptResolver(client)
        async with resolver.session():
            result = await resolver.resolve(PromptSpec("test", (("human", "{content}"),)))
            assert result.fallback
            assert result.template.format_messages(content="hello")[0].content == "hello"

    asyncio.run(run())
