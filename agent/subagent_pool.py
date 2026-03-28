import asyncio
import logging

from providers.registry import provider_registry
from config import config
from .subagent import SubAgent, SubagentTask, SubagentResult

logger = logging.getLogger(__name__)


class SubagentPool:
    """
    Runs multiple subagents in parallel using asyncio.gather().
    Concurrency is controlled by a semaphore (max_concurrent from config).
    One subagent failure does NOT kill the others.
    """

    def __init__(self):
        self._max_concurrent = config.agents.subagents.max_concurrent
        self._semaphore: asyncio.Semaphore | None = None
        logger.info(f"subagent pool initialised — max_concurrent={self._max_concurrent}")

    def _get_semaphore(self) -> asyncio.Semaphore:
        # Created lazily inside a running event loop — safe
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    async def run_all(self, tasks: list[dict]) -> list[dict]:
        """
        Accept a list of task dicts (from spawn_subagents tool call),
        run them all in parallel, return list of result dicts.
        """
        subagent_tasks = [
            SubagentTask(
                id=t.get("id", f"task_{i}"),
                instruction=t.get("instruction", ""),
                context=t.get("context", ""),
            )
            for i, t in enumerate(tasks)
        ]

        raw_results = await asyncio.gather(
            *[self._run_one(t) for t in subagent_tasks],
            return_exceptions=True,
        )

        results = []
        for i, r in enumerate(raw_results):
            task_id = subagent_tasks[i].id
            if isinstance(r, Exception):
                logger.error(f"subagent '{task_id}' raised exception: {r}")
                results.append({"id": task_id, "success": False, "error": str(r)})
            else:
                results.append({
                    "id": r.id,
                    "success": r.success,
                    "result": r.result,
                    "error": r.error,
                })

        logger.info(
            f"subagent pool finished — "
            f"{sum(1 for r in results if r['success'])}/{len(results)} succeeded"
        )
        return results

    async def _run_one(self, task: SubagentTask) -> SubagentResult:
        async with self._get_semaphore():
            provider = await self._resolve_provider()
            agent = SubAgent(task=task, provider=provider)
            logger.debug(f"subagent '{task.id}' started on provider '{provider.name}'")
            return await agent.run()

    async def _resolve_provider(self):
        """Resolve subagent provider per config — auto or pinned."""
        sa_cfg = config.agents.subagents
        if sa_cfg.provider == "auto":
            return await provider_registry.auto_select()
        return provider_registry.get(sa_cfg.provider, sa_cfg.model)
