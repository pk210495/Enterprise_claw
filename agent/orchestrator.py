import logging
from typing import AsyncGenerator

from providers.registry import provider_registry
from tools.registry import ToolRegistry
from tools.subagent_tools import set_subagent_runner
from tools.skill_tools import set_skill_switcher
from tools.critic_tools import set_critic_runner
from agent.session import SessionManager
from agent.context_engine import ContextEngine
from agent.subagent_pool import SubagentPool
from config import config

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 20


class Orchestrator:
    """
    The main agent brain.

    On every request:
    1. Load session
    2. Bootstrap context (system prompt = security + soul + skill + memory + tools)
    3. Ingest user message
    4. Loop: call LLM → execute tools → feed results back → repeat until done
    5. Post-turn: maintain + save
    """

    def __init__(self, session_id: str, skill: str = "assistant"):
        self._session = SessionManager(session_id)
        self._context = ContextEngine(self._session, skill=skill)
        self._tools = ToolRegistry()
        self._pool = SubagentPool()
        self._provider = None

        # inject subagent runner into the spawn tool
        set_subagent_runner(self._pool.run_all)
        # inject the same runner into the critic tool (critic is a single subagent)
        set_critic_runner(self._pool.run_all)
        # inject skill switcher so the model can switch skills via tool call
        set_skill_switcher(self._context.switch_skill)

    # ── Provider resolution ──────────────────────────────────────────────────

    async def _get_provider(self):
        if self._provider is None:
            orch_cfg = config.agents.orchestrator
            if orch_cfg.provider == "auto":
                self._provider = await provider_registry.auto_select()
            else:
                self._provider = provider_registry.get(orch_cfg.provider, orch_cfg.model)
            logger.info(f"orchestrator provider: {self._provider.name}")
        return self._provider

    # ── Main run — full response ─────────────────────────────────────────────

    async def run(self, message: str) -> str:
        """Run a full agent turn and return the complete response."""
        provider = await self._get_provider()

        # always bootstrap system prompt (security + soul + skill + memory + tools)
        # even for returning sessions — ensures constitution is always present
        self._context.bootstrap(self._tools.schemas())

        self._context.ingest("user", message)

        full_response = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            messages = await self._context.assemble(provider)
            tool_calls_this_turn = []

            async for chunk in provider.chat(
                messages=messages,
                tools=self._tools.schemas(),
                stream=False,
            ):
                if chunk["type"] == "text":
                    full_response += chunk["content"]
                elif chunk["type"] == "tool_call":
                    tool_calls_this_turn.append(chunk)
                elif chunk["type"] == "done":
                    if not full_response:
                        full_response = chunk["content"]

            if not tool_calls_this_turn:
                break

            # record assistant turn with tool calls
            for tc in tool_calls_this_turn:
                self._context.ingest_tool_call(tc["id"], tc["name"], tc["arguments"])

            # execute tools and record results
            for tc in tool_calls_this_turn:
                result = await self._tools.execute(tc["name"], tc["arguments"])
                result_text = result.output if result.success else f"ERROR: {result.error}"
                self._context.ingest_tool_result(tc["id"], tc["name"], str(result_text))
                logger.debug(f"tool '{tc['name']}' → {'ok' if result.success else 'error'}")

            full_response = ""  # reset for next iteration

        self._context.ingest("assistant", full_response)
        self._context.maintain()
        return full_response

    # ── Streaming run ────────────────────────────────────────────────────────

    async def run_stream(self, message: str) -> AsyncGenerator[str, None]:
        """
        Run agent turn with streaming.
        Yields newline-delimited JSON events:
          {"type":"text",     "content":"..."}   — final response text (stream it)
          {"type":"thinking", "content":"..."}   — intermediate reasoning (hidden by default)
          {"type":"tool_start","name":"...","args":{}}  — tool about to run
          {"type":"tool_end",  "name":"...","result":"...","ok":true}  — tool finished
        """
        import json

        provider = await self._get_provider()
        self._context.bootstrap(self._tools.schemas())
        self._context.ingest("user", message)

        full_response = ""
        for iteration in range(MAX_TOOL_ITERATIONS):
            messages = await self._context.assemble(provider)
            tool_calls_this_turn = []
            text_chunks: list[str] = []
            turn_text = ""

            async for chunk in provider.chat(
                messages=messages,
                tools=self._tools.schemas(),
                stream=True,
            ):
                if chunk["type"] == "text":
                    text_chunks.append(chunk["content"])
                    turn_text += chunk["content"]
                elif chunk["type"] == "tool_call":
                    tool_calls_this_turn.append(chunk)
                elif chunk["type"] == "done":
                    if not turn_text and chunk.get("content"):
                        turn_text = chunk["content"]
                        text_chunks = [turn_text]

            if not tool_calls_this_turn:
                # Final iteration — stream text chunks as "text" events
                for ch in text_chunks:
                    if ch:
                        yield json.dumps({"type": "text", "content": ch})
                full_response = turn_text
                break

            # Intermediate iteration — emit thinking + tool events
            if turn_text.strip():
                yield json.dumps({"type": "thinking", "content": turn_text})

            for tc in tool_calls_this_turn:
                self._context.ingest_tool_call(tc["id"], tc["name"], tc["arguments"])
                yield json.dumps({
                    "type": "tool_start",
                    "name": tc["name"],
                    "args": tc["arguments"],
                })
                result = await self._tools.execute(tc["name"], tc["arguments"])
                ok = result.success
                result_text = result.output if ok else f"ERROR: {result.error}"
                self._context.ingest_tool_result(tc["id"], tc["name"], str(result_text))
                yield json.dumps({
                    "type": "tool_end",
                    "name": tc["name"],
                    "result": str(result_text)[:3000],
                    "ok": ok,
                })

            turn_text = ""

        self._context.ingest("assistant", full_response)
        self._context.maintain()

    # ── Utilities ────────────────────────────────────────────────────────────

    def switch_skill(self, skill: str):
        self._context.switch_skill(skill)

    def get_history(self) -> list[dict]:
        return self._session.get_history()

    def clear_session(self):
        self._session.clear()

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def message_count(self) -> int:
        return self._session.message_count
