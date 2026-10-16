import asyncio
from types import SimpleNamespace

import pytest

from app.agents.institution_review.nodes.clause_review import create_clause_review_node
from app.agents.institution_review.schemas import Clause
from app.core.errors import AppError


def state(*numbers):
    return {"title": "草稿", "clauses": [Clause(sequence=i, content=str(i)) for i in numbers]}


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

        node = create_clause_review_node(
            fake_model_factory(), SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(limit),
        )
        task = asyncio.create_task(node(state(1, 2, 3, 4)))
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

        node = create_clause_review_node(
            fake_model_factory(), SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        tasks = [asyncio.create_task(node(state(1, 2))), asyncio.create_task(node(state(3, 4)))]
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

        node = create_clause_review_node(
            fake_model_factory(), SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        result = await node(state(1, 2))
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

        node = create_clause_review_node(
            fake_model_factory(), SimpleNamespace(retrieve=retrieve),
            semaphore=asyncio.Semaphore(2),
        )
        first = asyncio.create_task(node(state(1, 2)))
        assert {await started.get(), await started.get()} == {1, 2}
        other = asyncio.create_task(node(state(3, 4)))
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
        assert len((await node(state(5, 6)))["clause_reviews"]) == 2
        assert active == set()
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_empty_retrieval_skips_model_and_passes(fake_model_factory):
    model = fake_model_factory()

    async def scenario():
        async def retrieve(*args, **kwargs):
            return []
        node = create_clause_review_node(
            model, SimpleNamespace(retrieve=retrieve), semaphore=asyncio.Semaphore(1),
        )
        result = await node(state(1))
        assert result["clause_reviews"][0].findings == []
        assert result["references"] == []
        assert model.calls == []
    asyncio.run(scenario())


def test_missing_rag_and_empty_clauses_return_app_errors(fake_model_factory):
    async def scenario():
        node = create_clause_review_node(
            fake_model_factory(), None, semaphore=asyncio.Semaphore(1),
        )
        with pytest.raises(AppError) as raised:
            await node(state(1))
        assert raised.value.code == "RAGFLOW_NOT_CONFIGURED"
        with pytest.raises(AppError) as raised:
            await node(state())
        assert raised.value.code == "REVIEW_CONTENT_EMPTY"
    asyncio.run(scenario())
