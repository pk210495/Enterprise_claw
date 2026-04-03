"""
Experiment journal — structured research memory.

Karpathy's insight: The git history IS the research memory for autoresearch.
But Enterprise Claw needs richer metadata: hypotheses before they're tested,
null results (as important as improvements), confirmed findings, and the
cumulative knowledge that survives across sessions.

Three log types (all in storage/research/journal.jsonl):
  1. hypothesis  — formed before an experiment (the "what if")
  2. experiment  — the result of running an experiment (improved or null)
  3. finding     — a confirmed, useful discovery worth building on

The simplicity criterion (Karpathy): improvements from messy code are penalised.
A 0.001% gain from 20 lines of hacky code is not worth keeping.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _journal_path() -> Path:
    p = config.research_dir / "journal.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _append(record: dict) -> None:
    with open(_journal_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_journal(type_filter: str | None = None, limit: int = 50) -> list[dict]:
    path = _journal_path()
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if type_filter is None or r.get("type") == type_filter:
                    records.append(r)
            except json.JSONDecodeError:
                pass
    return records[-limit:]


# ── Tools ─────────────────────────────────────────────────────────────────────

class LogHypothesisTool(BaseTool):
    name = "log_hypothesis"
    description = (
        "Record a hypothesis BEFORE running an experiment. "
        "This is step 1 of the experiment loop: form and commit a hypothesis, "
        "then test it. This prevents post-hoc rationalization and builds a "
        "real record of what you expected vs what happened. "
        "Returns a hypothesis_id to reference when logging the experiment result."
    )
    parameters = {
        "type": "object",
        "properties": {
            "hypothesis": {
                "type": "string",
                "description": "Specific, testable hypothesis. E.g.: 'Adding gradient clipping at 1.0 will reduce val_loss by reducing instability during training on long sequences'",
            },
            "rationale": {
                "type": "string",
                "description": "Why you think this will work — theory, prior art, intuition",
            },
            "change_plan": {
                "type": "string",
                "description": "Exactly what you plan to change to test this hypothesis",
            },
            "benchmark": {
                "type": "string",
                "description": "Which benchmark you'll use to evaluate this hypothesis",
            },
        },
        "required": ["hypothesis", "rationale", "change_plan"],
    }

    async def execute(
        self,
        hypothesis: str,
        rationale: str,
        change_plan: str,
        benchmark: str = "",
    ) -> ToolResult:
        hyp_id = str(uuid.uuid4())[:8]
        record = {
            "type":        "hypothesis",
            "id":          hyp_id,
            "hypothesis":  hypothesis,
            "rationale":   rationale,
            "change_plan": change_plan,
            "benchmark":   benchmark,
            "timestamp":   _now(),
        }
        try:
            _append(record)
            return ToolResult(
                success=True,
                output=(
                    f"Hypothesis logged (ID: {hyp_id}).\n\n"
                    f"Hypothesis: {hypothesis}\n"
                    f"Rationale:  {rationale}\n"
                    f"Plan:       {change_plan}\n\n"
                    f"Now implement the change, run the benchmark, and call log_experiment with hypothesis_id='{hyp_id}'."
                ),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class LogExperimentTool(BaseTool):
    name = "log_experiment"
    description = (
        "Record the result of a completed experiment. "
        "Call this after run_benchmark to capture what was tested and what happened. "
        "Include the hypothesis_id from log_hypothesis to link the result to its hypothesis. "
        "Be honest about null results — they are as scientifically valuable as improvements. "
        "The simplicity_penalty field enforces Karpathy's simplicity criterion: "
        "a small gain from complex code may not be worth keeping."
    )
    parameters = {
        "type": "object",
        "properties": {
            "hypothesis_id":     {"type": "string",  "description": "ID from log_hypothesis (links result to its hypothesis)"},
            "what_was_changed":  {"type": "string",  "description": "Exact description of what was modified"},
            "benchmark":         {"type": "string",  "description": "Benchmark name used to evaluate"},
            "score_before":      {"type": "number",  "description": "Score before the change (baseline)"},
            "score_after":       {"type": "number",  "description": "Score after the change"},
            "improved":          {"type": "boolean", "description": "Whether the benchmark score improved"},
            "lines_changed":     {"type": "integer", "description": "Approximate lines of code added/modified"},
            "simplicity_ok":     {"type": "boolean", "description": "Is the code change simple and readable? (Karpathy simplicity criterion: small gains from messy code are not worth keeping)"},
            "kept":              {"type": "boolean", "description": "Was this change committed (True) or discarded via git reset (False)?"},
            "notes":             {"type": "string",  "description": "What you learned — even from null results"},
        },
        "required": ["what_was_changed", "benchmark", "score_before", "score_after", "improved", "kept"],
    }

    async def execute(
        self,
        what_was_changed: str,
        benchmark: str,
        score_before: float,
        score_after: float,
        improved: bool,
        kept: bool,
        hypothesis_id: str = "",
        lines_changed: int = 0,
        simplicity_ok: bool = True,
        notes: str = "",
    ) -> ToolResult:
        record = {
            "type":             "experiment",
            "id":               str(uuid.uuid4())[:8],
            "hypothesis_id":    hypothesis_id,
            "what_was_changed": what_was_changed,
            "benchmark":        benchmark,
            "score_before":     score_before,
            "score_after":      score_after,
            "delta":            score_after - score_before,
            "improved":         improved,
            "lines_changed":    lines_changed,
            "simplicity_ok":    simplicity_ok,
            "kept":             kept,
            "notes":            notes,
            "timestamp":        _now(),
        }
        try:
            _append(record)
            verdict = "KEPT ✓" if kept else "DISCARDED ✗"
            reason = ""
            if improved and not simplicity_ok and not kept:
                reason = " (simplicity criterion: improvement too small for complexity added)"
            return ToolResult(
                success=True,
                output=(
                    f"Experiment logged [{verdict}]{reason}\n"
                    f"Change:    {what_was_changed}\n"
                    f"Benchmark: {benchmark}  {score_before} → {score_after}  "
                    f"({'improved' if improved else 'no improvement'})\n"
                    f"Notes:     {notes}"
                ),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class LogFindingTool(BaseTool):
    name = "log_finding"
    description = (
        "Record a confirmed, reusable discovery — something that genuinely worked "
        "and is worth building on in future sessions. "
        "Findings are the distilled knowledge output of the research loop. "
        "Only log something as a finding if it has been validated by the benchmark "
        "and committed to git. Do not log hypotheses or null results as findings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title":       {"type": "string", "description": "Short title of the finding, e.g. 'QK-Norm scalar multiplier was missing'"},
            "description": {"type": "string", "description": "What was discovered and why it works"},
            "evidence":    {"type": "string", "description": "Benchmark score improvement that validates this finding"},
            "impact":      {"type": "string", "description": "Why this finding matters — what it enables or explains"},
            "experiment_id": {"type": "string", "description": "Experiment ID that produced this finding"},
        },
        "required": ["title", "description", "evidence"],
    }

    async def execute(
        self,
        title: str,
        description: str,
        evidence: str,
        impact: str = "",
        experiment_id: str = "",
    ) -> ToolResult:
        record = {
            "type":          "finding",
            "id":            str(uuid.uuid4())[:8],
            "title":         title,
            "description":   description,
            "evidence":      evidence,
            "impact":        impact,
            "experiment_id": experiment_id,
            "timestamp":     _now(),
        }
        try:
            _append(record)
            return ToolResult(
                success=True,
                output=(
                    f"Finding recorded ✓\n"
                    f"Title:    {title}\n"
                    f"Summary:  {description}\n"
                    f"Evidence: {evidence}"
                ),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ReadJournalTool(BaseTool):
    name = "read_journal"
    description = (
        "Read the research journal — all logged hypotheses, experiments, and findings. "
        "Use this at the start of a session to understand what has been tried, "
        "what worked, and what null results to avoid repeating. "
        "Filter by type: 'hypothesis', 'experiment', 'finding', or None for all."
    )
    parameters = {
        "type": "object",
        "properties": {
            "type_filter": {
                "type": "string",
                "enum": ["hypothesis", "experiment", "finding"],
                "description": "Filter to a specific record type (omit for all)",
            },
            "limit": {
                "type": "integer",
                "description": "Max records to return (default 30)",
            },
            "findings_only": {
                "type": "boolean",
                "description": "Shortcut: return only confirmed findings (overrides type_filter)",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        type_filter: str | None = None,
        limit: int = 30,
        findings_only: bool = False,
    ) -> ToolResult:
        if findings_only:
            type_filter = "finding"

        records = _load_journal(type_filter=type_filter, limit=limit)
        if not records:
            label = f"'{type_filter}'" if type_filter else "research journal"
            return ToolResult(
                success=True,
                output=f"No {label} entries yet. The journal is empty.",
            )

        lines = [f"Research journal ({len(records)} records, type={type_filter or 'all'}):\n"]
        for r in records:
            t = r.get("type", "?")
            ts = r.get("timestamp", "?")[:10]
            if t == "hypothesis":
                lines.append(f"[{ts}] HYPOTHESIS {r.get('id','')}:")
                lines.append(f"  {r.get('hypothesis','')}")
                lines.append(f"  Plan: {r.get('change_plan','')}")
            elif t == "experiment":
                icon = "✓" if r.get("kept") else "✗"
                lines.append(
                    f"[{ts}] EXPERIMENT {r.get('id','')} [{icon}]  "
                    f"{r.get('benchmark','?')} {r.get('score_before','?')} → {r.get('score_after','?')}"
                )
                lines.append(f"  Changed: {r.get('what_was_changed','')}")
                if r.get("notes"):
                    lines.append(f"  Notes:   {r['notes']}")
            elif t == "finding":
                lines.append(f"[{ts}] FINDING {r.get('id','')}:  {r.get('title','')}")
                lines.append(f"  {r.get('description','')}")
                lines.append(f"  Evidence: {r.get('evidence','')}")
            lines.append("")

        return ToolResult(success=True, output="\n".join(lines))
