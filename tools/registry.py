import logging
from .base import BaseTool, ToolResult
from .file_tools import (
    ListFilesTool, ReadFileTool, WriteFileTool, EditFileTool,
    CreateFileTool, DeleteFileTool, AppendFileTool,
)
from .memory_tools import RememberTool, RecallTool
from .skill_tools import CreateSkillTool, EditSkillTool, ListSkillsTool, DeleteSkillTool, ActivateSkillTool
from .search_tools import SearchInFilesTool
from .system_tools import GetDatetimeTool, GetWorkspaceStatsTool, GetSessionInfoTool
from .subagent_tools import SpawnSubagentsTool
from .exec_tools import RunCodeTool
from .git_tools import GitTool
from .task_tools import CreateTaskTool, UpdateTaskTool, ListTasksTool, GetTaskTool
from .bus_tools import SendMessageTool, ReadMessagesTool, MarkReadTool, ListAgentsTool
from .critic_tools import CritiqueOutputTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registers all tools and routes the model's tool_call events to the right execute() method.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self):
        defaults = [
            # file operations
            ListFilesTool(),
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            CreateFileTool(),
            DeleteFileTool(),
            AppendFileTool(),
            # memory
            RememberTool(),
            RecallTool(),
            # skills
            CreateSkillTool(),
            EditSkillTool(),
            ListSkillsTool(),
            DeleteSkillTool(),
            ActivateSkillTool(),
            # search
            SearchInFilesTool(),
            # system
            GetDatetimeTool(),
            GetWorkspaceStatsTool(),
            GetSessionInfoTool(),
            # subagents
            SpawnSubagentsTool(),
            # code execution
            RunCodeTool(),
            # version control
            GitTool(),
            # task / project management
            CreateTaskTool(),
            UpdateTaskTool(),
            ListTasksTool(),
            GetTaskTool(),
            # inter-agent message bus
            SendMessageTool(),
            ReadMessagesTool(),
            MarkReadTool(),
            ListAgentsTool(),
            # self-review / critic loop
            CritiqueOutputTool(),
        ]
        for tool in defaults:
            self._tools[tool.name] = tool

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        """Return list of OpenAI-compatible tool schemas for all registered tools."""
        return [t.to_schema() for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False, output=None,
                error=f"Unknown tool: '{name}'. Available: {list(self._tools.keys())}"
            )
        try:
            return await tool.execute(**arguments)
        except TypeError as e:
            return ToolResult(
                success=False, output=None,
                error=f"Invalid arguments for tool '{name}': {e}"
            )
        except Exception as e:
            logger.exception(f"Tool '{name}' raised an exception")
            return ToolResult(success=False, output=None, error=str(e))
