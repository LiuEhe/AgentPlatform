import json
from uuid import uuid4

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import Settings
from app.infrastructure.langfuse.client import create_observer


def test_nested_compiled_graph_has_one_generation_per_model_request():
    import asyncio
    import json

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.runnables import RunnableLambda

    from app.agents import build_agent_registry
    from app.runtime.agent_runtime import AgentRegistry, AgentRuntime

    class Model(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self):
            return "controlled"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            schema = kwargs.get("output_schema")
            if schema and schema.__name__ == "IntentDecision":
                content = json.dumps(
                    {
                        "intent": "institution_review",
                        "action": "call_agent",
                        "target_agent_id": "institution_review",
                        "review_args": {
                            "review_mode": "standard_document",
                            "draft": {"kind": "user_message", "id": "d"},
                            "standard": {"kind": "user_message", "id": "s"},
                        },
                    }
                )
            else:
                content = schema().model_dump_json() if schema else "受控回答"
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=content,
                            usage_metadata={
                                "input_tokens": 10,
                                "output_tokens": 2,
                                "total_tokens": 12,
                            },
                        )
                    )
                ]
            )

        def with_structured_output(self, schema, **kwargs):
            return self.bind(output_schema=schema) | RunnableLambda(
                lambda message: schema.model_validate_json(message.content),
            )

    exporter = InMemorySpanExporter()
    observer = create_observer(
        Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key=f"pk-test-{uuid4()}",
            langfuse_secret_key="sk-test",
        ),
        exporter=exporter,
    )
    model = Model()

    async def run():
        registry = AgentRegistry()
        runtime = AgentRuntime(registry, observer=observer)
        build_agent_registry(
            model,
            registry=registry,
            invoke_agent=runtime.invoke,
            graph_config_factory=observer.graph_config,
            observer=observer,
        )
        turn = {
            "latest_message_id": "last",
            "messages": [
                {"id": "d", "role": "user", "content": "第一条 草稿。"},
                {"id": "s", "role": "user", "content": "第一条 标准。"},
                {"id": "last", "role": "user", "content": "按标准审核草稿"},
            ],
        }
        await asyncio.gather(*(runtime.invoke("conversation_assistant", turn) for _ in range(2)))

    asyncio.run(run())
    observer.client.flush()
    spans = exporter.get_finished_spans()
    generations = [
        s for s in spans if s.attributes.get("langfuse.observation.type") == "generation"
    ]
    assert len(generations) == model.calls == 10
    assert len({s.context.trace_id for s in generations}) == 2
    assert all(s.parent is not None for s in generations)
    assert "第一条" not in json.dumps([dict(s.attributes) for s in spans], ensure_ascii=False)
    observer.shutdown()


def test_real_export_drops_content_events_and_resource_attributes():
    exporter = InMemorySpanExporter()
    observer = create_observer(
        Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key=f"pk-test-{uuid4()}",
            langfuse_secret_key="sk-test",
        ),
        exporter=exporter,
    )
    with observer.scope("safe", attributes={"run_id": "r1"}):
        with observer.client.start_as_current_observation(
            name="llm",
            as_type="generation",
            input="PRIVATE_DOCUMENT",
            model="test",
            usage_details={"input": 10, "output": 2},
        ) as generation:
            generation.update(output="PRIVATE_DOCUMENT")
    observer.client.flush()
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert "PRIVATE_DOCUMENT" not in json.dumps([dict(s.attributes) for s in spans])
    assert all(not s.events for s in spans)
    usage = [
        json.loads(v) for s in spans for k, v in s.attributes.items() if k.endswith("usage_details")
    ]
    assert usage == [{"input": 10, "output": 2}]
    observer.shutdown()


def test_failure_and_cancellation_have_safe_observation_levels():
    import asyncio

    import pytest

    exporter = InMemorySpanExporter()
    observer = create_observer(
        Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key=f"pk-test-{uuid4()}",
            langfuse_secret_key="sk-test",
        ),
        exporter=exporter,
    )
    with pytest.raises(RuntimeError):
        with observer.scope("failed"):
            raise RuntimeError("PRIVATE_DOCUMENT")
    with pytest.raises(asyncio.CancelledError):
        with observer.scope("cancelled"):
            raise asyncio.CancelledError()
    observer.client.flush()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["failed"].attributes["langfuse.observation.level"] == "ERROR"
    assert spans["cancelled"].attributes["langfuse.observation.level"] == "WARNING"
    assert "PRIVATE_DOCUMENT" not in json.dumps([dict(s.attributes) for s in spans.values()])
    observer.shutdown()


def test_callback_setup_failure_degrades_observability_only(monkeypatch):
    from types import SimpleNamespace

    import langfuse.langchain

    from app.infrastructure.langfuse.tracing import LangfuseObserver

    class BrokenHandler:
        def __init__(self, **kwargs):
            raise RuntimeError("unavailable")

    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", BrokenHandler)
    observer = LangfuseObserver(SimpleNamespace(), "test")
    assert observer.graph_config(SimpleNamespace(agent_id="a", invocation_id="i")) == {}


def test_sample_rate_zero_exports_nothing():
    exporter = InMemorySpanExporter()
    observer = create_observer(Settings(_env_file=None, langfuse_enabled=True,
        langfuse_sample_rate=0, langfuse_public_key=f"pk-test-{uuid4()}",
        langfuse_secret_key="sk-test"), exporter=exporter)
    with observer.scope("sampled-out"):
        pass
    observer.client.flush()
    assert exporter.get_finished_spans() == ()
    observer.shutdown()


def test_session_and_environment_survive_final_export():
    exporter = InMemorySpanExporter()
    observer = create_observer(Settings(_env_file=None, app_env="test-env", langfuse_enabled=True,
        langfuse_public_key=f"pk-test-{uuid4()}", langfuse_secret_key="sk-test"), exporter=exporter)
    with observer.scope("root", attributes={"session_id": "session-1"}):
        with observer.scope("child"):
            pass
    observer.client.flush()
    spans = exporter.get_finished_spans()
    assert any(s.attributes.get("session.id") == "session-1" for s in spans)
    assert all(s.resource.attributes.get("langfuse.environment") == "test-env" for s in spans)
    observer.shutdown()


def test_content_disabled_never_queues_automatic_media(monkeypatch):
    import os

    from langfuse._task_manager.media_manager import MediaManager

    processed = []
    monkeypatch.setattr(MediaManager, "_process_media", lambda *a, **kw: processed.append(kw))
    before = os.environ.get("LANGFUSE_MEDIA_UPLOAD_ENABLED")
    exporter = InMemorySpanExporter()
    observer = create_observer(Settings(_env_file=None, langfuse_enabled=True,
        langfuse_public_key=f"pk-test-{uuid4()}", langfuse_secret_key="sk-test"), exporter=exporter)
    with observer.client.start_as_current_observation(name="media", input={
        "messages": [{"content": "data:text/plain;base64,UFJJVkFURV9ET0NVTUVOVA=="}],
    }):
        pass
    observer.client.flush()
    assert processed == []
    assert os.environ.get("LANGFUSE_MEDIA_UPLOAD_ENABLED") == before
    observer.shutdown()
