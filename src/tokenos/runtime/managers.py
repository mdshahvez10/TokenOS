import json
import time
from collections.abc import Callable
from typing import Literal

from tokenos.domain.models import BudgetExceeded
from tokenos.runtime.contracts import (
    CATEGORIES,
    Candidate,
    Chunk,
    Corpus,
    Document,
    Observation,
    Policy,
    Records,
    Selection,
    TaskRequest,
    ToolDefinition,
)
from tokenos.runtime.storage import digest, words


class ByteCounter:
    def count(self, text: str) -> int:
        return len(text.encode())


class Cache:
    def __init__(self, records: Records, ttl: int, clock: Callable[[], float] = time.time) -> None:
        self.records, self.ttl, self.clock = records, ttl, clock

    async def get(self, key: str) -> dict[str, object] | None:
        item = await self.records.get("cache", key)
        if item is None or float(str(item["expires"])) <= self.clock():
            return None
        value = item["value"]
        return value if isinstance(value, dict) else None

    async def put(self, key: str, value: dict[str, object]) -> None:
        await self.records.put("cache", key, {"expires": self.clock() + self.ttl, "value": value})


class RAGManager:
    def __init__(self, corpus: Corpus, cache: Cache, policy: Policy) -> None:
        self.corpus, self.cache, self.policy = corpus, cache, policy

    async def ingest(self, document: Document) -> int:
        if len(document.text) > self.policy.max_document_characters:
            raise ValueError("document exceeds size limit")
        tokens, chunks = document.text.split(), []
        revision = digest(document.model_dump())
        for start in range(0, len(tokens), self.policy.chunk_words - self.policy.chunk_overlap):
            text = " ".join(tokens[start : start + self.policy.chunk_words])
            chunks.append(
                Chunk(
                    chunk_id=f"{document.document_id}:{revision[:12]}:{start}",
                    document_id=document.document_id,
                    title=document.title,
                    text=text,
                    revision=revision,
                )
            )
            if start + self.policy.chunk_words >= len(tokens):
                break
        if not chunks:
            raise ValueError("document has no non-whitespace text")
        await self.corpus.upsert(document, chunks)
        return len(chunks)

    async def retrieve(
        self, query: str, use_cache: bool, fixed: bool
    ) -> tuple[list[Candidate], bool]:
        key = digest(["rag-v1", await self.corpus.revision(), query, self.policy.rag_top_k, fixed])
        hit = await self.cache.get(key) if use_cache else None
        if hit:
            values = hit["items"]
            if not isinstance(values, list):
                raise ValueError("invalid retrieval cache")
            return [Candidate.model_validate(value) for value in values], True
        chunks = await self.corpus.search(query, self.policy.rag_top_k)
        result = [
            Candidate(
                key=c.chunk_id,
                category="rag",
                text=json.dumps({"id": c.chunk_id, "title": c.title, "text": c.text}),
                score=max(0.01, c.score),
            )
            for c in chunks
            if fixed or c.score > 0
        ]
        if use_cache:
            await self.cache.put(key, {"items": [item.model_dump() for item in result]})
        return result, False


class ContextManager:
    def candidates(self, query: str, history: list[str], full: bool) -> list[Candidate]:
        seen: set[str] = set()
        result = []
        for i, text in enumerate(history):
            overlap = len(words(query) & words(text))
            if full or (text not in seen and overlap):
                result.append(
                    Candidate(
                        key=f"memory:{i}", category="context_memory", text=text, score=1 + overlap
                    )
                )
            seen.add(text)
        return result


class TrajectoryManager:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def candidates(self, observations: list[Observation], full: bool) -> list[Candidate]:
        result = []
        for i, obs in enumerate(observations):
            recent = i >= len(observations) - self.policy.recent_steps
            body = (
                obs.model_dump()
                if full or recent
                else {
                    "tool": obs.tool,
                    "step": obs.step,
                    "error": obs.error,
                    "artifact_id": obs.artifact_id,
                }
            )
            result.append(
                Candidate(
                    key=obs.artifact_id,
                    category="tool_results" if recent else "trajectory",
                    text=json.dumps(body),
                    score=10 if recent else 1,
                    mandatory=i == len(observations) - 1,
                )
            )
        return result


class ToolManager:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def candidates(self, query: str, tools: list[ToolDefinition], full: bool) -> list[Candidate]:
        ranked = sorted(
            tools,
            key=lambda t: (
                -len(words(query) & words(t.name.replace("_", " ") + " " + t.description)),
                t.name,
            ),
        )
        selected = ranked if full else ranked[: self.policy.tool_top_k]
        return [
            Candidate(
                key=t.name,
                category="tool_schemas",
                text=json.dumps(t.advertised()),
                score=1 + len(words(query) & words(t.description)),
            )
            for t in selected
        ]


class WorkflowRouter:
    def route(self, request: TaskRequest) -> Literal["direct", "react"]:
        if request.mode != "adaptive" or request.ablations.fixed_workflow:
            return "react"
        return (
            "react"
            if words(request.query)
            & {"order", "return", "policy", "calculate", "refund", "warranty", "search", "tool"}
            else "direct"
        )


def resource(item: Candidate) -> dict[str, object]:
    return {
        "id": item.key,
        "category": item.category,
        "content": item.text if item.category == "context_memory" else json.loads(item.text),
    }


class TokenController:
    def __init__(self, policy: Policy, counter: ByteCounter) -> None:
        self.policy, self.counter = policy, counter

    def allocate(
        self,
        request: TaskRequest,
        candidates: list[Candidate],
        available: int,
        step: int,
        overhead: int,
        errors: int,
        workflow: Literal["direct", "react"],
    ) -> tuple[list[Candidate], Selection]:
        output = min(self.policy.output_reserve, available)
        capacity = min(available, self.policy.context_window) - output - overhead
        if request.mode != "full":
            capacity = min(capacity, self.policy.input_budget - overhead)
        if capacity < 0:
            raise BudgetExceeded("pinned instructions, query and output cannot fit")
        weights = dict(self.policy.weights)
        reason = "fixed category weights"
        if request.mode == "adaptive":
            evidence = bool(words(request.query) & {"policy", "return", "refund", "warranty"})
            weights["rag"] *= 2 if evidence else 0.25
            weights["tool_results"] *= 1 + step
            weights["trajectory"] *= 1 + errors
            weights["tool_schemas"] *= 1 + errors
            reason = f"evidence_demand={evidence}; step={step}; errors={errors}"
        quotas = {
            key: int(capacity * weight / sum(weights.values())) for key, weight in weights.items()
        }
        costs = {c.key: self.counter.count(json.dumps(resource(c))) + 2 for c in candidates}
        selected = [c for c in candidates if c.mandatory]
        used: dict[str, int] = {
            cat: sum(costs[c.key] for c in selected if c.category == cat) for cat in CATEGORIES
        }
        if sum(used.values()) > capacity:
            raise BudgetExceeded("latest tool evidence cannot fit without unsafe truncation")
        ranked = sorted(
            [c for c in candidates if not c.mandatory],
            key=lambda c: (-c.score / max(1, costs[c.key]), c.key),
        )
        if request.mode == "full":
            if sum(costs.values()) > capacity:
                raise BudgetExceeded("full context exceeds available budget")
            selected = candidates[:]
            used = {
                cat: sum(costs[c.key] for c in selected if c.category == cat) for cat in CATEGORIES
            }
        else:
            for candidate in ranked:
                cost = costs[candidate.key]
                if (
                    used[candidate.category] + cost <= quotas[candidate.category]
                    and sum(used.values()) + cost <= capacity
                ):
                    selected.append(candidate)
                    used[candidate.category] += cost
            if request.mode == "adaptive":
                chosen = {c.key for c in selected}
                for candidate in ranked:
                    if (
                        candidate.key not in chosen
                        and sum(used.values()) + costs[candidate.key] <= capacity
                    ):
                        selected.append(candidate)
                        used[candidate.category] += costs[candidate.key]
        chosen = {c.key for c in selected}
        return selected, Selection(
            step=step,
            workflow=workflow,
            available=available,
            input_limit=capacity + overhead,
            output_reserve=output,
            quotas=quotas,
            retained=used,
            selected_ids=sorted(chosen),
            omitted_ids=[c.key for c in candidates if c.key not in chosen],
            reason=reason,
        )
