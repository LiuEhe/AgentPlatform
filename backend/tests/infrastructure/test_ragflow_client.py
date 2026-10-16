import asyncio
import logging

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.ragflow.client import RagFlowClient


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ragflow_base_url="http://ragflow.test",
        ragflow_api_key="test-api-key",
        ragflow_dataset_id="test-dataset",
    )


def test_logs_ragflow_business_code_without_response_content(caplog) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 102,
                "message": "private response detail",
                "data": {"chunks": [{"content": "private chunk content"}]},
            },
        )

    async def retrieve() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await RagFlowClient(_settings(), client).retrieve("private query text")

    caplog.set_level(logging.WARNING, logger="app.infrastructure.ragflow.client")

    with pytest.raises(AppError) as raised:
        asyncio.run(retrieve())

    assert raised.value.code == "RAGFLOW_ERROR"
    assert "upstream_code=102" in caplog.text
    assert "data_type=dict" in caplog.text
    assert "private response detail" not in caplog.text
    assert "private chunk content" not in caplog.text
    assert "private query text" not in caplog.text


def test_logs_invalid_chunks_type_without_chunk_value(caplog) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "data": {"chunks": "private malformed value"}},
        )

    async def retrieve() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await RagFlowClient(_settings(), client).retrieve("private query text")

    caplog.set_level(logging.WARNING, logger="app.infrastructure.ragflow.client")

    with pytest.raises(AppError) as raised:
        asyncio.run(retrieve())

    assert raised.value.code == "RAGFLOW_ERROR"
    assert "chunks_type=str" in caplog.text
    assert "data_type=dict" in caplog.text
    assert "private malformed value" not in caplog.text
    assert "private query text" not in caplog.text
