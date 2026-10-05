import asyncio
import json
from pathlib import Path

from tokenos.infrastructure.settings import Settings as FullSettings
from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app
from tokenos.runtime.benchmark import Case, evaluate
from pydantic import SecretStr

async def main():
    full = FullSettings()
    settings = Settings(
        backend="memory",
        api_key=SecretStr("benchmark-local-only-key-000000000"),
        runtime_provider="qwen",
        qwen_api_key=full.qwen_api_key,
        qwen_model_id="qwen/qwen-2.5-72b-instruct"
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        case_data = [{
            "case_id": "Calculate 12 + 7",
            "query": "Calculate 12 + 7",
            "expected": "19.0",
            "order_id": None,
            "creates_return": False,
            "history": []
        }]
        cases = [Case.model_validate(case) for case in case_data]
        
        # Modify evaluate to return the actual answer or let's just use runtime.execute
        from tokenos.application.execution import ExecuteRequest
        from tokenos.application.ledger import AblationConfig
        
        req = ExecuteRequest(
            task_id="test-calc-3",
            query="Calculate 12 + 7",
            budget_tokens=10000,
            ablations=AblationConfig(),
            mode="fixed"
        )
        runtime = app.state.runtime
        record = await runtime.execute(req)
        
        print(f"Status: {record.status}")
        print(f"Answer: {record.answer!r}")
        print("\nObservations:")
        for obs in record.observations:
            print(f"- Step {obs.step}: Tool {obs.tool} -> Error={obs.error}")
            print(f"  Args: {obs.arguments}")
            print(f"  Result: {obs.result}")

if __name__ == "__main__":
    asyncio.run(main())
