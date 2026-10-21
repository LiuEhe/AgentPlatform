import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace


def test_failure_is_counted_and_other_samples_continue():
    from scripts.run_langfuse_experiments import run_cases

    class Runtime:
        async def invoke(self, agent_id, payload):
            if payload.get("fail"):
                raise ValueError("controlled")
            return SimpleNamespace(invocation_id="i", output="ok")

    class Resolver:
        @asynccontextmanager
        async def session(self, **kwargs):
            yield

    cases = [
        {"id": str(i), "agent_id": "institution_review", "input": {"fail": i == 1}, "expected": {}}
        for i in range(3)
    ]
    result = asyncio.run(run_cases(cases, runtime=Runtime(), resolver=Resolver(), versions={}))
    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert len(result["items"]) == 3


def test_dry_run_has_no_network_or_model_calls(monkeypatch, capsys):
    from scripts.run_langfuse_experiments import main

    monkeypatch.setattr(
        "httpx.Client.request",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("unexpected network"),
        ),
    )
    code = main(
        [
            "--dataset",
            "tests/fixtures/langfuse/conversation_cases.json",
            "--prompt-versions",
            "tests/fixtures/langfuse/prompt_versions.example.json",
            "--run-name",
            "dry",
            "--dry-run",
        ]
    )
    assert code == 0
    assert '"total": 6' in capsys.readouterr().out


def test_sdk_item_failure_cannot_disappear_from_denominator():
    from scripts.run_langfuse_experiments import reconcile_results

    cases = [{"id": "a", "expected": {}}, {"id": "b", "expected": {}}]
    result = reconcile_results(cases, [], SimpleNamespace(item_results=[]))
    assert result["total"] == result["failed"] == 2
    assert result["succeeded"] == 0


def test_evaluator_failure_cannot_be_reported_as_success():
    from scripts.run_langfuse_experiments import reconcile_results

    case = {"id": "a", "expected": {"child_called": False}}
    item = {"id": "a", "status": "succeeded", "scores": []}
    experiment = SimpleNamespace(
        item_results=[
            SimpleNamespace(
                item=SimpleNamespace(input=case),
                evaluations=[],
            )
        ]
    )
    result = reconcile_results([case], [item], experiment)
    assert result["failed"] == 1
    assert result["items"][0]["error_type"] == "EXPERIMENT_EVALUATION_INCOMPLETE"


def test_all_tasks_use_one_loop_and_one_graph_build(monkeypatch, fake_model_factory):
    from contextvars import ContextVar

    from app.core.config import Settings
    from app.core.observability import NullObserver
    from scripts import run_langfuse_experiments as module
    from scripts.sync_langfuse_prompts import prompt_specs

    marker = ContextVar("sdk-test-marker", default=None)
    loops, markers, builds = [], [], []
    specs = {spec.name: spec for spec in prompt_specs()}

    async def model_handler(schema, messages):
        loops.append(id(asyncio.get_running_loop()))
        markers.append(marker.get())
        return {"intent": "general_chat", "action": "answer"} if schema else "ok"

    cases = [
        {
            "id": str(i),
            "agent_id": "conversation_assistant",
            "input": {
                "latest_message_id": "m",
                "messages": [{"id": "m", "role": "user", "content": "hi"}],
            },
            "expected": {"child_called": False},
        }
        for i in range(2)
    ]

    class Dataset:
        def run_experiment(self, *, task, evaluators, **kwargs):
            results = []
            for case in cases:
                token = marker.set("sdk-context")
                try:
                    item = SimpleNamespace(input=case)
                    output = task(item=item)
                    results.append(
                        SimpleNamespace(
                            item=item,
                            output=output,
                            evaluations=evaluators[0](output=output),
                            trace_id="trace",
                        )
                    )
                finally:
                    marker.reset(token)
            return SimpleNamespace(item_results=results, experiment_url="http://local/experiment")

    class Observer(NullObserver):
        client = SimpleNamespace(
            get_prompt=lambda name, **kwargs: SimpleNamespace(
                version=1, get_langchain_prompt=lambda: specs[name].messages
            )
        )

        def graph_config(self, context):
            return {}

    original = module.build_agent_registry

    def build(*args, **kwargs):
        builds.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        module, "Settings", lambda: Settings(_env_file=None, llm_model="test", llm_api_key="test")
    )
    monkeypatch.setattr(module, "create_observer", lambda _: Observer())
    monkeypatch.setattr(module, "create_llm_service", lambda _: fake_model_factory(model_handler))
    monkeypatch.setattr(module, "build_agent_registry", build)
    monkeypatch.setattr(module, "ensure_dataset", lambda *a, **kw: Dataset())
    result = asyncio.run(
        module.run_remote(
            SimpleNamespace(
                dataset_name="test",
                sync_dataset=False,
                run_name="test",
                concurrency=1,
                temperature=0,
            ),
            cases,
            {name: 1 for name in specs},
        )
    )
    assert result["total"] == result["succeeded"] == 2
    assert result["failed"] == 0
    assert len(set(loops)) == 1 and builds == [1]
    assert markers == ["sdk-context"] * 4


def test_dataset_sync_requires_explicit_flag_and_preserves_existing_items():
    from uuid import NAMESPACE_URL, uuid5

    import pytest

    from scripts.run_langfuse_experiments import ensure_dataset

    case = {"id": "one", "input": {}, "expected": {}}
    identifier = str(uuid5(NAMESPACE_URL, "dataset:one"))

    class Client:
        def get_dataset(self, name):
            return SimpleNamespace(items=[])

        def create_dataset_item(self, **kwargs):
            raise AssertionError("must not write")

    with pytest.raises(ValueError, match="DATASET_ITEM_MISSING"):
        ensure_dataset(Client(), name="dataset", cases=[case], sync=False)
    client = Client()
    client.get_dataset = lambda name: SimpleNamespace(
        items=[SimpleNamespace(id=identifier, input={"different": True}, expected_output={})]
    )
    with pytest.raises(ValueError, match="DATASET_CONTENT_CONFLICT"):
        ensure_dataset(client, name="dataset", cases=[case], sync=True)
