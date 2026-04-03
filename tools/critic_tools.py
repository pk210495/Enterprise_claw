"""
Critique tool — spawns a single critic subagent to review any output
before it reaches the user or is handed to the next stage.

The critic scores the output, identifies issues, and either approves or
requests a revision. This closes the self-correction loop without human input.
"""
import json
import logging

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Injected by orchestrator (same pattern as subagent_tools)
_subagent_runner = None


def set_critic_runner(runner):
    """Called by orchestrator to inject the subagent pool runner."""
    global _subagent_runner
    _subagent_runner = runner


class CritiqueOutputTool(BaseTool):
    name = "critique_output"
    description = (
        "Spawn a critic subagent to review a piece of work before finalising it. "
        "The critic checks whether the output fully meets the original instruction, "
        "identifies any gaps, errors, or improvements, and returns a structured review. "
        "Use this before delivering important outputs — code, documents, plans, analyses. "
        "If the critic scores below 7/10 or marks it not approved, revise and critique again."
    )
    parameters = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "The original task or requirement the output was supposed to fulfil",
            },
            "output": {
                "type": "string",
                "description": "The work to be reviewed — code, text, plan, analysis, etc.",
            },
            "criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional specific criteria to check against, "
                    "e.g. ['handles edge cases', 'follows security constitution', 'has tests']"
                ),
            },
        },
        "required": ["instruction", "output"],
    }

    async def execute(
        self,
        instruction: str,
        output: str,
        criteria: list[str] | None = None,
    ) -> ToolResult:
        if _subagent_runner is None:
            return ToolResult(
                success=False, output=None,
                error="Critic runner not initialised. This is an internal error.",
            )

        criteria_block = ""
        if criteria:
            criteria_block = "\n\nAdditional criteria to check:\n" + "\n".join(
                f"- {c}" for c in criteria
            )

        critic_instruction = (
            "You are a senior technical reviewer. Your job is to critically evaluate "
            "a piece of work against its original requirement.\n\n"
            f"ORIGINAL INSTRUCTION:\n{instruction}\n\n"
            f"OUTPUT TO REVIEW:\n{output}"
            f"{criteria_block}\n\n"
            "Provide your review in this exact JSON format:\n"
            "{\n"
            '  "score": <integer 1-10>,\n'
            '  "approved": <true if score >= 7 and no blockers, else false>,\n'
            '  "summary": "<one sentence verdict>",\n'
            '  "issues": ["<issue 1>", "<issue 2>"],\n'
            '  "suggestions": ["<improvement 1>", "<improvement 2>"],\n'
            '  "missing": ["<thing missing 1>"]\n'
            "}\n\n"
            "Be direct and specific. Do not praise unnecessarily. "
            "Score 10 only if the output is complete, correct, and production-ready."
        )

        try:
            results = await _subagent_runner([{
                "id": "critic",
                "instruction": critic_instruction,
                "context": "You are acting as a quality critic. Return only valid JSON.",
            }])

            critic_result = results[0] if results else {}
            if not critic_result.get("success"):
                return ToolResult(
                    success=False, output=None,
                    error=f"Critic subagent failed: {critic_result.get('error', 'unknown')}",
                )

            raw = critic_result.get("result", "").strip()

            # Extract JSON even if wrapped in markdown
            if "```" in raw:
                import re
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
                if match:
                    raw = match.group(1)

            try:
                review = json.loads(raw)
            except json.JSONDecodeError:
                # Fallback: return raw text
                return ToolResult(success=True, output=f"CRITIC REVIEW:\n{raw}")

            score = review.get("score", "?")
            approved = review.get("approved", False)
            verdict = "APPROVED" if approved else "NEEDS REVISION"

            lines = [
                f"CRITIC REVIEW  [{verdict}]  Score: {score}/10",
                f"Summary: {review.get('summary', '')}",
            ]
            if review.get("issues"):
                lines.append("\nIssues:")
                for i in review["issues"]:
                    lines.append(f"  ✗ {i}")
            if review.get("missing"):
                lines.append("\nMissing:")
                for m in review["missing"]:
                    lines.append(f"  ? {m}")
            if review.get("suggestions"):
                lines.append("\nSuggestions:")
                for s in review["suggestions"]:
                    lines.append(f"  → {s}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
            )

        except Exception as e:
            logger.exception("critique_output failed")
            return ToolResult(success=False, output=None, error=str(e))
