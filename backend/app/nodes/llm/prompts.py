"""公共 Prompt 解析会话、编译与模型调用；不包含 Agent 策略。"""

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

_active = ContextVar("prompt_resolver", default=None)
_session = ContextVar("prompt_session", default=None)


@dataclass(frozen=True)
class PromptSpec:
    name: str
    messages: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ResolvedPrompt:
    template: ChatPromptTemplate
    name: str
    version: int | None = None
    fallback: bool = True


class PromptResolver:
    @asynccontextmanager
    async def session(self, *, versions: Mapping[str, int] | None = None, strict=False):
        if _active.get() is self and _session.get() is not None:
            yield
            return
        active = _active.set(self)
        state = _session.set(({}, versions, strict))
        try:
            yield
        finally:
            cache, _, _ = _session.get()
            pending = [task for task in cache.values() if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            _session.reset(state)
            _active.reset(active)

    async def resolve(self, spec: PromptSpec) -> ResolvedPrompt:
        state = _session.get() if _active.get() is self else None
        if state is None:
            return await self._resolve(spec, version=None, strict=False)
        cache, versions, strict = state
        if strict and (versions is None or spec.name not in versions):
            raise ValueError("PROMPT_VERSION_UNAVAILABLE")
        if spec.name not in cache:
            cache[spec.name] = asyncio.create_task(
                self._resolve(
                    spec,
                    version=versions.get(spec.name) if versions else None,
                    strict=strict,
                )
            )
        return await asyncio.shield(cache[spec.name])

    async def _resolve(self, spec, *, version, strict):
        if strict:
            raise ValueError("PROMPT_VERSION_UNAVAILABLE")
        template = ChatPromptTemplate.from_messages(spec.messages)
        template.metadata = {"prompt_name": spec.name, "fallback": True}
        return ResolvedPrompt(template=template, name=spec.name)


async def invoke_prompt(model, spec: PromptSpec, variables, *, output_schema=None):
    resolver = _active.get() or PromptResolver()
    resolved = await resolver.resolve(spec)

    async def call(prompt):
        messages = [
            ("human" if m.type == "human" else m.type, m.content) for m in prompt.to_messages()
        ]
        target = model.with_structured_output(output_schema) if output_schema else model
        return await target.ainvoke(messages)

    # 保留真实 Prompt Runnable，回调可将版本关联到其后代 generation。
    return await (resolved.template | RunnableLambda(call)).ainvoke(variables)
