import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from tokenos.application.ledger import BudgetLedger
from tokenos.infrastructure.postgres import PostgresLedgerRepository
from tokenos.runtime.contracts import Document, Policy, TaskRequest
from tokenos.runtime.engine import AgentRuntime
from tokenos.runtime.providers import SandboxAgentModel
from tokenos.runtime.seed import seed
from tokenos.runtime.storage import PostgresCorpus, PostgresRecords
from tokenos.runtime.tools import MCPGateway

pytestmark = pytest.mark.postgres


@pytest.fixture
async def pg_runtime():
    dsn = os.getenv("TOKENOS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TOKENOS_TEST_DATABASE_URL not configured")
    schema = "runtime_test_" + uuid4().hex
    connection = await asyncpg.connect(dsn)
    await connection.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}", public')
    for path in sorted(Path("migrations").glob("*.sql")):
        await connection.execute(path.read_text())
    pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=4, server_settings={"search_path": schema + ",public"}
    )
    try:
        runtime = AgentRuntime(
            BudgetLedger(PostgresLedgerRepository(pool)),
            PostgresRecords(pool),
            PostgresCorpus(pool),
            SandboxAgentModel(),
            MCPGateway({}, 5),
            Policy(),
            "simulated",
            32,
            30,
            4,
        )
        await seed(runtime, Path("config/sandbox.json"))
        yield runtime
    finally:
        await pool.close()
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


async def test_postgres_full_task(pg_runtime):
    result = await pg_runtime.run(
        TaskRequest(query="Create return for order ORD100 using return policy")
    )
    assert result.status == "completed"
    assert await pg_runtime.records.get("returns", f"{result.request.task_id}:ORD100")


async def test_postgres_replace_document(pg_runtime):
    await pg_runtime.rag.ingest(
        Document(document_id="return-policy", title="New policy", text="Returns within 5 days.")
    )
    chunks = await pg_runtime.corpus.search("return policy", 20)
    assert chunks and all("30 days" not in chunk.text for chunk in chunks)
