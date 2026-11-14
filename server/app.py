"""Small API for the simulation UI.

    uv run uvicorn server.app:app --port 8000

GET  /api/meta      presets, strategies, crop facts with evidence, valley outline, models
GET  /api/cells     the grid with each cell's climate and GRACE trend
POST /api/simulate  runs a simulation and streams it as NDJSON, one line per year:
                    {"type":"start",...} {"type":"year",...}x N {"type":"done",...}
"""

from __future__ import annotations

import json
import os
import time
from contextlib import AsyncExitStack

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atlas import crops, simulate, weather
from atlas.config import CELLS_PATH, VALLEY_POLYGON
from atlas.decide import DeciderPool
from atlas.rules import rules_decider
from atlas.scenario import PRESETS, Priorities, Scenario
from atlas.sim_constants import STRESS_THRESHOLD_CM, SUSTAINABLE_SUPPLY_CM

app = FastAPI(title="Rotation Atlas API")

CELLS = json.loads(CELLS_PATH.read_text())
CELL_BY_ID = {c["id"]: c for c in CELLS}

CITIES = [
    {"name": "Redding", "lat": 40.59, "lon": -122.39},
    {"name": "Chico", "lat": 39.73, "lon": -121.84},
    {"name": "Sacramento", "lat": 38.58, "lon": -121.49},
    {"name": "Stockton", "lat": 37.96, "lon": -121.29},
    {"name": "Fresno", "lat": 36.74, "lon": -119.79},
    {"name": "Bakersfield", "lat": 35.37, "lon": -119.02},
]

# Rough cost per decision for the paid LLM baseline, for the UI's confirm dialog.
LLM_USD_PER_CALL = 0.01


def available_models() -> dict:
    return {
        "drex": bool(os.environ.get("DEEPINFRA_API_KEY")),
        "llm": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "rules": True,
    }


@app.get("/api/meta")
def meta():
    d = crops.load()
    return {
        "presets": {k: v.to_dict() for k, v in PRESETS.items()},
        "strategies": {k: {**v, "summary": crops.strategy_summary(k)} for k, v in d["strategies"].items()},
        "crops": d["crops"],
        "crops_placeholder": crops.is_placeholder(),
        "valley_polygon": VALLEY_POLYGON,
        "cities": CITIES,
        "models": available_models(),
        "llm_usd_per_call": LLM_USD_PER_CALL,
        "constants": {"sustainable_supply_cm": SUSTAINABLE_SUPPLY_CM,
                      "stress_threshold_cm": STRESS_THRESHOLD_CM},
    }


@app.get("/api/cells")
def cells():
    out = []
    for c in CELLS:
        cl = c["climate"]
        out.append({
            "id": c["id"], "row": c["row"], "col": c["col"], "lat": c["lat"], "lon": c["lon"],
            "bbox": c["bbox"],
            "rain_mm": cl["rain_mm"], "frost_days": cl["frost_days"], "heat_days": cl["heat_days"],
            "gw_trend_cm_yr": c["grace"]["trend_cm_yr"], "gw_source": c["grace"]["source"],
        })
    return out


def _nearest_city(lat: float, lon: float) -> dict:
    return min(CITIES, key=lambda c: (c["lat"] - lat) ** 2 + (c["lon"] - lon) ** 2)


@app.get("/api/field/{cell_id}")
def field(cell_id: str):
    """One field: its climate, GRACE trend, nearest city and monthly weather
    for the replay years."""
    c = CELL_BY_ID.get(cell_id)
    if c is None:
        raise HTTPException(404, f"unknown field {cell_id!r}")
    cl = c["climate"]
    return {
        "id": c["id"], "lat": c["lat"], "lon": c["lon"], "bbox": c["bbox"],
        "near": _nearest_city(c["lat"], c["lon"])["name"],
        "rain_mm": cl["rain_mm"], "frost_days": cl["frost_days"], "heat_days": cl["heat_days"],
        "period": cl["period"], "gw_trend_cm_yr": c["grace"]["trend_cm_yr"], "gw_source": c["grace"]["source"],
        "monthly": weather.for_cell(c),
    }


class PrioritiesIn(BaseModel):
    save_water: float = Field(0.5, ge=0, le=1)
    income: float = Field(0.5, ge=0, le=1)
    build_soil: float = Field(0.5, ge=0, le=1)


class SimulateIn(BaseModel):
    preset: str = "Drought replay"
    rain_pct: float | None = Field(None, ge=-50, le=50)
    temp_delta_c: float | None = Field(None, ge=0, le=4)
    gw_offset_cm_yr: float | None = Field(None, ge=-3, le=3)
    priorities: PrioritiesIn = PrioritiesIn()
    model: str = "rules"
    years: int = Field(10, ge=1, le=10)
    cell_ids: list[str] | None = Field(None, max_length=600, description="limit the run to these fields")
    confirm_paid: bool = False


_cache: dict[str, list[str]] = {}


def _scenario(req: SimulateIn) -> Scenario:
    if req.preset not in PRESETS:
        raise HTTPException(400, f"unknown preset {req.preset!r}")
    base = PRESETS[req.preset]
    return Scenario(
        name=base.name,
        rain_pct=base.rain_pct if req.rain_pct is None else req.rain_pct,
        temp_delta_c=base.temp_delta_c if req.temp_delta_c is None else req.temp_delta_c,
        gw_offset_cm_yr=base.gw_offset_cm_yr if req.gw_offset_cm_yr is None else req.gw_offset_cm_yr,
    )


@app.post("/api/simulate")
async def simulate_endpoint(req: SimulateIn):
    if req.model not in ("drex", "llm", "rules"):
        raise HTTPException(400, "model must be drex, llm or rules")
    if not available_models()[req.model]:
        raise HTTPException(400, f"{req.model} is not configured on the server (missing API key)")
    run_cells = CELLS if not req.cell_ids else [CELL_BY_ID[c] for c in req.cell_ids if c in CELL_BY_ID]
    if not run_cells:
        raise HTTPException(400, "no known cell_ids")
    if req.model == "llm" and not req.confirm_paid and len(run_cells) * req.years > 20:
        raise HTTPException(402, "LLM runs are paid; resend with confirm_paid=true")

    scenario = _scenario(req)
    priorities = Priorities(**req.priorities.model_dump())
    key = json.dumps({"s": scenario.to_dict(), "p": priorities.to_dict(), "m": req.model, "y": req.years,
                      "c": [c["id"] for c in run_cells] if req.cell_ids else None}, sort_keys=True)

    async def stream():
        if key in _cache:
            for line in _cache[key]:
                yield line
            return
        lines = []

        def emit(obj):
            line = json.dumps(obj, separators=(",", ":")) + "\n"
            lines.append(line)
            return line

        yield emit({"type": "start", "scenario": scenario.to_dict(), "priorities": priorities.to_dict(),
                    "model": req.model, "years": [y for y, _ in simulate.scenario_years(scenario, req.years)],
                    "cells": len(run_cells)})
        t0 = time.perf_counter()
        try:
            async with AsyncExitStack() as stack:
                decider = rules_decider if req.model == "rules" else \
                    await stack.enter_async_context(DeciderPool(req.model))
                async for year, timing, records in simulate.iter_years(
                    run_cells, scenario, priorities, decider, req.model, req.years
                ):
                    yield emit({"type": "year", "year": year, "timing": timing, "cells": records})
        except Exception as e:  # noqa: BLE001 - report to the UI instead of a broken stream
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return
        yield emit({"type": "done", "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
        _cache[key] = lines

    return StreamingResponse(stream(), media_type="application/x-ndjson")
