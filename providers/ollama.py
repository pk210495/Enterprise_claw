import json
import logging
from typing import AsyncGenerator

import httpx

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class OllamaProvider(BaseProvider):
    """Ollama local model provider — llama3, mistral, codellama, phi3, etc."""

    def __init__(self):
        import os
        cfg = config.providers.get("ollama")
        self._host = (os.environ.get("OLLAMA_BASE_URL") or cfg.get("base_url") or cfg.get("host", "http://localhost:11434")).rstrip("/")
        self._default_model = os.environ.get("OLLAMA_MODEL") or cfg.get("model", "llama3")

    @property
    def name(self) -> str:
        return "ollama"

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        url = f"{self._host}/api/chat"
        payload = {
            "model": self._default_model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        full_text = ""
        async with httpx.AsyncClient(timeout=120.0) as client:
            if stream:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = chunk.get("message", {})
                        content = msg.get("content", "")
                        if content:
                            full_text += content
                            yield {"type": "text", "content": content}

                        # tool calls (Ollama 0.3+)
                        for tc in msg.get("tool_calls", []):
                            fn = tc.get("function", {})
                            yield {
                                "type": "tool_call",
                                "id": tc.get("id", ""),
                                "name": fn.get("name", ""),
                                "arguments": fn.get("arguments", {}),
                            }

                        if chunk.get("done"):
                            break
            else:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                msg = data.get("message", {})
                content = msg.get("content", "")
                full_text = content
                if content:
                    yield {"type": "text", "content": content}
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    yield {
                        "type": "tool_call",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", {}),
                    }

        yield {"type": "done", "content": full_text}

    async def count_tokens(self, messages: list[dict]) -> int:
        # rough estimate: 1 token ≈ 4 chars
        return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    async def is_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._host}/api/tags")
                return r.status_code == 200
        except Exception as e:
            logger.debug(f"ollama health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
