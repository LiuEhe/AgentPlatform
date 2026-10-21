from decimal import Decimal


def test_cached_tokens_are_not_double_counted():
    from app.infrastructure.langfuse.costs import CnyPricing, estimate_cny

    pricing = CnyPricing("model", Decimal("0.8"), Decimal("2.7"), Decimal("0.1"))
    assert estimate_cny(
        {"input": 900000, "input_cache_read": 100000, "output": 1000000}, pricing
    ) == Decimal("3.43")
    assert estimate_cny(
        {
            "prompt_tokens": 1000000,
            "completion_tokens": 1000000,
            "prompt_tokens_details": {"cached_tokens": 100000},
        },
        pricing,
    ) == Decimal("3.43")


def test_unknown_usage_or_model_price_is_not_zero():
    from app.infrastructure.langfuse.costs import CnyPricing, estimate_cny

    pricing = CnyPricing("model", Decimal("0.8"), Decimal("2.7"), Decimal("0.1"))
    assert estimate_cny({"total": 100}, pricing) is None
    assert estimate_cny({"input": 10, "output": 2, "input_audio": 3}, pricing) is None
    assert estimate_cny({"input": -1, "output": 2}, pricing) is None
    assert (
        estimate_cny(
            {"prompt_tokens": 3, "completion_tokens": 1, "prompt_tokens_details": 42}, pricing
        )
        is None
    )


def test_generation_records_cny_without_inventing_usd_cost():
    import json
    from uuid import uuid4

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.core.config import Settings
    from app.infrastructure.langfuse.client import create_observer

    exporter = InMemorySpanExporter()
    observer = create_observer(
        Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key=f"pk-test-{uuid4()}",
            langfuse_secret_key="sk-test",
            langfuse_cost_model="priced",
            langfuse_input_cny_per_million="0.8",
            langfuse_output_cny_per_million="2.7",
            langfuse_cached_input_cny_per_million="0.1",
        ),
        exporter=exporter,
    )
    with observer.client.start_as_current_observation(
        name="priced",
        as_type="generation",
        model="priced",
        usage_details={"input": 900000, "input_cache_read": 100000, "output": 1000000},
    ):
        pass
    observer.client.flush()
    attributes = exporter.get_finished_spans()[0].attributes
    assert json.loads(attributes["langfuse.observation.metadata.estimated_cost_cny"]) == 3.43
    assert json.loads(attributes["langfuse.observation.metadata.cost_currency"]) == "CNY"
    assert "langfuse.observation.cost_details" not in attributes
    observer.shutdown()
