import logging
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)


class RememberTool(BaseTool):
    name = "remember"
    description = (
        "Save information to long-term memory. This persists across all sessions forever. "
        "Use this when the user shares important facts about themselves, their preferences, "
        "ongoing projects, decisions made, or anything that should be remembered in future conversations. "
        "Provide a clear key (e.g. 'user_profile', 'project_context', 'decisions') and the content to store."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Memory file key, e.g. 'user_profile', 'project_context', 'facts', 'decisions'",
            },
            "content": {
                "type": "string",
                "description": "Information to store. Will append to existing content for this key.",
            },
        },
        "required": ["key", "content"],
    }

    async def execute(self, key: str, content: str) -> ToolResult:
        try:
            mem_dir = config.memory_dir
            mem_dir.mkdir(parents=True, exist_ok=True)

            # sanitise key to safe filename
            safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
            file_path = mem_dir / f"{safe_key}.md"

            if file_path.exists():
                existing = file_path.read_text(encoding="utf-8")
                updated = existing.rstrip() + "\n\n" + content
            else:
                updated = f"# {key}\n\n{content}"

            file_path.write_text(updated, encoding="utf-8")

            # update index
            _update_memory_index(mem_dir)

            return ToolResult(success=True, output=f"Remembered under '{key}'.")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RecallTool(BaseTool):
    name = "recall"
    description = (
        "Read from long-term memory. Provide a key to retrieve a specific memory file, "
        "or use 'all' to get everything remembered. "
        "Use this when you need to check what was previously stored about the user or project."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Memory key to retrieve, e.g. 'user_profile'. Use 'all' to get all memories.",
            }
        },
        "required": ["key"],
    }

    async def execute(self, key: str) -> ToolResult:
        try:
            mem_dir = config.memory_dir
            if not mem_dir.exists():
                return ToolResult(success=True, output="(no memories stored yet)")

            if key == "all":
                parts = []
                for f in sorted(mem_dir.glob("*.md")):
                    if f.name == "index.md":
                        continue
                    parts.append(f"## {f.stem}\n{f.read_text(encoding='utf-8')}")
                return ToolResult(
                    success=True,
                    output="\n\n---\n\n".join(parts) if parts else "(no memories stored yet)"
                )

            safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
            file_path = mem_dir / f"{safe_key}.md"
            if not file_path.exists():
                return ToolResult(success=False, output=None, error=f"No memory found for key '{key}'.")

            return ToolResult(success=True, output=file_path.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


def _update_memory_index(mem_dir: Path) -> None:
    """Rebuild the index.md file listing all memory keys."""
    try:
        files = sorted(f for f in mem_dir.glob("*.md") if f.name != "index.md")
        lines = ["# Memory Index\n"]
        for f in files:
            lines.append(f"- **{f.stem}** → `{f.name}`")
        (mem_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to update memory index: {e}")


def load_all_memories() -> str:
    """
    Load all long-term memory files into a single string.
    Called at session start to inject into the system prompt.
    """
    mem_dir = config.memory_dir
    if not mem_dir.exists():
        return ""
    parts = []
    for f in sorted(mem_dir.glob("*.md")):
        if f.name == "index.md":
            continue
        try:
            parts.append(f.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    return "\n\n".join(parts)
