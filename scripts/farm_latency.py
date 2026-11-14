"""Farm latency: one real Drex call, then all 36 fields at two concurrencies.

    DEEPINFRA_API_KEY or DREX_API_KEY must be set.
    python scripts/farm_latency.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas.envfile import load_local_env  # noqa: E402

load_local_env()

from atlas.decide import DeciderPool, decide_states  # noqa: E402
from atlas.farm import farm_cells, load  # noqa: E402
from atlas.farm_actions import (  # noqa: E402
    DEFAULT_STOCK,
    FARM_QUESTIONS,
    build_state,
    initial_field_state,
    season_weather,
)
from atlas.scenario import Priorities  # noqa: E402
from atlas.weather import for_cell  # noqa: E402


def _states() -> list[tuple[str, str]]:
    farm = load()
    fields = farm["fields"]
    monthly = for_cell(farm_cells()[0])
    weather = season_weather(monthly["2014"], 2)
    book = {"n": 36, "aquifer_cm": 0, "stock": dict(DEFAULT_STOCK), "compost": 8, "cows": 24}
    out = []
    for field in fields:
        state = build_state(field, initial_field_state(field, {}), book, "2014", 2, weather, Priorities(), "Fresno")
        out.append((field["id"], state))
    return out


async def main():
    if not os.environ.get("DEEPINFRA_API_KEY"):
        sys.exit("DEEPINFRA_API_KEY is not set. Add it, or set DREX_API_KEY in rotation-atlas/.env.")
    states = _states()
    if len(states) != 36:
        sys.exit(f"expected 36 fields, found {len(states)}")

    async with DeciderPool("drex", questions=FARM_QUESTIONS) as pool:
        print("--- one field state ---")
        print(states[0][1])
        answers, ms, usage = await pool(states[0][1])
        missing = [k for k in FARM_QUESTIONS if k not in answers]
        if missing:
            sys.exit(f"Drex answer is missing question keys: {', '.join(missing)}")
        print(f"--- parsed answer ({ms:.0f} ms, usage {usage}) ---")
        print(json.dumps(answers, indent=1))

        print("\nfields  concurrency  wall_ms  p50_ms  p95_ms  errors")
        for concurrency in (36, 128):
            result = await decide_states(states, pool, "drex", concurrency=concurrency)
            for row in result["results"]:
                if row["answers"] is None:
                    continue
                missing = [k for k in FARM_QUESTIONS if k not in row["answers"]]
                if missing:
                    sys.exit(f"{row['cell_id']} is missing question keys: {', '.join(missing)}")
            t = result["timing"]
            print(f"{len(states):6d}  {concurrency:11d}  {t['wall_ms']:7.0f}  "
                  f"{t['p50_ms'] or 0:6.0f}  {t['p95_ms'] or 0:6.0f}  {t['errors']:6d}")
            for err in {r["error"] for r in result["results"] if r["error"]}:
                print(f"       error: {err}")


if __name__ == "__main__":
    asyncio.run(main())
