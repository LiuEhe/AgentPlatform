"""按显式配置的在线文本价格估算人民币；不写入美元成本字段。"""

import json
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CnyPricing:
    model: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_per_million: Decimal


def pricing_from_settings(settings):
    values = (
        settings.langfuse_input_cny_per_million,
        settings.langfuse_output_cny_per_million,
        settings.langfuse_cached_input_cny_per_million,
    )
    if not settings.langfuse_cost_model or any(v is None for v in values):
        return None
    return CnyPricing(settings.langfuse_cost_model, *values)


def estimate_cny(usage, pricing):
    if not isinstance(usage, dict):
        return None
    if "prompt_tokens" in usage:
        details = usage.get("prompt_tokens_details") or {}
        if not isinstance(details, dict):
            return None
        cached = details.get("cached_tokens", 0)
        raw_input = usage.get("prompt_tokens")
        output = usage.get("completion_tokens")
        if any(type(v) is not int or v < 0 for v in (raw_input, output, cached)):
            return None
        if cached > raw_input:
            return None
        plain_input = raw_input - cached
    else:
        plain_input, output = usage.get("input"), usage.get("output")
        cache_keys = {"input_cache_read", "input_cached_tokens", "input_cache_read_tokens"}
        known = {
            "input",
            "output",
            "total",
            "output_reasoning",
            "output_reasoning_tokens",
        } | cache_keys
        if any(k not in known and v not in (0, None) for k, v in usage.items()):
            return None
        cache_values = [usage.get(key, 0) for key in cache_keys]
        reasoning_values = [
            usage.get(key, 0) for key in ("output_reasoning", "output_reasoning_tokens")
        ]
        if any(type(v) is not int or v < 0 for v in (*cache_values, *reasoning_values)):
            return None
        if sum(v > 0 for v in cache_values) > 1 or sum(v > 0 for v in reasoning_values) > 1:
            return None
        cached = sum(cache_values)
        reasoning = sum(reasoning_values)
        if any(type(v) is not int or v < 0 for v in (plain_input, output, cached, reasoning)):
            return None
        output += reasoning
    return (
        Decimal(plain_input) * pricing.input_per_million
        + Decimal(output) * pricing.output_per_million
        + Decimal(cached) * pricing.cached_per_million
    ) / Decimal(1000000)


def add_cost_metadata(attributes, pricing):
    if pricing is None or attributes.get("langfuse.observation.type") != "generation":
        return attributes
    if attributes.get("langfuse.observation.model.name") != pricing.model:
        return attributes
    try:
        usage = json.loads(attributes.get("langfuse.observation.usage_details", "null"))
        amount = estimate_cny(usage, pricing)
    except (ValueError, TypeError, ArithmeticError):
        return attributes
    if amount is None:
        return attributes
    return {
        **attributes,
        "langfuse.observation.metadata.estimated_cost_cny": json.dumps(float(amount)),
        "langfuse.observation.metadata.cost_currency": json.dumps("CNY"),
        "langfuse.observation.metadata.cost_basis": json.dumps("online-token-estimate"),
    }
