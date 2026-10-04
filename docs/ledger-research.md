# Research plan — accounting and budget admission

## Research role

The ledger makes adaptive allocation measurable and enforceable. It does not select useful memories, retrieve better evidence or compress prompts. Its research value is accurate accounting, a shared resource constraint and reproducible intervention points for later policies.

The central eventual question remains: **Does adaptive allocation outperform the strongest fixed-allocation baseline under comparable reliability constraints?** Building this ledger alone does not answer it.

## Expected effects, not measured savings

| Outcome | Expectation for this module | How to verify |
|---|---|---|
| Token reduction | No intrinsic compression benefit. Admission can prevent excess calls; lower token usage may also mean premature failure. | Compare all-task token usage and task success together. |
| Cost | Can avoid unadmitted calls. Adds database/telemetry infrastructure cost. Cache reads change price, not logical token totals. | Measure actual usage at frozen rates plus separate runtime infrastructure cost. |
| Latency | Adds estimation, reservation, dispatch and settlement work. Can shorten paths only by stopping work. | Paired end-to-end latency plus controller/ledger/provider spans. |
| Reliability | Prevents quota races and duplicate accounting. Conservative unresolved holds can stop otherwise affordable work. | Inject duplicate requests, cancellation, timeouts and delayed usage callbacks. |

No percentage token/cost/latency saving is claimed. The local simulator and memory microbenchmark verify mechanics only.

## Primary metric

For a fixed benchmark with one row per task/trial:

`TPS = total tokens consumed across every task/trial / number of successful task/trials`

Numerator includes failed tasks, retries, routing, summarization, verification and all other model calls within each task/trial. Denominator counts successful task/trials, not successful individual model calls. Repeated trials receive unique IDs. Do not count both individual retries and the encompassing task row.

If no task succeeds, TPS is undefined (represented as `null` by this module). If any attempt has unresolved usage, complete TPS is unavailable. Report the accounting coverage; do not silently omit unknown attempts or assign them zero.

Example: a successful task consumes 100 tokens and a failed task consumes 300. TPS is 400, not 100. Success rate is 50%. Both figures are needed to interpret efficiency.

`application/evaluation.py` implements these aggregation rules. It does not determine task success: the benchmark supplies success using an independent oracle. It rejects datasets mixing simulated and provider token sources.

## Metrics

| Group | Metric |
|---|---|
| Task outcome | Deterministic task success; failure taxonomy; repeated-trial success variance |
| Efficiency | TPS; total input/output; per-task median and p95; calls and retries per task |
| Accounting | Settled-call coverage; unresolved reservation age/count; duplicate settlement rate |
| Budget enforcement | Admission oversubscription count; estimate-overrun frequency; budget breach frequency and size |
| Estimation | Actual minus estimated input; absolute and relative error by model/task family |
| Cost | Known billed-cost estimate per task/success; rate/model revision; cache-read token proportion |
| Latency | End-to-end p50/p95/p99; ledger transaction latency; input-estimation time; pool queue time |
| Runtime | DB rows/events per task; event storage growth; ledger CPU time and memory |

Provider usage is authoritative for supported normalized totals. Prices are supplied snapshots, so the computed number is a price-based estimate rather than an invoice reconciliation. Multimodal/cache-write/batch discounts need provider-specific support before economic claims.

Component shares are estimated attribution. Compare their sum with actual input usage and retain the discrepancy; do not scale estimated shares and label them measured ground truth.

## Initial experiments

### Experiment A: accounting correctness

Use deterministic fixtures with known input/output counts and inject duplicate settlements, concurrent admission, provider timeouts, missing metadata, retry attempts and process restarts.

Pass criteria:

- No duplicate charge for the same settled reservation.
- No pre-admission overcommit when predictions are within reserved bounds.
- Unresolved calls never silently regain quota.
- Actual overrun is visible even when it exceeds the original budget.
- Event versions and snapshots agree after committed transitions.

Distinguish admission correctness from provider-budget adherence: unknown remote usage cannot be strictly bounded by a heuristic token estimate.

### Experiment B: runtime overhead

Compare the same baseline with pass-through execution, passive accounting and enforced accounting. Use identical prompts, provider/model snapshot, maximum output, concurrency and evaluation tasks. Disable provider SDK retries or instrument them explicitly.

First run local fixtures to isolate ledger cost. Then run PostgreSQL with concurrency levels such as 1, 8 and 32 and separate same-run contention from independent-run throughput. Finally measure a small real-provider pilot. Record all benchmark parameters as configuration rather than treating these example levels as universal constants.

### Experiment C: reliability under a budget

Sweep task budgets using a held-out task family. Report success-versus-token and success-versus-cost curves, including quota rejection as a task failure where appropriate. A hard cap that stops every task is not an optimization success.

Use deterministic oracles where possible: exact numeric outputs, expected API call arguments or expected sandbox database state. Reserve human/LLM judging for genuinely open-ended outputs and track judge cost separately from agent TPS.

## Ablation design

| Variant | What changes | Question answered |
|---|---|---|
| Passive accounting | Record actual usage after every call, without budget admission | What overhead does enforcement add? |
| Fixed admission | Same ledger with one fixed task budget and fixed output cap | What does quota enforcement alone achieve? |
| No safety margin | Set admission margin to zero | How much headroom is needed for estimator error? |
| Margin sweep | Tune margin on development data, then freeze | Which setting balances utilization and breaches? |
| No ledger locking, fixture only | Controlled unsafe experimental adapter, never production | Does concurrent oversubscription occur without serialization? |
| Future fixed component quotas | Same ledger, deterministic fixed allocation | Baseline for the adaptive controller |
| Future adaptive allocation | Same ledger and managers, state-dependent reallocation | Does coordination improve the efficiency/reliability frontier? |

The first release does not ship the unsafe no-lock adapter or claim these experiments have run. All production comparisons must retain accurate measurement; “without a ledger” means without admission policy, not without measuring tokens.

For the full project compare full-context, tuned fixed-budget, independently optimized managers and joint adaptive allocation. Add leave-one-manager-out ablations only after each manager is implemented. Use the same overall budget when testing allocation quality.

## Experimental protocol

1. Partition by task template/family into development and held-out test sets before tuning.
2. Freeze policies, model revision, prompts, tool registry and RAG corpus for each comparison.
3. Run a pilot to estimate outcome variability and API cost; choose task counts and repetitions from that evidence and the semester budget.
4. Run paired task/trials across policies with randomized execution order to reduce temporal/cache bias.
5. Separate cold and warm cache experiments. Report both logical tokens and price-based costs.
6. Include failure and retry consumption. Report unknown-usage coverage and investigate incomplete runs.
7. Bootstrap paired task-level results for confidence intervals; preserve task clustering for repeated trials.
8. Report paired success differences with uncertainty and a predeclared acceptable success-loss margin.
9. Plot Pareto tradeoffs rather than optimizing a single aggregate while hiding task failures.

A candidate target such as 30% lower TPS with no more than 2 percentage points of success loss is a hypothesis to test, not a promised result. Confirm a feasible non-inferiority design after the pilot. Do not repeatedly tune against the held-out set.

## Provenance

This module stores run/model/policy identifiers, rate versions, timestamps, request hashes, usage source, lifecycle and events. Before paper experiments, add an experiment manifest covering: git commit, benchmark version, task/trial IDs, provider model snapshot, prompt template version, sampling configuration, counter version, tool/RAG corpus versions, cache condition and evaluator version. Archive raw provider usage under an explicitly reviewed retention/redaction policy.

Graph state and a simulator trace are not substitutes for a reproducible benchmark manifest. The attached report's prior-work numbers should be independently checked against the original papers when writing related work.

## Four-month positioning

- Weeks 1–2: validate this foundation against PostgreSQL and one provider; establish the baseline and task oracle.
- Weeks 3–6: tool selection and RAG admission with component estimates and source references.
- Weeks 7–9: context/trajectory retention, rehydration and controlled workflow routing.
- Weeks 10–11: deterministic joint controller and budget reallocation.
- Weeks 12–14: held-out evaluations, reliability tests and component ablations.
- Weeks 15–16: dashboard, thesis/paper, reproducible release and viva demonstration.

A learned policy is optional after the deterministic controller has useful logged data. Foundation-model training, tokenizer changes, kernel work and complex RL remain outside the MVP.

## Viva explanation

“The budget ledger is the accounting system behind TokenOS. Before an agent calls a model, it reserves enough budget for the estimated prompt and maximum completion. After the call, it replaces the reservation with actual usage. It prevents parallel steps from spending the same quota and keeps uncertain calls reserved. This makes adaptive allocation measurable, although the controller still needs to prove that its choices improve task success per token.”
