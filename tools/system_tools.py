import os
from datetime import datetime, timezone
from .base import BaseTool, ToolResult
from config import config


class GetDatetimeTool(BaseTool):
    name = "get_datetime"
    description = "Get the current date and time in UTC."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        now = datetime.now(timezone.utc)
        return ToolResult(success=True, output=now.strftime("%Y-%m-%d %H:%M:%S UTC"))


class GetWorkspaceStatsTool(BaseTool):
    name = "get_workspace_stats"
    description = "Get statistics about the workspace — file count, total size."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        try:
            workspace = config.workspace.path.resolve()
            if not workspace.exists():
                return ToolResult(success=True, output="Workspace is empty.")
            files = [
                f for f in workspace.rglob("*")
                if f.is_file() and f.suffix in config.workspace.allowed_extensions
            ]
            total_bytes = sum(f.stat().st_size for f in files)
            lines = [
                f"Files: {len(files)}",
                f"Total size: {total_bytes / 1024:.1f} KB",
                f"Path: {workspace}",
            ]
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetSessionInfoTool(BaseTool):
    name = "get_session_info"
    description = "Get information about active sessions."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        try:
            sessions_dir = config.sessions_dir
            if not sessions_dir.exists():
                return ToolResult(success=True, output="No sessions found.")
            sessions = sorted(sessions_dir.glob("*.jsonl"))
            lines = [f"Active sessions ({len(sessions)}):"]
            for s in sessions:
                size_kb = s.stat().st_size / 1024
                lines.append(f"  - {s.stem}  ({size_kb:.1f} KB)")
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
