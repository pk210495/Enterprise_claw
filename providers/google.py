import asyncio
import logging
import os
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class GoogleProvider(BaseProvider):
    """Google Gemini provider via google-generativeai SDK."""

    def __init__(self):
        cfg = config.providers.get("google")
        self._api_key = os.environ.get("GOOGLE_API_KEY") or cfg.get("api_key", "")
        self._default_model = os.environ.get("GOOGLE_MODEL") or cfg.get("model", "gemini-1.5-pro")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._client = genai
        return self._client

    @property
    def name(self) -> str:
        return "google"

    def _convert_tools(self, tools: list[dict]):
        """Convert OpenAI-style tool schemas to Gemini function_declarations."""
        import google.generativeai as genai
        declarations = []
        for t in tools:
            fn = t.get("function", t)
            params = fn.get("parameters", {"type": "object", "properties": {}})
            declarations.append(
                genai.protos.FunctionDeclaration(
                    name=fn.get("name", ""),
                    description=fn.get("description", ""),
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: genai.protos.Schema(
                                type=genai.protos.Type[v.get("type", "string").upper()]
                                if v.get("type", "string").upper() in ("STRING", "NUMBER", "INTEGER", "BOOLEAN", "ARRAY", "OBJECT")
                                else genai.protos.Type.STRING,
                                description=v.get("description", ""),
                            )
                            for k, v in params.get("properties", {}).items()
                        },
                        required=params.get("required", []),
                    ),
                )
            )
        return [genai.protos.Tool(function_declarations=declarations)] if declarations else []

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        genai = self._get_client()

        # split system prompt from conversation
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        history = []

        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                continue
            elif role == "user":
                history.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                history.append({"role": "model", "parts": [content]})

        # inject system into first user message
        if system_parts and history:
            sys_text = "\n\n".join(system_parts)
            history[0]["parts"] = [f"{sys_text}\n\n{history[0]['parts'][0]}"]

        last_msg = history[-1]["parts"][0] if history else ""
        gemini_tools = self._convert_tools(tools) if tools else []

        model_kwargs = {}
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools
        model = genai.GenerativeModel(self._default_model, **model_kwargs)

        full_text = ""

        def _send():
            if stream:
                return model.generate_content(last_msg, stream=True)
            return model.generate_content(last_msg)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _send)

        if stream:
            # Streaming: collect full response then check for function calls
            for chunk in response:
                for part in (chunk.candidates[0].content.parts if chunk.candidates else []):
                    if hasattr(part, "function_call") and part.function_call.name:
                        fc = part.function_call
                        yield {
                            "type": "tool_call",
                            "id": f"gemini_{fc.name}",
                            "name": fc.name,
                            "arguments": dict(fc.args),
                        }
                    elif hasattr(part, "text") and part.text:
                        full_text += part.text
                        yield {"type": "text", "content": part.text}
        else:
            for part in (response.candidates[0].content.parts if response.candidates else []):
                if hasattr(part, "function_call") and part.function_call.name:
                    fc = part.function_call
                    yield {
                        "type": "tool_call",
                        "id": f"gemini_{fc.name}",
                        "name": fc.name,
                        "arguments": dict(fc.args),
                    }
                elif hasattr(part, "text") and part.text:
                    full_text += part.text
                    yield {"type": "text", "content": part.text}

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
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: list(genai.list_models()))
            return True
        except Exception as e:
            logger.debug(f"google health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
