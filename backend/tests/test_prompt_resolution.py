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


def test_send_chunks_share_prompt_resolution_session(fake_model_factory):
    from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph
    from app.agents.institution_review.nodes.clause_split import split_clauses
    from app.infrastructure.langfuse.prompts import LangfusePromptResolver

    class Client:
        calls = 0
        version = 1

        def get_prompt(self, name, **kwargs):
            assert name == "institution-review/standard-clause"
            self.calls += 1
            version = self.version
            return SimpleNamespace(
                version=version,
                get_langchain_prompt=lambda: [
                    ("system", f"remote-version-{version}"),
                    ("human", "{content}"),
                ],
            )

    async def run():
        client = Client()

        async def handler(schema, messages):
            client.version = 2  # 本轮其他并发 chunk 不应因此刷新模板
            return schema()

        model = fake_model_factory(handler)
        graph = build_chunk_review_graph(model, None, semaphore=asyncio.Semaphore(2))
        value = {
            "title": "草稿",
            "content": "\n".join(f"第{i}条 原文" for i in range(1, 5)),
            "review_mode": "standard_document",
            "standard_name": "标准",
            "standard_content": "标准全文",
        }
        value.update(split_clauses(value))
        resolver = LangfusePromptResolver(client)
        async with resolver.session():
            result = await graph.ainvoke(value)
        assert len(result["clause_reviews"]) == 4
        assert client.calls == 1
        assert len(model.calls) == 4
        assert [messages[0][1] for _, messages in model.calls] == ["remote-version-1"] * 4
        async with resolver.session():
            await graph.ainvoke(value)
        assert client.calls == 2
        assert [messages[0][1] for _, messages in model.calls[4:]] == ["remote-version-2"] * 4

    asyncio.run(run())
