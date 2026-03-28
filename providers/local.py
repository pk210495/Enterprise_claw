import logging
from pathlib import Path
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class LocalProvider(BaseProvider):
    """
    Local GGUF model provider via llama-cpp-python.
    Zero internet dependency — always available if model file exists.
    """

    def __init__(self):
        cfg = config.providers.get("local")
        self._model_path = Path(cfg.get("model_path", ""))
        self._context_window = cfg.get("context_window", 8192)
        self._max_tokens = cfg.get("max_tokens", 2048)
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(
                model_path=str(self._model_path),
                n_ctx=self._context_window,
                n_threads=4,
                verbose=False,
            )
        return self._llm

    @property
    def name(self) -> str:
        return "local"

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        import asyncio
        llm = self._get_llm()

        def _run():
            return llm.create_chat_completion(
                messages=messages,
                max_tokens=self._max_tokens,
                stream=stream,
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run)

        full_text = ""
        if stream:
            for chunk in result:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_text += content
                    yield {"type": "text", "content": content}
        else:
            content = result["choices"][0]["message"].get("content", "")
            full_text = content
            yield {"type": "text", "content": content}

        yield {"type": "done", "content": full_text}

    async def count_tokens(self, messages: list[dict]) -> int:
        try:
            llm = self._get_llm()
            text = " ".join(str(m.get("content", "")) for m in messages)
            return len(llm.tokenize(text.encode()))
        except Exception:
            return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    async def is_healthy(self) -> bool:
        exists = self._model_path.exists() and self._model_path.is_file()
        if not exists:
            logger.debug(f"local model not found at {self._model_path}")
        return exists

    def get_available_models(self) -> list[str]:
        return [self._model_path.stem]
