import json
from pathlib import Path

from tokenos.runtime.contracts import Document, ToolDefinition
from tokenos.runtime.engine import AgentRuntime


async def seed(runtime: AgentRuntime, path: Path) -> None:
    data = json.loads(path.read_text())
    await runtime.records.create("business_policy", "returns", data["policy"])
    for order in data["orders"]:
        await runtime.records.create("orders", order["order_id"], order)
    definitions: list[tuple[str, str, dict[str, object], bool]] = [
        (
            "get_order",
            "Read order delivery status and return eligibility",
            {"order_id": {"type": "string"}},
            True,
        ),
        (
            "create_return",
            "Create return request for an eligible order",
            {"order_id": {"type": "string"}},
            False,
        ),
        (
            "read_artifact",
            "Read full stored tool result artifact",
            {"artifact_id": {"type": "string"}},
            True,
        ),
        (
            "calculator",
            "Calculate arithmetic add subtract multiply divide",
            {
                "a": {"type": "number"},
                "b": {"type": "number"},
                "operator": {"enum": ["add", "subtract", "multiply", "divide"]},
            },
            True,
        ),
    ]
    for i in range(data["distractor_tools"]):
        definitions.append(
            (f"catalog_archive_{i}", f"List archived warehouse inventory batch {i}", {}, True)
        )
    for name, description, properties, read_only in definitions:
        tool = ToolDefinition(
            name=name,
            description=description,
            schema={
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
            read_only=read_only,
        )
        await runtime.records.create("tools", name, tool.model_dump(mode="json", by_alias=True))
    if not await runtime.corpus.documents(1):
        await runtime.rag.ingest(
            Document(document_id="return-policy", title="Return policy", text=data["policy_text"])
        )
