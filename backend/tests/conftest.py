from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document

from app.schemas.conversation_turn import ConversationTurnInput, TurnMessage


@pytest.fixture(autouse=True)
def isolate_external_settings(monkeypatch):
    import os

    for key in tuple(os.environ):
        if key.startswith(("CONVERSATION_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PROMPTS_ENABLED", "false")
    for key in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_DATASET_ID",
        "INSTITUTION_REVIEW_CONCURRENCY",
        "DOCUMENT_EXPORT_TIMEOUT_SECONDS",
        "DOCUMENT_EXPORT_CONCURRENCY",
        "DOCUMENT_EXPORT_MAX_CHARS",
        "DOCUMENT_EXPORT_MAX_BODY_BYTES",
        "DOCUMENT_EXPORT_MAX_OUTPUT_BYTES",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def fake_model_factory():
    class FakeModel:
        def __init__(self, handler=None):
            self.calls = []
            self.handler = handler

        async def call(self, schema, messages):
            self.calls.append((schema, messages))
            if self.handler:
                return await self.handler(schema, messages)
            return schema() if schema else "未发现术语问题，无需基于本次检查修改。"

        def with_structured_output(self, schema):
            async def invoke(messages):
                return await self.call(schema, messages)

            return SimpleNamespace(ainvoke=invoke)

        async def ainvoke(self, messages):
            return await self.call(None, messages)

    return FakeModel


@pytest.fixture
def docx_bytes_factory():
    def make(*, title="草稿", body="第一条 正文"):
        doc = Document()
        doc.add_heading(title, level=1)
        for line in body.splitlines():
            doc.add_paragraph(line)
        buffer = BytesIO()
        doc.save(buffer)
        return buffer.getvalue()

    return make


@pytest.fixture
def turn_factory():
    def make(*, role="user", content="你好", documents=(), continuation=None, history=()):
        return ConversationTurnInput(
            latest_message_id="m1",
            messages=(
                *history,
                TurnMessage(
                    id="m1",
                    role=role,
                    content=content,
                    document_ids=tuple(d.id for d in documents),
                ),
            ),
            documents=documents,
            continuation=continuation,
        )

    return make
