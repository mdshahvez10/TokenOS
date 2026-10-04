"""Paired fixture evaluation; success is checked from answers AND persisted effects."""

import random
from typing import Literal, cast
from uuid import uuid4

from pydantic import Field

from tokenos.domain.models import Value
from tokenos.runtime.contracts import Ablations, TaskRequest
from tokenos.runtime.engine import AgentRuntime


class Case(Value):
    case_id: str
    query: str
    expected: str
    order_id: str | None = None
    creates_return: bool = False
    history: list[str] = Field(default_factory=list)


async def evaluate(
    runtime: AgentRuntime,
    cases: list[Case],
    repetitions: int,
    budget: int,
    seed: int,
    ablations: bool = False,
) -> dict[str, object]:
    variants = ["full", "fixed", "adaptive"]
    if ablations:
        variants += ["full_memory", "all_tools", "fixed_rag", "full_trajectory", "fixed_workflow"]
    schedule = [
        (trial, case, variant)
        for trial in range(repetitions)
        for case in cases
        for variant in variants
    ]
    random.Random(seed).shuffle(schedule)
    rows = []
    for trial, case, variant in schedule:
        flags = {"no_cache": True}
        if variant not in ("full", "fixed", "adaptive"):
            flags[variant] = True
        request = TaskRequest(
            query=case.query,
            history=case.history,
            budget_tokens=budget,
            mode=cast(
                Literal["adaptive", "fixed", "full"],
                variant if variant in ("full", "fixed", "adaptive") else "adaptive",
            ),
            ablations=Ablations.model_validate(flags),
        )
        result = await runtime.run(request)
        ledger = await runtime.ledger.read(request.task_id)
        effect = (
            await runtime.records.get("returns", f"{request.task_id}:{case.order_id}")
            if case.order_id
            else None
        )
        success = (
            result.status == "completed"
            and case.expected.lower() in result.answer.lower()
            and bool(effect) == case.creates_return
        )
        rows.append(
            {
                "case": case.case_id,
                "trial": trial,
                "variant": variant,
                "task_id": str(request.task_id),
                "success": success,
                "status": result.status,
                "tokens": ledger.spent_tokens,
                "unresolved": ledger.reserved_tokens,
                "cost": str(ledger.cost) if ledger.cost is not None else None,
                "latency_ms": result.latency_ms,
                "steps": len(result.decisions),
                "source": result.source,
            }
        )
    summary = []
    for variant in variants:
        group = [row for row in rows if row["variant"] == variant]
        successful = sum(bool(row["success"]) for row in group)
        tokens = sum(int(str(row["tokens"])) for row in group)
        complete = not any(row["unresolved"] for row in group)
        summary.append(
            {
                "variant": variant,
                "tasks": len(group),
                "successes": successful,
                "success_rate": successful / len(group) if group else None,
                "total_tokens": tokens,
                "tps": tokens / successful if successful and complete else None,
                "accounting_complete": complete,
            }
        )
    report = {
        "benchmark_id": str(uuid4()),
        "seed": seed,
        "repetitions": repetitions,
        "budget": budget,
        "source": runtime.source,
        "model": runtime.model.model_id,
        "policy": runtime.policy.model_dump(),
        "corpus_revision": await runtime.corpus.revision(),
        "cases": [case.model_dump() for case in cases],
        "counter": "utf8-byte-conservative-v1",
        "summary": summary,
        "rows": rows,
    }
    await runtime.records.put("benchmarks", str(report["benchmark_id"]), report)
    return report
