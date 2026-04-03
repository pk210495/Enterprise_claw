"""
Agent Message Bus — async, file-backed inter-agent communication.

Each agent has an inbox at storage/bus/{agent_id}/inbox.jsonl.
Messages are append-only; read status is tracked by a 'read' boolean flag
(achieved by rewriting the file on mark-read, which is infrequent).

This is intentionally simple: agents check their inbox at turn-start,
act on messages, and reply by sending to the sender's inbox.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inbox_path(agent_id: str) -> Path:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in agent_id)
    path = config.bus_dir / safe_id / "inbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def send_message(
    to: str,
    from_: str,
    subject: str,
    body: str,
    priority: str = "normal",
    metadata: dict | None = None,
) -> str:
    """
    Write a message to the recipient's inbox. Returns the message ID.
    """
    msg = {
        "id":       str(uuid.uuid4())[:8],
        "from":     from_,
        "to":       to,
        "subject":  subject,
        "body":     body,
        "priority": priority,
        "read":     False,
        "sent_at":  _now(),
        **(metadata or {}),
    }
    path = _inbox_path(to)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    logger.debug(f"bus: message {msg['id']} → {to} from {from_} [{subject}]")
    return msg["id"]


def read_messages(agent_id: str, unread_only: bool = True) -> list[dict]:
    """Return messages from an agent's inbox."""
    path = _inbox_path(agent_id)
    if not path.exists():
        return []
    messages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if unread_only and msg.get("read"):
                    continue
                messages.append(msg)
            except json.JSONDecodeError:
                logger.warning(f"bus: corrupt line in {agent_id} inbox")
    # Sort by priority then time
    _priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    messages.sort(key=lambda m: (
        _priority_order.get(m.get("priority", "normal"), 2),
        m.get("sent_at", ""),
    ))
    return messages


def mark_read(agent_id: str, message_ids: list[str]) -> int:
    """Mark specific messages as read. Returns count marked."""
    path = _inbox_path(agent_id)
    if not path.exists():
        return 0
    msgs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("id") in message_ids:
                    msg["read"] = True
                msgs.append(msg)
            except json.JSONDecodeError:
                pass
    count = sum(1 for m in msgs if m.get("id") in message_ids)
    with open(path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return count


def list_agents_with_inbox() -> list[str]:
    """Return list of agent IDs that have an inbox directory."""
    bus = config.bus_dir
    if not bus.exists():
        return []
    return [d.name for d in sorted(bus.iterdir()) if d.is_dir()]
