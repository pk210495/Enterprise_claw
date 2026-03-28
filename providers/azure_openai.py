import json
import logging
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(BaseProvider):
    """
    Azure OpenAI provider — supports both GPT and Claude (Anthropic) deployments on Azure.
    Uses the openai SDK pointed at the Azure endpoint.
    Auth uses api-key header instead of Bearer token (Azure requirement).
    """

    def __init__(self):
        cfg = config.providers.get("azure_openai")
        self._endpoint = cfg.get("endpoint", "")
        self._api_key = cfg.get("api_key", "")
        self._api_version = cfg.get("api_version", "2024-02-01")
        self._default_model = cfg.get("model", "claude-3-7-sonnet")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncAzureOpenAI
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=self._api_key,
                api_version=self._api_version,
            )
        return self._client

    @property
    def name(self) -> str:
        return "azure_openai"

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        client = self._get_client()
        kwargs = dict(
            model=self._default_model,
            messages=messages,
            stream=stream,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if stream:
            async for chunk in self._stream(client, kwargs):
                yield chunk
        else:
            async for chunk in self._complete(client, kwargs):
                yield chunk

    async def _stream(self, client, kwargs) -> AsyncGenerator[dict, None]:
        full_text = ""
        tool_calls_buf: dict[int, dict] = {}

        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # text delta
            if delta.content:
                full_text += delta.content
                yield {"type": "text", "content": delta.content}

            # tool call deltas
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buf:
                        tool_calls_buf[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_buf[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buf[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buf[idx]["arguments"] += tc.function.arguments

        # emit complete tool calls
        for tc in tool_calls_buf.values():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {"raw": tc["arguments"]}
            yield {"type": "tool_call", "id": tc["id"], "name": tc["name"], "arguments": args}

        yield {"type": "done", "content": full_text}

    async def _complete(self, client, kwargs) -> AsyncGenerator[dict, None]:
        kwargs["stream"] = False
        response = await client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        if msg.content:
            yield {"type": "text", "content": msg.content}

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                yield {"type": "tool_call", "id": tc.id, "name": tc.function.name, "arguments": args}

        yield {"type": "done", "content": msg.content or ""}

    async def count_tokens(self, messages: list[dict]) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            total = 0
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, str):
                    total += len(enc.encode(content))
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            total += len(enc.encode(block.get("text", "")))
            return total
        except Exception:
            return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    async def is_healthy(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception as e:
            logger.debug(f"azure_openai health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
