import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from tokenos.application.execution import InstrumentedCall
from tokenos.domain.models import Conflict, UsageUnavailable
from tokenos.infrastructure.graph import build_baseline
from tokenos.infrastructure.models import LangChainModelAdapter, SimulatedModel


async def test_graph_baseline_accounts_and_does_not_reexecute(ledger, spec):
    model = SimulatedModel("test-model", "demo", 8)
    call = InstrumentedCall(ledger, model, safety_tokens=10, timeout_seconds=1)
    graph = build_baseline(call)
    state = {
        "run_id": spec.run_id,
        "reservation_id": uuid4(),
        "prompt": "hello",
        "max_output_tokens": 10,
    }
    result = await graph.ainvoke(state)
    assert result["result"].usage.source == "simulated"
    assert (await ledger.read(spec.run_id)).spent_tokens == 17
    with pytest.raises(Conflict):
        await graph.ainvoke(state)
    assert (await ledger.read(spec.run_id)).spent_tokens == 17


async def test_provider_timeout_keeps_budget_reserved(ledger, spec):
    model = SimulatedModel("test-model", "demo", 8)

    async def slow(*args):
        await asyncio.Event().wait()

    model.invoke = slow
    call = InstrumentedCall(ledger, model, safety_tokens=10, timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        await call.execute(spec.run_id, uuid4(), "hello", 10)
    run = await ledger.read(spec.run_id)
    assert run.spent_tokens == 0 and run.reserved_tokens == 33
    events = [e async for e in ledger.repository.events(spec.run_id, -1, 100)]
    assert events[-1].kind == "unknown"


async def test_cancellation_keeps_hold(ledger, spec):
    entered = asyncio.Event()
    model = SimulatedModel("test-model", "demo", 8)

    async def wait(*args):
        entered.set()
        await asyncio.Event().wait()

    model.invoke = wait
    call = InstrumentedCall(ledger, model, 10, 10)
    task = asyncio.create_task(call.execute(spec.run_id, uuid4(), "hi", 10))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ledger.read(spec.run_id)).reserved_tokens == 30


async def test_langchain_normalization_and_cap_factory():
    model = Mock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 20,
                "output_tokens": 8,
                "total_tokens": 28,
                "input_token_details": {"cache_read": 10},
                "output_token_details": {"reasoning": 3},
            },
        )
    )
    factory = Mock(return_value=model)
    adapter = LangChainModelAdapter("model", factory, len, 0)
    result = await adapter.invoke("hello", 50)
    factory.assert_called_once_with(50)
    assert result.usage.total == 28 and result.usage.reasoning_tokens == 3
    assert result.usage.cached_input_tokens == 10


async def test_missing_usage_is_not_reported_as_free():
    model = Mock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    adapter = LangChainModelAdapter("model", lambda cap: model, len, 0)
    with pytest.raises(UsageUnavailable):
        await adapter.invoke("hello", 20)


async def test_cache_write_requires_explicit_normalizer():
    model = Mock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 20,
                "output_tokens": 8,
                "total_tokens": 28,
                "input_token_details": {"cache_creation": 10},
            },
        )
    )
    adapter = LangChainModelAdapter("model", lambda cap: model, len, 0)
    with pytest.raises(UsageUnavailable, match="cache-write"):
        await adapter.invoke("hello", 20)
