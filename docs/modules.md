# Module engineering and research specifications

All modules share the architecture/class/sequence diagrams and folder map in architecture.md. SQL migrations are executable schema; interfaces are injectable protocols; config/policy.json controls runtime heuristics. Research impacts below are hypotheses, not measured LLM claims.

## Token Controller
**Problem:** Static context caps ignore remaining budget and error history.

**Design and production code:** `src/tokenos/managers.TokenController + application.ledger` (dotted paths identify classes). Weighted score/cost selection pins required observations, reserves generation, adjusts RAG/error weights and reclaims unused quotas. Atomic ledger admission is separate from heuristic selection.

**Schema and API:** Run, reservation and event tables; /v1/runs and reservation endpoints.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Budget exhaustion, concurrent admission, exact settlement, unknown usage, category attribution. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Expected fewer prompt tokens vs full baseline; cost may fall with input usage. Sorting adds CPU; fewer paid calls matters more than sorting.

**Performance metrics:** TPS, success rate, overages, unresolved holds, allocation overhead.

**Ablation:** Freeze weights, disable reclaim, sweep budgets and compare fixed/full.

## Context Manager
**Problem:** Repeated and irrelevant history consumes context.

**Design and production code:** `src/tokenos/managers.ContextManager` (dotted paths identify classes). Exact deduplication and lexical relevance. Raw history is retained in artifacts. No paid summarizer.

**Schema and API:** records artifacts; history in POST /v1/tasks.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Duplicate and irrelevant history; Unicode; bounded history size. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Expected input reduction on repetitive history, lower input cost, small linear CPU overhead.

**Performance metrics:** Retained bytes, evidence recall, task success by history length.

**Ablation:** full_memory retains all duplicates; paired noisy and relevant histories.

## Trajectory Manager
**Problem:** Full trajectories repeat old results every turn.

**Design and production code:** `src/tokenos/managers.TrajectoryManager` (dotted paths identify classes). Keep recent structured results; older steps become artifact references; latest observation mandatory.

**Schema and API:** Task observations and raw artifacts; task/artifact GET endpoints.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Mandatory result overflow, artifact ownership, malformed actions, max-step termination. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Expected lower repeated input; retrieval of omitted details can add calls and latency.

**Performance metrics:** Tokens by step, recovery calls, task success after long tool sequences.

**Ablation:** full_trajectory retains complete earlier observations.

## Tool Manager
**Problem:** Large schema catalogs and unconstrained tool execution inflate context and risk duplicate effects.

**Design and production code:** `src/tokenos/managers.ToolManager + tools.ToolExecutor` (dotted paths identify classes). Lexical top-k schema ranking, JSON Schema validation, operation claims, read cache and independently validated sandbox returns.

**Schema and API:** records tools/tool_operations/returns; /v1/tools.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Ineligible returns, read-only request, duplicate task execution, invalid arguments. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Expected schema input reduction; cache reduces tool latency, schema misses can increase total calls.

**Performance metrics:** Schema bytes, tool recall, errors, duplicate effects, tool latency.

**Ablation:** all_tools supplies complete bounded catalog.

## RAG Manager
**Problem:** Static retrieval can supply redundant or irrelevant evidence.

**Design and production code:** `src/tokenos/managers.RAGManager + storage.Corpus implementations` (dotted paths identify classes). Chunk overlap, lexical hashed vectors, cosine ranking, relevance filtering, top-k cap and revision-keyed cache. No learned embeddings required.

**Schema and API:** documents/chunks vector(256); /v1/documents.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Corpus replacement invalidates cache; missing evidence; oversized document; PG replacement gate. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Expected input savings from selection; no embedding API cost, exact scan latency grows with corpus size.

**Performance metrics:** Evidence recall/precision, retrieved bytes, query latency, success with policy exceptions.

**Ablation:** fixed_rag removes relevance filtering; sweep k/chunk sizes; add semantic embeddings only later.

## Workflow Router
**Problem:** Every task need not pay a full tool loop.

**Design and production code:** `src/tokenos/managers.WorkflowRouter + engine.AgentRuntime` (dotted paths identify classes). Keyword direct/ReAct route; observations promote tool routing; max steps limits complexity. Both routes share graph and ledger.

**Schema and API:** Task decision records; POST /v1/tasks.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Calculator and return tasks; direct unknown queries; budget and step limits. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Potentially lower schema/context overhead on direct tasks; mistaken routing hurts success and latency.

**Performance metrics:** Route accuracy, calls per task, latency, success by difficulty.

**Ablation:** fixed_workflow always chooses ReAct. Evaluate broad held-out tasks before tuning keywords.

## MCP Gateway
**Problem:** External tool schemas and results need governed integration.

**Design and production code:** `src/tokenos/tools.MCPGateway` (dotted paths identify classes). Official async SDK, configured-server allowlist, namespace names, schema validation and external write denial. No automatic discovery on startup.

**Schema and API:** Tool registry; POST /v1/mcp/{server}/discover.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Real SDK over in-process ASGI tests initialize/list/call; unconfigured/write calls denied. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Gateway alone does not reduce tokens; enables tool selection. Discovery and connection handshakes add latency.

**Performance metrics:** Discovery latency, schema footprint, tool-call errors, result sizes.

**Ablation:** All schemas versus selected schemas with same server catalog; pool connections as later optimization.

## Telemetry Layer
**Problem:** Token savings claims fail without measured usage and failure visibility.

**Design and production code:** `src/tokenos/infrastructure.telemetry + ledger events` (dotted paths identify classes). Structured metadata logs, OpenTelemetry spans, provider/simulated source labels, optional versioned prices. Raw prompts stay out of logs.

**Schema and API:** Events and task model artifacts; /v1/runs/{id}/events.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Provider reasoning counted once; missing usage holds; repeated settlement and overages. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Small CPU/export overhead; no direct reduction, enables optimization and cost attribution.

**Performance metrics:** Input/output/cached/reasoning totals, cost, unresolved reservations, p50/p95 latency.

**Ablation:** Exporter off/on overhead study; never omit accounting as an efficiency shortcut.

## Cache Layer
**Problem:** Repeated retrieval and read tools waste work.

**Design and production code:** `src/tokenos/managers.Cache` (dotted paths identify classes). TTL cache in repository, corpus revision keys, task-scoped tool keys, schema-version keys. No response or semantic cache.

**Schema and API:** records cache namespace; no public mutation endpoint.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** TTL boundary, corpus replacement, no caching writes. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Primarily saves retrieval/tool latency; tool result still enters model context so token savings are not automatic.

**Performance metrics:** Hit ratio, stale-result rate, latency, cache storage growth.

**Ablation:** no_cache flag; compare warm and cold repeated-query cohorts separately.

## Evaluation Framework
**Problem:** Successful-looking answers can conceal missing side effects or uncharged failures.

**Design and production code:** `src/tokenos/runtime.benchmark + scripts/benchmark.py` (dotted paths identify classes). Paired shuffled schedule, common budgets and model, independent expected answer and persisted-return checks, all charged failure tokens in numerator.

**Schema and API:** Benchmark records/reports; /v1/benchmarks and CLI.

**Implementation steps:** validate inputs; inject repository/adapter; apply deterministic policy; persist decision/provenance; enforce ledger admission before calls; verify outcome through tests.

**Unit/integration coverage and edge cases:** Nine fixtures x three policies; benchmark success and unresolved usage assertions. Executed coverage is listed in validation.md; listed edge cases also guide further research testing.

**Token, cost and latency expectations:** Evaluation spends tokens for live runs; gives evidence of tradeoffs rather than claiming improvement by construction.

**Performance metrics:** TPS, success rate, cost/success, latency, calls, unresolved accounting.

**Ablation:** Five controller switches, separate cache cohorts, budget sweeps and paired task-level confidence intervals.
