"""Exercise the actual FastAPI -> LangGraph -> ledger path using simulated usage."""

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from pydantic import SecretStr

from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app


async def run(client):
    run_id = str(uuid4())
    response = await client.post(
        "/v1/runs",
        json={
            "run_id": run_id,
            "budget_tokens": 1000,
            "context_window": 500,
            "model_id": "tokenos-simulator-v1",
            "policy_version": "baseline-v0",
        },
    )
    response.raise_for_status()
    before = response.json()
    response = await client.post(
        f"/v1/runs/{run_id}/baseline",
        json={
            "reservation_id": str(uuid4()),
            "prompt": "Explain a token budget.",
            "max_output_tokens": 100,
        },
    )
    response.raise_for_status()
    result = response.json()
    after = await client.get(f"/v1/runs/{run_id}")
    events = await client.get(f"/v1/runs/{run_id}/events")
    after.raise_for_status()
    events.raise_for_status()
    return {
        "notice": "SIMULATED usage; this is not a token-savings experiment",
        "before": before,
        "result": result,
        "after": after.json(),
        "events": events.json(),
    }


async def main(args):
    if args.in_process:
        key = secrets.token_urlsafe(32)
        app = create_app(Settings(backend="memory", api_key=SecretStr(key), demo_enabled=True))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://tokenos",
                headers={"X-API-Key": key},
            ) as client,
        ):
            report = await run(client)
    else:
        load_dotenv()
        async with httpx.AsyncClient(
            base_url=args.url, headers={"X-API-Key": os.environ["TOKENOS_API_KEY"]}
        ) as client:
            report = await run(client)
    output = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--output")
    asyncio.run(main(parser.parse_args()))
