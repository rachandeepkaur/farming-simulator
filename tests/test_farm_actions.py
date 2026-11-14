"""Farm view: field actions engine, budgets, circular waste loop, API stream."""
import json

import pytest
from fastapi.testclient import TestClient

from atlas import farm, farm_actions, weather
from atlas.farm_actions import (DEFAULT_STOCK, FARM_QUESTIONS, farm_rules_decider, initial_field_state,
                                iter_seasons, rule_answers)
from atlas.scenario import PRESETS, Priorities


def _state(**kw):
    f = farm.load()["fields"][0]
    st = initial_field_state(f, {})
    st.update(kw)
    fm = {"n": 36, "aquifer_cm": 0.0, "stock": dict(DEFAULT_STOCK), "compost": 8.0, "cows": 24}
    w = {"rain_mm": 3, "tmax_c": 35, "heat_days": 30, "frost_days": 0}
    return farm_actions.build_state(f, st, fm, "2014", 2, w, Priorities(), "Fresno")


def test_questions_shape():
    for k, q in FARM_QUESTIONS.items():
        assert q["type"] in ("noul", "choice")
        if q["type"] == "choice":
            assert len(q["criteria"]) >= 2


def test_state_is_deterministic_and_rules_read_it():
    assert _state() == _state()
    a = rule_answers(_state(ph=5.2, pests=80, n=20))
    assert set(a) == set(FARM_QUESTIONS)
    assert a["lime"]["value"] is True
    assert a["spray_pests"]["value"] is True
    assert a["fertilize"]["value"] in ("compost", "synthetic")
    assert rule_answers(_state(ph=7.2))["lime"]["value"] is False


async def _run(**over):
    fields = farm.load()["fields"]
    cells = farm.farm_cells()
    out = []
    stock = {**DEFAULT_STOCK, **over.pop("stock", {})}
    async for m in iter_seasons(fields, weather.for_cell(cells[0]), PRESETS["Drought replay"], Priorities(),
                                farm_rules_decider, "rules", over, stock, "Fresno", -2.0, n_years=2):
        out.append(m)
    return out


@pytest.mark.asyncio
async def test_budget_is_enforced():
    pests = {f["id"]: 90 for f in farm.load()["fields"]}
    seasons = await _run(pests=pests, stock={"spray_pests": 3})
    for s in seasons:
        sprayed = sum(r["actions"]["spray_pests"] for r in s["cells"].values())
        assert sprayed <= 3
    assert any(s["farm"]["denied"]["spray_pests"] > 0 for s in seasons)


@pytest.mark.asyncio
async def test_circular_loop_and_scores():
    seasons = await _run()
    assert len(seasons) == 8
    last = seasons[-1]["farm"]
    assert 0 <= last["scores"]["sustainability"] <= 100
    assert last["compost"] >= 0
    assert all(r["health"] >= 0 for r in seasons[-1]["cells"].values())


def test_api_stream():
    from server.app import app
    r = TestClient(app).post("/api/farm/run", json={"model": "rules", "years": 1, "cows": 10})
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert lines[0]["type"] == "start" and lines[-1]["type"] == "done"
    assert sum(x["type"] == "season" for x in lines) == 4
