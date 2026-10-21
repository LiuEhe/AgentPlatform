import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from app.runtime.agent_runtime import AgentRegistry, AgentRuntime


class RecordingObserver:
    def __init__(self):
        self.current = ContextVar("recording", default=None)
        self.records = []

    @contextmanager
    def scope(self, name, *, kind="span", attributes=None, detached=False):
        parent = None if detached else self.current.get()
        record = {"name": name, "parent": parent, **(attributes or {})}
        self.records.append(record)
        token = self.current.set(record)
        try:
            yield SimpleNamespace(trace_id="trace", update=lambda **kw: record.update(**kw))
        finally:
            self.current.reset(token)

    def current_trace_id(self):
        return "trace" if self.current.get() else None


def test_parallel_runs_and_child_agents_keep_separate_contexts():
    async def run():
        observer = RecordingObserver()
        registry = AgentRegistry()
        runtime = AgentRuntime(registry, observer=observer)

        class Child:
            async def invoke(self, payload, context):
                await asyncio.sleep(0)
                return payload["id"]

        class Parent:
            async def invoke(self, payload, context):
                return (await runtime.invoke("child", payload)).output

        registry.register("parent", Parent())
        registry.register("child", Child())
        results = await asyncio.gather(*(runtime.invoke("parent", {"id": i}) for i in (1, 2)))
        assert [r.output for r in results] == [1, 2]
        parents = [r for r in observer.records if r["agent_id"] == "parent"]
        children = [r for r in observer.records if r["agent_id"] == "child"]
        assert len(parents) == len(children) == 2
        assert all(r["parent"] in parents for r in children)
        assert len({r["invocation_id"] for r in observer.records}) == 4
        assert observer.current.get() is None

    asyncio.run(run())
