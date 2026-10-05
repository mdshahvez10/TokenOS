import asyncio
from tokenos.infrastructure.settings import Settings as FullSettings
from tokenos.infrastructure.settings import Settings
from tokenos.interfaces.api import create_app
from tokenos.application.execution import ExecuteRequest
from tokenos.application.ledger import AblationConfig
from pydantic import SecretStr

async def main():
    full = FullSettings()
    settings = Settings(
        backend="memory",
        api_key=SecretStr("local"),
        runtime_provider="qwen",
        qwen_api_key=full.qwen_api_key,
        qwen_model_id="qwen/qwen-2.5-72b-instruct"
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        req = ExecuteRequest(
            task_id="test-calc-2",
            query="Calculate 12 + 7",
            budget_tokens=10000,
            ablations=AblationConfig(),
            mode="adaptive"
        )
        runtime = app.state.runtime
        record = await runtime.execute(req)
        
        print(f"Status: {record.status}")
        print(f"Answer: {record.answer}")
        print("\nObservations:")
        for obs in record.observations:
            print(f"- Step {obs.step}: Tool {obs.tool} -> Error={obs.error}")
            print(f"  Result: {obs.result}")
            print(f"  Args: {obs.arguments}")
            
if __name__ == "__main__":
    asyncio.run(main())
