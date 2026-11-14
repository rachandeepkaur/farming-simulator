"""Small API for the simulation UI.

    uv run uvicorn server.app:app --port 8000

GET  /api/meta      presets, strategies, crop facts with evidence, valley outline, models
GET  /api/cells     the grid with each cell's climate and GRACE trend
GET  /api/farm      the farm's fields (soil, crop), parent cell and monthly weather
POST /api/farm/run  farm god sim: streams one line per season with every field's actions (NDJSON)
                    (POST /api/simulate with farm=true and supply_cm={field: cm} runs the farm)
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

from atlas import crops, farm, farm_actions, simulate, weather
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


@app.get("/api/farm")
def farm_endpoint():
    """The farm: fields with soil, the parent valley cell, and its monthly weather."""
    f = farm.load()
    parent = CELL_BY_ID[f["parent_cell"]]
    return {**{k: v for k, v in f.items() if k != "fields"},
            "fields": f["fields"],
            "near": _nearest_city(parent["lat"], parent["lon"])["name"],
            "parent": {"id": parent["id"], "bbox": parent["bbox"], "rain_mm": parent["climate"]["rain_mm"],
                       "frost_days": parent["climate"]["frost_days"], "heat_days": parent["climate"]["heat_days"],
                       "period": parent["climate"]["period"], "gw_trend_cm_yr": parent["grace"]["trend_cm_yr"],
                       "gw_source": parent["grace"]["source"]},
            "monthly": weather.for_cell(parent),
            "default_supply_cm": SUSTAINABLE_SUPPLY_CM}


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
    farm: bool = Field(False, description="simulate the farm's fields instead of valley cells")
    supply_cm: dict[str, float] | None = Field(None, description="farm: water allocated to each field, cm/yr")
    ph: dict[str, float] | None = Field(None, description="farm: soil pH per field (after liming or a scenario)")
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
    if req.farm:
        supply = {k: max(0.0, min(120.0, v)) for k, v in (req.supply_cm or {}).items()}
        ph = {k: max(3.5, min(10.0, v)) for k, v in (req.ph or {}).items()}
        run_cells = farm.farm_cells(supply, ph)
    else:
        run_cells = CELLS if not req.cell_ids else [CELL_BY_ID[c] for c in req.cell_ids if c in CELL_BY_ID]
    if not run_cells:
        raise HTTPException(400, "no known cell_ids")
    if req.model == "llm" and not req.confirm_paid and len(run_cells) * req.years > 20:
        raise HTTPException(402, "LLM runs are paid; resend with confirm_paid=true")

    scenario = _scenario(req)
    priorities = Priorities(**req.priorities.model_dump())
    key = json.dumps({"s": scenario.to_dict(), "p": priorities.to_dict(), "m": req.model, "y": req.years,
                      "c": [c["id"] for c in run_cells] if req.cell_ids else None,
                      "farm": req.farm, "w": {c["id"]: c.get("supply_cm") for c in run_cells} if req.farm else None,
                      "ph": req.ph if req.farm else None},
                     sort_keys=True)

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


# ---------------------------------------------------------------- farm view --
class FarmRunIn(BaseModel):
    """One farm run as a god sim: season-by-season field actions decided by Drex."""
    preset: str = "Drought replay"
    rain_pct: float | None = Field(None, ge=-50, le=50)
    temp_delta_c: float | None = Field(None, ge=0, le=4)
    gw_offset_cm_yr: float | None = Field(None, ge=-3, le=3)
    priorities: PrioritiesIn = PrioritiesIn()
    model: str = "rules"
    years: int = Field(10, ge=1, le=10)
    supply_cm: dict[str, float] | None = None   # water share per field, cm/yr
    ph: dict[str, float] | None = None          # soil pH per field
    pests: dict[str, float] | None = None       # starting pest pressure per field (scenarios)
    n: dict[str, float] | None = None           # starting soil nitrogen per field
    crops: dict[str, str] | None = None         # replanted fields
    stock: dict[str, int] | None = None         # lime / synthetic / spray_pests / cover_crop per year
    cows: int = Field(24, ge=0, le=200)
    confirm_paid: bool = False


_farm_cache: dict[str, list[str]] = {}


@app.post("/api/farm/run")
async def farm_run(req: FarmRunIn):
    if req.model not in ("drex", "llm", "rules"):
        raise HTTPException(400, "model must be drex, llm or rules")
    if not available_models()[req.model]:
        raise HTTPException(400, f"{req.model} is not configured on the server (missing API key)")
    f = farm.load()
    fields = f["fields"]
    if req.model == "llm" and not req.confirm_paid:
        raise HTTPException(402, "LLM runs are paid; resend with confirm_paid=true")
    sc = _scenario(SimulateIn(preset=req.preset, rain_pct=req.rain_pct, temp_delta_c=req.temp_delta_c,
                              gw_offset_cm_yr=req.gw_offset_cm_yr))
    prio = Priorities(**req.priorities.model_dump())
    valid = set(crops.load()["crops"]) & set(farm_actions.PRICE_PER_ACRE)
    overrides = {"supply_cm": req.supply_cm or {}, "ph": req.ph or {}, "pests": req.pests or {}, "n": req.n or {},
                 "crops": {k: v for k, v in (req.crops or {}).items() if v in valid}}
    stock = {**farm_actions.DEFAULT_STOCK, **{k: int(v) for k, v in (req.stock or {}).items() if k in farm_actions.DEFAULT_STOCK}}
    parent = CELL_BY_ID[f["parent_cell"]]
    key = json.dumps({"r": req.model_dump(exclude={"confirm_paid"}), "f": f["parent_cell"]}, sort_keys=True)

    async def stream():
        if key in _farm_cache:
            for line in _farm_cache[key]:
                yield line
            return
        lines = []

        def emit(obj):
            line = json.dumps(obj, separators=(",", ":")) + "\n"
            lines.append(line)
            return line

        yield emit({"type": "start", "scenario": sc.to_dict(), "model": req.model, "fields": len(fields),
                    "stock": stock, "cows": req.cows})
        t0 = time.perf_counter()
        try:
            async with AsyncExitStack() as stack:
                if req.model == "rules":
                    decider = farm_actions.farm_rules_decider
                else:
                    kw = {"questions": farm_actions.FARM_QUESTIONS}
                    if req.model == "llm":
                        kw["system"] = farm_actions.FARM_SYSTEM
                    decider = await stack.enter_async_context(DeciderPool(req.model, **kw))
                async for msg in farm_actions.iter_seasons(
                    fields, weather.for_cell(parent), sc, prio, decider, req.model, overrides, stock,
                    _nearest_city(parent["lat"], parent["lon"])["name"], parent["grace"]["trend_cm_yr"],
                    cows=req.cows, n_years=req.years,
                ):
                    yield emit(msg)
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return
        yield emit({"type": "done", "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
        _farm_cache[key] = lines

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/farm/questions")
def farm_questions():
    """The exact question set Drex gets for the farm view (for the request viewer)."""
    return {"questions": farm_actions.FARM_QUESTIONS, "default_stock": farm_actions.DEFAULT_STOCK,
            "prices_per_acre": farm_actions.PRICE_PER_ACRE, "costs": farm_actions.COST}
