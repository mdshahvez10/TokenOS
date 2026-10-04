"""Reserve -> claim -> invoke -> settle. Each provider attempt needs its own reservation."""

import asyncio
import hashlib
from typing import Protocol
from uuid import UUID

import structlog

from tokenos.application.ledger import BudgetLedger
from tokenos.domain.models import Components, Conflict, ReservationSpec, Usage, Value


class ModelResult(Value):
    text: str
    usage: Usage


class ModelPort(Protocol):
    model_id: str

    async def estimate(self, prompt: str) -> Components: ...
    async def invoke(self, prompt: str, max_output_tokens: int) -> ModelResult: ...


class InstrumentedCall:
    def __init__(
        self,
        ledger: BudgetLedger,
        model: ModelPort,
        safety_tokens: int,
        timeout_seconds: float,
    ) -> None:
        self.ledger = ledger
        self.model = model
        self.safety_tokens = safety_tokens
        self.timeout_seconds = timeout_seconds

    async def execute(
        self,
        run_id: UUID,
        reservation_id: UUID,
        prompt: str,
        max_output_tokens: int,
        attribution: Components | None = None,
    ) -> ModelResult:
        run = await self.ledger.read(run_id)
        if run.spec.model_id != self.model.model_id:
            raise Conflict("run model does not match the configured model adapter")
        components = await self.model.estimate(prompt)
        if attribution is not None:
            if attribution.total != components.total:
                raise Conflict("component attribution must sum to input estimate")
            components = attribution
        await self.ledger.reserve(
            run_id,
            ReservationSpec(
                reservation_id=reservation_id,
                request_digest=hashlib.sha256(prompt.encode()).hexdigest(),
                components=components,
                max_output_tokens=max_output_tokens,
                safety_tokens=self.safety_tokens,
                purpose="agent" if attribution is not None else "baseline",
            ),
        )
        await self.ledger.dispatch(run_id, reservation_id)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.model.invoke(prompt, max_output_tokens)
            await self.ledger.settle(run_id, reservation_id, result.usage)
            return result
        except (Exception, asyncio.CancelledError):
            # Even if this write fails or process death prevents it, DISPATCHED holds budget.
            try:
                await self.ledger.unknown(run_id, reservation_id)
            except Exception as reconciliation_error:
                structlog.get_logger().error(
                    "usage_reconciliation_required",
                    run_id=str(run_id),
                    reservation_id=str(reservation_id),
                    error_type=type(reconciliation_error).__name__,
                )
            raise
