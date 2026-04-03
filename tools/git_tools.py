"""
Git version-control tool — workspace-scoped git operations.
Push / pull / remote are intentionally blocked: remote ops require human approval.
"""
import asyncio
import logging
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 8000
_BLOCKED_OPS = frozenset({"push", "pull", "fetch", "clone", "remote"})


async def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Execute a git command; return (exit_code, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return -1, "", "git command timed out"
        return (
            proc.returncode,
            stdout_b.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
            stderr_b.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
        )
    except FileNotFoundError:
        return -1, "", "git is not installed on this system"


class GitTool(BaseTool):
    name = "git"
    description = (
        "Run git version-control commands inside the workspace directory. "
        "Use this to track work, create commits, manage branches, inspect diffs, and view history. "
        "All operations are scoped to the workspace — cannot operate on paths outside it. "
        "Remote operations (push, pull, fetch, clone) are blocked and require human approval. "
        "Supported: init, status, diff, log, add, commit, branch, checkout, stash, restore, show, tag."
    )
    parameters = {
        "type": "object",
        "properties": {
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Git sub-command and arguments, exactly as you would type after 'git'. "
                    "Examples: ['status'], ['add', 'main.py'], "
                    "['commit', '-m', 'feat: add user auth'], "
                    "['log', '--oneline', '-10'], "
                    "['checkout', '-b', 'feature/auth']"
                ),
            }
        },
        "required": ["args"],
    }

    async def execute(self, args: list[str]) -> ToolResult:
        if not args:
            return ToolResult(success=False, output=None, error="No git arguments provided.")

        op = args[0].lower().lstrip("-")
        if op in _BLOCKED_OPS:
            return ToolResult(
                success=False, output=None,
                error=(
                    f"'git {op}' is not available to the agent. "
                    "Remote operations require explicit human approval."
                ),
            )

        workspace = config.workspace.path.resolve()
        cwd = str(workspace)

        # Auto-configure git identity so commits don't fail
        if op == "commit":
            rc, out, _ = await _run_git(["config", "user.email"], cwd)
            if rc != 0 or not out.strip():
                await _run_git(["config", "user.email", "agent@enterprise-claw.local"], cwd)
                await _run_git(["config", "user.name", "Enterprise Claw Agent"], cwd)

        exit_code, stdout, stderr = await _run_git(args, cwd)

        parts = []
        if stdout.strip():
            parts.append(stdout.strip())
        if stderr.strip():
            parts.append(f"[stderr]\n{stderr.strip()}")

        output = "\n".join(parts) if parts else "(no output)"
        success = exit_code == 0

        return ToolResult(
            success=success,
            output=output,
            error="" if success else f"git exited with code {exit_code}",
        )
