from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from tokenos.runtime.contracts import Document, TaskRecord, TaskRequest
from tokenos.runtime.engine import AgentRuntime

router = APIRouter(prefix="/v1")


@router.get("/runtime")
async def info(request: Request) -> dict[str, object]:
    r: AgentRuntime = request.app.state.runtime
    return {"source": r.source, "model": r.model.model_id, "policy": r.policy.model_dump()}


@router.post("/tasks")
async def run(body: TaskRequest, request: Request) -> TaskRecord:
    if body.budget_tokens > request.app.state.max_task_budget:
        raise HTTPException(422, "task budget exceeds maximum")
    try:
        runtime: AgentRuntime = request.app.state.runtime
        return await runtime.run(body)
    except ValueError as error:
        raise HTTPException(422, "invalid task") from error


@router.get("/tasks")
async def tasks(request: Request, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, object]]:
    runtime: AgentRuntime = request.app.state.runtime
    return await runtime.records.list("tasks", limit)


@router.get("/tasks/{task_id}")
async def task(task_id: UUID, request: Request) -> dict[str, object]:
    r: AgentRuntime = request.app.state.runtime
    record = await r.records.get("tasks", str(task_id))
    if record is None:
        raise HTTPException(404, "task not found")
    return {"task": record, "ledger": (await r.ledger.read(task_id)).model_dump(mode="json")}


@router.get("/tasks/{task_id}/artifacts/{key:path}")
async def artifact(task_id: UUID, key: str, request: Request) -> dict[str, object]:
    runtime: AgentRuntime = request.app.state.runtime
    result = await runtime.records.get("artifacts", f"{task_id}:{key}")
    if result is None:
        raise HTTPException(404, "artifact not found")
    return result


@router.post("/documents")
async def ingest(body: Document, request: Request) -> dict[str, str]:
    await request.app.state.runtime.rag.ingest(body)
    return {"document_id": body.document_id}


@router.get("/documents")
async def documents(request: Request, limit: int = Query(20, ge=1, le=100)) -> list[Document]:
    runtime: AgentRuntime = request.app.state.runtime
    return await runtime.corpus.documents(limit)


@router.get("/tools")
async def tools(request: Request) -> list[dict[str, object]]:
    return [
        t.model_dump(mode="json", by_alias=True)
        for t in await request.app.state.runtime.tool_definitions()
    ]


@router.post("/mcp/{server}/discover")
async def discover(server: str, request: Request) -> dict[str, int]:
    r: AgentRuntime = request.app.state.runtime
    try:
        definitions = await r.remote.discover(server)
    except ValueError as error:
        raise HTTPException(404, "server not configured") from error
    for tool in definitions:
        await r.records.put("tools", tool.name, tool.model_dump(mode="json", by_alias=True))
    return {"tools": len(definitions)}


@router.get("/benchmarks")
async def benchmarks(request: Request) -> list[dict[str, object]]:
    runtime: AgentRuntime = request.app.state.runtime
    return await runtime.records.list("benchmarks", 20)
