"""Task 13: run the valley simulation and save it (also the per-preset cache
the PRD uses as the offline fallback).

    uv run python scripts/run_simulation.py --model rules                 # offline
    uv run python scripts/run_simulation.py --model drex --scenario "Drought replay"
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from contextlib import AsyncExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import simulate  # noqa: E402
from atlas.config import CELLS_PATH, ROOT  # noqa: E402
from atlas.decide import DeciderPool  # noqa: E402
from atlas.rules import rules_decider  # noqa: E402
from atlas.scenario import PRESETS, Priorities  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="drex", choices=["drex", "llm", "rules"])
    ap.add_argument("--scenario", default="Drought replay", choices=list(PRESETS))
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--save-water", type=float, default=0.5)
    ap.add_argument("--income", type=float, default=0.5)
    ap.add_argument("--build-soil", type=float, default=0.5)
    ap.add_argument("--yes", action="store_true", help="confirm paid LLM calls")
    args = ap.parse_args()

    cells = json.loads(CELLS_PATH.read_text())
    if args.model == "llm" and not args.yes:
        sys.exit(f"LLM simulation = {len(cells) * args.years} paid calls. Re-run with --yes.")
    pr = Priorities(args.save_water, args.income, args.build_soil)
    sc = PRESETS[args.scenario]

    def on_year(y, t):
        print(f"  {y}: {t['wall_ms']:.0f} ms, {t['errors']} errors")

    async with AsyncExitStack() as stack:
        decider = rules_decider if args.model == "rules" else await stack.enter_async_context(DeciderPool(args.model))
        print(f"simulating {sc.name} for {args.years} years over {len(cells)} cells with {args.model}...")
        result = await simulate.run(cells, sc, pr, decider, args.model, args.years,
                                    args.concurrency, on_year=on_year)

    result["scenario"] = sc.to_dict()
    result["priorities"] = pr.to_dict()
    result["model"] = args.model
    out = ROOT / "results" / "simulations"
    out.mkdir(parents=True, exist_ok=True)
    slug = f"{sc.name.lower().replace(' ', '_')}_{args.model}_w{args.save_water}_i{args.income}_s{args.build_soil}"
    path = out / f"{slug}.json"
    path.write_text(json.dumps(result))

    final = [h[-1] for h in result["cells"].values()]
    gw = sorted(f["groundwater_cm"] for f in final)
    print(f"\nfinal year {result['years'][-1]}:")
    print(f"  strategies: {dict(Counter(f['strategy'] for f in final))}")
    print(f"  groundwater change cm: min {gw[0]}, median {gw[len(gw) // 2]}, max {gw[-1]}")
    print(f"  stressed cells: {sum(f['stress'] for f in final)}  "
          f"mean soil score: {sum(f['soil_score'] for f in final) / len(final):.1f}")
    print(f"  total decision time: {sum(t['wall_ms'] for t in result['timing']) / 1000:.1f} s")
    print(f"wrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
