"""Never use a production database. Each test owns a unique isolated schema."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from tokenos.application.ledger import BudgetLedger
from tokenos.domain.models import BudgetExceeded, Usage
from tokenos.infrastructure.postgres import PostgresLedgerRepository

pytestmark = pytest.mark.postgres


@pytest.fixture
async def database():
    dsn = os.getenv("TOKENOS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TOKENOS_TEST_DATABASE_URL not configured")
    schema = "tokenos_test_" + uuid4().hex
    connection = await asyncpg.connect(dsn)
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}"')
    sql = Path(__file__).parents[2] / "migrations/001_ledger.sql"
    await connection.execute(sql.read_text())
    pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=8, server_settings={"search_path": schema}
    )
    try:
        yield pool, dsn, schema
    finally:
        await pool.close()
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


async def test_concurrent_workers_admit_atomically(database, spec, reservation):
    pool, _, _ = database
    first = BudgetLedger(PostgresLedgerRepository(pool))
    second = BudgetLedger(PostgresLedgerRepository(pool))
    await first.create(spec)
    results = await asyncio.gather(
        *(
            (first if i % 2 else second).reserve(
                spec.run_id, reservation.model_copy(update={"reservation_id": uuid4()})
            )
            for i in range(40)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(x, Exception) for x in results) == 6
    assert sum(isinstance(x, BudgetExceeded) for x in results) == 34
    assert (await first.read(spec.run_id)).reserved_tokens == 960


async def test_persists_across_pool_restart_and_settles_once(database, spec, reservation):
    pool, dsn, schema = database
    ledger = BudgetLedger(PostgresLedgerRepository(pool))
    await ledger.create(spec)
    await ledger.reserve(spec.run_id, reservation)
    await ledger.dispatch(spec.run_id, reservation.reservation_id)
    await pool.close()
    replacement = await asyncpg.create_pool(
        dsn, min_size=1, max_size=2, server_settings={"search_path": schema}
    )
    try:
        restarted = BudgetLedger(PostgresLedgerRepository(replacement))
        assert (await restarted.read(spec.run_id)).reserved_tokens == 160
        usage = Usage(input_tokens=100, output_tokens=20)
        await asyncio.gather(
            *(restarted.settle(spec.run_id, reservation.reservation_id, usage) for _ in range(10))
        )
        assert (await restarted.read(spec.run_id)).spent_tokens == 120
    finally:
        await replacement.close()


async def test_sql_transaction_rollback(database, spec):
    pool, _, _ = database
    ledger = BudgetLedger(PostgresLedgerRepository(pool))
    before = await ledger.create(spec)
    with pytest.raises(RuntimeError):
        async with ledger.repository.transaction(spec.run_id) as tx:
            await tx.save_run(before.model_copy(update={"spent_tokens": 800}))
            raise RuntimeError("rollback")
    assert await ledger.read(spec.run_id) == before
