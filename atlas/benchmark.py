"""Task 11: benchmark Drex against the LLM on identical requests.

Metrics (PRD "Success metrics"):
- full-map re-decision time: wall-clock to decide every cell, same concurrency
- agreement with guide rules: share of applicable rule checks passed
- consistency: share of cells whose recommendation is identical across repeats
- review flags: share of cells flagged for local review
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from . import rules
from .decide import Decider, decide_states
from .scenario import Priorities, Scenario
from .state import build_state


async def run_model(
    cells: list[dict],
    scenario: Scenario,
    priorities: Priorities,
    decider: Decider,
    model_name: str,
    repeats: int = 3,
    concurrency: int = 128,
) -> dict:
    items = [(c["id"], build_state(c, scenario, priorities)) for c in cells]
    runs = []
    for _ in range(repeats):
        runs.append(await decide_states(items, decider, model_name, concurrency))
    return {"model": model_name, "runs": runs}


def summarise(model_run: dict) -> dict:
    runs = model_run["runs"]
    walls = [r["timing"]["wall_ms"] for r in runs]
    lats = sorted(x["latency_ms"] for r in runs for x in r["results"] if x["latency_ms"] is not None)
    errors = sum(r["timing"]["errors"] for r in runs)
    n_calls = sum(r["timing"]["n"] for r in runs)

    checks = passed = 0
    per_rule = defaultdict(lambda: [0, 0])
    review = decided = 0
    for x in runs[0]["results"]:
        if x["answers"] is None:
            continue
        decided += 1
        review += bool(x["answers"]["needs_local_review"]["value"])
        for c in rules.check(x["state"], x["answers"]):
            checks += 1
            passed += c["passed"]
            per_rule[c["rule"]][0] += c["passed"]
            per_rule[c["rule"]][1] += 1

    recs = defaultdict(list)
    for r in runs:
        for x in r["results"]:
            recs[x["cell_id"]].append(x["answers"]["recommended"]["value"] if x["answers"] else None)
    complete = [v for v in recs.values() if None not in v]
    consistent = sum(len(set(v)) == 1 for v in complete)

    def pct(p):
        return round(lats[min(len(lats) - 1, int(p * len(lats)))], 1) if lats else None

    return {
        "model": model_run["model"],
        "cells": len(recs),
        "repeats": len(runs),
        "full_map_wall_ms_mean": round(sum(walls) / len(walls), 1),
        "full_map_wall_ms_each": walls,
        "latency_p50_ms": pct(0.5),
        "latency_p95_ms": pct(0.95),
        "error_rate": round(errors / n_calls, 4) if n_calls else None,
        "rule_agreement": round(passed / checks, 4) if checks else None,
        "rule_agreement_by_rule": {k: round(p / t, 4) for k, (p, t) in per_rule.items()},
        "consistency": round(consistent / len(complete), 4) if complete else None,
        "review_flag_share": round(review / decided, 4) if decided else None,
    }


def cross_model_agreement(a: dict, b: dict) -> float | None:
    """Share of cells where two models' first runs recommend the same strategy."""
    ra = {x["cell_id"]: x["answers"] for x in a["runs"][0]["results"]}
    rb = {x["cell_id"]: x["answers"] for x in b["runs"][0]["results"]}
    both = [k for k in ra if ra[k] and rb.get(k)]
    if not both:
        return None
    same = sum(ra[k]["recommended"]["value"] == rb[k]["recommended"]["value"] for k in both)
    return round(same / len(both), 4)


def write_csv(model_runs: list[dict], path: Path) -> None:
    """P1 benchmark export: one row per request."""
    from .questions import QUESTIONS

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "run", "cell_id", "latency_ms", "error", *QUESTIONS])
        for mr in model_runs:
            for i, r in enumerate(mr["runs"]):
                for x in r["results"]:
                    vals = [x["answers"][k]["value"] if x["answers"] else "" for k in QUESTIONS]
                    w.writerow([mr["model"], i, x["cell_id"], x["latency_ms"], x["error"] or "", *vals])
