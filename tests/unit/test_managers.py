import httpx
import pytest

from tokenos.domain.models import UsageUnavailable
from tokenos.runtime.contracts import Policy
from tokenos.runtime.managers import Cache, ContextManager
from tokenos.runtime.providers import GeminiModel
from tokenos.runtime.storage import MemoryRecords


def test_policy_rejects_invalid_chunk_overlap():
    with pytest.raises(ValueError):
        Policy(chunk_words=20, chunk_overlap=20)


def test_dedup_memory():
    manager = ContextManager()
    assert len(manager.candidates("order", ["order note", "order note"], False)) == 1
    assert len(manager.candidates("order", ["order note", "order note"], True)) == 2


async def test_cache_expiry():
    now = [0.0]
    cache = Cache(MemoryRecords(), 5, lambda: now[0])
    await cache.put("k", {"answer": 1})
    assert await cache.get("k") == {"answer": 1}
    now[0] = 5
    assert await cache.get("k") is None


async def test_gemini_usage_includes_reasoning_once():
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "totalTokenCount": 140,
                    "thoughtsTokenCount": 30,
                    "cachedContentTokenCount": 10,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = GeminiModel(client, "model-id", "test-key", "https://provider.test/v1beta")
        result = await model.invoke("prompt", 100)
        assert result.usage.total == 140
        assert result.usage.reasoning_tokens == 30
        assert result.usage.output_tokens == 40


async def test_gemini_missing_usage_fails_closed():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(UsageUnavailable):
            await GeminiModel(
                client, "model-id", "test-key", "https://provider.test/v1beta"
            ).invoke("prompt", 100)
