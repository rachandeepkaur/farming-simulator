"""Task 13: the valley simulation (PRD "Valley simulation").

Each simulated year: build every cell's state (that year's climate + carried
groundwater/soil + priorities), decide all cells in parallel, then update each
cell with simulate_year(). The update is deterministic; only the decisions
come from Drex or the LLM.
"""

from __future__ import annotations

import time

from . import crops
from .config import REPLAY_YEARS
from .decide import Decider, decide_states
from .scenario import PRESETS, Priorities, Scenario, apply
from .sim_constants import (
    PUMP_TO_STORAGE,
    RECHARGE_SHARE,
    SOIL_DELTA,
    SOIL_REPEAT_PENALTY,
    SOIL_START,
    STRESS_THRESHOLD_CM,
    SUSTAINABLE_SUPPLY_CM,
)
from .state import build_state


def initial_state() -> dict:
    return {"groundwater_cm": 0.0, "soil_score": SOIL_START, "last_strategy": "existing", "year_index": 0}


def water_balance(climate: dict, strategy: str) -> tuple[float, float, float]:
    """(water need, shortfall pumped beyond sustainable supply, recharge), cm."""
    rain_cm = climate["rain_mm"] / 10
    need, used_rain, irrigation = crops.strategy_irrigation_cm(strategy, climate["rain_mm"], climate["heat_days"])
    shortfall = max(0.0, irrigation - SUSTAINABLE_SUPPLY_CM)
    recharge = max(0.0, rain_cm - used_rain) * RECHARGE_SHARE
    return need, shortfall, recharge


def simulate_year(sim: dict, climate: dict, strategy: str, baseline: dict) -> dict:
    """Advance one cell by one year.

    `climate` is scenario.apply() for this year; `baseline` is scenario.apply()
    for the Today preset (the multi-year mean).

    Groundwater: the GRACE trend already reflects today's pumping under the
    existing rotation, so we add only the *difference* from that baseline:
    trend + (recharge - baseline recharge) - (shortfall - baseline shortfall)
    x PUMP_TO_STORAGE. The existing rotation in today's climate therefore
    reproduces the GRACE trend exactly.
    Soil: strategy effect, minus a penalty for repeating last year's strategy.
    """
    need, shortfall, recharge = water_balance(climate, strategy)
    _, base_shortfall, base_recharge = water_balance(baseline, "existing")

    gw = (sim["groundwater_cm"] + climate["gw_trend_cm_yr"]
          + (recharge - base_recharge)
          - (shortfall - base_shortfall) * PUMP_TO_STORAGE)

    soil = sim["soil_score"] + SOIL_DELTA[strategy]
    if strategy == sim["last_strategy"] and strategy != "cover_crop":
        soil += SOIL_REPEAT_PENALTY
    soil = min(100.0, max(0.0, soil))

    return {
        "groundwater_cm": round(gw, 2),
        "soil_score": round(soil, 1),
        "last_strategy": strategy,
        "year_index": sim["year_index"] + 1,
        "stress": gw < STRESS_THRESHOLD_CM,
        "water_need_cm": need,
        "shortfall_cm": round(shortfall, 1),
    }


def scenario_years(scenario: Scenario, n_years: int) -> list[tuple[int, str | None]]:
    """(display year, POWER year or None). The drought replay uses real years;
    synthetic presets use the multi-year mean every year."""
    if scenario.name == "Drought replay":
        return [(y, str(y)) for y in REPLAY_YEARS[:n_years]]
    start = REPLAY_YEARS[0]
    return [(start + i, None) for i in range(n_years)]


async def iter_years(
    cells: list[dict],
    scenario: Scenario,
    priorities: Priorities,
    decider: Decider,
    model_name: str,
    n_years: int = 10,
    concurrency: int = 128,
):
    """Run the simulation one year at a time. Yields (year, timing, records)
    where records maps cell id -> that year's record, so a server can stream
    the map as it fills in."""
    sims = {c["id"]: initial_state() for c in cells}
    baselines = {c["id"]: apply(c, PRESETS["Today"]) for c in cells}

    for display_year, power_year in scenario_years(scenario, n_years):
        items = [
            (c["id"], build_state(c, scenario, priorities, year=power_year, sim=sims[c["id"]]))
            for c in cells
        ]
        t0 = time.perf_counter()
        decided = await decide_states(items, decider, model_name, concurrency)
        wall_ms = (time.perf_counter() - t0) * 1000
        by_id = {r["cell_id"]: r for r in decided["results"]}

        records = {}
        for c in cells:
            r = by_id[c["id"]]
            prev = sims[c["id"]]
            a = r["answers"]
            if a is None:
                # Failed decision: keep last year's strategy so the run continues,
                # and mark the year so the UI can show it.
                strategy, review, failed = prev["last_strategy"], True, True
            else:
                strategy = a["recommended"]["value"]
                review = a["needs_local_review"]["value"]
                failed = False
            climate = apply(c, scenario, power_year)
            nxt = simulate_year(prev, climate, strategy, baseline=baselines[c["id"]])
            sims[c["id"]] = nxt
            records[c["id"]] = {
                "year": display_year,
                "strategy": strategy,
                "groundwater_cm": nxt["groundwater_cm"],
                "soil_score": nxt["soil_score"],
                "stress": nxt["stress"],
                "review": review or nxt["stress"],
                "decision_failed": failed,
                "rain_mm": climate["rain_mm"],
                "frost_days": climate["frost_days"],
                "heat_days": climate["heat_days"],
                "irrigation_cm": {
                    s: crops.strategy_irrigation_cm(s, climate["rain_mm"], climate["heat_days"])[2]
                    for s in crops.STRATEGIES
                },
                "answers": None if a is None else {
                    "frost_risk": a["frost_risk"]["value"],
                    "soil_benefit": a["soil_benefit"]["value"],
                    "fits": {s: a[f"fit_{s}"]["value"] for s in crops.STRATEGIES},
                    "recommended_probs": a["recommended"].get("probs") or {},
                },
                "error": r["error"],
            }
        year_timing = {"year": display_year, "wall_ms": round(wall_ms, 1),
                       "p50_ms": decided["timing"]["p50_ms"], "errors": decided["timing"]["errors"]}
        yield display_year, year_timing, records


async def run(
    cells: list[dict],
    scenario: Scenario,
    priorities: Priorities,
    decider: Decider,
    model_name: str,
    n_years: int = 10,
    concurrency: int = 128,
    on_year=None,
) -> dict:
    """Run the whole simulation. Returns the /simulate shape (schema/README.md §5).
    `on_year(year, timing)` is called after each year."""
    history: dict[str, list] = {c["id"]: [] for c in cells}
    timing, years = [], []
    async for year, year_timing, records in iter_years(
        cells, scenario, priorities, decider, model_name, n_years, concurrency
    ):
        years.append(year)
        timing.append(year_timing)
        for cid, rec in records.items():
            history[cid].append(rec)
        if on_year:
            on_year(year, year_timing)
    return {"years": years, "cells": history, "timing": timing}
