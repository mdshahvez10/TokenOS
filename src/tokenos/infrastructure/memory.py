"""Single-process development adapter with rollback; not a durable deployment backend."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from tokenos.application.ports import LedgerTransaction
from tokenos.domain.models import Conflict, Event, NotFound, Reservation, Run, RunSpec


class MemoryTransaction:
    def __init__(self, run: Run, reservations: dict[UUID, Reservation]) -> None:
        self.run = run
        self.reservations = dict(reservations)
        self.pending: list[Event] = []

    async def get_run(self) -> Run:
        return self.run

    async def save_run(self, run: Run) -> None:
        self.run = run

    async def get_reservation(self, reservation_id: UUID) -> Reservation | None:
        return self.reservations.get(reservation_id)

    async def save_reservation(self, reservation: Reservation) -> None:
        self.reservations[reservation.spec.reservation_id] = reservation

    async def append_event(self, event: Event) -> None:
        self.pending.append(event)


class MemoryLedgerRepository:
    def __init__(self) -> None:
        self._runs: dict[UUID, Run] = {}
        self._reservations: dict[UUID, dict[UUID, Reservation]] = {}
        self._events: dict[UUID, list[Event]] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _lock(self, run_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    async def create(self, spec: RunSpec) -> Run:
        async with self._lock(spec.run_id):
            if existing := self._runs.get(spec.run_id):
                if existing.spec != spec:
                    raise Conflict("run id was reused with different parameters")
                return existing
            run = Run(spec=spec, cost=Decimal(0) if spec.rates else None)
            self._runs[spec.run_id] = run
            self._reservations[spec.run_id] = {}
            self._events[spec.run_id] = [
                Event(
                    run_id=spec.run_id,
                    version=0,
                    kind="created",
                    payload=spec.model_dump(mode="json"),
                )
            ]
            return run

    async def read(self, run_id: UUID) -> Run:
        if run_id not in self._runs:
            raise NotFound("run not found")
        return self._runs[run_id]

    @asynccontextmanager
    async def transaction(self, run_id: UUID) -> AsyncIterator[LedgerTransaction]:
        async with self._lock(run_id):
            tx = MemoryTransaction(await self.read(run_id), self._reservations[run_id])
            yield tx
            self._runs[run_id] = tx.run
            self._reservations[run_id] = tx.reservations
            self._events[run_id].extend(tx.pending)

    async def events(self, run_id: UUID, after: int, limit: int) -> AsyncIterator[Event]:
        await self.read(run_id)
        snapshot = [event for event in self._events[run_id] if event.version > after][:limit]
        for event in snapshot:
            yield event
