import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from tokenos.domain.models import Conflict
from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app
from tokenos.runtime.benchmark import Case, evaluate
from tokenos.runtime.contracts import Document, TaskRequest


@pytest.fixture
async def runtime_app():
    app = create_app(
        Settings(backend="memory", api_key=SecretStr("test-key-for-runtime-00000000000000"))
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.mark.parametrize("mode", ["full", "fixed", "adaptive"])
async def test_success_and_attribution(runtime_app, mode):
    runtime = runtime_app.state.runtime
    request = TaskRequest(query="Create return for order ORD100 using return policy", mode=mode)
    result = await runtime.run(request)
    assert result.status == "completed", result
    assert await runtime.records.get("returns", f"{request.task_id}:ORD100")
    ledger = await runtime.ledger.read(request.task_id)
    assert ledger.spent_tokens > 0 and ledger.reserved_tokens == 0
    assert ledger.spent_tokens <= request.budget_tokens
    assert len(result.decisions) == 3
    repeated = await runtime.run(request)
    assert repeated == result
    assert await runtime.ledger.read(request.task_id) == ledger


@pytest.mark.parametrize("order_id", ["ORD101", "ORD102", "ORD103"])
async def test_ineligible(runtime_app, order_id):
    runtime = runtime_app.state.runtime
    result = await runtime.run(
        TaskRequest(query=f"Create return for order {order_id} using return policy")
    )
    assert result.status == "completed"
    assert "eligible=False" in result.answer
    assert not await runtime.records.get("returns", f"{result.request.task_id}:{order_id}")


async def test_read_only_and_budget(runtime_app):
    runtime = runtime_app.state.runtime
    result = await runtime.run(
        TaskRequest(query="Check return policy for ORD100. Do not submit anything.")
    )
    assert "eligible=True" in result.answer
    assert not await runtime.records.get("returns", f"{result.request.task_id}:ORD100")
    result = await runtime.run(
        TaskRequest(query="Create return for order ORD100", budget_tokens=10)
    )
    assert result.status == "budget_exhausted"
    assert (await runtime.ledger.read(result.request.task_id)).spent_tokens == 0


async def test_claim_conflict(runtime_app):
    runtime = runtime_app.state.runtime
    request = TaskRequest(query="Calculate 12 + 7")
    results = await asyncio.gather(
        runtime.run(request), runtime.run(request), return_exceptions=True
    )
    assert sum(isinstance(x, Conflict) for x in results) == 1


async def test_rag_revision_invalidates_cache(runtime_app):
    runtime = runtime_app.state.runtime
    _, hit = await runtime.rag.retrieve("return policy", True, False)
    assert not hit
    _, hit = await runtime.rag.retrieve("return policy", True, False)
    assert hit
    await runtime.rag.ingest(
        Document(document_id="return-policy", title="Updated", text="Return policy within 5 days.")
    )
    docs, hit = await runtime.rag.retrieve("return policy", True, False)
    assert not hit and all("30 days" not in doc.text for doc in docs)


async def test_http_task_and_auth(runtime_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app), base_url="http://test"
    ) as client:
        assert (await client.get("/v1/runtime")).status_code == 401
        client.headers["X-API-Key"] = "test-key-for-runtime-00000000000000"
        response = await client.post("/v1/tasks", json={"query": "Calculate 12 + 7"})
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "19.0"
        task_id = response.json()["request"]["task_id"]
        assert (await client.get(f"/v1/tasks/{task_id}")).status_code == 200
        assert (await client.get(f"/v1/tasks/{uuid4()}/artifacts/history")).status_code == 404


async def test_benchmark(runtime_app):
    cases = [Case.model_validate(x) for x in json.loads(Path("benchmarks/cases.json").read_text())]
    report = await evaluate(runtime_app.state.runtime, cases, 1, 100000, 42)
    assert len(report["rows"]) == 27
    assert all(row["success"] for row in report["rows"]), report["summary"]
    assert all(row["unresolved"] == 0 for row in report["rows"])
