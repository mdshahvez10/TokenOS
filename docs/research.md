# Research protocol
## Objective
Minimize total charged input + output tokens across all attempts divided by successful tasks, subject to a predeclared success/reliability constraint. Cached input is part of input, reasoning is part of output: neither is added twice. Report TPS as unavailable if no tasks succeed or any call has unresolved usage. Report failure counts and unresolved holds alongside known usage.

## Current functional benchmark
Nine starter cases: eligible return, three ineligible returns, read-only eligibility, three arithmetic tasks, and duplicate long history. One seeded randomized paired repetition, equal 100,000-unit task budgets. Both fixed and adaptive use ranked candidates; fixed retains fixed quotas and does not reclaim unused category capacity. Full retains all bounded candidates/trajectory and can fail if budget is insufficient. The baseline is not an unbounded context oracle.

| Policy | Successful | Total simulated units | Units/success |
|---|---:|---:|---:|
| full | 9/9 | 201,446 | 22,382.9 |
| fixed | 9/9 | 52,208 | 5,800.9 |
| adaptive | 9/9 | 58,166 | 6,462.9 |

These are UTF-8 byte-based sandbox units. The model is a deterministic fixture that reads compiled context; these results are not actual LLM tokens, financial savings, general reasoning capability, or publishable superiority evidence. Adaptive currently uses more units than fixed. Greedy reclaim can include resources unnecessary for these easy tasks. This is a useful negative result, not something to hide. Timing is machine-local; no paid model was called. Missing configured prices yield null cost.

## Experimental design
1. Create disjoint development and held-out datasets across document QA, customer support and multi-tool workflows. Add rare tool names, contradictory policies, long relevant history and recoverable errors.
2. Freeze provider/model/version, prices, prompts, fixture snapshots, corpus and tool catalog. Count model calls for any summarizer/verifier in the same ledger; external API costs need a separate ledger extension.
3. Compare full bounded context, strong tuned fixed baseline and adaptive policy across multiple budgets. Randomize paired run order. Repetitions must not leak cache or cross-task state.
4. Predeclare a non-inferiority success margin, sample size and task-level paired bootstrap confidence intervals. Report TPS jointly with success, cost/success, calls and p50/p95 latency. Do not optimize on test tasks.
5. Disable one heuristic at a time through ablation switches. Cache requires separate warm/cold repeated-query cohorts; the primary benchmark disables it for fair context comparison.
6. Replace fixture answer matching with domain-specific verifiers and human adjudication for open-ended tasks. Cited ID membership is provenance checking, not proof of semantic grounding.
7. Calibrate provider-specific input estimates on held-out prompts and monitor overruns. UTF-8 bytes are an MVP approximation and may omit protocol/model-specific overhead. The system records actual overspend honestly rather than guaranteeing an impossible strict bound.

## Four-month schedule
| Weeks | Deliverable and exit criterion |
|---|---|
| 1–2 | Run this release, validate PostgreSQL/containers, freeze task definitions |
| 3–4 | Provider token calibration and held-out verifiers |
| 5–6 | Expand datasets and establish strong fixed/full baselines |
| 7–8 | Tune deterministic controller on development set only |
| 9–10 | Budget sweeps, failures, ablations and paired repetitions |
| 11–12 | Analyze confidence intervals and negative results |
| 13–14 | Load/failure testing, operational recovery and demonstration |
| 15–16 | Thesis, paper, reproducibility archive and viva preparation |

No foundation-model training, tokenizer/kernel changes or complex RL is needed. A small learned ranking policy is a later experiment only if deterministic baselines show a stable gap.

## Sources
Implementation references: [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [Gemini generateContent](https://ai.google.dev/api/generate-content), [PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html), [Streamlit](https://docs.streamlit.io/). These are API references, not evidence of TokenOS novelty. Establish novelty with a separate related-work review before claiming a research contribution.
