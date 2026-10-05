import asyncio
import json
import re

import httpx

from tokenos.application.execution import ModelResult
from tokenos.domain.models import Components, Usage, UsageUnavailable


class GeminiModel:
    MAX_ATTEMPTS = 8
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    MAX_BACKOFF_SECONDS = 30.0

    def __init__(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        key: str,
        base_url: str,
    ) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model_id):
            raise ValueError("invalid model ID")

        self.client = client
        self.model_id = model_id
        self.key = key
        self.base_url = base_url

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()))

    async def _request(
        self,
        prompt: str,
        max_output_tokens: int,
    ) -> httpx.Response:
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = await self.client.post(
                    f"{self.base_url.rstrip('/')}/models/{self.model_id}:generateContent",
                    headers={
                        "x-goog-api-key": self.key,
                    },
                    json={
                        "contents": [
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "text": prompt,
                                    }
                                ],
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0,
                            "maxOutputTokens": max_output_tokens,
                        },
                    },
                )
            except httpx.TimeoutException:
                print(f"\nGEMINI REQUEST TIMEOUT (attempt {attempt}/{self.MAX_ATTEMPTS})")
                if attempt == self.MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(self.MAX_BACKOFF_SECONDS)
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                print(
                    f"\nGEMINI REQUEST FAILED "
                    f"(attempt {attempt}/{self.MAX_ATTEMPTS})"
                )
                print(f"Status: {response.status_code}")
                print("Response:")
                print(response.text[:2000])

            if response.status_code not in self.RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response

            if attempt == self.MAX_ATTEMPTS:
                response.raise_for_status()

            retry_after = response.headers.get("Retry-After")

            try:
                delay = float(retry_after) if retry_after else 2.0**attempt
            except ValueError:
                delay = 2.0**attempt

            delay = min(delay, self.MAX_BACKOFF_SECONDS)

            print(f"Retrying Gemini request in {delay:.1f} seconds...")

            await asyncio.sleep(delay)

        raise RuntimeError("Gemini request retry loop exited unexpectedly")

    async def invoke(
        self,
        prompt: str,
        max_output_tokens: int,
    ) -> ModelResult:
        response = await self._request(
            prompt,
            max_output_tokens,
        )

        data = response.json()
        metadata = data.get("usageMetadata")

        if (
            not metadata
            or "promptTokenCount" not in metadata
            or "totalTokenCount" not in metadata
        ):
            raise UsageUnavailable(
                "Gemini usage is incomplete; reconcile before retrying"
            )

        usage = Usage(
            input_tokens=metadata["promptTokenCount"],
            output_tokens=(
                metadata["totalTokenCount"]
                - metadata["promptTokenCount"]
            ),
            cached_input_tokens=metadata.get(
                "cachedContentTokenCount",
                0,
            ),
            reasoning_tokens=metadata.get(
                "thoughtsTokenCount",
                0,
            ),
            source="provider",
        )

        candidates = data.get("candidates", [])

        text = (
            ""
            if not candidates
            else "".join(
                part.get("text", "")
                for part in candidates[0]
                .get("content", {})
                .get("parts", [])
                if not part.get("thought", False)
            )
        )

        return ModelResult(
            text=text,
            usage=usage,
        )


class QwenModel:
    """Qwen3 8B via OpenRouter (OpenAI-compatible API)."""

    MAX_ATTEMPTS = 4
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    MAX_BACKOFF_SECONDS = 8.0
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        api_key: str,
    ) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_./:@-]+", model_id):
            raise ValueError("invalid model ID")
        self.client = client
        self.model_id = model_id
        self.api_key = api_key

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()))

    async def _request(
        self,
        prompt: str,
        max_output_tokens: int,
    ) -> httpx.Response:
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            response = await self.client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_output_tokens,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                print(
                    f"\nQWEN REQUEST FAILED "
                    f"(attempt {attempt}/{self.MAX_ATTEMPTS})"
                )
                print(f"Status: {response.status_code}")
                print(response.text[:2000])

            if response.status_code not in self.RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response

            if attempt == self.MAX_ATTEMPTS:
                response.raise_for_status()

            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2.0**attempt
            except ValueError:
                delay = 2.0**attempt

            delay = min(delay, self.MAX_BACKOFF_SECONDS)
            print(f"Retrying Qwen request in {delay:.1f} seconds...")
            await asyncio.sleep(delay)

        raise RuntimeError("Qwen request retry loop exited unexpectedly")

    async def invoke(
        self,
        prompt: str,
        max_output_tokens: int,
    ) -> ModelResult:
        response = await self._request(prompt, max_output_tokens)
        data = response.json()

        usage_data = data.get("usage")
        if not usage_data or "prompt_tokens" not in usage_data or "completion_tokens" not in usage_data:
            raise UsageUnavailable(
                "Qwen/OpenRouter usage is incomplete; reconcile before retrying"
            )

        usage = Usage(
            input_tokens=usage_data["prompt_tokens"],
            output_tokens=usage_data["completion_tokens"],
            cached_input_tokens=0,
            reasoning_tokens=0,
            source="provider",
        )

        choices = data.get("choices", [])
        text = (
            ""
            if not choices
            else choices[0].get("message", {}).get("content", "")
        )

        return ModelResult(text=text, usage=usage)


class SandboxAgentModel:
    """Deterministic fixture reading only compiled context. NOT an LLM."""

    model_id = "tokenos-sandbox-agent-v1"

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()))

    async def invoke(
        self,
        prompt: str,
        max_output_tokens: int,
    ) -> ModelResult:
        packet = json.loads(prompt)
        query, resources = packet["query"], packet["resources"]

        tools = {
            x["content"]["name"]
            for x in resources
            if x["category"] == "tool_schemas"
        }

        observations = [
            x["content"]
            for x in resources
            if x["category"] in {"tool_results", "trajectory"}
        ]

        successful = {
            x["tool"]: x["result"]
            for x in observations
            if "tool" in x
            and "result" in x
            and not x.get("error", False)
        }

        evidence = [
            x
            for x in resources
            if x["category"] == "rag"
        ]

        match = re.search(
            r"ORD-?\d+",
            query,
            re.I,
        )

        action: dict[str, object]

        if match:
            order_id = match.group().upper()

            if (
                "get_order" not in successful
                and "get_order" in tools
            ):
                action = {
                    "kind": "tool",
                    "name": "get_order",
                    "arguments": {
                        "order_id": order_id,
                    },
                }

            elif "create_return" in successful:
                action = {
                    "kind": "final",
                    "answer": json.dumps(
                        successful["create_return"]
                    ),
                    "evidence_ids": [
                        x["id"]
                        for x in evidence
                    ],
                }

            elif (
                "get_order" in successful
                and evidence
            ):
                order = successful["get_order"]

                policy = " ".join(
                    x["content"]["text"]
                    for x in evidence
                )

                window = re.search(
                    r"within (\d+) days",
                    policy,
                )

                eligible = bool(
                    window
                    and order.get("status") == "delivered"
                    and int(
                        order.get(
                            "days_since_delivery",
                            9999,
                        )
                    )
                    <= int(window.group(1))
                    and not (
                        order.get("category") == "digital"
                        and "digital" in policy.lower()
                    )
                )

                wants = (
                    bool(
                        re.search(
                            r"\b(create|submit|process)\b",
                            query,
                            re.I,
                        )
                    )
                    and not bool(
                        re.search(
                            r"\bdo not (create|submit|process)\b",
                            query,
                            re.I,
                        )
                    )
                )

                if (
                    eligible
                    and wants
                    and "create_return" in tools
                ):
                    action = {
                        "kind": "tool",
                        "name": "create_return",
                        "arguments": {
                            "order_id": order_id,
                        },
                    }

                else:
                    action = {
                        "kind": "final",
                        "answer": (
                            f"{order_id}: "
                            f"eligible={eligible}"
                        ),
                        "evidence_ids": [
                            x["id"]
                            for x in evidence
                        ],
                    }

            else:
                action = {
                    "kind": "final",
                    "answer": (
                        "Insufficient order or "
                        "policy evidence."
                    ),
                    "evidence_ids": [],
                }

        elif "calculator" in successful:
            action = {
                "kind": "final",
                "answer": str(
                    successful["calculator"]["value"]
                ),
                "evidence_ids": [],
            }

        else:
            calculation = re.search(
                r"(-?\d+(?:\.\d+)?)\s*([+*/-])\s*(-?\d+(?:\.\d+)?)",
                query,
            )

            if (
                calculation
                and "calculator" in tools
            ):
                action = {
                    "kind": "tool",
                    "name": "calculator",
                    "arguments": {
                        "a": float(calculation[1]),
                        "b": float(calculation[3]),
                        "operator": {
                            "+": "add",
                            "-": "subtract",
                            "*": "multiply",
                            "/": "divide",
                        }[calculation[2]],
                    },
                }

            else:
                action = {
                    "kind": "final",
                    "answer": (
                        "Sandbox fixture supports "
                        "order and calculator tasks."
                    ),
                    "evidence_ids": [],
                }

        text = (
            json.dumps(action)
            .encode()[:max_output_tokens]
            .decode(errors="ignore")
        )

        return ModelResult(
            text=text,
            usage=Usage(
                input_tokens=len(
                    prompt.encode()
                ),
                output_tokens=len(
                    text.encode()
                ),
                source="simulated",
            ),
        )