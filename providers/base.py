from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseProvider(ABC):
    """
    Contract every LLM provider must fulfill.
    Orchestrator and subagents call only these methods — never provider internals.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """
        Send messages to the model.

        Yields dicts of shape:
          {"type": "text",      "content": "..."}         — streamed text delta
          {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
          {"type": "done",      "content": "full text"}   — final assembled text
        """
        ...

    @abstractmethod
    async def count_tokens(self, messages: list[dict]) -> int:
        """Estimate token count for context budget management."""
        ...

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Ping the provider — return True if reachable and usable."""
        ...

    @abstractmethod
    def get_available_models(self) -> list[str]:
        """Return list of model IDs this provider supports."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier string, e.g. 'azure_openai'."""
        ...
