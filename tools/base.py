from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    output: Any
    error: str = ""

    def to_message(self) -> dict:
        if self.success:
            return {"role": "tool", "content": str(self.output)}
        return {"role": "tool", "content": f"ERROR: {self.error}"}


class BaseTool(ABC):
    """
    Base class for all agent tools.
    Each tool exposes a JSON schema the model uses to call it,
    and an execute() method that runs the actual logic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool identifier — must match what the model calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Clear description for the model — what it does and when to use it."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema object defining the tool's input parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Run the tool with given arguments. Always returns a ToolResult."""
        ...

    def to_schema(self) -> dict:
        """Convert to OpenAI-compatible tool schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
