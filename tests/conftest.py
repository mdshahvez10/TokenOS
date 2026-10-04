from uuid import uuid4

import pytest

from tokenos.application.ledger import BudgetLedger
from tokenos.domain.models import Components, ReservationSpec, RunSpec
from tokenos.infrastructure.memory import MemoryLedgerRepository


@pytest.fixture
def spec():
    return RunSpec(
        run_id=uuid4(),
        budget_tokens=1000,
        context_window=500,
        model_id="test-model",
        policy_version="test-v1",
    )


@pytest.fixture
async def ledger(spec):
    service = BudgetLedger(MemoryLedgerRepository())
    await service.create(spec)
    return service


@pytest.fixture
def reservation():
    return ReservationSpec(
        reservation_id=uuid4(),
        request_digest="a" * 64,
        components=Components(user=100),
        max_output_tokens=50,
        safety_tokens=10,
        purpose="agent",
    )
