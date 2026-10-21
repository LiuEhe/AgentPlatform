"""对合成数据显式运行真实 Agent；默认只验证本地文件。"""

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from app.agents import build_agent_registry
from app.agents.conversation_assistant.evaluation import evaluate_case as evaluate_conversation
from app.agents.institution_review.evaluation import evaluate_case as evaluate_review
from app.core.config import Settings
from app.infrastructure.langfuse.client import create_observer, shutdown_observer
from app.infrastructure.langfuse.prompts import LangfusePromptResolver
from app.infrastructure.ragflow.client import RagFlowClient
from app.runtime.agent_runtime import AgentRegistry, AgentRuntime
from app.services.llm_service import create_llm_service
from scripts.sync_langfuse_prompts import prompt_specs


async def execute_case(case, *, runtime, resolver, versions, projections=None):
    try:
        async with resolver.session(versions=versions, strict=True):
            execution = await runtime.invoke(case["agent_id"], case["input"])
        actual = (projections or {}).pop(execution.invocation_id, {})
        evaluator = (
            evaluate_conversation
            if case["agent_id"] == "conversation_assistant"
            else evaluate_review
        )
        return {
            "id": case["id"],
            "status": "succeeded",
            "evaluation": actual,
            "scores": evaluator(case["expected"], actual),
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "status": "failed",
            "error_type": type(exc).__name__,
            "scores": [{"name": "execution_success", "value": 0.0, "comment": "failed"}],
        }


async def run_cases(cases, *, runtime, resolver, versions, concurrency=1, projections=None):
    if concurrency < 1:
        raise ValueError("INVALID_CONCURRENCY")
    slots = asyncio.Semaphore(concurrency)

    async def run(case):
        async with slots:
            return await execute_case(
                case, runtime=runtime, resolver=resolver, versions=versions, projections=projections
            )

    items = await asyncio.gather(*(run(case) for case in cases))
    return summarize(items)


def summarize(items):
    succeeded = sum(item["status"] == "succeeded" for item in items)
    return {
        "total": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        "score_denominator": len(items),
        "items": items,
    }


def reconcile_results(cases, task_items, experiment):
    completed = {item["id"]: item for item in task_items}
    reported = {}
    for result in experiment.item_results:
        source = result.item
        case = source.get("input") if isinstance(source, dict) else source.input
        if isinstance(case, dict) and isinstance(case.get("id"), str):
            reported[case["id"]] = result
    items = []
    for case in cases:
        identifier = case["id"]
        item, result = completed.get(identifier), reported.get(identifier)
        error = None
        if item is None or result is None:
            error = "EXPERIMENT_ITEM_MISSING"
        else:
            required = {"execution_success"}
            if item["status"] == "succeeded":
                required.update(case["expected"])
            valid = {score.name for score in result.evaluations
                     if isinstance(score.value, (int, float)) and math.isfinite(score.value)}
            if not required.issubset(valid):
                error = "EXPERIMENT_EVALUATION_INCOMPLETE"
        if error:
            item = {"id": identifier, "status": "failed", "error_type": error,
                    "scores": [{"name": "execution_success", "value": 0.0,
                                "comment": "experiment pipeline failed"}]}
        items.append(item)
    return summarize(items)


def load_inputs(dataset_path, versions_path):
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    versions = json.loads(Path(versions_path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("INVALID_DATASET")
    seen = set()
    for case in cases:
        if (
            not isinstance(case.get("id"), str)
            or case["id"] in seen
            or case.get("agent_id") not in {"conversation_assistant", "institution_review"}
            or not isinstance(case.get("input"), dict)
            or not isinstance(case.get("expected"), dict)
        ):
            raise ValueError("INVALID_DATASET_ITEM")
        seen.add(case["id"])
    if set(versions) != {p.name for p in prompt_specs()} or any(
        type(v) is not int or v < 1 for v in versions.values()
    ):
        raise ValueError("INVALID_PROMPT_VERSIONS")
    return cases, versions


def ensure_dataset(client, *, name, cases, sync=False):
    try:
        dataset = client.get_dataset(name)
    except Exception as exc:
        if not sync or getattr(exc, "status_code", None) != 404:
            raise
        client.create_dataset(name=name, description="AgentPlatform synthetic acceptance")
        dataset = client.get_dataset(name)
    existing = {item.id: item for item in dataset.items}
    expected_ids = {str(uuid5(NAMESPACE_URL, f"{name}:{case['id']}")) for case in cases}
    if set(existing) - expected_ids:
        raise ValueError("DATASET_CONTENT_CONFLICT")
    # 先验证全部已有项，再创建缺失项，避免遇到冲突前部分写入。
    for case in cases:
        identifier = str(uuid5(NAMESPACE_URL, f"{name}:{case['id']}"))
        item = existing.get(identifier)
        if item is not None and (item.input != case or item.expected_output != case["expected"]):
            raise ValueError("DATASET_CONTENT_CONFLICT")
        if item is None and not sync:
            raise ValueError("DATASET_ITEM_MISSING")
    for case in cases:
        identifier = str(uuid5(NAMESPACE_URL, f"{name}:{case['id']}"))
        if identifier not in existing:
            client.create_dataset_item(
                dataset_name=name, id=identifier, input=case, expected_output=case["expected"]
            )
    return client.get_dataset(name)


async def run_remote(args, cases, versions):
    settings = Settings()
    observer = create_observer(settings)
    try:
        if not hasattr(observer, "client"):
            raise ValueError("LANGFUSE_NOT_CONFIGURED")
        if settings.readiness_issues():
            raise ValueError("MODEL_NOT_CONFIGURED")
        resolver = LangfusePromptResolver(
            observer.client, cache_ttl_seconds=settings.langfuse_prompt_cache_ttl_seconds
        )
        # 固定版本缺失时，在任何付费模型请求或数据集写入之前失败。
        async with resolver.session(versions=versions, strict=True):
            await asyncio.gather(*(resolver.resolve(spec) for spec in prompt_specs()))
        dataset = await asyncio.to_thread(
            ensure_dataset,
            observer.client,
            name=args.dataset_name,
            cases=cases,
            sync=args.sync_dataset,
        )
        projections = {}

        @asynccontextmanager
        async def scope(context):
            async with resolver.session(versions=versions, strict=True):
                yield

        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as http:
            rag = (
                RagFlowClient(settings, http, observer=observer)
                if not settings.ragflow_issues()
                else None
            )
            registry = AgentRegistry()
            runtime = AgentRuntime(registry, observer=observer, execution_scope_factory=scope)
            model = create_llm_service(settings)
            model.temperature = args.temperature
            build_agent_registry(
                model,
                rag,
                registry=registry,
                invoke_agent=runtime.invoke,
                institution_review_concurrency=settings.institution_review_concurrency,
                conversation_max_review_chars=settings.max_review_chars,
                observer=observer,
                graph_config_factory=observer.graph_config,
                evaluation_sink=lambda agent, invocation, projection: projections.__setitem__(
                    invocation, dict(projection)
                ),
            )
            loop = asyncio.get_running_loop()
            items = []

            def task(*, item, **kwargs):
                future = asyncio.run_coroutine_threadsafe(
                    execute_case(
                        item.input,
                        runtime=runtime,
                        resolver=resolver,
                        versions=versions,
                        projections=projections,
                    ),
                    loop,
                )
                result = future.result()
                items.append(result)
                return result

            def evaluate(*, output, **kwargs):
                from langfuse import Evaluation

                values = output["scores"]
                if output["status"] == "succeeded":
                    values = [*values, {"name": "execution_success", "value": 1.0, "comment": "ok"}]
                return [Evaluation(**score) for score in values]

            digest = hashlib.sha256(
                json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            code = (
                subprocess.run(
                    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
                ).stdout.strip()
                or "unknown"
            )
            experiment = await asyncio.to_thread(
                dataset.run_experiment,
                name=args.run_name,
                run_name=f"{args.run_name}-{uuid4().hex[:8]}",
                task=task,
                evaluators=[evaluate],
                max_concurrency=args.concurrency,
                metadata={
                    "dataset_digest": digest,
                    "versions": versions,
                    "code_version": code,
                    "model": settings.llm_model,
                    "temperature": args.temperature,
                },
            )
            summary = reconcile_results(cases, items, experiment)
            summary["experiment_url"] = experiment.experiment_url
            summary["trace_ids"] = [item.trace_id for item in experiment.item_results]
            return summary
    finally:
        await shutdown_observer(observer)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--prompt-versions", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--dataset-name")
    parser.add_argument("--sync-dataset", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        cases, versions = load_inputs(args.dataset, args.prompt_versions)
        if (
            args.concurrency < 1
            or not math.isfinite(args.temperature)
            or not 0 <= args.temperature <= 2
            or (args.execute and not args.dataset_name)
        ):
            raise ValueError("INVALID_EXPERIMENT_ARGUMENTS")
        if args.sync_dataset and not args.execute:
            raise ValueError("SYNC_REQUIRES_EXECUTE")
        if not args.execute:
            print(json.dumps({"total": len(cases), "dry_run": True}))
            return 0
        result = asyncio.run(run_remote(args, cases, versions))
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["failed"] else 0
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
