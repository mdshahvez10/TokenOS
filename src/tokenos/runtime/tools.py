import asyncio
import json
import math
from typing import Protocol

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tokenos.domain.models import Conflict
from tokenos.runtime.contracts import Policy, Records, ToolDefinition
from tokenos.runtime.managers import Cache
from tokenos.runtime.storage import digest


class RemoteTools(Protocol):
    async def discover(self, server: str) -> list[ToolDefinition]: ...
    async def call(
        self, tool: ToolDefinition, arguments: dict[str, object]
    ) -> dict[str, object]: ...


class MCPGateway:
    def __init__(
        self, servers: dict[str, str], timeout: float, client: httpx.AsyncClient | None = None
    ) -> None:
        self.servers, self.timeout, self.client = servers, timeout, client

    async def discover(self, server: str) -> list[ToolDefinition]:
        if server not in self.servers:
            raise ValueError("server not configured")
        result = []
        async with (
            asyncio.timeout(self.timeout),
            streamable_http_client(self.servers[server], http_client=self.client) as io,
        ):
            async with ClientSession(io[0], io[1]) as session:
                await session.initialize()
                cursor = None
                while True:
                    page = await session.list_tools(cursor=cursor)
                    for tool in page.tools:
                        Draft202012Validator.check_schema(tool.inputSchema)
                        result.append(
                            ToolDefinition(
                                name=f"{server}.{tool.name}",
                                description=tool.description or tool.name,
                                schema=tool.inputSchema,
                                read_only=bool(tool.annotations and tool.annotations.readOnlyHint),
                                server=server,
                                remote_name=tool.name,
                                version=digest(tool.model_dump(mode="json")),
                            )
                        )
                    cursor = page.nextCursor
                    if not cursor:
                        break
        return result

    async def call(self, tool: ToolDefinition, arguments: dict[str, object]) -> dict[str, object]:
        if not tool.read_only or tool.server not in self.servers or not tool.remote_name:
            raise ValueError("external writes/unconfigured servers are blocked")
        async with (
            asyncio.timeout(self.timeout),
            streamable_http_client(self.servers[tool.server], http_client=self.client) as io,
        ):
            async with ClientSession(io[0], io[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool.remote_name, arguments=arguments)
                if result.isError:
                    raise ValueError("remote tool failed")
                return result.model_dump(mode="json")


class ToolExecutor:
    def __init__(self, records: Records, cache: Cache, policy: Policy, remote: RemoteTools) -> None:
        self.records, self.cache, self.policy, self.remote = records, cache, policy, remote

    async def execute(
        self,
        task_id: str,
        step: int,
        tool: ToolDefinition,
        arguments: dict[str, object],
        use_cache: bool,
    ) -> tuple[dict[str, object], bool]:
        Draft202012Validator(tool.schema_).validate(arguments)
        key = digest(["tool-v1", task_id, tool.name, tool.version, arguments])
        if use_cache and tool.read_only:
            cached = await self.cache.get(key)
            if cached is not None:
                return cached, True
        operation = f"{task_id}:{step}:{tool.name}"
        if not await self.records.create("tool_operations", operation, {"status": "dispatched"}):
            raise Conflict("operation already dispatched; inspect before replay")
        try:
            async with asyncio.timeout(self.policy.tool_timeout):
                result = await self._call(task_id, tool, arguments)
            if len(json.dumps(result).encode()) > self.policy.max_result_bytes:
                raise ValueError("tool result exceeds storage bound")
            await self.records.put(
                "tool_operations", operation, {"status": "completed", "result": result}
            )
            if use_cache and tool.read_only:
                await self.cache.put(key, result)
            return result, False
        except Exception as error:
            await self.records.put(
                "tool_operations",
                operation,
                {"status": "unknown", "error_type": type(error).__name__},
            )
            raise

    async def _call(
        self, task_id: str, tool: ToolDefinition, arguments: dict[str, object]
    ) -> dict[str, object]:
        if tool.server:
            return await self.remote.call(tool, arguments)
        if tool.name == "get_order":
            order = await self.records.get("orders", str(arguments["order_id"]))
            if order is None:
                raise ValueError("order not found")
            return order
        if tool.name == "create_return":
            order_id = str(arguments["order_id"])
            order = await self.records.get("orders", order_id)
            policy = await self.records.get("business_policy", "returns")
            if not order or not policy:
                raise ValueError("missing order/policy")
            excluded = policy["excluded_categories"]
            if not isinstance(excluded, list):
                raise ValueError("invalid policy")
            if (
                order["status"] != "delivered"
                or int(str(order["days_since_delivery"])) > int(str(policy["window_days"]))
                or order["category"] in excluded
            ):
                raise ValueError("order ineligible")
            value = {
                "order_id": order_id,
                "return_id": f"RET-{task_id[:8]}-{order_id}",
                "status": "created",
                "simulated": True,
            }
            key = f"{task_id}:{order_id}"
            await self.records.create("returns", key, value)
            return await self.records.get("returns", key) or value
        if tool.name == "calculator":
            a, b = float(str(arguments["a"])), float(str(arguments["b"]))
            if not math.isfinite(a) or not math.isfinite(b):
                raise ValueError("operands must be finite")
            operators = {
                "add": lambda: a + b,
                "subtract": lambda: a - b,
                "multiply": lambda: a * b,
                "divide": lambda: a / b,
            }
            answer = operators[str(arguments["operator"])]()
            if not math.isfinite(answer):
                raise ValueError("result must be finite")
            return {"value": answer}
        if tool.name == "read_artifact":
            artifact_id = str(arguments["artifact_id"])
            if not artifact_id.startswith(task_id + ":"):
                raise ValueError("artifact belongs to another task")
            artifact = await self.records.get("artifacts", artifact_id)
            if artifact is None:
                raise ValueError("artifact not found")
            return artifact
        return {"tool": tool.name, "records": [], "simulated": True}
