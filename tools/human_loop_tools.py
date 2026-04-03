"""
Human escalation queue — the Autonomy Slider.

Karpathy's Iron Man Suit principle: "Not autonomous robots, but tools that
augment humans while maintaining human oversight."

The autonomy slider defines which actions the agent executes freely vs.
which it must queue for human approval first.

Design:
- Agent calls request_approval() for high-stakes ops before executing them
- Requests land in storage/human_review/queue.jsonl
- Human reviews via GET /human-review and approves/rejects via POST /human-review/{id}
- Agent polls with check_approval() before proceeding
- Approved: agent executes. Rejected: agent aborts and logs the decision.

Default autonomy tiers (agent cannot override these):
  AUTO   — agent executes freely
  REVIEW — agent must request approval before proceeding
  BLOCK  — agent cannot perform this class of action at all

Karpathy: "Each constraint directly addresses a specific failure mode."
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

# ── Autonomy tiers ────────────────────────────────────────────────────────────
# AUTO   = agent acts immediately
# REVIEW = agent must get human approval first
# BLOCK  = never allowed without direct human instruction

AUTONOMY_TIERS: dict[str, str] = {
    # Free actions
    "read_file":              "AUTO",
    "write_file":             "AUTO",
    "run_code":               "AUTO",
    "git_status":             "AUTO",
    "git_diff":               "AUTO",
    "git_add":                "AUTO",
    "git_commit":             "AUTO",
    "git_log":                "AUTO",
    "run_benchmark":          "AUTO",
    "log_hypothesis":         "AUTO",
    "log_experiment":         "AUTO",
    "log_finding":            "AUTO",
    "create_task":            "AUTO",
    "update_task":            "AUTO",
    "send_message":           "AUTO",
    # Requires human approval
    "delete_file":            "REVIEW",
    "git_reset_hard":         "REVIEW",
    "modify_benchmark":       "REVIEW",
    "deploy":                 "REVIEW",
    "modify_schema":          "REVIEW",
    "external_api_call":      "REVIEW",
    "install_package":        "REVIEW",
    # Never allowed
    "git_push":               "BLOCK",
    "git_force_push":         "BLOCK",
    "modify_security_md":     "BLOCK",
    "modify_eval_code":       "BLOCK",
    "delete_session_data":    "BLOCK",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_path() -> Path:
    p = config.human_review_dir / "queue.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_queue() -> list[dict]:
    path = _queue_path()
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _save_queue(records: list[dict]) -> None:
    with open(_queue_path(), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Tools ─────────────────────────────────────────────────────────────────────

class RequestApprovalTool(BaseTool):
    name = "request_approval"
    description = (
        "Request human approval before performing a high-stakes or irreversible action. "
        "ALWAYS call this before: deleting files, hard-resetting git, modifying schemas, "
        "deploying code, installing packages, or calling external APIs. "
        "Returns a request_id. Then use check_approval(request_id) to see if approved. "
        "If not yet approved, pause and wait — do NOT proceed without approval. "
        "This is the autonomy slider: the agent acts freely on safe ops, "
        "but humans gate irreversible ones."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action":      {"type": "string", "description": "What action you want to perform"},
            "reason":      {"type": "string", "description": "Why you need to perform this action"},
            "impact":      {"type": "string", "description": "What will happen if approved / what is irreversible"},
            "urgency":     {"type": "string", "enum": ["low", "normal", "high"], "description": "How urgently this is needed"},
            "alternatives": {"type": "string", "description": "What you'll do if the human rejects this request"},
        },
        "required": ["action", "reason", "impact"],
    }

    async def execute(
        self,
        action: str,
        reason: str,
        impact: str,
        urgency: str = "normal",
        alternatives: str = "",
    ) -> ToolResult:
        try:
            request_id = str(uuid.uuid4())[:8]
            record = {
                "id":           request_id,
                "action":       action,
                "reason":       reason,
                "impact":       impact,
                "urgency":      urgency,
                "alternatives": alternatives,
                "status":       "pending",
                "requested_at": _now(),
                "reviewed_at":  None,
                "reviewer_note": "",
            }
            queue = _load_queue()
            queue.append(record)
            _save_queue(queue)

            return ToolResult(
                success=True,
                output=(
                    f"Approval requested (ID: {request_id}).\n\n"
                    f"Action:       {action}\n"
                    f"Reason:       {reason}\n"
                    f"Impact:       {impact}\n"
                    f"Urgency:      {urgency}\n\n"
                    f"Status: PENDING — human review required.\n"
                    f"Use check_approval('{request_id}') to check status before proceeding.\n"
                    f"DO NOT perform the action until approved."
                ),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckApprovalTool(BaseTool):
    name = "check_approval"
    description = (
        "Check whether a human has approved or rejected a pending request. "
        "Call this after request_approval() to see if you can proceed. "
        "Status will be 'pending', 'approved', or 'rejected'. "
        "If pending: do not proceed — the human has not yet reviewed it. "
        "If approved: you may now perform the action. "
        "If rejected: abort the action and follow your stated alternatives."
    )
    parameters = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "The ID returned by request_approval"},
        },
        "required": ["request_id"],
    }

    async def execute(self, request_id: str) -> ToolResult:
        try:
            queue = _load_queue()
            for r in queue:
                if r["id"] == request_id:
                    status = r["status"]
                    if status == "approved":
                        note = r.get("reviewer_note", "")
                        return ToolResult(
                            success=True,
                            output=(
                                f"APPROVED ✓ — you may proceed with: {r['action']}\n"
                                + (f"Reviewer note: {note}" if note else "")
                            ),
                        )
                    elif status == "rejected":
                        note = r.get("reviewer_note", "")
                        return ToolResult(
                            success=True,
                            output=(
                                f"REJECTED ✗ — do NOT perform: {r['action']}\n"
                                + (f"Reviewer note: {note}\n" if note else "")
                                + f"Alternatives: {r.get('alternatives', 'none specified')}"
                            ),
                        )
                    else:
                        return ToolResult(
                            success=True,
                            output=(
                                f"PENDING — human has not yet reviewed request '{request_id}'.\n"
                                f"Action: {r['action']}\n"
                                "Do not proceed. Check again later."
                            ),
                        )
            return ToolResult(
                success=False, output=None,
                error=f"Request '{request_id}' not found in the review queue.",
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetAutonomyTierTool(BaseTool):
    name = "get_autonomy_tier"
    description = (
        "Check the autonomy tier for a class of action before performing it. "
        "Returns AUTO (proceed freely), REVIEW (request human approval first), "
        "or BLOCK (not permitted). "
        "Use this when unsure whether an action requires human approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action_class": {
                "type": "string",
                "description": "The class of action to check, e.g. 'delete_file', 'git_push', 'run_code'",
            },
        },
        "required": ["action_class"],
    }

    async def execute(self, action_class: str) -> ToolResult:
        tier = AUTONOMY_TIERS.get(action_class.lower(), "REVIEW")  # default to REVIEW if unknown
        explanations = {
            "AUTO":   "You may perform this action immediately without approval.",
            "REVIEW": "You must call request_approval() and wait for human approval before proceeding.",
            "BLOCK":  "This action is not permitted for the agent under any circumstances.",
        }
        return ToolResult(
            success=True,
            output=f"Action class '{action_class}': {tier}\n{explanations[tier]}",
        )


# ── Public helpers for the API layer ─────────────────────────────────────────

def get_pending_reviews() -> list[dict]:
    return [r for r in _load_queue() if r["status"] == "pending"]


def resolve_review(request_id: str, approved: bool, reviewer_note: str = "") -> bool:
    """Called by the API endpoint when a human approves or rejects."""
    queue = _load_queue()
    for r in queue:
        if r["id"] == request_id:
            r["status"] = "approved" if approved else "rejected"
            r["reviewed_at"] = _now()
            r["reviewer_note"] = reviewer_note
            _save_queue(queue)
            logger.info(f"human review: {request_id} → {'approved' if approved else 'rejected'}")
            return True
    return False
