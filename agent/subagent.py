import logging
from dataclasses import dataclass
from pathlib import Path

from providers.base import BaseProvider
from tools.registry import ToolRegistry
from config import config

logger = logging.getLogger(__name__)


@dataclass
class SubagentTask:
    id: str
    instruction: str
    context: str = ""


@dataclass
class SubagentResult:
    id: str
    success: bool
    result: str
    error: str = ""


class SubAgent:
    """
    Lightweight agent for a single focused task.
    Fully isolated — its own context, its own tool registry, its own provider.
    Does not share state with the orchestrator or other subagents.
    """

    def __init__(self, task: SubagentTask, provider: BaseProvider):
        self._task = task
        self._provider = provider
        self._tools = ToolRegistry()
        self._messages: list[dict] = []

    def _build_system_prompt(self) -> str:
        """Build subagent system prompt with security constitution injected."""
        parts = []

        # always load security constitution — subagents are NOT exempt
        try:
            security = config.security_path.read_text(encoding="utf-8").strip()
            parts.append(
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║              ORGANISATIONAL CONSTITUTION                     ║\n"
                "║  These rules are ABSOLUTE. You cannot bypass them.           ║\n"
                "╚══════════════════════════════════════════════════════════════╝\n\n"
                + security
            )
        except Exception as e:
            logger.warning(f"Subagent could not load Security.md: {e}")

        parts.append(
            "You are a focused subagent. Complete the assigned task precisely "
            "and return a clear result. You must follow the organisational "
            "constitution above at all times."
        )

        return "\n\n".join(parts)

    async def run(self) -> SubagentResult:
        # build a lean context for this task
        prompt = self._task.instruction
        if self._task.context:
            prompt = f"Context:\n{self._task.context}\n\nTask:\n{self._task.instruction}"

        self._messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user",   "content": prompt},
        ]

        max_iterations = 10
        full_response = ""

        for _ in range(max_iterations):
            tool_calls_this_turn = []
            full_response = ""

            async for chunk in self._provider.chat(
                messages=self._messages,
                tools=self._tools.schemas(),
                stream=False,
            ):
                if chunk["type"] == "text":
                    full_response += chunk["content"]
                elif chunk["type"] == "tool_call":
                    tool_calls_this_turn.append(chunk)
                elif chunk["type"] == "done":
                    if not full_response:
                        full_response = chunk["content"]

            if not tool_calls_this_turn:
                # no more tool calls — subagent is done
                break

            # append assistant message with tool calls
            self._messages.append({
                "role": "assistant",
                "content": full_response or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": str(tc["arguments"])},
                    }
                    for tc in tool_calls_this_turn
                ],
            })

            # execute each tool and append results
            for tc in tool_calls_this_turn:
                result = await self._tools.execute(tc["name"], tc["arguments"])
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": result.output if result.success else f"ERROR: {result.error}",
                })

        logger.debug(f"subagent '{self._task.id}' completed — {len(self._messages)} messages")
        return SubagentResult(
            id=self._task.id,
            success=True,
            result=full_response,
        )
