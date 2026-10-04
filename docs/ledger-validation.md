# Validation report

Recorded 16 September 2026. Runtime: CPython 3.13.15 on Linux. Dependencies are locked in `uv.lock`.

## Executed

| Check | Result |
|---|---|
| `uv sync --locked` dependency resolution/install | Successful Python 3.13 environment |
| `uv run pytest -q --junitxml=docs/test-results.xml` | **29 passed, 3 skipped** |
| `uv run mypy` | **No issues in 17 source files**, strict mode |
| `uv run ruff check src tests scripts` | Passed |
| In-process FastAPI → LangGraph → memory ledger demo | Passed; response explicitly marked simulated |
| OpenAPI schema generation | Generated 10 path templates in `docs/openapi.json` |
| Memory-ledger microbenchmark | 1,000 serial reserve+dispatch+settle cycles; timings in `microbenchmark.json` |

Unit tests cover concurrency admission, duplicate reservation/dispatch/settlement, conflicting payloads, context rejection, pre-send release, unknown usage, overrun accounting, transaction rollback, invalid token types/subsets, price calculation, graph execution, timeout, cancellation, LangChain normalization, unsupported cache writes, missing metadata and TPS semantics.

HTTP tests use the actual application lifespan, authentication, request validation, routes and graph. They run in process, not over a live network server.

## Demo result

The captured fixture began with a 1,000-token task budget. It reserved 163 simulated tokens for estimated input, safety margin and maximum output. It then settled **68 simulated tokens**, released the unused reservation and reported **932 available** with no outstanding hold.

The event sequence was `created → reserved → dispatched → settled`. The difference between reserved and consumed tokens is unused headroom, **not measured optimization savings**. The model returns a configured fixture string rather than answering the prompt.

## Not executed or established

- **3 PostgreSQL tests skipped** because `TOKENOS_TEST_DATABASE_URL` was not available. They cover independent-service admission, pool restart/deduplicated settlement and rollback. PostgreSQL was absent; package installation failed because required user/group operations were not permitted in the authoring environment.
- Docker image build, Compose startup and container restart were **not run** because Docker was unavailable.
- GitHub Actions workflow was supplied but **not run** on GitHub.
- No paid or free live LLM provider was invoked. The generic LangChain adapter was tested with controlled message fixtures.
- No provider-billing reconciliation, hard real-provider budget guarantee, task-success study or token-savings result has been established.
- The local memory timing is not a PostgreSQL, cloud or production throughput measurement.

## Remaining acceptance gates

1. Run all tests with the disposable PostgreSQL service configured; no PostgreSQL skips should remain.
2. Build/start Compose, exercise the HTTP demo, restart both services and read the prior run.
3. Integrate one fixed provider/model adapter with tested token estimation, output cap, disabled hidden retries and reliable usage.
4. Verify live successful, failed and timed-out requests against provider usage before running research benchmarks.

Deployment and research limitations are described in `architecture.md` and `research.md`. The implementation is a validated first-module foundation, not evidence that the complete TokenOS system is finished.
