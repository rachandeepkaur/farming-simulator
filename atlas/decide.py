"""decide_all(): decide every cell for one scenario, in parallel, with timing.

This is what Arpan's /decide endpoint (task 7) calls. The same function runs
Drex or the LLM with the same parallelism, which is the benchmark's fairness
rule.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Awaitable, Callable

from . import drex, llm
from .scenario import Priorities, Scenario
from .state import build_state

# (state) -> (answers, latency_ms, usage)
Decider = Callable[[str], Awaitable[tuple[dict, float, dict]]]


class DeciderPool:
    """Owns the HTTP client for one model so connections are reused across
    calls. Use as `async with DeciderPool("drex") as pool: await pool(state)`."""

    def __init__(self, model: str, **kwargs):
        if model not in ("drex", "llm"):
            raise ValueError("model must be 'drex' or 'llm'")
        self.model = model
        self.kwargs = kwargs
        self.client = None

    async def __aenter__(self):
        self.client = drex.make_client() if self.model == "drex" else llm.make_client()
        return self

    async def __aexit__(self, *exc):
        await self.client.close()

    async def __call__(self, state: str):
        mod = drex if self.model == "drex" else llm
        return await mod.decide(self.client, state, **self.kwargs)


def _timing(latencies: list[float], wall_ms: float, errors: int, n: int) -> dict:
    lat = sorted(latencies)

    def pct(p):
        if not lat:
            return None
        return round(lat[min(len(lat) - 1, int(p * len(lat)))], 1)

    return {
        "wall_ms": round(wall_ms, 1),
        "p50_ms": round(statistics.median(lat), 1) if lat else None,
        "p95_ms": pct(0.95),
        "n": n,
        "errors": errors,
    }


async def decide_states(
    items: list[tuple[str, str]],
    decider: Decider,
    model_name: str,
    concurrency: int = 128,
) -> dict:
    """Decide (cell_id, state) pairs in parallel. Never raises for a single
    cell: a failed cell gets answers=None and an error message."""
    sem = asyncio.Semaphore(concurrency)

    async def one(cell_id: str, state: str):
        async with sem:
            # Timed here, around the whole call including retries, so Drex and
            # the LLM are measured the same way.
            t0 = time.perf_counter()
            try:
                answers, _api_ms, _usage = await decider(state)
                latency_ms = (time.perf_counter() - t0) * 1000
                return {"cell_id": cell_id, "model": model_name, "latency_ms": round(latency_ms, 1),
                        "state": state, "answers": answers, "error": None}
            except Exception as e:  # noqa: BLE001 - one bad cell must not sink the map
                return {"cell_id": cell_id, "model": model_name, "latency_ms": None,
                        "state": state, "answers": None, "error": str(e)}

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(cid, s) for cid, s in items))
    wall_ms = (time.perf_counter() - t0) * 1000
    lats = [r["latency_ms"] for r in results if r["latency_ms"] is not None]
    errors = sum(r["error"] is not None for r in results)
    return {"results": results, "timing": _timing(lats, wall_ms, errors, len(results))}


async def decide_all(
    cells: list[dict],
    scenario: Scenario,
    priorities: Priorities,
    decider: Decider,
    model_name: str,
    concurrency: int = 128,
) -> dict:
    items = [(c["id"], build_state(c, scenario, priorities)) for c in cells]
    return await decide_states(items, decider, model_name, concurrency)
