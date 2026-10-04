"""Per-run row locking across workers. Short transactions contain only ledger operations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

import asyncpg

from tokenos.application.ports import LedgerTransaction
from tokenos.domain.models import Conflict, Event, NotFound, Reservation, Run, RunSpec


class PostgresTransaction:
    def __init__(
        self,
        connection: asyncpg.Connection | asyncpg.pool.PoolConnectionProxy,
        run_id: UUID,
    ) -> None:
        self.connection = connection
        self.run_id = run_id

    async def get_run(self) -> Run:
        value = await self.connection.fetchval(
            "SELECT snapshot FROM tokenos_runs WHERE run_id=$1",
            self.run_id,
        )
        if value is None:
            raise NotFound("run not found")
        return Run.model_validate_json(value)

    async def save_run(self, run: Run) -> None:
        await self.connection.execute(
            """UPDATE tokenos_runs SET spent_tokens=$2,reserved_tokens=$3,version=$4,
            snapshot=$5::jsonb,updated_at=now() WHERE run_id=$1""",
            self.run_id,
            run.spent_tokens,
            run.reserved_tokens,
            run.version,
            run.model_dump_json(exclude={"available_tokens"}),
        )

    async def get_reservation(self, reservation_id: UUID) -> Reservation | None:
        value = await self.connection.fetchval(
            "SELECT snapshot FROM tokenos_reservations WHERE run_id=$1 AND reservation_id=$2",
            self.run_id,
            reservation_id,
        )
        return None if value is None else Reservation.model_validate_json(value)

    async def save_reservation(self, reservation: Reservation) -> None:
        await self.connection.execute(
            """INSERT INTO tokenos_reservations(run_id,reservation_id,state,snapshot)
            VALUES ($1,$2,$3,$4::jsonb) ON CONFLICT (run_id,reservation_id)
            DO UPDATE SET state=EXCLUDED.state,snapshot=EXCLUDED.snapshot,updated_at=now()""",
            self.run_id,
            reservation.spec.reservation_id,
            reservation.state.value,
            reservation.model_dump_json(),
        )

    async def append_event(self, event: Event) -> None:
        await self.connection.execute(
            """INSERT INTO tokenos_events
            (event_id,run_id,reservation_id,version,kind,occurred_at,payload)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
            event.event_id,
            event.run_id,
            event.reservation_id,
            event.version,
            event.kind,
            event.at,
            event.model_dump_json(),
        )


class PostgresLedgerRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(self, spec: RunSpec) -> Run:
        run = Run(spec=spec, cost=Decimal(0) if spec.rates else None)
        async with self.pool.acquire() as connection, connection.transaction():
            inserted = await connection.fetchval(
                """INSERT INTO tokenos_runs(run_id,spec,budget_tokens,snapshot)
                VALUES ($1,$2::jsonb,$3,$4::jsonb)
                ON CONFLICT (run_id) DO NOTHING RETURNING run_id""",
                spec.run_id,
                spec.model_dump_json(),
                spec.budget_tokens,
                run.model_dump_json(exclude={"available_tokens"}),
            )
            tx = PostgresTransaction(connection, spec.run_id)
            if inserted:
                await tx.append_event(
                    Event(
                        run_id=spec.run_id,
                        version=0,
                        kind="created",
                        payload=spec.model_dump(mode="json"),
                    )
                )
            existing = await tx.get_run()
            if existing.spec != spec:
                raise Conflict("run id was reused with different parameters")
            return existing

    async def read(self, run_id: UUID) -> Run:
        async with self.pool.acquire() as connection:
            return await PostgresTransaction(connection, run_id).get_run()

    @asynccontextmanager
    async def transaction(self, run_id: UUID) -> AsyncIterator[LedgerTransaction]:
        async with self.pool.acquire() as connection, connection.transaction():
            found = await connection.fetchval(
                "SELECT run_id FROM tokenos_runs WHERE run_id=$1 FOR UPDATE",
                run_id,
            )
            if found is None:
                raise NotFound("run not found")
            yield PostgresTransaction(connection, run_id)

    async def events(self, run_id: UUID, after: int, limit: int) -> AsyncIterator[Event]:
        await self.read(run_id)
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT payload FROM tokenos_events WHERE run_id=$1 AND version>$2
                ORDER BY version LIMIT $3""",
                run_id,
                after,
                limit,
            )
        for row in rows:
            yield Event.model_validate_json(row["payload"])
