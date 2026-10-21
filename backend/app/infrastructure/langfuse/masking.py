"""在 SDK 及最终 OTel 导出边界过滤数据。"""

import json
from collections.abc import Mapping, Sequence

from app.infrastructure.langfuse.costs import add_cost_metadata

SAFE_METADATA = frozenset(
    {
        "request_id",
        "session_id",
        "conversation_id",
        "run_id",
        "agent_id",
        "invocation_id",
        "status",
        "error_type",
        "error_code",
        "method",
        "path",
        "status_code",
        "elapsed_ms",
        "chunk_id",
        "sequence",
        "count",
        "similarity",
        "fallback",
        "prompt_name",
        "prompt_version",
        "langgraph_node",
        "langgraph_step",
        "langgraph_path",
        "ls_model_name",
        "ls_model_type",
        "dataset_digest",
        "code_version",
        "model",
        "temperature",
        "versions",
        "stage",
    }
)
SENSITIVE = ("secret", "api_key", "authorization", "password", "credential", "access_token")


def mask_export(value: object, *, capture_content: bool, secrets: Sequence[str]) -> object:
    def redact(item):
        if isinstance(item, str):
            for secret in secrets:
                if secret:
                    item = item.replace(secret, "[REDACTED]")
            return item
        if isinstance(item, Mapping):
            result = {}
            for key, val in item.items():
                key = str(key)
                if any(word in key.lower() for word in SENSITIVE):
                    continue
                if not capture_content and key in {
                    "input",
                    "output",
                    "messages",
                    "documents",
                    "exception",
                    "status_message",
                }:
                    continue
                if key == "metadata" and isinstance(val, Mapping):
                    val = {k: v for k, v in val.items() if k in SAFE_METADATA}
                result[key] = redact(val)
            return result
        if isinstance(item, (list, tuple)):
            return [redact(x) for x in item]
        if item is None or isinstance(item, (int, float, bool)):
            return item
        return "[REDACTED]"

    return redact(value)


def sanitize_attributes(attributes, *, capture_content, secrets):
    result = {}
    for key, value in attributes.items():
        if any(word in key.lower() for word in SENSITIVE):
            continue
        if "metadata." in key:
            if key.split("metadata.", 1)[1] not in SAFE_METADATA:
                continue
        elif any(word in key for word in ("input", "output", "prompt", "completion")):
            if not capture_content and not any(
                word in key for word in ("usage", "tokens", "cost", "prompt.name", "prompt.version")
            ):
                continue
        elif key != "session.id" and not key.startswith(
            ("langfuse.", "gen_ai.", "llm.", "openinference.")
        ):
            continue
        if "status_message" in key:
            continue
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = value
            safe = mask_export(
                decoded,
                capture_content=capture_content or "usage" in key or "cost" in key,
                secrets=secrets,
            )
            value = json.dumps(safe, ensure_ascii=False) if decoded != value else safe
        result[key] = value
    return result


def sanitized_exporter(delegate, *, capture_content, secrets, pricing=None):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter
    from opentelemetry.trace import Status

    class SanitizedExporter(SpanExporter):
        def export(self, spans):
            cleaned = []
            for span in spans:
                cleaned.append(
                    ReadableSpan(
                        name=mask_export(span.name, capture_content=True, secrets=secrets),
                        context=span.context,
                        parent=span.parent,
                        kind=span.kind,
                        resource=Resource(
                            {
                                "service.name": "agent-platform",
                                "langfuse.environment": span.resource.attributes.get(
                                    "langfuse.environment",
                                    "default",
                                ),
                            }
                        ),
                        attributes=add_cost_metadata(
                            sanitize_attributes(
                                span.attributes or {},
                                capture_content=capture_content,
                                secrets=secrets,
                            ),
                            pricing,
                        ),
                        events=(),
                        links=(),
                        status=Status(span.status.status_code),
                        start_time=span.start_time,
                        end_time=span.end_time,
                        instrumentation_scope=span.instrumentation_scope,
                    )
                )
            return delegate.export(cleaned)

        def shutdown(self):
            return delegate.shutdown()

        def force_flush(self, timeout_millis=30000):
            return delegate.force_flush(timeout_millis)

    return SanitizedExporter()
