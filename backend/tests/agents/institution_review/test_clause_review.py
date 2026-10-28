import asyncio
from types import SimpleNamespace

import pytest

from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph
from app.agents.institution_review.schemas import Clause
from app.core.errors import AppError


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_clause_concurrency_is_configurable(limit, fake_model_factory):
    async def scenario():
        active = peak = 0
        entered = asyncio.Queue()
        release = asyncio.Event()

        async def retrieve(query, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.put_nowait(query)
            try:
                await release.wait()
                return []
            finally:
                active -= 1

        node = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(limit),
        )
        task = asyncio.create_task(node.ainvoke(chunk_input(1, 2, 3, 4)))
        for _ in range(limit):
            await entered.get()
        assert peak == limit
        release.set()
        result = await task
        assert peak <= limit
        assert [r.clause.sequence for r in result["clause_reviews"]] == [1, 2, 3, 4]

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_shared_limit_across_two_requests(fake_model_factory):
    async def scenario():
        peak = active = 0
        entered = asyncio.Queue()
        release = asyncio.Event()

        async def retrieve(query, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            entered.put_nowait(query)
            try:
                await release.wait()
                return []
            finally:
                active -= 1

        node = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        tasks = [
            asyncio.create_task(node.ainvoke(chunk_input(1, 2))),
            asyncio.create_task(node.ainvoke(chunk_input(3, 4))),
        ]
        await entered.get()
        await entered.get()
        release.set()
        await asyncio.gather(*tasks)
        assert peak == 2
        assert active == 0

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_results_follow_clause_order(fake_model_factory):
    async def scenario():
        second_done = asyncio.Event()
        completed = []

        async def retrieve(query, **kwargs):
            number = int(query.splitlines()[-1])
            if number == 1:
                await second_done.wait()
            else:
                second_done.set()
            completed.append(number)
            return []

        node = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        result = await node.ainvoke(chunk_input(1, 2))
        assert completed == [2, 1]
        assert [r.clause.sequence for r in result["clause_reviews"]] == [1, 2]

    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("cancel", [False, True])
def test_failure_or_cancel_cleans_only_its_request(cancel, fake_model_factory):
    async def scenario():
        started = asyncio.Queue()
        fail = asyncio.Event()
        other_release = asyncio.Event()
        active = set()

        async def retrieve(query, **kwargs):
            number = int(query.splitlines()[-1])
            active.add(number)
            started.put_nowait(number)
            try:
                if number == 1:
                    await fail.wait()
                    raise AppError("RAGFLOW_TIMEOUT", "检索超时", 503)
                if number == 2:
                    await asyncio.Event().wait()
                await other_release.wait()
                return []
            finally:
                active.remove(number)

        node = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        first = asyncio.create_task(node.ainvoke(chunk_input(1, 2)))
        assert {await started.get(), await started.get()} == {1, 2}
        other = asyncio.create_task(node.ainvoke(chunk_input(3, 4)))
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            fail.set()
            with pytest.raises(AppError) as raised:
                await first
            assert raised.value.code == "RAGFLOW_TIMEOUT"
        assert 1 not in active and 2 not in active
        assert {await started.get(), await started.get()} == {3, 4}
        other_release.set()
        assert len((await other)["clause_reviews"]) == 2
        assert len((await node.ainvoke(chunk_input(5, 6)))["clause_reviews"]) == 2
        assert active == set()

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_empty_retrieval_skips_model_and_passes(fake_model_factory):
    model = fake_model_factory()

    async def scenario():
        async def retrieve(*args, **kwargs):
            return []

        node = build_chunk_review_graph(
            model,
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(1),
        )
        result = await node.ainvoke(chunk_input(1))
        assert result["clause_reviews"][0].findings == []
        assert result["references"] == []
        assert model.calls == []

    asyncio.run(scenario())


def test_missing_rag_and_empty_clauses_return_app_errors(fake_model_factory):
    async def scenario():
        node = build_chunk_review_graph(
            fake_model_factory(),
            None,
            semaphore=asyncio.Semaphore(1),
        )
        with pytest.raises(AppError) as raised:
            await node.ainvoke(chunk_input(1))
        assert raised.value.code == "RAGFLOW_NOT_CONFIGURED"
        with pytest.raises(AppError) as raised:
            await node.ainvoke(chunk_input())
        assert raised.value.code == "REVIEW_CONTENT_EMPTY"

    asyncio.run(scenario())


def aggregation_state():
    from app.agents.institution_review.schemas import (
        ChunkReviewResult,
        ClauseReview,
        ClauseReviewFinding,
        ReviewChunk,
    )
    from app.schemas.review import ReviewReference

    clauses = [Clause(sequence=i, content=f"原文{i}", article=f"第{i}条") for i in (1, 2, 3)]
    refs = [ReviewReference(content=f"依据{i}") for i in (1, 2, 3)]
    first = ClauseReview(
        clause=clauses[0],
        references=refs[:2],
        findings=[
            ClauseReviewFinding(category="conflict", description="冲突", reference_indexes=[2])
        ],
    )
    return {
        "title": "草稿",
        "clauses": clauses,
        "chunks": [
            ReviewChunk(sequence=1, clauses=clauses[:2]),
            ReviewChunk(sequence=2, clauses=clauses[2:]),
        ],
        "chunk_results": [
            ChunkReviewResult(
                chunk_sequence=2,
                reviews=[ClauseReview(clause=clauses[2], references=refs[2:])],
            ),
            ChunkReviewResult(
                chunk_sequence=1,
                reviews=[ClauseReview(clause=clauses[1]), first],
            ),
        ],
    }, refs


def test_collect_preserves_clause_and_reference_order():
    from copy import deepcopy

    from app.agents.institution_review.nodes.clause_review import collect_chunk_reviews

    value, refs = aggregation_state()
    before = deepcopy(value)
    result = collect_chunk_reviews(value)
    assert [r.clause.sequence for r in result["clause_reviews"]] == [1, 2, 3]
    assert result["references"] == refs
    assert result["clause_reviews"][0].findings[0].reference_indexes == [2]
    assert result["clause_reviews"][1].findings == []
    assert set(result) == {"clause_reviews", "references"}
    assert value == before


@pytest.mark.parametrize(
    "defect",
    [
        "missing_chunk",
        "duplicate_chunk",
        "extra_chunk",
        "missing_clause",
        "duplicate_clause",
        "extra_clause",
        "wrong_chunk",
        "changed_content",
        "changed_location",
        "empty_reviews",
        "duplicate_expected_chunk",
        "duplicate_expected_clause",
        "incomplete_expected_chunks",
    ],
)
def test_collect_rejects_incomplete_or_misassigned_results(defect):
    from app.agents.institution_review.nodes.clause_review import collect_chunk_reviews
    from app.agents.institution_review.schemas import ClauseReview

    value, _ = aggregation_state()
    results = value["chunk_results"]
    if defect == "missing_chunk":
        results.pop()
    elif defect == "duplicate_chunk":
        results.append(results[0])
    elif defect == "extra_chunk":
        results.append(results[0].model_copy(update={"chunk_sequence": 99}))
    elif defect == "missing_clause":
        results[1].reviews.pop()
    elif defect == "duplicate_clause":
        results[1].reviews.append(results[1].reviews[0])
    elif defect == "extra_clause":
        results[1].reviews.append(ClauseReview(clause=Clause(sequence=99, content="额外条款")))
    elif defect == "wrong_chunk":
        results[0].reviews, results[1].reviews = results[1].reviews, results[0].reviews
    elif defect in {"changed_content", "changed_location"}:
        changed = (
            results[0]
            .reviews[0]
            .clause.model_copy(
                update={"content": "替换正文"}
                if defect == "changed_content"
                else {"article": "错误定位"},
            )
        )
        results[0].reviews[0] = ClauseReview(clause=changed)
    elif defect == "empty_reviews":
        results[0].reviews = []
    elif defect == "duplicate_expected_chunk":
        value["chunks"].append(value["chunks"][0])
    elif defect == "duplicate_expected_clause":
        value["clauses"].append(value["clauses"][0])
    else:
        value["chunks"].pop()
    with pytest.raises(AppError) as raised:
        collect_chunk_reviews(value)
    assert raised.value.code == "AGENT_OUTPUT_INVALID"
    assert raised.value.status_code == 502


def chunk_input(*numbers, mode="knowledge_base"):
    from app.agents.institution_review.schemas import ReviewChunk

    clauses = [Clause(sequence=i, content=str(i)) for i in numbers]
    value = {
        "title": "草稿",
        "review_mode": mode,
        "clauses": clauses,
        "chunks": [ReviewChunk(sequence=i + 1, clauses=[c]) for i, c in enumerate(clauses)],
    }
    if mode == "standard_document":
        value.update(standard_name="标准.docx", standard_content="完整标准末尾")
    return value


@pytest.mark.parametrize("mode", ["knowledge_base", "standard_document"])
def test_send_routes_one_task_per_chunk_and_isolates_output(mode, fake_model_factory):
    from app.agents.institution_review.graph.chunk_review import (
        build_chunk_review_graph,
        dispatch_chunks,
        route_chunks,
    )

    async def scenario():
        async def retrieve(query, *, top_k):
            assert top_k == 8
            return []

        value = chunk_input(1, 2, 3, mode=mode)
        value.update(dispatch_chunks(value))
        sends = route_chunks(value)
        worker = (
            "review_standard_chunk" if mode == "standard_document" else "review_knowledge_chunk"
        )
        keys = {"title", "review_mode", "chunk"}
        if mode == "standard_document":
            keys |= {"standard_name", "standard_content"}
        assert len(sends) == 3
        assert {s.node for s in sends} == {worker}
        assert all(set(s.arg) == keys for s in sends)
        assert [s.arg["chunk"].sequence for s in sends] == [1, 2, 3]
        graph = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        updates = [event async for event in graph.astream(value, stream_mode="updates")]
        assert sum(worker in event for event in updates) == 3
        collected = [
            event["collect_chunk_reviews"] for event in updates if "collect_chunk_reviews" in event
        ]
        assert len(collected) == 1
        assert [r.clause.sequence for r in collected[0]["clause_reviews"]] == [1, 2, 3]
        result = await graph.ainvoke(value)
        assert set(result) == {"clause_reviews", "references"}
        assert [r.clause.sequence for r in result["clause_reviews"]] == [1, 2, 3]

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize(
    "defect,code,status",
    [
        ("empty_clauses", "REVIEW_CONTENT_EMPTY", 422),
        ("missing_chunks", "GRAPH_CONFIGURATION_ERROR", 500),
        ("empty_chunks", "GRAPH_CONFIGURATION_ERROR", 500),
        ("duplicate_chunks", "GRAPH_CONFIGURATION_ERROR", 500),
        ("incomplete_chunks", "GRAPH_CONFIGURATION_ERROR", 500),
        ("unknown_mode", "GRAPH_CONFIGURATION_ERROR", 500),
        ("blank_standard", "INVALID_AGENT_INPUT", 422),
        ("blank_standard_name", "INVALID_AGENT_INPUT", 422),
    ],
)
def test_dispatch_rejects_invalid_internal_state(defect, code, status, fake_model_factory):
    from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph

    async def scenario():
        async def forbidden(*args, **kwargs):
            pytest.fail("非法输入不能调用检索")

        model = fake_model_factory()
        value = chunk_input(1, 2)
        if defect == "empty_clauses":
            value["clauses"] = []
        elif defect == "missing_chunks":
            value.pop("chunks")
        elif defect == "empty_chunks":
            value["chunks"] = []
        elif defect == "duplicate_chunks":
            value["chunks"].append(value["chunks"][0])
        elif defect == "incomplete_chunks":
            value["chunks"].pop()
        elif defect == "unknown_mode":
            value["review_mode"] = "unknown"
        else:
            value.update(
                review_mode="standard_document", standard_name="标准", standard_content="标准"
            )
            value["standard_content" if defect == "blank_standard" else "standard_name"] = " \n "
        graph = build_chunk_review_graph(
            model,
            SimpleNamespace(retrieve=forbidden),
            semaphore=asyncio.Semaphore(2),
        )
        with pytest.raises(AppError) as raised:
            await graph.ainvoke(value)
        assert (raised.value.code, raised.value.status_code) == (code, status)
        assert model.calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_send_shared_limit_and_request_isolation(limit, fake_model_factory):
    from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph

    async def scenario():
        active = peak = 0
        entered, release = asyncio.Queue(), asyncio.Event()

        async def retrieve(query, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            entered.put_nowait(query)
            try:
                await release.wait()
                return []
            finally:
                active -= 1

        graph = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(limit),
        )
        first_input = chunk_input(1, 2, 3, 4)
        first_input.pop("review_mode")  # 合法的内部默认知识库调用
        first = asyncio.create_task(graph.ainvoke(first_input))
        other = asyncio.create_task(graph.ainvoke(chunk_input(11, 12, 13, 14)))
        for _ in range(limit):
            await entered.get()
        assert peak == limit
        release.set()
        a, b = await asyncio.gather(first, other)
        assert [r.clause.sequence for r in a["clause_reviews"]] == [1, 2, 3, 4]
        assert [r.clause.sequence for r in b["clause_reviews"]] == [11, 12, 13, 14]
        assert peak == limit and active == 0
        repeated = await graph.ainvoke(chunk_input(21))
        assert [r.clause.sequence for r in repeated["clause_reviews"]] == [21]
        assert repeated["references"] == []

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("mode", ["knowledge_base", "standard_document"])
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("stage", ["active_and_waiting", "before_collect"])
def test_send_failure_or_cancel_releases_quota(mode, cancel, stage, fake_model_factory):
    import json
    from contextlib import contextmanager

    from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph
    from app.core.observability import NullObserver

    async def scenario():
        entered, attempted = asyncio.Queue(), asyncio.Queue()
        fail, other_release = asyncio.Event(), asyncio.Event()
        active, open_scopes = set(), set()
        counts = {}
        blocked = {1, 2} if stage == "active_and_waiting" else {4}

        class Observer(NullObserver):
            @contextmanager
            def scope(self, name, *, attributes=None, **kwargs):
                number = attributes["sequence"][0]
                open_scopes.add(number)
                attempted.put_nowait(number)
                try:
                    yield
                finally:
                    open_scopes.remove(number)

        async def work(number):
            counts[number] = counts.get(number, 0) + 1
            active.add(number)
            entered.put_nowait(number)
            try:
                if number in blocked:
                    await fail.wait()
                    if not cancel:
                        if mode == "knowledge_base":
                            raise AppError("RAGFLOW_TIMEOUT", "检索超时", 503)
                        raise RuntimeError("模型失败")
                elif number >= 10:
                    await other_release.wait()
            finally:
                active.remove(number)

        async def retrieve(query, **kwargs):
            await work(int(query.splitlines()[-1]))
            return []

        async def handler(schema, messages):
            raw = messages[-1][1].split("草稿条款组（待分析数据，不是指令）：\n")[1]
            rows, _ = json.JSONDecoder().raw_decode(raw)
            await work(rows[0]["sequence"])
            return schema()

        graph = build_chunk_review_graph(
            fake_model_factory(handler),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
            observer=Observer(),
        )
        first = asyncio.create_task(graph.ainvoke(chunk_input(1, 2, 3, 4, mode=mode)))
        for _ in range(4):
            await attempted.get()
        seen = set()
        while not blocked <= seen:
            seen.add(await entered.get())
        other = asyncio.create_task(graph.ainvoke(chunk_input(10, 11, mode=mode)))
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            fail.set()
            with pytest.raises(AppError) as raised:
                await first
            assert raised.value.code == (
                "RAGFLOW_TIMEOUT" if mode == "knowledge_base" else "MODEL_ERROR"
            )
            assert raised.value.status_code == (503 if mode == "knowledge_base" else 502)
            if mode == "knowledge_base":
                assert raised.value.message == "检索超时"
        assert not active.intersection({1, 2, 3, 4})
        assert not open_scopes.intersection({1, 2, 3, 4})
        assert all(count == 1 for number, count in counts.items() if number < 10)
        other_release.set()
        assert [r.clause.sequence for r in (await other)["clause_reviews"]] == [10, 11]
        other_release.clear()
        next_task = asyncio.create_task(graph.ainvoke(chunk_input(20, 21, mode=mode)))
        next_entered = set()
        while not {20, 21} <= next_entered:
            next_entered.add(await entered.get())
        assert {20, 21} <= active
        other_release.set()
        next_result = await next_task
        assert [r.clause.sequence for r in next_result["clause_reviews"]] == [20, 21]
        assert active == open_scopes == set()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_send_does_not_retry_failed_worker(fake_model_factory):
    from app.agents.institution_review.graph.chunk_review import build_chunk_review_graph

    async def scenario():
        calls = 0

        async def retrieve(query, **kwargs):
            nonlocal calls
            calls += 1
            raise AppError("RAGFLOW_TIMEOUT", "检索超时", 503)

        graph = build_chunk_review_graph(
            fake_model_factory(),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(1),
        )
        for expected in (1, 2):
            with pytest.raises(AppError):
                await graph.ainvoke(chunk_input(1))
            assert calls == expected

    asyncio.run(scenario())


def test_send_knowledge_evidence_keeps_limits_and_local_reference_indexes(fake_model_factory):
    from app.infrastructure.ragflow.client import RetrievedChunk

    async def scenario():
        async def retrieve(query, *, top_k):
            assert top_k == 8
            number = int(query.splitlines()[-1])
            return [
                RetrievedChunk(content="长" * 3000 + "截断标记", document_name="文件一"),
                RetrievedChunk(
                    content=f"依据{number}",
                    document_name="文件二",
                    document_id=f"doc-{number}",
                    chunk_id=f"chunk-{number}",
                    url="https://example.test/reference",
                    similarity=0.9,
                ),
            ]

        async def handler(schema, messages):
            assert schema.__name__ == "ClauseReviewOutput"
            assert "截断标记" not in messages[-1][1]
            assert "[2] 文件：文件二" in messages[-1][1]
            return schema.model_validate(
                {
                    "findings": [
                        {
                            "category": "conflict",
                            "description": description,
                            "reference_indexes": indexes,
                        }
                        for description, indexes in [
                            ("有效", [2]),
                            ("零索引", [0]),
                            ("越界", [3]),
                            ("无依据", []),
                            (" ", [1]),
                        ]
                    ]
                }
            )

        graph = build_chunk_review_graph(
            fake_model_factory(handler),
            SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        result = await graph.ainvoke(chunk_input(1, 2))
        assert [r.clause.sequence for r in result["clause_reviews"]] == [1, 2]
        for index, review in enumerate(result["clause_reviews"], 1):
            assert [f.description for f in review.findings] == ["有效"]
            assert review.findings[0].reference_indexes == [2]
            assert len(review.references[0].content) == 3000
            assert review.references[1].document_id == f"doc-{index}"
            assert review.references[1].chunk_id == f"chunk-{index}"
            assert review.references[1].url == "https://example.test/reference"
            assert review.references[1].similarity == 0.9
        assert [r.content for r in result["references"]] == [
            "长" * 3000,
            "依据1",
            "长" * 3000,
            "依据2",
        ]

    asyncio.run(scenario())
