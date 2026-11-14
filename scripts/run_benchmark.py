"""Task 11: benchmark runs (latency, agreement with guide rules, consistency).

    uv run python scripts/run_benchmark.py --models rules            # offline dry run
    uv run python scripts/run_benchmark.py --models drex --repeats 3
    uv run python scripts/run_benchmark.py --models drex,llm --cells 100 --yes

The LLM run costs real money (one Claude call per cell per repeat), so it
needs --yes. Writes results/benchmark_<scenario>.json and .csv.
"""

import argparse
import asyncio
import json
import random
import sys
from contextlib import AsyncExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import benchmark  # noqa: E402
from atlas.config import CELLS_PATH, ROOT  # noqa: E402
from atlas.decide import DeciderPool  # noqa: E402
from atlas.llm import DEFAULT_EFFORT  # noqa: E402
from atlas.llm import DEFAULT_MODEL as LLM_MODEL  # noqa: E402
from atlas.drex import DEFAULT_MODEL as DREX_MODEL  # noqa: E402
from atlas.rules import rules_decider  # noqa: E402
from atlas.scenario import PRESETS, Priorities  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="drex,llm", help="comma list of drex, llm, rules")
    ap.add_argument("--scenario", default="Today", choices=list(PRESETS))
    ap.add_argument("--cells", type=int, default=0, help="random sample size; 0 = all")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--yes", action="store_true", help="confirm paid LLM calls")
    args = ap.parse_args()

    models = args.models.split(",")
    cells = json.loads(CELLS_PATH.read_text())
    if args.cells:
        cells = random.Random(args.seed).sample(cells, args.cells)
    if "llm" in models and not args.yes:
        sys.exit(f"LLM run = {len(cells) * args.repeats} paid {LLM_MODEL} calls. Re-run with --yes.")

    scenario, priorities = PRESETS[args.scenario], Priorities()
    model_runs = []
    async with AsyncExitStack() as stack:
        for m in models:
            if m == "rules":
                decider = rules_decider
            else:
                decider = await stack.enter_async_context(DeciderPool(m))
            print(f"running {m} on {len(cells)} cells x {args.repeats} (concurrency {args.concurrency})...")
            mr = await benchmark.run_model(cells, scenario, priorities, decider, m,
                                           args.repeats, args.concurrency)
            model_runs.append(mr)

    summaries = [benchmark.summarise(mr) for mr in model_runs]
    report = {
        "scenario": scenario.to_dict(),
        "priorities": priorities.to_dict(),
        "concurrency": args.concurrency,
        "model_ids": {"drex": DREX_MODEL, "llm": f"{LLM_MODEL} (effort {DEFAULT_EFFORT})"},
        "summaries": summaries,
    }
    if len(model_runs) >= 2:
        report["cross_model_agreement"] = benchmark.cross_model_agreement(model_runs[0], model_runs[1])

    out = ROOT / "results"
    slug = args.scenario.lower().replace(" ", "_")
    (out).mkdir(exist_ok=True)
    (out / f"benchmark_{slug}.json").write_text(json.dumps(report, indent=1))
    benchmark.write_csv(model_runs, out / f"benchmark_{slug}.csv")

    print("\nmodel   cells  full-map wall ms  p50 ms  p95 ms  rule agree  consistent  review  errors")
    for s in summaries:
        print(f"{s['model']:6s} {s['cells']:6d}  {s['full_map_wall_ms_mean']:16.0f}  "
              f"{s['latency_p50_ms'] or 0:6.0f}  {s['latency_p95_ms'] or 0:6.0f}  "
              f"{s['rule_agreement'] or 0:10.1%}  {s['consistency'] or 0:10.1%}  "
              f"{s['review_flag_share'] or 0:6.1%}  {s['error_rate'] or 0:6.1%}")
    if "cross_model_agreement" in report:
        print(f"cross-model agreement on recommendation: {report['cross_model_agreement']:.1%}")
    print(f"wrote {out}/benchmark_{slug}.json and .csv")


if __name__ == "__main__":
    asyncio.run(main())
