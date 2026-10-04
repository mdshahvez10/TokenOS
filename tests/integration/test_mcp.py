import json

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from tokenos.runtime.tools import MCPGateway


async def test_real_mcp_protocol_over_asgi():
    server = FastMCP("fixture", stateless_http=True, json_response=True)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def inventory(sku: str) -> dict[str, object]:
        return {"sku": sku, "stock": 7}

    app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            gateway = MCPGateway({"warehouse": "http://localhost:8001/mcp"}, 5, client)
            tools = await gateway.discover("warehouse")
            assert tools[0].name == "warehouse.inventory"
            result = await gateway.call(tools[0], {"sku": "ABC"})
            structured = result.get("structuredContent")
            if structured is None:
                structured = json.loads(result["content"][0]["text"])
            assert structured["stock"] == 7
