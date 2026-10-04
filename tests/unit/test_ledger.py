import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tokenos.domain.models import (
    BudgetExceeded,
    Components,
    Conflict,
    Rates,
    Usage,
)


async def test_reserve_settle_and_repeated_settlement(ledger, spec, reservation):
    await ledger.reserve(spec.run_id, reservation)
    run = await ledger.read(spec.run_id)
    assert (run.reserved_tokens, run.available_tokens) == (160, 840)
    await ledger.dispatch(spec.run_id, reservation.reservation_id)
    usage = Usage(input_tokens=100, output_tokens=20)
    await ledger.settle(spec.run_id, reservation.reservation_id, usage)
    await ledger.settle(spec.run_id, reservation.reservation_id, usage)
    run = await ledger.read(spec.run_id)
    assert (run.spent_tokens, run.reserved_tokens, run.available_tokens) == (120, 0, 880)
    events = [e async for e in ledger.repository.events(spec.run_id, -1, 100)]
    assert [e.kind for e in events] == ["created", "reserved", "dispatched", "settled"]
    assert [e.version for e in events] == list(range(4))


async def test_conflicting_idempotency_payloads(ledger, spec, reservation):
    await ledger.reserve(spec.run_id, reservation)
    with pytest.raises(Conflict):
        await ledger.reserve(
            spec.run_id, reservation.model_copy(update={"request_digest": "b" * 64})
        )
    with pytest.raises(Conflict):
        await ledger.create(spec.model_copy(update={"budget_tokens": 2000}))
    assert (await ledger.read(spec.run_id)).reserved_tokens == 160


async def test_concurrent_admission_does_not_overspend(ledger, spec, reservation):
    requests = [reservation.model_copy(update={"reservation_id": uuid4()}) for _ in range(40)]
    results = await asyncio.gather(
        *(ledger.reserve(spec.run_id, req) for req in requests),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 6
    assert sum(isinstance(r, BudgetExceeded) for r in results) == 34
    assert (await ledger.read(spec.run_id)).reserved_tokens == 960


async def test_duplicate_parallel_reservations_charge_once(ledger, spec, reservation):
    await asyncio.gather(*(ledger.reserve(spec.run_id, reservation) for _ in range(30)))
    assert (await ledger.read(spec.run_id)).reserved_tokens == 160
    claims = await asyncio.gather(
        *(ledger.dispatch(spec.run_id, reservation.reservation_id) for _ in range(20)),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in claims) == 1


async def test_context_limit_and_task_limit_are_distinct(ledger, spec, reservation):
    with pytest.raises(BudgetExceeded, match="context"):
        await ledger.reserve(
            spec.run_id,
            reservation.model_copy(
                update={
                    "components": Components(user=450),
                }
            ),
        )
    await ledger.reserve(spec.run_id, reservation)
    assert (await ledger.read(spec.run_id)).reserved_tokens == 160


async def test_undispatched_release_is_idempotent(ledger, spec, reservation):
    await ledger.reserve(spec.run_id, reservation)
    await ledger.release(spec.run_id, reservation.reservation_id)
    await ledger.release(spec.run_id, reservation.reservation_id)
    assert (await ledger.read(spec.run_id)).available_tokens == 1000
    with pytest.raises(Conflict):
        await ledger.dispatch(spec.run_id, reservation.reservation_id)


async def test_unknown_usage_keeps_hold_and_can_reconcile(ledger, spec, reservation):
    await ledger.reserve(spec.run_id, reservation)
    await ledger.dispatch(spec.run_id, reservation.reservation_id)
    await ledger.unknown(spec.run_id, reservation.reservation_id)
    with pytest.raises(Conflict):
        await ledger.release(spec.run_id, reservation.reservation_id)
    assert (await ledger.read(spec.run_id)).reserved_tokens == 160
    await ledger.settle(
        spec.run_id, reservation.reservation_id, Usage(input_tokens=110, output_tokens=40)
    )
    assert (await ledger.read(spec.run_id)).spent_tokens == 150


async def test_overrun_is_recorded_and_future_dispatch_blocked(ledger, spec, reservation):
    later = reservation.model_copy(update={"reservation_id": uuid4()})
    await ledger.reserve(spec.run_id, reservation)
    await ledger.reserve(spec.run_id, later)
    await ledger.dispatch(spec.run_id, reservation.reservation_id)
    settled = await ledger.settle(
        spec.run_id, reservation.reservation_id, Usage(input_tokens=900, output_tokens=200)
    )
    assert settled.estimate_exceeded
    run = await ledger.read(spec.run_id)
    assert run.spent_tokens == 1100 and run.breached and run.available_tokens == 0
    with pytest.raises(BudgetExceeded):
        await ledger.dispatch(spec.run_id, later.reservation_id)
    await ledger.release(spec.run_id, later.reservation_id)
    assert (await ledger.read(spec.run_id)).reserved_tokens == 0


async def test_settlement_conflict_does_not_mutate(ledger, spec, reservation):
    await ledger.reserve(spec.run_id, reservation)
    with pytest.raises(Conflict):
        await ledger.settle(
            spec.run_id, reservation.reservation_id, Usage(input_tokens=1, output_tokens=1)
        )
    await ledger.dispatch(spec.run_id, reservation.reservation_id)
    await ledger.settle(
        spec.run_id, reservation.reservation_id, Usage(input_tokens=1, output_tokens=1)
    )
    with pytest.raises(Conflict):
        await ledger.settle(
            spec.run_id, reservation.reservation_id, Usage(input_tokens=2, output_tokens=1)
        )
    assert (await ledger.read(spec.run_id)).spent_tokens == 2


async def test_transaction_rolls_back_on_failure(ledger, spec):
    before = await ledger.read(spec.run_id)
    with pytest.raises(RuntimeError):
        async with ledger.repository.transaction(spec.run_id) as tx:
            await tx.save_run(before.model_copy(update={"spent_tokens": 999}))
            raise RuntimeError("simulated write failure")
    assert await ledger.read(spec.run_id) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"input_tokens": -1, "output_tokens": 0},
        {"input_tokens": True, "output_tokens": 0},
        {"input_tokens": "12", "output_tokens": 0},
        {"input_tokens": 1, "output_tokens": 1, "cached_input_tokens": 2},
        {"input_tokens": 1, "output_tokens": 1, "reasoning_tokens": 2},
    ],
)
def test_invalid_usage_rejected(fields):
    with pytest.raises(ValidationError):
        Usage(**fields)


def test_cost_and_subset_tokens_not_double_counted():
    usage = Usage(
        input_tokens=1000, cached_input_tokens=600, output_tokens=200, reasoning_tokens=100
    )
    rates = Rates(
        currency="USD",
        version="synthetic-test",
        input_per_million=Decimal("2"),
        cached_input_per_million=Decimal("0.5"),
        output_per_million=Decimal("8"),
    )
    assert usage.total == 1200
    assert usage.cost(rates) == Decimal("0.0027")
    assert usage.cost(None) is None
