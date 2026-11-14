"""Farm benchmark: Drex vs LLM vs rules on the same field states.

States come from one rules run of farm_actions.iter_seasons, so every model
sees the same realistic season. Metrics: wall time per season, latency,
tokens and cost, agreement with Drex per action, consistency over repeats,
and agreement with the farm guide rules.
"""

from __future__ import annotations

import os
from statistics import mean

from .decide import Decider, decide_states
from .farm_actions import ACTION_KEYS, FARM_QUESTIONS
from . import farm_rules

COMPARE_KEYS = ["irrigation", "fertilize", "lime", "spray_pests", "cover_crop"]


def _tokens(usage: dict | None) -> tuple[int, int]:
    usage = usage or {}
    inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    return int(inp or 0), int(out or 0)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars, or None when a price is not set. Rules are free."""
    if model == "rules":
        return 0.0
    if model == "drex":
        price = os.environ.get("DREX_PRICE_PER_MTOK")
        if not price:
            return None
        return (input_tokens + output_tokens) / 1e6 * float(price)
    pin = os.environ.get("FRONTIER_PRICE_IN_PER_MTOK") or os.environ.get("LLM_PRICE_IN_PER_MTOK")
    pout = os.environ.get("FRONTIER_PRICE_OUT_PER_MTOK") or os.environ.get("LLM_PRICE_OUT_PER_MTOK")
    if not pin and not pout:
        return None
    return input_tokens / 1e6 * float(pin or 0) + output_tokens / 1e6 * float(pout or 0)


def _action(answers: dict | None, key: str):
    if not answers or key not in answers:
        return None
    return answers[key].get("value")


def agreement_with(reference: list[list[dict]], other: list[list[dict]]) -> dict:
    """Share of fields where each action matches, using the first repeat."""
    totals = {k: [0, 0] for k in COMPARE_KEYS}  # matches, compared
    for ref_season, oth_season in zip(reference, other):
        by_ref = {r["cell_id"]: r for r in ref_season["results"]}
        by_oth = {r["cell_id"]: r for r in oth_season["results"]}
        for cid, ref in by_ref.items():
            oth = by_oth.get(cid)
            if not oth:
                continue
            for key in COMPARE_KEYS:
                a, b = _action(ref["answers"], key), _action(oth["answers"], key)
                if a is None or b is None:
                    continue
                totals[key][1] += 1
                totals[key][0] += a == b
    return {k: (round(m / n, 4) if n else None) for k, (m, n) in totals.items()}


def _summarise(model: str, runs: list[list[dict]], usages: list[dict]) -> dict:
    walls = [s["timing"]["wall_ms"] for run in runs for s in run]
    lats = sorted(x["latency_ms"] for run in runs for s in run for x in s["results"] if x["latency_ms"] is not None)
    errors = sum(s["timing"]["errors"] for run in runs for s in run)
    calls = sum(s["timing"]["n"] for run in runs for s in run)
    inp = out = 0
    for usage in usages:
        i, o = _tokens(usage)
        inp += i
        out += o

    checks = passed = 0
    first = runs[0]
    for season in first:
        for row in season["results"]:
            if not row["answers"]:
                continue
            for item in farm_rules.check(row["state"], row["answers"]):
                checks += 1
                passed += item["passed"]

    # consistency: same action tuple on every repeat of the same field
    ids = [r["cell_id"] for r in first[0]["results"]]
    consistent = compared = 0
    for si in range(len(first)):
        for cid in ids:
            series = []
            ok = True
            for run in runs:
                row = next(r for r in run[si]["results"] if r["cell_id"] == cid)
                if not row["answers"]:
                    ok = False
                    break
                series.append(tuple(_action(row["answers"], k) for k in COMPARE_KEYS))
            if not ok:
                continue
            compared += 1
            consistent += len(set(series)) == 1

    def pct(p):
        if not lats:
            return None
        return round(lats[min(len(lats) - 1, int(p * len(lats)))], 1)

    cost = estimate_cost(model, inp, out)
    return {
        "model": model,
        "seasons": len(first),
        "repeats": len(runs),
        "wall_ms_per_season": round(mean(walls), 1) if walls else None,
        "latency_p50_ms": pct(0.5),
        "latency_p95_ms": pct(0.95),
        "input_tokens": inp,
        "output_tokens": out,
        "cost_usd": None if cost is None else round(cost, 6),
        "guide_rule_agreement": round(passed / checks, 4) if checks else None,
        "consistency": round(consistent / compared, 4) if compared else None,
        "errors": errors,
        "calls": calls,
        "questions": list(FARM_QUESTIONS),
        "actions_tracked": list(ACTION_KEYS),
    }


async def evaluate(
    deciders: dict[str, Decider],
    seasons: list[list[str]],
    repeats: int = 5,
    concurrency: int = 128,
) -> dict:
    """Decide the same season states with each decider. `seasons` is a list of
    field-state lists (one list per season, same order every time)."""
    raw: dict[str, list[list[dict]]] = {}
    summaries = {}
    for name, decider in deciders.items():
        usages: list[dict] = []

        async def counting(state: str, _decider=decider, _usages=usages):
            answers, ms, usage = await _decider(state)
            _usages.append(usage or {})
            return answers, ms, usage or {}

        runs = []
        for _ in range(repeats):
            run = []
            for si, states in enumerate(seasons):
                items = [(f"s{si}f{fi}", state) for fi, state in enumerate(states)]
                run.append(await decide_states(items, counting, name, concurrency))
            runs.append(run)
        raw[name] = runs
        summaries[name] = _summarise(name, runs, usages)

    if "drex" in raw:
        ref = raw["drex"][0]
        for name, runs in raw.items():
            summaries[name]["agreement_with_drex"] = (
                {k: 1.0 for k in COMPARE_KEYS} if name == "drex" else agreement_with(ref, runs[0])
            )
    else:
        for name in summaries:
            summaries[name]["agreement_with_drex"] = None
    return {"models": summaries, "repeats": repeats, "concurrency": concurrency, "seasons": len(seasons)}


def markdown_table(report: dict) -> str:
    headers = [
        "model", "wall ms/season", "p50 ms", "p95 ms", "input tokens", "cost",
        "guide rules", "consistency", "agree irr", "agree fert", "agree lime",
        "agree spray", "agree cover",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]

    def money(v):
        return "n/a" if v is None else f"${v:.4f}"

    def pct(v):
        return "n/a" if v is None else f"{v:.1%}"

    for name, s in report["models"].items():
        agree = s.get("agreement_with_drex") or {}
        row = [
            name,
            str(s["wall_ms_per_season"]),
            str(s["latency_p50_ms"]),
            str(s["latency_p95_ms"]),
            str(s["input_tokens"]),
            money(s["cost_usd"]),
            pct(s["guide_rule_agreement"]),
            pct(s["consistency"]),
            pct(agree.get("irrigation")),
            pct(agree.get("fertilize")),
            pct(agree.get("lime")),
            pct(agree.get("spray_pests")),
            pct(agree.get("cover_crop")),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("Agreement columns compare each model with Drex on the first repeat. Cost is n/a when the price env var is unset.")
    return "\n".join(lines)
