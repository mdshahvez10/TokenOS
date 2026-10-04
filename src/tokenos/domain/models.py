"""Validated values. No dependency on the orchestration, HTTP or persistence framework."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Tokens = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
PositiveTokens = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LedgerError(Exception):
    """Expected application error, safe to expose without database/provider details."""


class NotFound(LedgerError):
    pass


class Conflict(LedgerError):
    pass


class BudgetExceeded(LedgerError):
    pass


class UsageUnavailable(LedgerError):
    pass


class Components(Value):
    """Mutually exclusive estimated input attribution, including otherwise hidden overhead."""

    system: Tokens = 0
    context_memory: Tokens = 0
    rag: Tokens = 0
    tool_schemas: Tokens = 0
    tool_results: Tokens = 0
    trajectory: Tokens = 0
    user: Tokens = 0
    overhead: Tokens = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in type(self).model_fields)


class Rates(Value):
    """Currency units per million tokens. Frozen into each run for reproducible cost."""

    currency: str = Field(min_length=3, max_length=3)
    version: str = Field(min_length=1, max_length=200)
    input_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_per_million: Decimal = Field(ge=0, allow_inf_nan=False)


class Usage(Value):
    input_tokens: Tokens
    output_tokens: Tokens
    cached_input_tokens: Tokens = 0
    reasoning_tokens: Tokens = 0
    source: Literal["provider", "simulated"] = "provider"

    @model_validator(mode="after")
    def validate_subsets(self) -> "Usage":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input must be a subset of input tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning must be a subset of output tokens")
        if self.total > 2**63 - 1:
            raise ValueError("total usage exceeds ledger integer capacity")
        return self

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost(self, rates: Rates | None) -> Decimal | None:
        if rates is None:
            return None
        return (
            (self.input_tokens - self.cached_input_tokens) * rates.input_per_million
            + self.cached_input_tokens * rates.cached_input_per_million
            + self.output_tokens * rates.output_per_million
        ) / Decimal(1_000_000)


class RunSpec(Value):
    run_id: UUID
    budget_tokens: PositiveTokens
    context_window: PositiveTokens
    model_id: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=200)
    rates: Rates | None = None


class Run(Value):
    spec: RunSpec
    spent_tokens: Tokens = 0
    reserved_tokens: Tokens = 0
    input_tokens: Tokens = 0
    output_tokens: Tokens = 0
    cached_input_tokens: Tokens = 0
    reasoning_tokens: Tokens = 0
    cost: Decimal | None = None
    breached: bool = False
    version: Tokens = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_tokens(self) -> int:
        return max(0, self.spec.budget_tokens - self.spent_tokens - self.reserved_tokens)


class ReservationSpec(Value):
    reservation_id: UUID
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    components: Components
    max_output_tokens: PositiveTokens
    safety_tokens: Tokens
    purpose: Literal["baseline", "controller", "summarizer", "agent", "verifier"]

    @model_validator(mode="after")
    def validate_capacity(self) -> "ReservationSpec":
        if self.hold_tokens > 2**63 - 1:
            raise ValueError("reservation exceeds ledger integer capacity")
        return self

    @property
    def hold_tokens(self) -> int:
        return self.components.total + self.safety_tokens + self.max_output_tokens


class ReservationState(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"
    SETTLED = "settled"
    RELEASED = "released"


class Reservation(Value):
    run_id: UUID
    spec: ReservationSpec
    state: ReservationState = ReservationState.RESERVED
    usage: Usage | None = None
    estimate_exceeded: bool = False


class Event(Value):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    reservation_id: UUID | None = None
    version: Tokens
    kind: Literal["created", "reserved", "dispatched", "unknown", "settled", "released"]
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, object] = Field(default_factory=dict)
