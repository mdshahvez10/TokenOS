import argparse
import asyncio
import json
from pathlib import Path

from pydantic import SecretStr

from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app
from tokenos.runtime.benchmark import Case, evaluate


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["sandbox", "gemini", "qwen"], default="sandbox")
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/cases.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results.json"))
    parser.add_argument("--budget", type=int, default=100000)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ablations", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 1 or args.budget < 1:
        parser.error("budget and repetitions must be positive")
    # Load from .env to pick up qwen_api_key and other secrets
    from tokenos.infrastructure.settings import Settings as _FullSettings
    full = _FullSettings()  # type: ignore[call-arg]
    settings = Settings(
        backend="memory",
        api_key=SecretStr("benchmark-local-only-key-000000000"),
        runtime_provider=args.provider,
        qwen_api_key=full.qwen_api_key,
        qwen_model_id=full.qwen_model_id,
        gemini_api_key=full.gemini_api_key,
        gemini_model=full.gemini_model,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        cases = [Case.model_validate(case) for case in json.loads(args.cases.read_text())]
        report = await evaluate(
            app.state.runtime, cases, args.repetitions, args.budget, args.seed, args.ablations
        )
        for row in report['rows']:
            if not row['success']:
                print(row)
                
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
