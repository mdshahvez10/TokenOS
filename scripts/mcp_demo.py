"""Optional read-only MCP fixture. Configure warehouse URL before discovery."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

server = FastMCP("warehouse", host="127.0.0.1", port=8001, stateless_http=True, json_response=True)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def inventory(sku: str) -> dict[str, object]:
    return {"sku": sku, "stock": 7, "simulated": True}


if __name__ == "__main__":
    server.run(transport="streamable-http")
