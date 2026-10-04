"""Evaluation uses actual reported totals, includes failures, and excludes unknown usage."""

from statistics import mean
from typing import Literal

from pydantic import Field

from tokenos.domain.models import Tokens, Value


class Attempt(Value):
    task_id: str
    success: bool
    total_tokens: Tokens | None  # None means incomplete provider accounting, not zero.
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    source: Literal["provider", "simulated"]


class Evaluation(Value):
    attempts: int
    successes: int
    success_rate: float
    tokens_per_success: float | None
    accounting_complete: bool
    mean_latency_ms: float
    source: Literal["provider", "simulated"]


def evaluate(attempts: list[Attempt]) -> Evaluation:
    if not attempts:
        raise ValueError("at least one evaluated task attempt is required")
    sources = {attempt.source for attempt in attempts}
    if len(sources) != 1:
        raise ValueError("simulated and provider results must be evaluated separately")
    # One row per task/trial. Internal model retries belong inside that row's total.
    if len({attempt.task_id for attempt in attempts}) != len(attempts):
        raise ValueError("task/trial IDs must be unique; aggregate internal retries first")
    successes = sum(attempt.success for attempt in attempts)
    complete = all(attempt.total_tokens is not None for attempt in attempts)
    total = sum(attempt.total_tokens or 0 for attempt in attempts)
    return Evaluation(
        attempts=len(attempts),
        successes=successes,
        success_rate=successes / len(attempts),
        tokens_per_success=total / successes if successes and complete else None,
        accounting_complete=complete,
        mean_latency_ms=mean(attempt.latency_ms for attempt in attempts),
        source=attempts[0].source,
    )
