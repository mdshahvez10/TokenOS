import asyncio
from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from tokenos.application.execution import ModelResult
from tokenos.domain.models import Components, Usage, UsageUnavailable


class SimulatedModel:
    """A byte-counting fixture, NOT an LLM tokenizer or a task-solving model."""

    def __init__(self, model_id: str, response: str, overhead_tokens: int) -> None:
        self.model_id = model_id
        self.response = response
        self.overhead_tokens = overhead_tokens

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()), overhead=self.overhead_tokens)

    async def invoke(self, prompt: str, max_output_tokens: int) -> ModelResult:
        text = self.response.encode()[:max_output_tokens].decode(errors="ignore")
        return ModelResult(
            text=text,
            usage=Usage(
                input_tokens=(await self.estimate(prompt)).total,
                output_tokens=len(text.encode()),
                source="simulated",
            ),
        )


class LangChainModelAdapter:
    """Inject a provider-specific factory that ENFORCES the requested output cap.

    The factory must disable SDK retries (one ledger reservation per attempt), identify a
    fixed model, and expose reliable usage metadata. This adapter never treats missing
    usage as zero. Output includes provider-reported reasoning; do not add it twice.
    """

    def __init__(
        self,
        model_id: str,
        model_factory: Callable[[int], BaseChatModel],
        input_counter: Callable[[str], int],
        overhead_tokens: int,
    ) -> None:
        self.model_id = model_id
        self.model_factory = model_factory
        self.input_counter = input_counter
        self.overhead_tokens = overhead_tokens

    async def estimate(self, prompt: str) -> Components:
        count = await asyncio.to_thread(self.input_counter, prompt)
        return Components(user=count, overhead=self.overhead_tokens)

    async def invoke(self, prompt: str, max_output_tokens: int) -> ModelResult:
        model = self.model_factory(max_output_tokens)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        metadata = response.usage_metadata
        if metadata is None:
            raise UsageUnavailable("provider did not return usage; reconcile before retrying")
        inputs = metadata.get("input_token_details") or {}
        outputs = metadata.get("output_token_details") or {}
        usage = Usage(
            input_tokens=metadata["input_tokens"],
            output_tokens=metadata["output_tokens"],
            cached_input_tokens=inputs.get("cache_read", 0),
            reasoning_tokens=outputs.get("reasoning", 0),
            source="provider",
        )
        if metadata["total_tokens"] != usage.total:
            raise UsageUnavailable("inconsistent provider token totals require reconciliation")
        if inputs.get("cache_creation", 0):
            raise UsageUnavailable(
                "cache-write billing needs a provider-specific normalizer; reconcile raw usage"
            )
        text = response.content if isinstance(response.content, str) else str(response.content)
        return ModelResult(text=text, usage=usage)
