import json
import logging
import os
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    """OpenAI direct API provider — GPT-4o, o1, etc."""

    def __init__(self):
        cfg = config.providers.get("openai")
        self._api_key = os.environ.get("OPENAI_API_KEY") or cfg.get("api_key", "")
        self._default_model = os.environ.get("OPENAI_MODEL") or cfg.get("model", "gpt-4o")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @property
    def name(self) -> str:
        return "openai"

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        client = self._get_client()
        kwargs = dict(model=self._default_model, messages=messages, stream=stream)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        full_text = ""
        tool_calls_buf: dict[int, dict] = {}

        if stream:
            async with client.chat.completions.create(**kwargs) as s:
                async for chunk in s:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    if delta.content:
                        full_text += delta.content
                        yield {"type": "text", "content": delta.content}
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_buf:
                                tool_calls_buf[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_buf[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_buf[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_buf[idx]["arguments"] += tc.function.arguments
        else:
            kwargs["stream"] = False
            response = await client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            if msg.content:
                full_text = msg.content
                yield {"type": "text", "content": msg.content}
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    yield {"type": "tool_call", "id": tc.id, "name": tc.function.name, "arguments": args}

        for tc in tool_calls_buf.values():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except Exception:
                args = {}
            yield {"type": "tool_call", "id": tc["id"], "name": tc["name"], "arguments": args}

        yield {"type": "done", "content": full_text}

    async def count_tokens(self, messages: list[dict]) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return sum(len(enc.encode(str(m.get("content", "")))) for m in messages)
        except Exception:
            return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    async def is_healthy(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception as e:
            logger.debug(f"openai health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
