"""
Structured task/plan memory — the agent's internal project management brain.

Tasks are stored as JSONL in storage/plans/tasks.jsonl.
Each task is a JSON object with a stable UUID, status, priority, and optional
parent_id for hierarchical decomposition (epic → story → subtask).
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

_VALID_STATUSES  = {"pending", "in_progress", "blocked", "done", "cancelled"}
_VALID_PRIORITIES = {"low", "normal", "high", "critical"}


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _tasks_path() -> Path:
    return config.plans_dir / "tasks.jsonl"


def _load_tasks() -> list[dict]:
    path = _tasks_path()
    if not path.exists():
        return []
    tasks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    tasks.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("tasks.jsonl: skipping corrupt line")
    return tasks


def _save_tasks(tasks: list[dict]) -> None:
    path = _tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_task(t: dict) -> str:
    tags = ", ".join(t.get("tags", [])) or "—"
    notes = t.get("notes", [])
    lines = [
        f"ID:          {t['id']}",
        f"Title:       {t['title']}",
        f"Status:      {t['status']}",
        f"Priority:    {t['priority']}",
        f"Tags:        {tags}",
        f"Assigned to: {t.get('assigned_to') or '—'}",
        f"Parent:      {t.get('parent_id') or '—'}",
        f"Created:     {t['created_at']}",
        f"Updated:     {t['updated_at']}",
    ]
    if t.get("description"):
        lines.append(f"Description: {t['description']}")
    if notes:
        lines.append("Notes:")
        for n in notes[-5:]:  # show last 5 notes
            lines.append(f"  • {n}")
    return "\n".join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────

class CreateTaskTool(BaseTool):
    name = "create_task"
    description = (
        "Create a new task in the project task board. "
        "Use this to decompose work into trackable units — epics, stories, subtasks. "
        "Tasks are persistent across sessions and form the agent's project memory. "
        "Set parent_id to link a subtask to a parent task for hierarchical planning."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title":       {"type": "string",  "description": "Short, clear task title"},
            "description": {"type": "string",  "description": "Detailed description of what needs to be done"},
            "priority":    {"type": "string",  "enum": ["low", "normal", "high", "critical"], "description": "Task priority (default: normal)"},
            "tags":        {"type": "array",   "items": {"type": "string"}, "description": "Labels, e.g. ['backend', 'auth', 'bug']"},
            "parent_id":   {"type": "string",  "description": "ID of parent task (for subtasks)"},
            "assigned_to": {"type": "string",  "description": "Role or agent name, e.g. 'backend_engineer'"},
        },
        "required": ["title"],
    }

    async def execute(
        self,
        title: str,
        description: str = "",
        priority: str = "normal",
        tags: list[str] | None = None,
        parent_id: str | None = None,
        assigned_to: str | None = None,
    ) -> ToolResult:
        if priority not in _VALID_PRIORITIES:
            priority = "normal"

        task: dict[str, Any] = {
            "id":          str(uuid.uuid4())[:8],
            "title":       title.strip(),
            "description": description.strip(),
            "status":      "pending",
            "priority":    priority,
            "tags":        tags or [],
            "parent_id":   parent_id,
            "assigned_to": assigned_to,
            "notes":       [],
            "created_at":  _now(),
            "updated_at":  _now(),
        }

        try:
            tasks = _load_tasks()
            # Validate parent exists
            if parent_id and not any(t["id"] == parent_id for t in tasks):
                return ToolResult(
                    success=False, output=None,
                    error=f"Parent task '{parent_id}' not found.",
                )
            tasks.append(task)
            _save_tasks(tasks)
            return ToolResult(success=True, output=f"Task created.\n\n{_fmt_task(task)}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class UpdateTaskTool(BaseTool):
    name = "update_task"
    description = (
        "Update an existing task's status, add a note, reassign it, or change its priority. "
        "Use this to track progress as you work. "
        "Always update task status when you start working (in_progress) and finish (done)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id":     {"type": "string", "description": "Task ID to update"},
            "status":      {"type": "string", "enum": ["pending", "in_progress", "blocked", "done", "cancelled"]},
            "note":        {"type": "string", "description": "Progress note to append to the task history"},
            "assigned_to": {"type": "string", "description": "Reassign to a different role/agent"},
            "priority":    {"type": "string", "enum": ["low", "normal", "high", "critical"]},
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        status: str | None = None,
        note: str | None = None,
        assigned_to: str | None = None,
        priority: str | None = None,
    ) -> ToolResult:
        try:
            tasks = _load_tasks()
            for task in tasks:
                if task["id"] == task_id:
                    if status and status in _VALID_STATUSES:
                        task["status"] = status
                    if note:
                        task.setdefault("notes", []).append(f"[{_now()}] {note}")
                    if assigned_to is not None:
                        task["assigned_to"] = assigned_to
                    if priority and priority in _VALID_PRIORITIES:
                        task["priority"] = priority
                    task["updated_at"] = _now()
                    _save_tasks(tasks)
                    return ToolResult(success=True, output=f"Task updated.\n\n{_fmt_task(task)}")
            return ToolResult(
                success=False, output=None,
                error=f"Task '{task_id}' not found.",
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ListTasksTool(BaseTool):
    name = "list_tasks"
    description = (
        "List tasks from the project board, optionally filtered by status, priority, or tags. "
        "Use this at the start of each session to understand what needs to be done. "
        "Returns tasks sorted by priority then creation date."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status":   {"type": "string", "enum": ["pending", "in_progress", "blocked", "done", "cancelled"], "description": "Filter by status"},
            "priority": {"type": "string", "enum": ["low", "normal", "high", "critical"], "description": "Filter by priority"},
            "tag":      {"type": "string", "description": "Filter by a single tag"},
            "limit":    {"type": "integer", "description": "Max tasks to return (default 20)"},
        },
        "required": [],
    }

    _PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}

    async def execute(
        self,
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        try:
            tasks = _load_tasks()
            if not tasks:
                return ToolResult(success=True, output="No tasks found. Use create_task to add work items.")

            filtered = tasks
            if status:
                filtered = [t for t in filtered if t.get("status") == status]
            if priority:
                filtered = [t for t in filtered if t.get("priority") == priority]
            if tag:
                filtered = [t for t in filtered if tag in t.get("tags", [])]

            # Sort: priority first, then creation time
            filtered.sort(key=lambda t: (
                self._PRIORITY_ORDER.get(t.get("priority", "normal"), 2),
                t.get("created_at", ""),
            ))

            filtered = filtered[:max(1, int(limit))]

            if not filtered:
                return ToolResult(success=True, output="No tasks match the given filters.")

            lines = [f"Showing {len(filtered)} task(s):\n"]
            for t in filtered:
                tags = f" [{', '.join(t.get('tags', []))}]" if t.get("tags") else ""
                assigned = f" → {t['assigned_to']}" if t.get("assigned_to") else ""
                lines.append(
                    f"  [{t['status'].upper():<11}] [{t['priority']:<8}] "
                    f"{t['id']}  {t['title']}{tags}{assigned}"
                )

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetTaskTool(BaseTool):
    name = "get_task"
    description = "Get full details of a specific task by its ID, including all notes and history."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID to retrieve"},
        },
        "required": ["task_id"],
    }

    async def execute(self, task_id: str) -> ToolResult:
        try:
            tasks = _load_tasks()
            for t in tasks:
                if t["id"] == task_id:
                    # Also show direct subtasks
                    subtasks = [s for s in tasks if s.get("parent_id") == task_id]
                    output = _fmt_task(t)
                    if subtasks:
                        output += f"\n\nSubtasks ({len(subtasks)}):"
                        for s in subtasks:
                            output += f"\n  [{s['status'].upper():<11}] {s['id']}  {s['title']}"
                    return ToolResult(success=True, output=output)
            return ToolResult(
                success=False, output=None,
                error=f"Task '{task_id}' not found.",
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
