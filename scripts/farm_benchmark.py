"""Benchmark the farm view: Drex vs LLM vs the rule stand-in.

    python scripts/farm_benchmark.py --models rules --seasons 4
    python scripts/farm_benchmark.py --models drex,llm,rules --seasons 4 --yes

Writes results/farm_benchmark_<time>.json and .md. LLM calls are paid and
need --yes. States are captured once from the rules run so every model sees
the same fields.
"""

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas.envfile import load_local_env  # noqa: E402

load_local_env()

from atlas.config import ROOT  # noqa: E402
from atlas.decide import DeciderPool  # noqa: E402
from atlas.farm import farm_cells, load  # noqa: E402
from atlas.farm_actions import (  # noqa: E402
    DEFAULT_STOCK,
    FARM_QUESTIONS,
    FARM_SYSTEM,
    farm_rules_decider,
    iter_seasons,
)
from atlas.farm_benchmark import evaluate, markdown_table  # noqa: E402
from atlas.scenario import PRESETS, Priorities  # noqa: E402
from atlas.weather import for_cell  # noqa: E402


async def capture_states(n_seasons: int) -> list[list[str]]:
    farm = load()
    fields = farm["fields"]
    buckets: list[list[str]] = []
    current: list[str] = []

    async def wrap(state: str):
        nonlocal current
        current.append(state)
        if len(current) == len(fields):
            buckets.append(current)
            current = []
        return await farm_rules_decider(state)

    years = max(1, (n_seasons + 3) // 4)
    async for _ in iter_seasons(
        fields, for_cell(farm_cells()[0]), PRESETS["Drought replay"], Priorities(),
        wrap, "rules", {}, dict(DEFAULT_STOCK), "Fresno", -2.0,
        n_years=years, include_state=False,
    ):
        if len(buckets) >= n_seasons:
            break
    if len(buckets) < n_seasons:
        sys.exit(f"only captured {len(buckets)} seasons, wanted {n_seasons}")
    return buckets[:n_seasons]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="drex,llm,rules")
    ap.add_argument("--seasons", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--yes", action="store_true", help="confirm paid LLM calls")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in models if m not in ("drex", "llm", "rules")]
    if unknown:
        sys.exit(f"unknown model: {', '.join(unknown)}")
    if "llm" in models and not args.yes:
        calls = args.seasons * 36 * args.repeats
        sys.exit(f"LLM run is about {calls} paid calls. Re-run with --yes.")

    print(f"capturing {args.seasons} season(s) of field states from the rules run...")
    seasons = await capture_states(args.seasons)
    print(f"captured {len(seasons)} seasons x {len(seasons[0])} fields")

    deciders = {}
    async with AsyncExitStack() as stack:
        for name in models:
            if name == "rules":
                deciders[name] = farm_rules_decider
            else:
                kw = {"questions": FARM_QUESTIONS}
                if name == "llm":
                    kw["system"] = FARM_SYSTEM
                deciders[name] = await stack.enter_async_context(DeciderPool(name, **kw))
        print(f"running {', '.join(models)} x {args.repeats} repeats...")
        report = await evaluate(deciders, seasons, args.repeats, args.concurrency)

    report["created"] = datetime.now().isoformat(timespec="seconds")
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out / f"farm_benchmark_{stamp}.json"
    md_path = out / f"farm_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    table = markdown_table(report)
    md_path.write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    print(f"\nwrote {json_path.name} and {md_path.name}")


if __name__ == "__main__":
    asyncio.run(main())
