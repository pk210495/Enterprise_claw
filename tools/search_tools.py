import re
import logging
from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)


class SearchInFilesTool(BaseTool):
    name = "search_in_files"
    description = (
        "Search for a keyword or phrase across all files in the workspace. "
        "Returns matching lines with file names and line numbers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for. Supports simple regex.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether to match case. Defaults to false.",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, case_sensitive: bool = False) -> ToolResult:
        try:
            workspace = config.workspace.path.resolve()
            if not workspace.exists():
                return ToolResult(success=True, output="(workspace is empty)")

            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(query, flags)
            except re.error as e:
                return ToolResult(success=False, output=None, error=f"Invalid regex: {e}")

            results = []
            for file_path in sorted(workspace.rglob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix not in config.workspace.allowed_extensions:
                    continue
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                    rel = str(file_path.relative_to(workspace))
                    for i, line in enumerate(lines, 1):
                        if pattern.search(line):
                            results.append(f"{rel}:{i}: {line.strip()}")
                except Exception:
                    pass

            if not results:
                return ToolResult(success=True, output=f"No matches found for '{query}'.")
            return ToolResult(success=True, output="\n".join(results))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
