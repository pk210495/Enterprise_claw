import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages a single conversation session.
    All messages, tool calls, and results are persisted as JSONL.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._path = config.sessions_dir / f"{session_id}.jsonl"
        self._messages: list[dict] = []
        config.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    # ── Load / Save ──────────────────────────────────────────────────────────

    def _load(self):
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(f"session '{self.session_id}': skipping corrupt line in JSONL")
            logger.debug(f"session '{self.session_id}' loaded {len(self._messages)} messages")

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            for msg in self._messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    # ── Message operations ───────────────────────────────────────────────────

    def append(self, role: str, content: str, **meta):
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **meta,
        }
        self._messages.append(entry)

    def append_tool_call(self, tool_id: str, tool_name: str, arguments: dict):
        self._messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def append_tool_result(self, tool_id: str, tool_name: str, result: str):
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_id,
            "name": tool_name,
            "content": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_history(self) -> list[dict]:
        """Return all messages without internal metadata fields."""
        clean = []
        for m in self._messages:
            entry = {k: v for k, v in m.items() if k != "timestamp"}
            clean.append(entry)
        return clean

    def get_recent(self, n: int) -> list[dict]:
        """Return the last N messages."""
        return self.get_history()[-n:]

    def compact(self, summary_content: str, kept_messages: list[dict]) -> None:
        """Replace session history with a summary + the messages to keep.
        Used by ContextEngine to compress old history without touching _messages directly."""
        self._messages = []
        self.append("system", summary_content)
        for m in kept_messages:
            self._messages.append(m)
        self.save()

    def clear(self):
        self._messages = []
        if self._path.exists():
            self._path.unlink()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    # ── Session listing ──────────────────────────────────────────────────────

    @staticmethod
    def list_all() -> list[dict]:
        sessions_dir = config.sessions_dir
        if not sessions_dir.exists():
            return []
        result = []
        for f in sorted(sessions_dir.glob("*.jsonl")):
            try:
                stat = f.stat()
                result.append({
                    "session_id": f.stem,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
            except Exception:
                pass
        return result
