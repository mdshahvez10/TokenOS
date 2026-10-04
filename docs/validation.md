# Release validation — 2026-09-16

Environment: Python 3.13.15. Dependencies resolved and locked in uv.lock and hash-locked requirements.lock.

Executed on this release:
- 47 pytest tests passed, 5 PostgreSQL tests skipped because TOKENOS_TEST_DATABASE_URL was not configured.
- Ruff check across src, tests, scripts and dashboard passed.
- Strict mypy across 27 source files passed.
- 27 sandbox benchmark task runs (9 cases x 3 policies) succeeded with no unresolved usage.
- Real MCP SDK initialize/list/call against an in-process ASGI server passed.
- Streamlit AppTest rendered all four tabs without exceptions.
- Local launcher started both API and Streamlit; authenticated runtime endpoint and UI health returned HTTP 200.
- Gemini adapter usage normalization and missing-usage behavior verified with mocked HTTP responses.

Included but NOT executed here: PostgreSQL/pgvector integration tests, Docker image/Compose startup, live Gemini calls, external MCP network deployment, multi-worker load, penetration testing and real-world success validation. The five database tests cover ledger concurrent admission/restart/invariants and runtime task/document persistence, but passing memory tests does not establish PostgreSQL correctness.

This is an integrated research MVP with production-oriented engineering, not certification that it is safe to expose publicly. The starter benchmark is deterministic and byte-counted. It does not establish actual LLM token savings. Historical ledger-only results remain in ledger-validation.md; this file supersedes them for the current release.
