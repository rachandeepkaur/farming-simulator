import json

import httpx
import pytest

from atlas import crops, drex, llm, rules
from atlas.config import CELLS_PATH
from atlas.decide import decide_states
from atlas.grid import build_grid, point_in_polygon
from atlas.power import summarise
from atlas.questions import QUESTIONS
from atlas.scenario import PRESETS, Priorities, Scenario, apply
from atlas.simulate import initial_state, run, simulate_year
from atlas.state import build_state


def fake_cell(**clim):
    climate = {
        "rain_mm": 300.0, "frost_days": 5.0, "heat_days": 90.0,
        "heat_days_by_dt": [90.0 + 4 * i for i in range(9)],
        "frost_days_by_dt": [5.0 - 0.5 * i for i in range(9)],
        "years": {"2014": {"rain_mm": 150.0, "frost_days": 3, "heat_days": 110}},
        "power_pixel": "36.5_-120.0", "period": "2001-2025",
    }
    climate.update(clim)
    return {"id": "r000c000", "row": 0, "col": 0, "lat": 36.7, "lon": -120.0,
            "bbox": [-120.05, 36.65, -119.95, 36.75], "climate": climate,
            "grace": {"trend_cm_yr": -2.0, "source": "fallback"}}


# --- grid and POWER ---------------------------------------------------------

def test_grid_size_and_inside():
    cells = build_grid()
    assert 450 <= len(cells) <= 600
    assert len({c["id"] for c in cells}) == len(cells)
    assert point_in_polygon(-119.8, 36.75, [(-121, 35), (-118, 35), (-118, 38), (-121, 38)])
    assert not point_in_polygon(-117.0, 36.75, [(-121, 35), (-118, 35), (-118, 38), (-121, 38)])


def test_power_summarise_counts_days():
    days = {f"2014{m:02d}{d:02d}": None for m in range(1, 13) for d in range(1, 31)}
    keys = list(days)
    tmax = {k: (36.0 if i < 10 else 20.0) for i, k in enumerate(keys)}
    tmin = {k: (-1.0 if i >= len(keys) - 4 else 5.0) for i, k in enumerate(keys)}
    prec = {k: 1.0 for k in keys}
    s = summarise({"T2M_MAX": tmax, "T2M_MIN": tmin, "PRECTOTCORR": prec})
    assert s["heat_days"] == 10 and s["frost_days"] == 4 and s["rain_mm"] == 360.0
    # +0.5 C warming lifts nothing over 35 here (20.5) but keeps the 10 hot days.
    assert s["heat_days_by_dt"][0] == 10
    assert s["years"]["2014"]["heat_days"] == 10


def test_power_summarise_skips_fill_values():
    keys = [f"2015{m:02d}{d:02d}" for m in range(1, 13) for d in range(1, 31)] + ["20151231"]
    data = {"T2M_MAX": {k: 20.0 for k in keys}, "T2M_MIN": {k: 5.0 for k in keys},
            "PRECTOTCORR": {k: 1.0 for k in keys}}
    data["PRECTOTCORR"]["20150101"] = -999.0
    s = summarise(data)
    assert s["rain_mm"] == 360.0  # 361 days minus the one fill value


@pytest.mark.skipif(not CELLS_PATH.exists(), reason="run scripts/build_cells.py first")
def test_cells_file_matches_contract():
    cells = json.loads(CELLS_PATH.read_text())
    c = cells[0]
    for k in ("id", "row", "col", "lat", "lon", "bbox", "climate", "grace"):
        assert k in c
    for k in ("rain_mm", "frost_days", "heat_days", "heat_days_by_dt", "frost_days_by_dt", "years"):
        assert k in c["climate"]
    assert len(c["climate"]["heat_days_by_dt"]) == 9
    assert c["grace"]["source"] in ("grace", "fallback")


# --- scenario and state -----------------------------------------------------

def test_scenario_apply():
    cell = fake_cell()
    today = apply(cell, PRESETS["Today"])
    assert today["rain_mm"] == 300.0 and today["heat_days"] == 90.0
    hot = apply(cell, Scenario("x", rain_pct=-50, temp_delta_c=2.0, gw_offset_cm_yr=-1.0))
    assert hot["rain_mm"] == 150.0 and hot["heat_days"] == 106.0 and hot["gw_trend_cm_yr"] == -3.0
    replay = apply(cell, Scenario("Drought replay"), year="2014")
    assert replay["rain_mm"] == 150.0 and replay["heat_days"] == 110


def test_state_is_deterministic_and_parseable():
    cell = fake_cell()
    s1 = build_state(cell, PRESETS["Dry decade"], Priorities(0.9, 0.1, 0.5))
    s2 = build_state(cell, PRESETS["Dry decade"], Priorities(0.9, 0.1, 0.5))
    assert s1 == s2
    f = rules.facts_from_state(s1)
    assert f["rain_mm"] == 210 and f["save_water"] == 1.0 and f["income"] == 0.0
    assert f["gw_fallback"] is True
    assert set(f["irrigation"]) == set(crops.STRATEGIES) and f["supply"] == 40


def test_state_includes_simulation_block():
    s = build_state(fake_cell(), PRESETS["Today"], Priorities(),
                    sim={"groundwater_cm": -4.2, "soil_score": 55, "last_strategy": "cover_crop", "year_index": 2})
    assert "groundwater change -4.2 cm" in s and "soil health 55/100" in s
    assert rules.facts_from_state(s)["soil_score"] == 55


# --- Drex client --------------------------------------------------------------

def drex_reply(rec="cover_crop"):
    answers = {}
    for k, q in QUESTIONS.items():
        if q["type"] == "noul":
            answers[k] = {"type": "noul", "noul": 0.8}
        else:
            opts = list(q["criteria"])
            pick = rec if k == "recommended" else opts[0]
            answers[k] = {"type": "choice", "choice": pick,
                          "probabilities": {o: (0.9 if o == pick else 0.05) for o in opts},
                          "confidence": 0.9}
    return {"model": "nace-ai/drex-v2.0", "answers": answers, "usage": {"input_tokens": 500, "output_tokens": 8}}


async def test_drex_decide_sends_contract_and_retries_429():
    calls = []

    def handler(request: httpx.Request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=drex_reply())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answers, ms, usage = await drex.decide(client, "state text", model="nace-ai/drex-v2.0")
    assert len(calls) == 2
    body = calls[0]
    assert body["model"] == "nace-ai/drex-v2.0" and body["state"] == "state text"
    assert body["questions"] == QUESTIONS
    assert answers["recommended"]["value"] == "cover_crop"
    assert answers["fits_water_budget"] == {"value": True, "p": 0.8}
    assert usage["output_tokens"] == 8


async def test_drex_decide_raises_on_4xx():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))) as c:
        with pytest.raises(drex.DrexError, match="401"):
            await drex.decide(c, "s")


# --- LLM baseline -------------------------------------------------------------

def test_llm_schema_matches_questions():
    schema = llm.output_schema()
    assert set(schema["required"]) == set(QUESTIONS)
    assert schema["properties"]["recommended"]["enum"] == ["existing", "cover_crop", "drought_tolerant"]
    assert schema["properties"]["needs_local_review"] == {"type": "boolean"}


class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Usage:
    input_tokens, output_tokens = 900, 120


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Block("thinking"), _Block("text", text)]
        self.stop_reason, self.stop_details, self.usage = stop, None, _Usage()


class _FakeAnthropic:
    def __init__(self, resp):
        self.kwargs = None
        outer = self

        class _Messages:
            async def create(self, **kw):
                outer.kwargs = kw
                return resp

        class _Beta:
            messages = _Messages()

        self.beta = _Beta()


async def test_llm_decide_parses_json_and_normalises():
    raw = {k: (True if q["type"] == "noul" else list(q["criteria"])[0]) for k, q in QUESTIONS.items()}
    fake = _FakeAnthropic(_Resp(json.dumps(raw)))
    answers, ms, usage = await llm.decide(fake, "state text")
    assert answers["recommended"] == {"value": "existing", "probs": {}}
    assert answers["fits_water_budget"] == {"value": True, "p": None}
    assert fake.kwargs["model"] == "claude-opus-5-5"
    assert fake.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "state text" in fake.kwargs["messages"][0]["content"]


async def test_llm_decide_refusal_raises():
    with pytest.raises(llm.LLMError, match="refused"):
        await llm.decide(_FakeAnthropic(_Resp("", stop="refusal")), "s")


# --- runner, rules, simulation -------------------------------------------------

async def test_decide_states_isolates_failures():
    async def flaky(state):
        if state == "bad":
            raise RuntimeError("boom")
        return rules.rule_answers(build_state(fake_cell(), PRESETS["Today"], Priorities())), 1.0, {}

    out = await decide_states([("a", "ok"), ("b", "bad")], flaky, "test")
    by = {r["cell_id"]: r for r in out["results"]}
    assert by["a"]["answers"] is not None and by["b"]["error"] == "boom"
    assert out["timing"]["errors"] == 1 and out["timing"]["n"] == 2


def test_rules_flag_wrong_answers():
    s = build_state(fake_cell(rain_mm=100.0), PRESETS["Dry decade"], Priorities())
    good = rules.rule_answers(s)
    assert all(c["passed"] for c in rules.check(s, good))
    bad = json.loads(json.dumps(good))
    bad["fits_water_budget"]["value"] = not bad["fits_water_budget"]["value"]
    assert not all(c["passed"] for c in rules.check(s, bad))


def test_existing_in_todays_climate_reproduces_grace_trend():
    cell = fake_cell()
    today = apply(cell, PRESETS["Today"])
    nxt = simulate_year(initial_state(), today, "existing", baseline=today)
    assert nxt["groundwater_cm"] == pytest.approx(cell["grace"]["trend_cm_yr"])


def test_drier_year_and_thirstier_strategy_draw_down_more():
    cell = fake_cell()
    base = apply(cell, PRESETS["Today"])
    dry = apply(cell, Scenario("dry", rain_pct=-50))
    gw_today = simulate_year(initial_state(), base, "existing", base)["groundwater_cm"]
    gw_dry = simulate_year(initial_state(), dry, "existing", base)["groundwater_cm"]
    gw_cover = simulate_year(initial_state(), base, "cover_crop", base)["groundwater_cm"]
    gw_drought = simulate_year(initial_state(), base, "drought_tolerant", base)["groundwater_cm"]
    assert gw_dry < gw_today
    assert gw_cover <= gw_today <= gw_drought


def test_soil_score_moves_and_clamps():
    base = apply(fake_cell(), PRESETS["Today"])
    s = initial_state()
    for _ in range(30):
        s = simulate_year(s, base, "cover_crop", base)
    assert s["soil_score"] == 100.0
    for _ in range(80):
        s = simulate_year(s, base, "existing", base)
    assert s["soil_score"] == 0.0


async def test_simulation_run_shape_and_replay_years():
    cells = [fake_cell()]
    out = await run(cells, PRESETS["Drought replay"], Priorities(), rules.rules_decider, "rules", n_years=3)
    assert out["years"] == [2012, 2013, 2014]
    hist = out["cells"]["r000c000"]
    assert [h["year"] for h in hist] == [2012, 2013, 2014]
    assert len(out["timing"]) == 3
    for h in hist:
        assert h["strategy"] in crops.STRATEGIES


async def test_simulation_survives_failed_decisions():
    async def always_fail(state):
        raise RuntimeError("down")

    out = await run([fake_cell()], PRESETS["Today"], Priorities(), always_fail, "x", n_years=2)
    hist = out["cells"]["r000c000"]
    assert all(h["decision_failed"] and h["strategy"] == "existing" for h in hist)
    assert out["timing"][0]["errors"] == 1


# --- GRACE regrid (needs `uv sync --extra grace`) -----------------------------

def test_grace_regrid_recovers_known_trend(tmp_path):
    np = pytest.importorskip("numpy")
    xr = pytest.importorskip("xarray")
    from atlas.grace import regrid_from_file

    times = np.array([np.datetime64("2003-01-01") + np.timedelta64(30 * i, "D") for i in range(120)])
    lats = np.arange(34.25, 41.75, 0.5)
    lons = np.arange(237.25, 242.75, 0.5)  # 0-360 like JPL mascon files
    years = (times - times[0]) / np.timedelta64(1, "D") / 365.25
    # Trend of -2 cm/yr everywhere, plus a seasonal wiggle.
    data = (-2.0 * years + np.sin(2 * np.pi * years))[:, None, None] * np.ones((1, len(lats), len(lons)))
    ds = xr.Dataset({"lwe_thickness": (("time", "lat", "lon"), data)},
                    coords={"time": times, "lat": lats, "lon": lons})
    path = tmp_path / "grace.nc"
    ds.to_netcdf(path)

    cells = build_grid()[:20]
    regrid_from_file(cells, path, start="2003-01-01", end="2013-01-01")
    for c in cells:
        assert c["grace"]["source"] == "grace"
        assert c["grace"]["trend_cm_yr"] == pytest.approx(-2.0, abs=0.1)
