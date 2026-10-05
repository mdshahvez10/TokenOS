import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import asyncpg
import httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from tokenos.application.execution import InstrumentedCall, ModelPort, ModelResult
from tokenos.application.ledger import BudgetLedger
from tokenos.application.ports import LedgerRepository
from tokenos.domain.models import (
    BudgetExceeded,
    Conflict,
    Event,
    LedgerError,
    NotFound,
    PositiveTokens,
    Reservation,
    ReservationSpec,
    Run,
    RunSpec,
    Usage,
    UsageUnavailable,
    Value,
)
from tokenos.infrastructure.graph import BaselineState, build_baseline
from tokenos.infrastructure.memory import MemoryLedgerRepository
from tokenos.infrastructure.models import SimulatedModel
from tokenos.infrastructure.postgres import PostgresLedgerRepository
from tokenos.infrastructure.settings import Settings
from tokenos.infrastructure.telemetry import configure
from tokenos.runtime.api import router
from tokenos.runtime.engine import AgentRuntime
from tokenos.runtime.providers import GeminiModel, QwenModel, SandboxAgentModel
from tokenos.runtime.seed import seed
from tokenos.runtime.storage import MemoryCorpus, MemoryRecords, PostgresCorpus, PostgresRecords
from tokenos.runtime.tools import MCPGateway

log = structlog.get_logger()


class BaselineRequest(Value):
    reservation_id: UUID
    prompt: str = Field(min_length=1)
    max_output_tokens: PositiveTokens


def create_app(
    settings: Settings | None = None,
    repository: LedgerRepository | None = None,
    model: ModelPort | None = None,
) -> FastAPI:
    config = settings or Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        telemetry = configure(config)
        pool = None
        client = httpx.AsyncClient(timeout=config.provider_timeout_seconds)
        try:
            repo = repository
            if repo is None:
                if config.backend == "memory":
                    repo = MemoryLedgerRepository()
                else:
                    assert config.database_url is not None
                    pool = await asyncpg.create_pool(
                        config.database_url.get_secret_value(),
                        min_size=config.pool_min,
                        max_size=config.pool_max,
                        command_timeout=config.db_timeout_seconds,
                    )
                    assert pool is not None
                    repo = PostgresLedgerRepository(pool)
            ledger = BudgetLedger(repo)
            app.state.ledger = ledger
            app.state.repository = repo
            selected_model = model
            if selected_model is None and config.demo_enabled:
                selected_model = SimulatedModel(
                    config.demo_model_id,
                    config.demo_response,
                    config.demo_overhead_tokens,
                )
            app.state.graph = (
                None
                if selected_model is None
                else build_baseline(
                    InstrumentedCall(
                        ledger,
                        selected_model,
                        config.safety_tokens,
                        config.provider_timeout_seconds,
                    ),
                )
            )
            runtime_model = (
                SandboxAgentModel()
                if config.runtime_provider == "sandbox"
                else QwenModel(
                    client,
                    config.qwen_model_id,
                    config.qwen_api_key.get_secret_value() if config.qwen_api_key else "",
                )
                if config.runtime_provider == "qwen"
                else GeminiModel(
                    client,
                    config.gemini_model or "",
                    config.gemini_api_key.get_secret_value() if config.gemini_api_key else "",
                    config.gemini_base_url,
                )
            )
            app.state.runtime = AgentRuntime(
                ledger,
                MemoryRecords() if pool is None else PostgresRecords(pool),
                MemoryCorpus() if pool is None else PostgresCorpus(pool),
                runtime_model,
                MCPGateway(config.mcp_servers, config.provider_timeout_seconds, client),
                config.runtime_policy(),
                "simulated" if config.runtime_provider == "sandbox" else "provider",
                config.safety_tokens,
                config.provider_timeout_seconds,
                config.concurrency,
                config.model_rates,
            )
            app.state.max_task_budget = config.max_task_budget
            await seed(app.state.runtime, config.sandbox_fixture)
            yield
        finally:
            await client.aclose()
            if pool is not None:
                try:
                    await asyncio.wait_for(pool.close(), config.shutdown_timeout_seconds)
                except TimeoutError:
                    pool.terminate()
            await asyncio.to_thread(telemetry.shutdown)

    async def authenticate(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if x_api_key is None or not secrets.compare_digest(
            x_api_key.encode(),
            config.api_key.get_secret_value().encode(),
        ):
            raise HTTPException(status_code=401, detail="invalid API key")

    app = FastAPI(
        title="TokenOS Runtime",
        version="0.2.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
    )

    def get_ledger(request: Request) -> BudgetLedger:
        ledger: BudgetLedger = request.app.state.ledger
        return ledger

    Ledger = Annotated[BudgetLedger, Depends(get_ledger)]

    @app.exception_handler(LedgerError)
    async def ledger_error(request: Request, error: LedgerError) -> JSONResponse:
        status = 409
        if isinstance(error, NotFound):
            status = 404
        elif isinstance(error, BudgetExceeded):
            status = 422
        elif isinstance(error, UsageUnavailable):
            status = 502
        return JSONResponse(
            status_code=status,
            content={
                "error": type(error).__name__,
                "detail": str(error),
            },
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        # Exception messages can contain credentials or prompts. Log class only.
        log.error("request_failed", error_type=type(error).__name__)
        return JSONResponse(status_code=503, content={"error": "dependency_unavailable"})

    @app.middleware("http")
    async def traced_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        with trace.get_tracer(__name__).start_as_current_span("http.request") as span:
            span.set_attribute("http.request.method", request.method)
            response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.post("/v1/runs", response_model=Run, status_code=201)
    async def create_run(spec: RunSpec, ledger: Ledger) -> Run:
        if spec.budget_tokens > config.max_task_budget:
            raise HTTPException(status_code=422, detail="task budget exceeds configured maximum")
        return await ledger.create(spec)

    @app.get("/v1/runs/{run_id}", response_model=Run)
    async def read_run(run_id: UUID, ledger: Ledger) -> Run:
        return await ledger.read(run_id)

    @app.post("/v1/runs/{run_id}/reservations", response_model=Reservation, status_code=201)
    async def reserve(run_id: UUID, spec: ReservationSpec, ledger: Ledger) -> Reservation:
        if spec.max_output_tokens > config.max_output_tokens:
            raise HTTPException(status_code=422, detail="output cap exceeds configured maximum")
        return await ledger.reserve(run_id, spec)

    @app.post("/v1/runs/{run_id}/reservations/{reservation_id}/dispatch")
    async def dispatch(run_id: UUID, reservation_id: UUID, ledger: Ledger) -> Reservation:
        return await ledger.dispatch(run_id, reservation_id)

    @app.post("/v1/runs/{run_id}/reservations/{reservation_id}/settle")
    async def settle(
        run_id: UUID,
        reservation_id: UUID,
        usage: Usage,
        ledger: Ledger,
    ) -> Reservation:
        return await ledger.settle(run_id, reservation_id, usage)

    @app.post("/v1/runs/{run_id}/reservations/{reservation_id}/unknown")
    async def unknown(run_id: UUID, reservation_id: UUID, ledger: Ledger) -> Reservation:
        return await ledger.unknown(run_id, reservation_id)

    @app.post("/v1/runs/{run_id}/reservations/{reservation_id}/release")
    async def release(run_id: UUID, reservation_id: UUID, ledger: Ledger) -> Reservation:
        return await ledger.release(run_id, reservation_id)

    @app.get("/v1/runs/{run_id}/events", response_model=list[Event])
    async def events(
        run_id: UUID,
        ledger: Ledger,
        after_version: Annotated[int, Query(ge=-1)] = -1,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[Event]:
        return [event async for event in ledger.repository.events(run_id, after_version, limit)]

    @app.post("/v1/runs/{run_id}/baseline", response_model=ModelResult)
    async def baseline(
        run_id: UUID,
        body: BaselineRequest,
        request: Request,
    ) -> ModelResult:
        if len(body.prompt) > config.max_prompt_characters:
            raise HTTPException(status_code=422, detail="prompt exceeds configured maximum")
        if body.max_output_tokens > config.max_output_tokens:
            raise HTTPException(status_code=422, detail="output cap exceeds configured maximum")
        if request.app.state.graph is None:
            raise Conflict("baseline disabled; configure an adapter or enable demo mode")
        state: BaselineState = {
            "run_id": run_id,
            "reservation_id": body.reservation_id,
            "prompt": body.prompt,
            "max_output_tokens": body.max_output_tokens,
        }
        result = await request.app.state.graph.ainvoke(state)
        return ModelResult.model_validate(result["result"])

    app.include_router(router)
    return app
