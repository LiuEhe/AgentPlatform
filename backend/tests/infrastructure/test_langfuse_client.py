import asyncio

from app.core.config import Settings


def test_disabled_does_not_construct_sdk_or_connect():
    from app.infrastructure.langfuse.client import create_observer

    observer = create_observer(Settings(_env_file=None))
    with observer.scope("disabled") as span:
        assert span.trace_id is None
    assert observer.current_trace_id() is None


def test_missing_keys_degrades_observability_only():
    from app.infrastructure.langfuse.client import create_observer

    settings = Settings(_env_file=None, langfuse_enabled=True, llm_model="x", llm_api_key="x")
    assert create_observer(settings).current_trace_id() is None
    assert settings.readiness_issues() == []


def test_sdk_shutdown_after_tasks_without_blocking_loop():
    from app.infrastructure.langfuse.client import shutdown_observer

    class SlowObserver:
        def shutdown(self):
            import time

            time.sleep(0.03)

    async def run():
        task = asyncio.create_task(shutdown_observer(SlowObserver()))
        await asyncio.sleep(0.005)
        assert not task.done()
        await task

    asyncio.run(run())
