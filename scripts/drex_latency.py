"""Task 2: test a Drex call and measure real round-trip time and throughput.

    export DEEPINFRA_API_KEY=...
    uv run python scripts/drex_latency.py                    # 1 call, then bursts
    uv run python scripts/drex_latency.py --levels 1,32,128,516

Prints one sample answer (to confirm question types parse), then for each
concurrency level: wall time to decide that many cells, p50/p95 latency, errors.
The 516-cell row is the "full map in about a second" check.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import drex  # noqa: E402
from atlas.config import CELLS_PATH  # noqa: E402
from atlas.decide import DeciderPool, decide_states  # noqa: E402
from atlas.scenario import PRESETS, Priorities  # noqa: E402
from atlas.state import build_state  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="1,16,64,128,256,516")
    ap.add_argument("--model", default=drex.DEFAULT_MODEL)
    args = ap.parse_args()

    cells = json.loads(CELLS_PATH.read_text())
    states = [(c["id"], build_state(c, PRESETS["Today"], Priorities())) for c in cells]

    async with DeciderPool("drex", model=args.model) as pool:
        print(f"model: {args.model}")
        print("--- sample request state ---")
        print(states[0][1])
        answers, ms, usage = await pool(states[0][1])
        print(f"--- sample answer ({ms:.0f} ms, usage {usage}) ---")
        print(json.dumps(answers, indent=1))

        print("\ncells  concurrency  wall_ms  p50_ms  p95_ms  errors")
        for n in (int(x) for x in args.levels.split(",")):
            batch = (states * (n // len(states) + 1))[:n]
            r = await decide_states(batch, pool, "drex", concurrency=n)
            t = r["timing"]
            print(f"{n:5d}  {n:11d}  {t['wall_ms']:7.0f}  {t['p50_ms'] or 0:6.0f}  "
                  f"{t['p95_ms'] or 0:6.0f}  {t['errors']:6d}")
            errs = {x["error"] for x in r["results"] if x["error"]}
            for e in list(errs)[:3]:
                print(f"       error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
