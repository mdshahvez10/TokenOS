"""Atomic admission and settlement. Never hold a DB transaction during model I/O."""

from uuid import UUID

import structlog
from opentelemetry import trace

from tokenos.application.ports import LedgerRepository, LedgerTransaction
from tokenos.domain.models import (
    BudgetExceeded,
    Conflict,
    Event,
    NotFound,
    Reservation,
    ReservationSpec,
    ReservationState,
    Run,
    RunSpec,
    Usage,
)

log = structlog.get_logger()
tracer = trace.get_tracer(__name__)


def updated_run(run: Run, **changes: object) -> Run:
    return Run.model_validate({**run.model_dump(exclude={"available_tokens"}), **changes})


class BudgetLedger:
    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    async def create(self, spec: RunSpec) -> Run:
        return await self.repository.create(spec)

    async def read(self, run_id: UUID) -> Run:
        return await self.repository.read(run_id)

    async def _record(
        self,
        tx: LedgerTransaction,
        run: Run,
        reservation: Reservation,
        kind: str,
    ) -> None:
        event = Event.model_validate(
            {
                "run_id": run.spec.run_id,
                "reservation_id": reservation.spec.reservation_id,
                "version": run.version,
                "kind": kind,
                "payload": reservation.model_dump(mode="json"),
            }
        )
        await tx.save_run(run)
        await tx.save_reservation(reservation)
        await tx.append_event(event)

    async def reserve(self, run_id: UUID, spec: ReservationSpec) -> Reservation:
        with tracer.start_as_current_span("ledger.reserve"):
            async with self.repository.transaction(run_id) as tx:
                run = await tx.get_run()
                existing = await tx.get_reservation(spec.reservation_id)
                if existing:
                    if existing.spec != spec:
                        raise Conflict("reservation id was reused with different parameters")
                    return existing
                if run.breached:
                    raise BudgetExceeded("run breached its budget; further calls are blocked")
                if spec.hold_tokens > run.spec.context_window:
                    raise BudgetExceeded("request reservation exceeds the model context window")
                if spec.hold_tokens > run.available_tokens:
                    raise BudgetExceeded("insufficient unreserved task budget")
                reservation = Reservation(run_id=run_id, spec=spec)
                run = updated_run(
                    run,
                    reserved_tokens=run.reserved_tokens + spec.hold_tokens,
                    version=run.version + 1,
                )
                await self._record(tx, run, reservation, "reserved")
            log.info("budget_reserved", run_id=str(run_id), tokens=spec.hold_tokens)
            return reservation

    async def dispatch(self, run_id: UUID, reservation_id: UUID) -> Reservation:
        """Claim once. Repeated claims cannot authorize another model invocation."""
        return await self._transition(run_id, reservation_id, ReservationState.DISPATCHED)

    async def unknown(self, run_id: UUID, reservation_id: UUID) -> Reservation:
        """Provider may have consumed tokens. Keep the full hold until reconciliation."""
        return await self._transition(run_id, reservation_id, ReservationState.UNKNOWN)

    async def release(self, run_id: UUID, reservation_id: UUID) -> Reservation:
        """Only a call that has not been dispatched can be safely released."""
        return await self._transition(run_id, reservation_id, ReservationState.RELEASED)

    async def _transition(
        self,
        run_id: UUID,
        reservation_id: UUID,
        target: ReservationState,
    ) -> Reservation:
        async with self.repository.transaction(run_id) as tx:
            run = await tx.get_run()
            current = await tx.get_reservation(reservation_id)
            if current is None:
                raise NotFound("reservation not found")
            if current.state == target and target != ReservationState.DISPATCHED:
                return current
            allowed = {
                ReservationState.DISPATCHED: {ReservationState.RESERVED},
                ReservationState.UNKNOWN: {ReservationState.DISPATCHED},
                ReservationState.RELEASED: {ReservationState.RESERVED},
            }
            if current.state not in allowed[target]:
                raise Conflict(f"cannot move {current.state} to {target}")
            # An earlier underestimation may have exhausted an already-reserved run.
            if target == ReservationState.DISPATCHED and run.breached:
                raise BudgetExceeded("run breached its budget before dispatch")
            reservation = current.model_copy(update={"state": target})
            released = current.spec.hold_tokens if target == ReservationState.RELEASED else 0
            run = updated_run(
                run, reserved_tokens=run.reserved_tokens - released, version=run.version + 1
            )
            await self._record(tx, run, reservation, target.value)
            return reservation

    async def settle(self, run_id: UUID, reservation_id: UUID, usage: Usage) -> Reservation:
        with tracer.start_as_current_span("ledger.settle"):
            async with self.repository.transaction(run_id) as tx:
                run = await tx.get_run()
                current = await tx.get_reservation(reservation_id)
                if current is None:
                    raise NotFound("reservation not found")
                if current.state == ReservationState.SETTLED:
                    if current.usage != usage:
                        raise Conflict("settlement already exists with different usage")
                    return current
                if current.state not in {ReservationState.DISPATCHED, ReservationState.UNKNOWN}:
                    raise Conflict("only dispatched or unknown calls can be settled")
                spent = run.spent_tokens + usage.total
                held = run.reserved_tokens - current.spec.hold_tokens
                cost = usage.cost(run.spec.rates)
                run = updated_run(
                    run,
                    spent_tokens=spent,
                    reserved_tokens=held,
                    input_tokens=run.input_tokens + usage.input_tokens,
                    output_tokens=run.output_tokens + usage.output_tokens,
                    cached_input_tokens=run.cached_input_tokens + usage.cached_input_tokens,
                    reasoning_tokens=run.reasoning_tokens + usage.reasoning_tokens,
                    cost=None if cost is None else (run.cost or 0) + cost,
                    breached=run.breached or spent + held > run.spec.budget_tokens,
                    version=run.version + 1,
                )
                reservation = current.model_copy(
                    update={
                        "state": ReservationState.SETTLED,
                        "usage": usage,
                        "estimate_exceeded": (
                            usage.input_tokens
                            > current.spec.components.total + current.spec.safety_tokens
                            or usage.output_tokens > current.spec.max_output_tokens
                        ),
                    }
                )
                await self._record(tx, run, reservation, "settled")
            log.info(
                "budget_settled",
                run_id=str(run_id),
                tokens=usage.total,
                breached=run.breached,
                source=usage.source,
            )
            return reservation
