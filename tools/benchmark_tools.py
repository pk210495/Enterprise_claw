"""
Benchmark system — Karpathy's immutable evaluation lock principle.

Core insight: "If you don't have evals, you can't tell whether your agent got
better or worse after a change — you're guessing."

Design rules (directly from autoresearch):
1. Benchmarks are WRITE-ONCE — agent cannot modify an evaluation after it's defined
2. Scores are tracked as a monotonic ratchet — baseline can only improve
3. A single, unambiguous metric per benchmark — prevents confusion and reward hacking
4. Simplicity criterion enforced in score comparison — tie goes to the simpler solution
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bench_dir() -> Path:
    d = config.research_dir / "benchmarks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(name: str) -> Path:
    return _bench_dir() / f"{name}.meta.json"


def _code_path(name: str) -> Path:
    return _bench_dir() / f"{name}.eval.py"


def _history_path(name: str) -> Path:
    return _bench_dir() / f"{name}.history.jsonl"


def _load_meta(name: str) -> dict | None:
    p = _meta_path(name)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _append_history(name: str, record: dict) -> None:
    with open(_history_path(name), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_history(name: str) -> list[dict]:
    p = _history_path(name)
    if not p.exists():
        return []
    records = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ── Tools ─────────────────────────────────────────────────────────────────────

class DefineBenchmarkTool(BaseTool):
    name = "define_benchmark"
    description = (
        "Define an immutable evaluation benchmark. "
        "CRITICAL: Once defined, the evaluation code CANNOT be changed. "
        "This is intentional — it prevents reward hacking and ensures all future "
        "experiments are measured on the same unchanging ground truth. "
        "Think carefully before defining a benchmark. The metric must be unambiguous: "
        "a single number, where lower_is_better is clearly true or false. "
        "Examples: validation loss (lower), accuracy (higher), latency_ms (lower), f1_score (higher)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Benchmark identifier, e.g. 'val_loss', 'test_accuracy', 'latency_p99'",
            },
            "description": {
                "type": "string",
                "description": "What this benchmark measures and why it matters",
            },
            "eval_code": {
                "type": "string",
                "description": (
                    "Python code that computes and PRINTS a single numeric score. "
                    "The code runs in the workspace directory. "
                    "It MUST print exactly one number on stdout as the final line. "
                    "Example: print(compute_validation_loss(model, val_data))"
                ),
            },
            "metric_name": {
                "type": "string",
                "description": "Name of the metric being measured, e.g. 'val_loss', 'accuracy_%'",
            },
            "lower_is_better": {
                "type": "boolean",
                "description": "True if lower scores are better (loss, error rate), False if higher is better (accuracy, F1)",
            },
            "baseline": {
                "type": "number",
                "description": "Starting baseline score (the score before any improvements). Required.",
            },
        },
        "required": ["name", "description", "eval_code", "metric_name", "lower_is_better", "baseline"],
    }

    async def execute(
        self,
        name: str,
        description: str,
        eval_code: str,
        metric_name: str,
        lower_is_better: bool,
        baseline: float,
    ) -> ToolResult:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

        if _meta_path(safe_name).exists():
            return ToolResult(
                success=False, output=None,
                error=(
                    f"Benchmark '{safe_name}' already exists and is immutable. "
                    "You cannot redefine an existing benchmark — this protects measurement integrity. "
                    "Create a new benchmark with a different name if you need a different evaluation."
                ),
            )

        try:
            # Write immutable eval code
            _code_path(safe_name).write_text(eval_code, encoding="utf-8")

            # Write metadata
            meta = {
                "name":            safe_name,
                "description":     description,
                "metric_name":     metric_name,
                "lower_is_better": lower_is_better,
                "baseline":        baseline,
                "current_best":    baseline,
                "created_at":      _now(),
                "run_count":       0,
            }
            _meta_path(safe_name).write_text(json.dumps(meta, indent=2), ensure_ascii=False)

            # Record baseline in history
            _append_history(safe_name, {
                "type":       "baseline",
                "score":      baseline,
                "improved":   False,
                "timestamp":  _now(),
                "note":       "Initial baseline",
            })

            return ToolResult(
                success=True,
                output=(
                    f"Benchmark '{safe_name}' defined and locked.\n"
                    f"Metric: {metric_name} ({'lower is better' if lower_is_better else 'higher is better'})\n"
                    f"Baseline: {baseline}\n"
                    f"Eval code is now immutable — all future experiments measure against this exact evaluation."
                ),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RunBenchmarkTool(BaseTool):
    name = "run_benchmark"
    description = (
        "Run a benchmark evaluation and compare the result against the current best baseline. "
        "Returns the score, whether it improved over baseline, and the improvement delta. "
        "Use this after every experiment to determine whether to keep (git commit) or discard (git reset) the change. "
        "The ratchet rule: only improvements advance the baseline. Regressions are automatically rejected."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Benchmark name to run",
            },
            "note": {
                "type": "string",
                "description": "What change was tested in this run (for the experiment log)",
            },
        },
        "required": ["name"],
    }

    async def execute(self, name: str, note: str = "") -> ToolResult:
        import asyncio, tempfile, os
        from pathlib import Path as P

        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        meta = _load_meta(safe_name)
        if meta is None:
            return ToolResult(
                success=False, output=None,
                error=f"Benchmark '{safe_name}' not found. Use define_benchmark first.",
            )

        eval_code = _code_path(safe_name).read_text(encoding="utf-8")
        workspace = str(config.workspace.path)

        # Write eval code to temp file and execute
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", dir=workspace,
                delete=False, encoding="utf-8"
            ) as f:
                f.write(eval_code)
                tmp = f.name

            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", tmp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=workspace,
                )
                try:
                    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return ToolResult(
                        success=False, output=None,
                        error="Benchmark timed out after 300s",
                    )
            finally:
                P(tmp).unlink(missing_ok=True)

            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            stdout_text = stdout_b.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                return ToolResult(
                    success=False, output=None,
                    error=f"Benchmark eval code failed (exit {proc.returncode}):\n{stderr_text}",
                )

            # Extract score from last line of stdout
            last_line = stdout_text.split("\n")[-1].strip()
            try:
                score = float(last_line)
            except ValueError:
                return ToolResult(
                    success=False, output=None,
                    error=(
                        f"Benchmark eval code must print a single number as its last line. "
                        f"Got: '{last_line}'\nFull stdout:\n{stdout_text}"
                    ),
                )

            # Compare against current best
            current_best = meta["current_best"]
            lower_is_better = meta["lower_is_better"]
            improved = score < current_best if lower_is_better else score > current_best

            delta = current_best - score if lower_is_better else score - current_best
            delta_pct = (abs(delta) / abs(current_best) * 100) if current_best != 0 else 0.0

            # Ratchet: only advance baseline if improved
            if improved:
                meta["current_best"] = score
                meta["run_count"] = meta.get("run_count", 0) + 1
                _meta_path(safe_name).write_text(json.dumps(meta, indent=2), ensure_ascii=False)

            _append_history(safe_name, {
                "type":      "run",
                "score":     score,
                "baseline":  current_best,
                "improved":  improved,
                "delta":     delta,
                "delta_pct": round(delta_pct, 3),
                "note":      note,
                "timestamp": _now(),
            })

            verdict = "IMPROVED ✓" if improved else "NO IMPROVEMENT ✗"
            direction = "lower" if lower_is_better else "higher"

            return ToolResult(
                success=True,
                output=(
                    f"Benchmark: {safe_name}  [{verdict}]\n"
                    f"Score:        {score}  ({direction} is better)\n"
                    f"Previous best: {current_best}\n"
                    f"Delta:        {'+' if improved else ''}{delta:.6f}  ({delta_pct:.2f}%)\n"
                    f"Action:       {'→ git commit and advance baseline' if improved else '→ git reset — discard this change'}"
                ),
            )

        except Exception as e:
            logger.exception("run_benchmark failed")
            return ToolResult(success=False, output=None, error=str(e))


class GetBenchmarkHistoryTool(BaseTool):
    name = "get_benchmark_history"
    description = (
        "View the full score history for a benchmark — all runs, improvements, and null results. "
        "Use this to understand what has been tried and what the improvement trajectory looks like."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name":  {"type": "string", "description": "Benchmark name"},
            "limit": {"type": "integer", "description": "Max history entries to show (default 20)"},
        },
        "required": ["name"],
    }

    async def execute(self, name: str, limit: int = 20) -> ToolResult:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        meta = _load_meta(safe_name)
        if meta is None:
            return ToolResult(
                success=False, output=None,
                error=f"Benchmark '{safe_name}' not found.",
            )

        history = _load_history(safe_name)
        runs = [h for h in history if h.get("type") == "run"]
        total = len(runs)
        improvements = sum(1 for h in runs if h.get("improved"))

        lines = [
            f"Benchmark: {safe_name}",
            f"Metric:    {meta['metric_name']} ({'lower' if meta['lower_is_better'] else 'higher'} is better)",
            f"Baseline:  {meta['baseline']}",
            f"Best:      {meta['current_best']}",
            f"Runs:      {total}  ({improvements} improvements, {total - improvements} null results)",
            "",
            "Recent history:",
        ]

        for h in history[-limit:]:
            t = h.get("type", "run")
            if t == "baseline":
                lines.append(f"  [BASELINE  ] {h['score']}  —  {h.get('note','')}")
            else:
                icon = "✓" if h.get("improved") else "✗"
                delta_str = f"{h.get('delta_pct', 0):.2f}%"
                lines.append(
                    f"  [{icon}] {h['score']:.6f}  Δ{delta_str:<8}  {h.get('note','')[:60]}"
                )

        return ToolResult(success=True, output="\n".join(lines))


class ListBenchmarksTool(BaseTool):
    name = "list_benchmarks"
    description = "List all defined benchmarks and their current best scores."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        bench_dir = _bench_dir()
        metas = sorted(bench_dir.glob("*.meta.json"))
        if not metas:
            return ToolResult(
                success=True,
                output="No benchmarks defined yet. Use define_benchmark to create one.",
            )
        lines = [f"{'Name':<20}  {'Metric':<20}  {'Baseline':>12}  {'Best':>12}  {'Runs':>5}"]
        lines.append("-" * 75)
        for mp in metas:
            try:
                m = json.loads(mp.read_text())
                lines.append(
                    f"{m['name']:<20}  {m['metric_name']:<20}  "
                    f"{m['baseline']:>12.6g}  {m['current_best']:>12.6g}  "
                    f"{m.get('run_count', 0):>5}"
                )
            except Exception:
                pass
        return ToolResult(success=True, output="\n".join(lines))
