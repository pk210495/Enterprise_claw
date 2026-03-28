import logging
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

# ── Protected paths — agent can NEVER write to these ────────────────────────
_PROTECTED = [
    config.security_path,
    config.security_hash_path,
    config.soul_path,
    config.core_skills_dir,
]


def _is_protected(path: Path) -> bool:
    resolved = path.resolve()
    for p in _PROTECTED:
        rp = p.resolve()
        if resolved == rp or str(resolved).startswith(str(rp)):
            return True
    return False


def _safe_path(relative: str) -> tuple[Path, str | None]:
    """
    Resolve path inside workspace.
    Returns (resolved_path, error_msg).
    error_msg is None if safe.
    """
    workspace = config.workspace.path.resolve()
    try:
        target = (workspace / relative).resolve()
    except Exception as e:
        return workspace, f"Invalid path: {e}"

    if not str(target).startswith(str(workspace)):
        return workspace, f"Path traversal blocked: '{relative}' is outside workspace."

    ext = target.suffix.lower()
    if ext and ext not in config.workspace.allowed_extensions:
        return target, f"Extension '{ext}' not allowed. Allowed: {config.workspace.allowed_extensions}"

    return target, None


# ── Tools ────────────────────────────────────────────────────────────────────

class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List all files in the workspace directory. Returns relative file paths."
    parameters = {
        "type": "object",
        "properties": {
            "subdir": {
                "type": "string",
                "description": "Optional subdirectory to list. Defaults to workspace root.",
            }
        },
        "required": [],
    }

    async def execute(self, subdir: str = "") -> ToolResult:
        try:
            base = config.workspace.path.resolve()
            target = (base / subdir).resolve() if subdir else base
            if not str(target).startswith(str(base)):
                return ToolResult(success=False, output=None, error="Path outside workspace.")
            if not target.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {subdir}")
            files = []
            for f in sorted(target.rglob("*")):
                if f.is_file() and f.suffix in config.workspace.allowed_extensions:
                    files.append(str(f.relative_to(base)))
            return ToolResult(success=True, output="\n".join(files) if files else "(workspace is empty)")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the full content of a file in the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to the file, e.g. 'README.md'"}
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if not target.exists():
            return ToolResult(success=False, output=None, error=f"File not found: {path}")
        try:
            content = target.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write (overwrite) a file in the workspace with new content. Use edit_file for surgical changes."
    parameters = {
        "type": "object",
        "properties": {
            "path":    {"type": "string", "description": "Relative path to the file"},
            "content": {"type": "string", "description": "Full content to write"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str) -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if _is_protected(target):
            return ToolResult(
                success=False, output=None,
                error="SECURITY VIOLATION: This file is protected and cannot be modified by the agent."
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"File written: {path}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Surgically edit a file by replacing a specific section of text. "
        "Provide the exact old_text to find and new_text to replace it with. "
        "Fails if old_text is not found."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path":     {"type": "string", "description": "Relative path to the file"},
            "old_text": {"type": "string", "description": "Exact text to find and replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def execute(self, path: str, old_text: str, new_text: str) -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if _is_protected(target):
            return ToolResult(
                success=False, output=None,
                error="SECURITY VIOLATION: This file is protected and cannot be modified by the agent."
            )
        if not target.exists():
            return ToolResult(success=False, output=None, error=f"File not found: {path}")
        try:
            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(success=False, output=None, error="old_text not found in file. No changes made.")
            updated = content.replace(old_text, new_text, 1)
            target.write_text(updated, encoding="utf-8")
            return ToolResult(success=True, output=f"Edit applied to {path}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CreateFileTool(BaseTool):
    name = "create_file"
    description = "Create a new file in the workspace. Fails if file already exists."
    parameters = {
        "type": "object",
        "properties": {
            "path":    {"type": "string", "description": "Relative path for the new file"},
            "content": {"type": "string", "description": "Initial content (can be empty string)"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str = "") -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if _is_protected(target):
            return ToolResult(success=False, output=None, error="SECURITY VIOLATION: Protected path.")
        if target.exists():
            return ToolResult(success=False, output=None, error=f"File already exists: {path}. Use write_file to overwrite.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"File created: {path}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file from the workspace. Cannot be undone — use with caution."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to the file to delete"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if _is_protected(target):
            return ToolResult(success=False, output=None, error="SECURITY VIOLATION: Protected path.")
        if not target.exists():
            return ToolResult(success=False, output=None, error=f"File not found: {path}")
        try:
            target.unlink()
            return ToolResult(success=True, output=f"Deleted: {path}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AppendFileTool(BaseTool):
    name = "append_to_file"
    description = "Append text to the end of an existing file."
    parameters = {
        "type": "object",
        "properties": {
            "path":    {"type": "string", "description": "Relative path to the file"},
            "content": {"type": "string", "description": "Text to append"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str) -> ToolResult:
        target, err = _safe_path(path)
        if err:
            return ToolResult(success=False, output=None, error=err)
        if _is_protected(target):
            return ToolResult(success=False, output=None, error="SECURITY VIOLATION: Protected path.")
        if not target.exists():
            return ToolResult(success=False, output=None, error=f"File not found: {path}")
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output=f"Appended to {path}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
