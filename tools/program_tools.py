"""
Research program tools — "Program the Programmer" pattern from Karpathy's autoresearch.

Key insight: "You don't optimize train.py — you optimize program.md.
You're programming the programmer."

The program.md file is the human's interface to direct the agent's research.
It contains three registers (Karpathy's exact framing):
  1. Instructions  — what to search for / explore
  2. Constraints   — what must not change (immutable boundaries)
  3. Stopping criteria — when to conclude the research session

The agent reads this at the start of every research loop iteration.
Humans update it to redirect the agent without touching code.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

_PROGRAM_FILENAME = "program.md"
_PROGRAM_TEMPLATE = """\
# Research Program

## Instructions
<!-- What should the agent explore? Be specific. -->
<!-- Example: "Explore learning rate schedules for the transformer model in train.py.
     Try cosine annealing, warmup+decay, and cyclic schedules.
     Target: reduce val_loss benchmark by at least 5%." -->

{instructions}

## Constraints
<!-- What must the agent NOT change? These are hard boundaries. -->
<!-- Example: -->
<!-- - Do not modify the model architecture -->
<!-- - Do not change the dataset or data preprocessing -->
<!-- - Keep batch size at 32 -->
<!-- - Do not add new dependencies -->

{constraints}

## Stopping Criteria
<!-- When should the agent stop and report? -->
<!-- Example: -->
<!-- - Stop after 20 experiments -->
<!-- - Stop if val_loss drops below 2.5 -->
<!-- - Stop if no improvement in 5 consecutive experiments -->

{stopping_criteria}

## Notes
<!-- Human notes, context, observations — not read by the agent loop, for reference only -->

{notes}
"""


def _program_path() -> Path:
    return config.research_dir / _PROGRAM_FILENAME


def _ensure_program_exists() -> None:
    path = _program_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _PROGRAM_TEMPLATE.format(
                instructions="(not yet set — update this file to direct the research agent)",
                constraints="- Do not modify benchmark evaluation code\n- Do not change data pipelines",
                stopping_criteria="- Stop after 10 experiments\n- Stop if no improvement in 3 consecutive experiments",
                notes="",
            ),
            encoding="utf-8",
        )


# ── Tools ─────────────────────────────────────────────────────────────────────

class ReadResearchProgramTool(BaseTool):
    name = "read_research_program"
    description = (
        "Read the current research program — the human-set instructions, constraints, "
        "and stopping criteria that direct this research session. "
        "Always call this at the start of every research loop iteration to understand "
        "what to explore and what boundaries must not be crossed. "
        "The program.md file is the human's primary interface to direct your work."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        _ensure_program_exists()
        try:
            content = _program_path().read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class WriteResearchProgramTool(BaseTool):
    name = "write_research_program"
    description = (
        "Update the research program that directs the agent's research loop. "
        "Use this to refine the research direction based on what you've learned so far. "
        "You can update instructions (what to explore next), constraints (new boundaries discovered), "
        "or stopping criteria (adjust based on progress). "
        "The human can also edit program.md directly at any time to redirect the agent."
    )
    parameters = {
        "type": "object",
        "properties": {
            "instructions": {
                "type": "string",
                "description": "What the agent should explore — be specific about hypotheses and targets",
            },
            "constraints": {
                "type": "string",
                "description": "What must not change — hard boundaries the agent cannot cross",
            },
            "stopping_criteria": {
                "type": "string",
                "description": "When to stop — experiment count, metric threshold, or consecutive failures",
            },
            "notes": {
                "type": "string",
                "description": "Human-readable notes and context (not used by the experiment loop)",
            },
        },
        "required": ["instructions"],
    }

    async def execute(
        self,
        instructions: str,
        constraints: str = "- Do not modify benchmark evaluation code",
        stopping_criteria: str = "- Stop after 10 experiments",
        notes: str = "",
    ) -> ToolResult:
        try:
            content = _PROGRAM_TEMPLATE.format(
                instructions=instructions,
                constraints=constraints,
                stopping_criteria=stopping_criteria,
                notes=notes,
            )
            _program_path().parent.mkdir(parents=True, exist_ok=True)
            _program_path().write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"Research program updated. The agent will follow this direction on the next loop iteration.\n\n{content}",
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetResearchStatusTool(BaseTool):
    name = "get_research_status"
    description = (
        "Get a summary of the current research session: "
        "program direction, active benchmarks, experiment count, and recent improvements. "
        "Use this for a quick orientation at the start of a session."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        import json
        _ensure_program_exists()
        try:
            research_dir = config.research_dir

            # Program summary
            program = _program_path().read_text(encoding="utf-8")
            # Extract just the Instructions section
            instructions_section = ""
            in_instructions = False
            for line in program.splitlines():
                if line.startswith("## Instructions"):
                    in_instructions = True
                    continue
                if line.startswith("## ") and in_instructions:
                    break
                if in_instructions and not line.startswith("<!--"):
                    instructions_section += line + "\n"

            # Benchmark summary
            bench_dir = research_dir / "benchmarks"
            bench_lines = []
            if bench_dir.exists():
                for mp in sorted(bench_dir.glob("*.meta.json")):
                    try:
                        m = json.loads(mp.read_text())
                        hist_path = bench_dir / f"{m['name']}.history.jsonl"
                        runs = 0
                        improvements = 0
                        if hist_path.exists():
                            with open(hist_path) as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        r = json.loads(line)
                                        if r.get("type") == "run":
                                            runs += 1
                                            if r.get("improved"):
                                                improvements += 1
                                    except Exception:
                                        pass
                        bench_lines.append(
                            f"  {m['name']}: baseline={m['baseline']} → best={m['current_best']} "
                            f"({runs} runs, {improvements} improvements)"
                        )
                    except Exception:
                        pass

            # Journal summary
            journal_path = research_dir / "journal.jsonl"
            total_experiments = 0
            total_findings = 0
            if journal_path.exists():
                with open(journal_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            r = json.loads(line)
                            if r.get("type") == "experiment":
                                total_experiments += 1
                            elif r.get("type") == "finding":
                                total_findings += 1
                        except Exception:
                            pass

            lines = [
                "═══ RESEARCH STATUS ═══",
                "",
                "[ Research Direction ]",
                instructions_section.strip() or "(not set)",
                "",
                "[ Benchmarks ]",
            ]
            if bench_lines:
                lines.extend(bench_lines)
            else:
                lines.append("  (no benchmarks defined)")
            lines += [
                "",
                f"[ Session Stats ]",
                f"  Total experiments logged: {total_experiments}",
                f"  Confirmed findings:       {total_findings}",
            ]

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
