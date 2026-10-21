"""供应商无关的观测接口与一次执行的关联标识。"""

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Protocol

observation_attributes: ContextVar[Mapping[str, str]] = ContextVar(
    "observation_attributes",
    default=MappingProxyType({}),
)


class Observation(Protocol):
    trace_id: str | None

    def update(self, *, attributes: Mapping[str, object]) -> None: ...


class Observer(Protocol):
    def scope(
        self,
        name: str,
        *,
        kind: str = "span",
        attributes: Mapping[str, object] | None = None,
        detached: bool = False,
    ) -> AbstractContextManager[Observation]: ...

    def current_trace_id(self) -> str | None: ...


class NullObservation:
    trace_id = None

    def update(self, *, attributes: Mapping[str, object]) -> None:
        pass


class NullObserver:
    @contextmanager
    def scope(self, name, *, kind="span", attributes=None, detached=False):
        yield NullObservation()

    def current_trace_id(self) -> str | None:
        return None


@contextmanager
def bind_observation_attributes(attributes: Mapping[str, str]) -> Iterator[None]:
    token = observation_attributes.set({**observation_attributes.get(), **attributes})
    try:
        yield
    finally:
        observation_attributes.reset(token)
