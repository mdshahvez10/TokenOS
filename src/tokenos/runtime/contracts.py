from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from tokenos.domain.models import PositiveTokens, Value

Category = Literal["context_memory", "rag", "tool_schemas", "tool_results", "trajectory"]
CATEGORIES: tuple[Category, ...] = (
    "context_memory",
    "rag",
    "tool_schemas",
    "tool_results",
    "trajectory",
)


class Policy(Value):
    version: str = "heuristic-v1"
    max_steps: int = Field(default=8, ge=1, le=50)
    input_budget: PositiveTokens = 6000
    output_reserve: PositiveTokens = 1200
    context_window: PositiveTokens = 100000
    max_candidates: int = Field(default=100, ge=1, le=1000)
    tool_top_k: int = Field(default=6, ge=1)
    rag_top_k: int = Field(default=6, ge=1)
    recent_steps: int = Field(default=2, ge=1)
    chunk_words: int = Field(default=100, ge=10)
    chunk_overlap: int = Field(default=20, ge=0)
    cache_ttl: int = Field(default=300, ge=1)
    result_characters: int = Field(default=2000, ge=100)
    max_result_bytes: int = Field(default=1000000, ge=100)
    max_document_characters: int = Field(default=200000, ge=100)
    max_history_characters: int = Field(default=200000, ge=1)
    tool_timeout: float = Field(default=15, gt=0)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "context_memory": 0.15,
            "rag": 0.3,
            "tool_schemas": 0.25,
            "tool_results": 0.2,
            "trajectory": 0.1,
        }
    )

    @model_validator(mode="after")
    def valid(self) -> "Policy":
        if self.chunk_overlap >= self.chunk_words:
            raise ValueError("overlap must be less than chunk size")
        if (
            set(self.weights) != set(CATEGORIES)
            or any(not 0 <= x <= 1 for x in self.weights.values())
            or sum(self.weights.values()) <= 0
        ):
            raise ValueError("provide nonnegative weights for all categories")
        return self


class Ablations(Value):
    full_memory: bool = False
    all_tools: bool = False
    fixed_rag: bool = False
    full_trajectory: bool = False
    no_cache: bool = False
    fixed_workflow: bool = False


class TaskRequest(Value):
    task_id: UUID = Field(default_factory=uuid4)
    query: str = Field(min_length=1, max_length=16000)
    history: list[str] = Field(default_factory=list, max_length=200)
    mode: Literal["adaptive", "fixed", "full"] = "adaptive"
    budget_tokens: PositiveTokens = 60000
    ablations: Ablations = Field(default_factory=Ablations)


class Candidate(Value):
    key: str
    category: Category
    text: str
    score: float = Field(ge=0)
    mandatory: bool = False


class Selection(Value):
    step: int
    workflow: Literal["direct", "react"]
    available: int
    input_limit: int
    output_reserve: int
    quotas: dict[str, int]
    retained: dict[str, int]
    selected_ids: list[str]
    omitted_ids: list[str]
    reason: str


class ToolDefinition(Value):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$")
    description: str
    schema_: dict[str, object] = Field(alias="schema")
    read_only: bool = True
    server: str | None = None
    remote_name: str | None = None
    version: str = "v1"

    def advertised(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description, "schema": self.schema_}


class ToolAction(Value):
    kind: Literal["tool"]
    name: str
    arguments: dict[str, object]


class FinalAction(Value):
    kind: Literal["final"]
    answer: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


Action = Annotated[ToolAction | FinalAction, Field(discriminator="kind")]


class Observation(Value):
    step: int
    tool: str
    arguments: dict[str, object]
    result: dict[str, object]
    artifact_id: str
    error: bool = False
    cache_hit: bool = False


class Document(Value):
    document_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class Chunk(Value):
    chunk_id: str
    document_id: str
    title: str
    text: str
    revision: str
    score: float = 0


class TaskRecord(Value):
    request: TaskRequest
    status: Literal["running", "completed", "budget_exhausted", "step_limit", "failed"]
    answer: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    decisions: list[Selection] = Field(default_factory=list)
    error: str | None = None
    source: Literal["simulated", "provider"]
    model_id: str
    policy: Policy
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    latency_ms: float = 0


class Records(Protocol):
    async def get(self, namespace: str, key: str) -> dict[str, object] | None: ...
    async def put(self, namespace: str, key: str, body: dict[str, object]) -> None: ...
    async def create(self, namespace: str, key: str, body: dict[str, object]) -> bool: ...
    async def list(self, namespace: str, limit: int = 100) -> list[dict[str, object]]: ...


class Corpus(Protocol):
    async def upsert(self, document: Document, chunks: list[Chunk]) -> None: ...
    async def search(self, query: str, limit: int) -> list[Chunk]: ...
    async def revision(self) -> str: ...
    async def documents(self, limit: int) -> list[Document]: ...
