"""
Message bus tools — agents use these to communicate with each other
and check their inboxes without human involvement.
"""
import logging

from .base import BaseTool, ToolResult
from agent.message_bus import send_message, read_messages, mark_read, list_agents_with_inbox

logger = logging.getLogger(__name__)


class SendMessageTool(BaseTool):
    name = "send_message"
    description = (
        "Send a message to another agent role via the internal message bus. "
        "Use this to delegate work, request reviews, report blockers, or hand off tasks. "
        "The recipient will see the message in their inbox on their next turn. "
        "Common recipients: 'tech_lead', 'backend_engineer', 'qa_engineer', 'product_manager', 'orchestrator'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "to":       {"type": "string",  "description": "Recipient agent ID or role name"},
            "subject":  {"type": "string",  "description": "Short message subject line"},
            "body":     {"type": "string",  "description": "Full message content"},
            "priority": {"type": "string",  "enum": ["low", "normal", "high", "critical"], "description": "Message priority (default: normal)"},
            "from_":    {"type": "string",  "description": "Sender identity (defaults to current agent role)"},
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(
        self,
        to: str,
        subject: str,
        body: str,
        priority: str = "normal",
        from_: str = "agent",
    ) -> ToolResult:
        try:
            msg_id = send_message(
                to=to, from_=from_, subject=subject,
                body=body, priority=priority,
            )
            return ToolResult(
                success=True,
                output=f"Message sent (ID: {msg_id}) to '{to}': {subject}",
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ReadMessagesTool(BaseTool):
    name = "read_messages"
    description = (
        "Read messages from an agent inbox. "
        "Use this at the start of each session to check for delegated tasks, "
        "review requests, or blocker notifications from other agents. "
        "Pass unread_only=false to see all messages including already-read ones."
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_id":    {"type": "string",  "description": "Agent ID or role name whose inbox to read"},
            "unread_only": {"type": "boolean", "description": "Only return unread messages (default: true)"},
        },
        "required": ["agent_id"],
    }

    async def execute(self, agent_id: str, unread_only: bool = True) -> ToolResult:
        try:
            messages = read_messages(agent_id, unread_only=unread_only)
            if not messages:
                return ToolResult(
                    success=True,
                    output=f"No {'unread ' if unread_only else ''}messages for '{agent_id}'.",
                )
            lines = [f"{len(messages)} message(s) for '{agent_id}':\n"]
            for m in messages:
                lines.append(
                    f"  [{m['id']}] [{m.get('priority','normal').upper():<8}] "
                    f"From: {m.get('from','?')}  |  {m['subject']}\n"
                    f"  Sent: {m.get('sent_at','?')}\n"
                    f"  {m.get('body','')[:300]}"
                    + ("…" if len(m.get("body","")) > 300 else "")
                )
                lines.append("")
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MarkReadTool(BaseTool):
    name = "mark_messages_read"
    description = (
        "Mark specific messages as read in an agent's inbox after you have acted on them. "
        "Always mark messages as read once you have processed them."
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_id":    {"type": "string",  "description": "Agent ID whose inbox to update"},
            "message_ids": {"type": "array",   "items": {"type": "string"}, "description": "List of message IDs to mark as read"},
        },
        "required": ["agent_id", "message_ids"],
    }

    async def execute(self, agent_id: str, message_ids: list[str]) -> ToolResult:
        try:
            count = mark_read(agent_id, message_ids)
            return ToolResult(success=True, output=f"Marked {count} message(s) as read.")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ListAgentsTool(BaseTool):
    name = "list_agents"
    description = (
        "List all agent roles that have active inboxes on the message bus. "
        "Use this to discover which agent roles exist before sending messages."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        try:
            agents = list_agents_with_inbox()
            if not agents:
                return ToolResult(success=True, output="No agent inboxes exist yet.")
            return ToolResult(
                success=True,
                output="Active agent roles:\n" + "\n".join(f"  - {a}" for a in agents),
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
