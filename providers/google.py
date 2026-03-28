import logging
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class GoogleProvider(BaseProvider):
    """Google Gemini provider via google-generativeai SDK."""

    def __init__(self):
        cfg = config.providers.get("google")
        self._api_key = cfg.get("api_key", "")
        self._default_model = cfg.get("model", "gemini-1.5-pro")
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

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        import asyncio
        genai = self._get_client()
        model = genai.GenerativeModel(self._default_model)

        # split system prompt from conversation
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        history = []
        last_user = None

        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                continue
            elif role == "user":
                last_user = content
                history.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                history.append({"role": "model", "parts": [content]})

        # inject system into first user message
        if system_parts and history:
            sys_text = "\n\n".join(system_parts)
            history[0]["parts"] = [f"{sys_text}\n\n{history[0]['parts'][0]}"]

        chat = model.start_chat(history=history[:-1] if len(history) > 1 else [])
        last_msg = history[-1]["parts"][0] if history else ""

        full_text = ""

        def _send():
            if stream:
                return model.generate_content(last_msg, stream=True)
            return model.generate_content(last_msg)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _send)

        if stream:
            for chunk in response:
                text = chunk.text if hasattr(chunk, "text") else ""
                if text:
                    full_text += text
                    yield {"type": "text", "content": text}
        else:
            text = response.text if hasattr(response, "text") else ""
            full_text = text
            yield {"type": "text", "content": text}

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
            import asyncio
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: list(genai.list_models()))
            return True
        except Exception as e:
            logger.debug(f"google health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
