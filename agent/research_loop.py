"""
Autonomous Research Loop — Karpathy's autoresearch experiment loop.

"Give an AI agent a small but real setup and let it experiment autonomously."

The loop runs indefinitely until stopping criteria are met:
  1. Read program.md  → understand direction and constraints
  2. Read journal     → understand what's been tried (avoid repeating null results)
  3. Form hypothesis  → log_hypothesis()
  4. Implement change → run_code / edit files
  5. Run benchmark    → run_benchmark()
  6. Git ratchet      → if improved: git commit + log_finding
                        if not: git reset + log null result
  7. Check stopping criteria → stop or loop

Key design decisions (from autoresearch):
  - Fixed max_experiments per session (prevents runaway loops)
  - Consecutive failures limit (stops thrashing)
  - Simplicity criterion enforced in loop prompt
  - All experiments logged — null results are scientifically valuable
  - The loop is transparent: every decision is visible in journal + git log
"""
import asyncio
import logging
from typing import AsyncGenerator

from providers.registry import provider_registry
from tools.registry import ToolRegistry
from tools.subagent_tools import set_subagent_runner
from tools.critic_tools import set_critic_runner
from tools.skill_tools import set_skill_switcher
from agent.session import SessionManager
from agent.context_engine import ContextEngine
from agent.subagent_pool import SubagentPool
from config import config

logger = logging.getLogger(__name__)

# The research loop system prompt injected alongside the security constitution.
# Embeds the experiment loop as a cognitive protocol the model follows.
_RESEARCH_LOOP_PROTOCOL = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## AUTONOMOUS RESEARCH LOOP — ACTIVE

You are running in autonomous experiment mode. Follow this protocol strictly.

### The Loop (repeat until stopping criteria met)

STEP 1 — ORIENT
  Call read_research_program() — understand current direction, constraints, stopping criteria.
  Call get_research_status()   — see active benchmarks and session stats.
  Call read_journal(findings_only=true) — absorb confirmed findings to build on.

STEP 2 — FORM HYPOTHESIS
  Based on what you've read, form ONE specific, testable hypothesis.
  The hypothesis must:
    - Be different from anything already tried (read_journal to check)
    - Be consistent with the constraints in program.md
    - Have a clear expected direction of improvement
  Call log_hypothesis() with the hypothesis, rationale, and change plan.

STEP 3 — IMPLEMENT
  Make the minimum change needed to test the hypothesis.
  Simpler is always better — the simplicity criterion applies:
    "A 0.001% gain from 20 lines of messy code is not worth keeping."
  Use git() to stage and commit: git(['add', '.'])

STEP 4 — MEASURE
  Call run_benchmark(name=<benchmark_name>, note=<brief description of change>).
  This tells you: improved or not, and the delta.

STEP 5 — RATCHET
  If IMPROVED:
    - git(['commit', '-m', '<description of improvement>'])
    - log_experiment(improved=True, kept=True, ...)
    - log_finding(title=..., description=..., evidence=...) — record the discovery
  If NOT IMPROVED:
    - Call request_approval(action='git reset --hard HEAD', reason='experiment did not improve benchmark', impact='discards uncommitted changes')
    - After approval: git(['checkout', '--', '.'])  (discard changes)
    - log_experiment(improved=False, kept=False, notes='what you learned')

STEP 6 — CHECK STOPPING CRITERIA
  Re-read program.md stopping criteria. Common checks:
    - Experiment count reached?
    - Target metric threshold reached?
    - N consecutive non-improvements?
  If stopping criteria met: summarise findings and exit the loop.
  Otherwise: return to STEP 1.

### Immutable Rules
- NEVER modify benchmark evaluation code (define_benchmark is write-once)
- NEVER skip logging — hypothesis AND experiment must both be logged
- NEVER keep a change that did not improve the benchmark (honesty ratchet)
- NEVER proceed past a REVIEW-tier action without human approval
- Simplicity wins ties: choose the simpler solution when scores are equal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


class ResearchOrchestrator:
    """
    Variant of Orchestrator specialised for autonomous research sessions.
    Injects the research loop protocol into the system prompt and runs
    the experiment loop for a configurable number of iterations.
    """

    def __init__(self, session_id: str, max_experiments: int = 10):
        self._session = SessionManager(session_id)
        self._context = ContextEngine(self._session, skill="researcher")
        self._tools = ToolRegistry()
        self._pool = SubagentPool()
        self._provider = None
        self._max_experiments = max_experiments

        set_subagent_runner(self._pool.run_all)
        set_critic_runner(self._pool.run_all)
        set_skill_switcher(self._context.switch_skill)

    async def _get_provider(self):
        if self._provider is None:
            orch_cfg = config.agents.orchestrator
            if orch_cfg.provider == "auto":
                self._provider = await provider_registry.auto_select()
            else:
                self._provider = provider_registry.get(orch_cfg.provider, orch_cfg.model)
        return self._provider

    async def run_loop(self) -> AsyncGenerator[str, None]:
        """
        Run the autonomous experiment loop. Yields status text as experiments progress.
        The loop runs until the agent decides stopping criteria are met or
        max_experiments is reached.
        """
        provider = await self._get_provider()

        # Inject research loop protocol into system prompt
        original_bootstrap = self._context.bootstrap

        def bootstrap_with_research(tool_schemas=None):
            base = original_bootstrap(tool_schemas)
            return base + "\n\n" + _RESEARCH_LOOP_PROTOCOL

        self._context.bootstrap = bootstrap_with_research
        self._context.bootstrap(self._tools.schemas())

        kick_off = (
            f"You are now in autonomous research mode. "
            f"Run the experiment loop for up to {self._max_experiments} experiments. "
            f"Follow the research loop protocol exactly. "
            f"Begin with STEP 1: read_research_program() then get_research_status()."
        )
        self._context.ingest("user", kick_off)
        yield f"[Research loop started — max {self._max_experiments} experiments]\n\n"

        from agent.orchestrator import MAX_TOOL_ITERATIONS

        full_response = ""
        for iteration in range(MAX_TOOL_ITERATIONS * 3):  # more iterations for long research sessions
            messages = await self._context.assemble(provider)
            tool_calls_this_turn = []
            turn_text = ""

            async for chunk in provider.chat(
                messages=messages,
                tools=self._tools.schemas(),
                stream=True,
            ):
                if chunk["type"] == "text":
                    turn_text += chunk["content"]
                    yield chunk["content"]
                elif chunk["type"] == "tool_call":
                    tool_calls_this_turn.append(chunk)
                elif chunk["type"] == "done":
                    if not turn_text:
                        turn_text = chunk["content"]
                        if turn_text:
                            yield turn_text

            if not tool_calls_this_turn:
                full_response = turn_text
                yield "\n\n[Research loop complete — agent reached stopping criteria]\n"
                break

            # Execute tools
            for tc in tool_calls_this_turn:
                self._context.ingest_tool_call(tc["id"], tc["name"], tc["arguments"])

            for tc in tool_calls_this_turn:
                result = await self._tools.execute(tc["name"], tc["arguments"])
                result_text = result.output if result.success else f"ERROR: {result.error}"
                self._context.ingest_tool_result(tc["id"], tc["name"], str(result_text))

                # Surface tool activity to the stream
                icon = "✓" if result.success else "✗"
                yield f"\n[tool:{tc['name']} {icon}]\n"

            turn_text = ""

        self._context.ingest("assistant", full_response)
        self._context.maintain()

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def message_count(self) -> int:
        return self._session.message_count
