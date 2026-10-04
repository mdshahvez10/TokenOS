import json
import re

import httpx

from tokenos.application.execution import ModelResult
from tokenos.domain.models import Components, Usage, UsageUnavailable


class GeminiModel:
    def __init__(self, client: httpx.AsyncClient, model_id: str, key: str, base_url: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model_id):
            raise ValueError("invalid model ID")
        self.client, self.model_id, self.key, self.base_url = client, model_id, key, base_url

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()))

    async def invoke(self, prompt: str, max_output_tokens: int) -> ModelResult:
        response = await self.client.post(
            f"{self.base_url.rstrip('/')}/models/{self.model_id}:generateContent",
            headers={"x-goog-api-key": self.key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": max_output_tokens,
                    "responseMimeType": "application/json",
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        metadata = data.get("usageMetadata")
        if not metadata or "promptTokenCount" not in metadata or "totalTokenCount" not in metadata:
            raise UsageUnavailable("Gemini usage is incomplete; reconcile before retrying")
        usage = Usage(
            input_tokens=metadata["promptTokenCount"],
            output_tokens=metadata["totalTokenCount"] - metadata["promptTokenCount"],
            cached_input_tokens=metadata.get("cachedContentTokenCount", 0),
            reasoning_tokens=metadata.get("thoughtsTokenCount", 0),
            source="provider",
        )
        candidates = data.get("candidates", [])
        text = (
            ""
            if not candidates
            else "".join(
                p.get("text", "")
                for p in candidates[0].get("content", {}).get("parts", [])
                if not p.get("thought", False)
            )
        )
        return ModelResult(text=text, usage=usage)


class SandboxAgentModel:
    """Deterministic fixture reading only compiled context. NOT an LLM."""

    model_id = "tokenos-sandbox-agent-v1"

    async def estimate(self, prompt: str) -> Components:
        return Components(user=len(prompt.encode()))

    async def invoke(self, prompt: str, max_output_tokens: int) -> ModelResult:
        packet = json.loads(prompt)
        query, resources = packet["query"], packet["resources"]
        tools = {x["content"]["name"] for x in resources if x["category"] == "tool_schemas"}
        observations = [
            x["content"] for x in resources if x["category"] in {"tool_results", "trajectory"}
        ]
        successful = {
            x["tool"]: x["result"]
            for x in observations
            if "tool" in x and "result" in x and not x.get("error", False)
        }
        evidence = [x for x in resources if x["category"] == "rag"]
        match = re.search(r"ORD-?\d+", query, re.I)
        action: dict[str, object]
        if match:
            order_id = match.group().upper()
            if "get_order" not in successful and "get_order" in tools:
                action = {"kind": "tool", "name": "get_order", "arguments": {"order_id": order_id}}
            elif "create_return" in successful:
                action = {
                    "kind": "final",
                    "answer": json.dumps(successful["create_return"]),
                    "evidence_ids": [x["id"] for x in evidence],
                }
            elif "get_order" in successful and evidence:
                order = successful["get_order"]
                policy = " ".join(x["content"]["text"] for x in evidence)
                window = re.search(r"within (\d+) days", policy)
                eligible = bool(
                    window
                    and order.get("status") == "delivered"
                    and int(order.get("days_since_delivery", 9999)) <= int(window.group(1))
                    and not (order.get("category") == "digital" and "digital" in policy.lower())
                )
                wants = bool(re.search(r"\b(create|submit|process)\b", query, re.I)) and not bool(
                    re.search(r"\bdo not (create|submit|process)\b", query, re.I)
                )
                if eligible and wants and "create_return" in tools:
                    action = {
                        "kind": "tool",
                        "name": "create_return",
                        "arguments": {"order_id": order_id},
                    }
                else:
                    action = {
                        "kind": "final",
                        "answer": f"{order_id}: eligible={eligible}",
                        "evidence_ids": [x["id"] for x in evidence],
                    }
            else:
                action = {
                    "kind": "final",
                    "answer": "Insufficient order or policy evidence.",
                    "evidence_ids": [],
                }
        elif "calculator" in successful:
            action = {
                "kind": "final",
                "answer": str(successful["calculator"]["value"]),
                "evidence_ids": [],
            }
        else:
            calculation = re.search(r"(-?\d+(?:\.\d+)?)\s*([+*/-])\s*(-?\d+(?:\.\d+)?)", query)
            if calculation and "calculator" in tools:
                action = {
                    "kind": "tool",
                    "name": "calculator",
                    "arguments": {
                        "a": float(calculation[1]),
                        "b": float(calculation[3]),
                        "operator": {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[
                            calculation[2]
                        ],
                    },
                }
            else:
                action = {
                    "kind": "final",
                    "answer": "Sandbox fixture supports order and calculator tasks.",
                    "evidence_ids": [],
                }
        text = json.dumps(action).encode()[:max_output_tokens].decode(errors="ignore")
        return ModelResult(
            text=text,
            usage=Usage(
                input_tokens=len(prompt.encode()),
                output_tokens=len(text.encode()),
                source="simulated",
            ),
        )
