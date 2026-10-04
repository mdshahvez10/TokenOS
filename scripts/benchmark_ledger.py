"""Memory-adapter microbenchmark, never an LLM or database performance claim."""

import argparse
import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from uuid import uuid4

import structlog

from tokenos.application.ledger import BudgetLedger
from tokenos.domain.models import Components, ReservationSpec, RunSpec, Usage
from tokenos.infrastructure.memory import MemoryLedgerRepository


async def main(args):
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))
    ledger = BudgetLedger(MemoryLedgerRepository())
    run_id = uuid4()
    await ledger.create(
        RunSpec(
            run_id=run_id,
            budget_tokens=args.iterations * 100,
            context_window=100,
            model_id="fixture",
            policy_version="microbenchmark",
        )
    )
    durations = []
    for _ in range(args.iterations):
        spec = ReservationSpec(
            reservation_id=uuid4(),
            request_digest="a" * 64,
            components=Components(user=20),
            max_output_tokens=10,
            safety_tokens=5,
            purpose="agent",
        )
        start = time.perf_counter_ns()
        await ledger.reserve(run_id, spec)
        await ledger.dispatch(run_id, spec.reservation_id)
        await ledger.settle(run_id, spec.reservation_id, Usage(input_tokens=20, output_tokens=5))
        durations.append((time.perf_counter_ns() - start) / 1_000_000)
    report = {
        "backend": "memory",
        "operation": "reserve+dispatch+settle",
        "iterations": args.iterations,
        "median_ms": statistics.median(durations),
        "p95_ms": sorted(durations)[int(0.95 * (len(durations) - 1))],
        "warning": "Local serial microbenchmark; not PostgreSQL or provider latency",
    }
    output = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.iterations <= 0:
        parser.error("iterations must be positive")
    asyncio.run(main(args))
