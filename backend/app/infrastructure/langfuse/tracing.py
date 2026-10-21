"""将中立观测及 LangChain 配置适配到 Langfuse。"""

import logging
from asyncio import CancelledError
from contextlib import contextmanager

from app.core.observability import NullObservation, observation_attributes

logger = logging.getLogger(__name__)


class LangfuseObservation:
    def __init__(self, span):
        self._span = span
        self.trace_id = span.trace_id

    def update(self, *, attributes):
        try:
            status = attributes.get("status")
            level = "ERROR" if status == "failed" else "WARNING" if status == "cancelled" else None
            self._span.update(metadata=dict(attributes), level=level)
        except Exception:
            logger.warning("observation_update_failed")


class LangfuseObserver:
    def __init__(self, client, public_key):
        self.client = client
        self.public_key = public_key

    @contextmanager
    def scope(self, name, *, kind="span", attributes=None, detached=False):
        from langfuse import propagate_attributes
        from opentelemetry import context

        token = context.attach(context.Context()) if detached else None
        cm = propagation = None
        attrs = {**observation_attributes.get(), **(attributes or {})}
        try:
            try:
                cm = self.client.start_as_current_observation(
                    name=name,
                    as_type=kind if kind in {"agent", "retriever"} else "span",
                    metadata=attrs,
                )
                span = cm.__enter__()
                propagation = propagate_attributes(
                    session_id=attrs.get("session_id"),
                    metadata={k: str(v) for k, v in attrs.items()},
                )
                propagation.__enter__()
                observation = LangfuseObservation(span)
            except Exception:
                logger.warning("observation_start_failed")
                observation = NullObservation()
            try:
                yield observation
            except BaseException as exc:
                observation.update(
                    attributes={
                        "status": "cancelled" if isinstance(exc, CancelledError) else "failed",
                        "error_type": type(exc).__name__,
                    }
                )
                raise
        finally:
            for manager in (propagation, cm):
                if manager is not None:
                    try:
                        manager.__exit__(None, None, None)
                    except Exception:
                        logger.warning("observation_close_failed")
            if token is not None:
                context.detach(token)

    def current_trace_id(self):
        try:
            return self.client.get_current_trace_id()
        except Exception:
            return None

    def graph_config(self, context):
        try:
            from langchain_core.runnables.config import ensure_config
            from langfuse.langchain import CallbackHandler

            config = ensure_config()
            existing = config.get("callbacks")
            handlers = getattr(existing, "handlers", existing or [])
            callbacks = (
                []
                if any(isinstance(h, CallbackHandler) for h in handlers)
                else [CallbackHandler(public_key=self.public_key)]
            )
            return {
                "callbacks": callbacks,
                "run_name": context.agent_id,
                "metadata": {"agent_id": context.agent_id, "invocation_id": context.invocation_id},
            }
        except Exception as exc:
            logger.warning("langfuse_callbacks_unavailable error_type=%s", type(exc).__name__)
            return {}

    def shutdown(self):
        self.client.shutdown()
