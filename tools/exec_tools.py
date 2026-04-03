"""
Code execution tool — runs python, bash, or node in a sandboxed subprocess
scoped to the workspace directory.
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30   # seconds
_MAX_TIMEOUT     = 120  # hard cap
_MAX_OUTPUT      = 8000  # chars — truncate noisy outputs


class RunCodeTool(BaseTool):
    name = "run_code"
    description = (
        "Execute code in a sandboxed subprocess and return stdout, stderr, and exit code. "
        "Use this to run scripts, test implementations, process data, or verify your work. "
        "Supported languages: python, bash, node. "
        "Execution is scoped to the workspace directory. "
        "Output is capped at 8000 characters. Default timeout: 30 seconds (max 120)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": ["python", "bash", "node"],
                "description": "Programming language / interpreter to use.",
            },
            "code": {
                "type": "string",
                "description": "Source code to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (1‑120, default 30).",
            },
        },
        "required": ["language", "code"],
    }

    _SUFFIX = {"python": ".py", "bash": ".sh", "node": ".js"}
    _INTERPRETER = {"python": "python3", "bash": "bash", "node": "node"}

    async def execute(self, language: str, code: str, timeout: int = _DEFAULT_TIMEOUT) -> ToolResult:
        if language not in self._INTERPRETER:
            return ToolResult(
                success=False, output=None,
                error=f"Unsupported language '{language}'. Allowed: python, bash, node.",
            )

        timeout = min(max(1, int(timeout)), _MAX_TIMEOUT)
        workspace = config.workspace.path
        workspace.mkdir(parents=True, exist_ok=True)

        try:
            suffix = self._SUFFIX[language]
            interpreter = self._INTERPRETER[language]

            # Write to a temp file — avoids any shell-injection risk
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, dir=str(workspace),
                delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = Path(f.name)

            try:
                proc = await asyncio.create_subprocess_exec(
                    interpreter, str(tmp_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(workspace),
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                try:
                    stdout_b, stderr_b = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return ToolResult(
                        success=False, output=None,
                        error=f"Execution timed out after {timeout}s.",
                    )
            finally:
                tmp_path.unlink(missing_ok=True)

            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            exit_code = proc.returncode

            parts = []
            if stdout.strip():
                out = stdout[:_MAX_OUTPUT]
                if len(stdout) > _MAX_OUTPUT:
                    out += f"\n… [truncated — {len(stdout)} chars total]"
                parts.append(f"STDOUT:\n{out}")
            if stderr.strip():
                err = stderr[:_MAX_OUTPUT]
                if len(stderr) > _MAX_OUTPUT:
                    err += "\n… [truncated]"
                parts.append(f"STDERR:\n{err}")
            parts.append(f"EXIT CODE: {exit_code}")

            output = "\n\n".join(parts)
            success = exit_code == 0
            return ToolResult(
                success=success,
                output=output,
                error="" if success else f"Process exited with code {exit_code}",
            )

        except FileNotFoundError:
            return ToolResult(
                success=False, output=None,
                error=f"Interpreter '{self._INTERPRETER[language]}' not found on this system.",
            )
        except Exception as e:
            logger.exception("run_code raised an unexpected error")
            return ToolResult(success=False, output=None, error=str(e))
