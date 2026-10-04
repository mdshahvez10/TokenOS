# TokenOS
Adaptive context and computation allocation for token-efficient agents. Python 3.13 research MVP with production-oriented boundaries; not a production-certified service.

## Start locally
Install Python 3.13 and uv, then from this directory:
```bash
uv sync --locked
uv run python scripts/run_local.py
```
Open http://127.0.0.1:8501. The launcher generates a temporary API key shared by the dashboard and API. Default sandbox requires no paid model key. It uses memory storage, which resets on restart. API: http://127.0.0.1:8000/docs (enter the launcher key through your own environment when accessing protected API endpoints directly).

Try `Create a return for order ORD100 using the return policy.` Other fixtures: ORD101 is too old, ORD102 digital, ORD103 undelivered. Calculator tasks include `Calculate 12 + 7`.

## What is implemented
- Atomic token reservations, dispatch, settlement, unknown-outcome holds, idempotency and event history.
- LangGraph allocate → model → act loop with task budget, output reserve and step bounds.
- Adaptive weighted allocation across memory, RAG, schemas, tool results and trajectory; fixed/full baselines.
- Context deduplication, lexical ranking, recent-observation retention, raw artifact retrieval.
- Schema selection, argument validation, read caches, task-scoped idempotent sandbox writes.
- Chunked RAG, deterministic hashed lexical vectors, pgvector repository and corpus-version cache invalidation.
- Direct/ReAct routing, allowlisted read-only MCP gateway, Gemini REST adapter and LangChain adapter.
- FastAPI, Streamlit inspection dashboard, structured logging and OpenTelemetry spans.
- Paired benchmark CLI, success verification, TPS accounting, ablation switches and example results.
- Docker Compose, migrations, locked dependencies, unit/integration tests and CI.

## Run evaluation
```bash
uv run python scripts/benchmark.py --output benchmarks/results.json
uv run python scripts/benchmark.py --ablations --repetitions 3 --output benchmarks/ablations.json
uv run pytest -q
uv run ruff check src tests scripts dashboard
uv run mypy
```
TPS = all charged tokens, including failed tasks, divided by successful tasks. Unresolved usage makes TPS unavailable. Sandbox counters measure UTF-8 bytes, not actual LLM tokens. Included benchmark outcomes are functional evidence only; adaptive does not beat fixed on the starter suite.

## PostgreSQL + Docker
```bash
python scripts/init_env.py
docker compose up --build
```
Compose starts pgvector, applies ordered migrations, then API and dashboard. This package includes database tests and container definitions; see docs/validation.md for what was actually executed. Use disposable PostgreSQL for tests:
```bash
TOKENOS_TEST_DATABASE_URL=postgresql://... uv run pytest -m postgres
```

## Live Gemini
Set TOKENOS_RUNTIME_PROVIDER=gemini, TOKENOS_GEMINI_API_KEY and TOKENOS_GEMINI_MODEL to a model available to your account. Optional TOKENOS_MODEL_RATES is a JSON Rates object; prices remain null when unspecified. Start API/dashboard with these environment variables, or use `uv run python scripts/benchmark.py --provider gemini`. No live calls are made by default. Gemini response usage is authoritative; prompt byte counts are a conservative heuristic, not a guaranteed model-specific token bound. Reasoning is included once in output usage. Actual overages are recorded and stop subsequent admissions.

## MCP
Run `uv run python scripts/mcp_demo.py`. Configure TOKENOS_MCP_SERVERS='{"warehouse":"http://127.0.0.1:8001/mcp"}' before starting API, then discover `warehouse` in the dashboard. Only explicitly configured servers are contacted. External writes are blocked. Tools declaring readOnlyHint are trusted to honor it: only connect servers you control. The sandbox provider supports its local fixtures; arbitrary MCP tool reasoning requires a live model.

## Documentation
- docs/architecture.md — folders, class/sequence diagrams, schema, endpoints.
- docs/modules.md — ten module designs, implementation, tests, metrics and ablations.
- docs/research.md — hypotheses, benchmark interpretation and four-month plan.
- docs/operations.md — deployment boundaries, recovery and scaling.
- docs/validation.md — executed verification and remaining gates.
- docs/ledger-*.md — original ledger design and historical validation.

## Limits
Single trusted workspace/API key; no tenant isolation, RBAC, job queue or automatic interrupted-task resume. Completed tasks persist in PostgreSQL; an interrupted running task must be inspected, not blindly replayed. Raw artifacts contain user data. Cache expiry prevents reuse but does not purge rows. Exact vector scan and lexical hashes target a small research corpus. Bounded candidate limits make the full baseline bounded, too. Use deployment-specific authentication, quotas, retention, provider calibration and load/security testing before public production deployment.
