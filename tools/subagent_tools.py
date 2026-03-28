import logging
from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Injected at runtime by the orchestrator to avoid circular imports
_subagent_runner = None


def set_subagent_runner(runner):
    """Called by orchestrator to inject the subagent pool runner."""
    global _subagent_runner
    _subagent_runner = runner


class SpawnSubagentsTool(BaseTool):
    name = "spawn_subagents"
    description = (
        "Spawn multiple subagents to run tasks IN PARALLEL. "
        "Use this when a task can be split into independent subtasks that don't need each other's results. "
        "All subagents run simultaneously and their results are returned when all complete. "
        "Each subagent has its own context, its own model call, and its own tool access. "
        "Example: analyse 5 files simultaneously, each subagent handles one file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "List of tasks to run in parallel.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":          {"type": "string", "description": "Unique ID for this task, e.g. 'task_1'"},
                        "instruction": {"type": "string", "description": "Full instruction for this subagent"},
                        "context":     {"type": "string", "description": "Optional extra context for this task"},
                    },
                    "required": ["id", "instruction"],
                },
            }
        },
        "required": ["tasks"],
    }

    async def execute(self, tasks: list[dict]) -> ToolResult:
        if _subagent_runner is None:
            return ToolResult(
                success=False, output=None,
                error="Subagent runner not initialised. This is an internal error."
            )
        try:
            results = await _subagent_runner(tasks)
            formatted = []
            for r in results:
                status = "✓" if r.get("success") else "✗"
                formatted.append(
                    f"[{status}] {r.get('id', '?')}:\n{r.get('result', r.get('error', ''))}"
                )
            return ToolResult(success=True, output="\n\n---\n\n".join(formatted))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
