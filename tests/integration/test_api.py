from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app

KEY = "test-only-api-key-with-32-characters"


@pytest.fixture
async def client():
    config = Settings(backend="memory", api_key=SecretStr(KEY), demo_enabled=True)
    app = create_app(config)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": KEY},
        ) as client,
    ):
        yield client


async def test_authenticated_api_baseline_and_event_pagination(client):
    run_id = str(uuid4())
    spec = {
        "run_id": run_id,
        "budget_tokens": 500,
        "context_window": 500,
        "model_id": "tokenos-simulator-v1",
        "policy_version": "baseline-v0",
    }
    response = await client.post("/v1/runs", json=spec)
    assert response.status_code == 201, response.text
    body = {"reservation_id": str(uuid4()), "prompt": "hello", "max_output_tokens": 50}
    result = await client.post(f"/v1/runs/{run_id}/baseline", json=body)
    assert result.status_code == 200, result.text
    usage = result.json()["usage"]
    assert usage["source"] == "simulated"
    run = (await client.get(f"/v1/runs/{run_id}")).json()
    assert run["spent_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert run["reserved_tokens"] == 0
    assert (await client.post(f"/v1/runs/{run_id}/baseline", json=body)).status_code == 409
    events = (await client.get(f"/v1/runs/{run_id}/events?after_version=1&limit=1")).json()
    assert len(events) == 1 and events[0]["version"] == 2


async def test_unauthorized_validation_and_not_found(client):
    assert (await client.get("/health", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await client.get(f"/v1/runs/{uuid4()}")).status_code == 404
    assert (await client.post("/v1/runs", json={"budget_tokens": -1})).status_code == 422


async def test_budget_rejection_before_execution(client):
    run_id = str(uuid4())
    await client.post(
        "/v1/runs",
        json={
            "run_id": run_id,
            "budget_tokens": 10,
            "context_window": 100,
            "model_id": "tokenos-simulator-v1",
            "policy_version": "v0",
        },
    )
    response = await client.post(
        f"/v1/runs/{run_id}/baseline",
        json={
            "reservation_id": str(uuid4()),
            "prompt": "hello",
            "max_output_tokens": 20,
        },
    )
    assert response.status_code == 422
    assert (await client.get(f"/v1/runs/{run_id}")).json()["spent_tokens"] == 0
