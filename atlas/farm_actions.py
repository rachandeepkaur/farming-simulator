"""Farm resource management: what each field should get this season.

The farm view's decision loop. Every season (4 a year, 10 years of real NASA
weather), Drex looks at each field's condition and decides its actions:
how much to irrigate, and whether to fertilize, lime, spray for pests or sow
a cover crop. Code then enforces the farm's limited resources (water shares,
lime, fertilizer, pesticide) and applies the season's weather.

Drex decides; code enforces budgets and does the bookkeeping. The crop on a
field does not change by decision (the farmer plants it; the god tools can
replant it). All numbers in this file are ILLUSTRATIVE round numbers, not
calibrated agronomy, and the UI says so.
"""

from __future__ import annotations

import math
import re
import time
from statistics import mean

from . import crops as cropdb
from .decide import Decider, decide_states

SEASONS = [("winter", (1, 2, 3)), ("spring", (4, 5, 6)), ("summer", (7, 8, 9)), ("fall", (10, 11, 12))]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---- the question set (Drex gets these unchanged; the LLM gets the same) ----
FARM_QUESTIONS: dict = {
    "irrigation": {
        "type": "choice",
        "instructions": "How much should this field be irrigated this season?",
        "criteria": {
            "none": "No irrigation: the crop is not in the ground, or soil water and rain cover it.",
            "light": "Light irrigation, about 8 cm this season.",
            "full": "Full irrigation, about 18 cm this season.",
        },
    },
    "fertilize": {
        "type": "choice",
        "instructions": "Should this field be fertilized this season, and with what?",
        "criteria": {
            "none": "No: nitrogen is adequate, or nothing is growing.",
            "compost": "Yes, with compost from the farm's own manure and crop residue (slower, builds soil).",
            "synthetic": "Yes, with bought synthetic nitrogen (fast, costs money, slowly acidifies soil).",
        },
    },
    "lime": {
        "type": "noul",
        "instructions": "Should this field be limed this season to raise its soil pH?",
        "criteria": {"true": "Soil pH is below about 6.0.", "false": "Soil pH is 6.0 or higher."},
    },
    "spray_pests": {
        "type": "noul",
        "instructions": "Should this field be sprayed for pests this season?",
        "criteria": {"true": "A crop is in the ground and pest pressure is high.",
                     "false": "Pest pressure is low, or nothing is growing."},
    },
    "cover_crop": {
        "type": "noul",
        "instructions": "Should a cover crop be sown on this field this season to rest and rebuild the soil?",
        "criteria": {"true": "The field is bare this season and the soil needs nitrogen or protection.",
                     "false": "A cash crop is in the ground, or the soil is fine."},
    },
    "needs_local_review": {
        "type": "noul",
        "instructions": "Should a local advisor check this field in person because the call is borderline or the data is thin?",
    },
}
ACTION_KEYS = ["lime", "spray_pests", "cover_crop"]      # yes/no actions that use stock
ALL_ACTIONS = ["compost", "synthetic", "lime", "spray_pests", "cover_crop"]
FARM_SYSTEM = (
    "You are a farm resource manager for one farm in California's Central Valley. "
    "You will be given one field's condition this season, the farm's remaining resources and the "
    "farmer's priorities, followed by questions. Answer every question using only the evidence given. "
    "For yes/no questions answer true or false. For choice questions answer with exactly one option key."
)

# ---- illustrative constants ----
IRRIGATION_CM = {"none": 0.0, "light": 8.0, "full": 18.0}
PRICE_PER_ACRE = {"processing_tomato": 3500, "winter_wheat": 650, "safflower": 550}  # $/acre at full health
COST = {"synthetic": 2000, "compost": 300, "lime": 1200, "spray_pests": 1500, "cover_crop": 800}  # $ per field application
PUMP_COST_PER_CM_ACRE = 14.0
PUMP_TO_AQUIFER = 0.35          # cm of farm-average storage lost per cm pumped on one field, / n fields
RECHARGE_SHARE = 0.3
LIME_TARGET_PH = 6.8
FERT_N = 35.0          # synthetic
COMPOST_N = 25.0       # compost: less N, but builds soil and doesn't acidify
COVER_N = 12.0
CASH_CROPS = list(PRICE_PER_ACRE)
DEFAULT_STOCK = {"lime": 6, "synthetic": 10, "spray_pests": 10, "cover_crop": 12}
STOCK_LABEL = {"lime": "lime", "synthetic": "synthetic fertilizer", "spray_pests": "pesticide", "cover_crop": "cover seed"}

# Circular farm: animals eat crop residue and cover-crop forage; their manure and
# the leftover residue become compost, which goes back on the fields.
RESIDUE_LOADS = {"processing_tomato": 1.0, "winter_wheat": 2.0, "safflower": 1.0}  # per harvested field, at full health
FORAGE_LOADS = 0.5          # grazeable cover crop per field per season
FEED_PER_COW = 0.125        # loads per cow per season
MANURE_PER_COW = 0.125      # loads per cow per season
RESIDUE_TO_COMPOST = 0.6    # composting shrinks residue
COMPOST_CAP = 40.0          # the pile can't grow forever; overflow is wasted
FEED_PRICE = 600            # $ per load of bought feed
MILK_PER_COW = 900          # $ per cow per season when fully fed


def _rnd(*xs) -> float:
    s = math.sin(sum((i + 1) * 12.9898 * x for i, x in enumerate(xs)) + 78.233) * 43758.5453
    return s - math.floor(s)


def crop_months(crop: str) -> list[int]:
    return cropdb.load()["crops"][crop]["months"]


def crop_phase(crop: str, q: int) -> dict:
    """Is the crop in the ground this season, and is it being planted or harvested."""
    months = crop_months(crop)
    qm = SEASONS[q][1]
    inside = [m for m in qm if m in months]
    return {"in_ground": bool(inside), "months": len(inside),
            "planting": months[0] in qm, "harvest": months[-1] in qm}


def season_weather(monthly_year: list, q: int) -> dict:
    ms = [monthly_year[m - 1] for m in SEASONS[q][1] if monthly_year[m - 1]]
    if not ms:
        return {"rain_mm": 0.0, "tmax_c": 20.0, "heat_days": 0, "frost_days": 0}
    return {"rain_mm": round(sum(m["rain_mm"] for m in ms), 1), "tmax_c": round(mean(m["tmax_c"] for m in ms), 1),
            "heat_days": int(sum(m["heat_days"] for m in ms)), "frost_days": int(sum(m["frost_days"] for m in ms))}


def scenario_monthly(monthly: dict, years: list[str], sc) -> dict:
    """Monthly weather per simulated year. The drought replay uses the real years;
    other presets use the 2012-2021 mean month, shifted by the scenario."""
    out = {}
    if sc.name == "Drought replay":
        base = {y: monthly[y] for y in years}
    else:
        avg = []
        for m in range(12):
            vals = [monthly[y][m] for y in monthly if monthly[y][m]]
            avg.append({k: mean(v[k] for v in vals) for k in ("rain_mm", "tmax_c", "heat_days", "frost_days")})
        base = {y: avg for y in years}
    dt = sc.temp_delta_c
    for y, ms in base.items():
        out[y] = [None if m is None else {
            "rain_mm": round(m["rain_mm"] * (1 + sc.rain_pct / 100), 1),
            "tmax_c": round(m["tmax_c"] + dt, 1),
            "heat_days": round(m["heat_days"] + (3 * dt if m["tmax_c"] > 27 else 0.3 * dt)),
            "frost_days": round(max(0.0, m["frost_days"] * (1 - 0.3 * dt))),
        } for m in ms]
    return out


def _level(x: float) -> str:
    return "high" if x >= 0.67 else "medium" if x >= 0.34 else "low"


def crop_use_cm(crop: str, phase: dict, w: dict) -> float:
    if not phase["in_ground"]:
        return 0.0
    c = cropdb.load()["crops"][crop]
    heat = 1 + max(0, w["heat_days"] - 15) * 0.005
    return round(c["water_need_cm"] * phase["months"] / len(c["months"]) * heat, 1)


def build_state(f: dict, st: dict, farm: dict, year: str, q: int, w: dict, prio, near: str) -> str:
    """Fixed-format text for one field this season (same inputs, same text)."""
    crop = st["crop"]
    ph = crop_phase(crop, q)
    cname = cropdb.load()["crops"][crop]["name"]
    stage = ("planting" if ph["planting"] else "harvest this season" if ph["harvest"] else "growing") if ph["in_ground"] else "not in the ground (field bare)"
    use = crop_use_cm(crop, ph, w)
    ph_note = "acidic" if st["ph"] < 6.0 else "alkaline" if st["ph"] > 8.4 else "fine"
    n_note = "low" if st["n"] < 35 else "adequate" if st["n"] < 70 else "high"
    p_note = "high" if st["pests"] >= 55 else "moderate" if st["pests"] >= 30 else "low"
    s = farm["stock"]
    lines = [
        f"Field {f['id']} ({f.get('acres', 40):.0f} acres) on a {farm['n']}-field farm near {near}, California.",
        f"Season: {SEASONS[q][0]} {year} ({MONTH_ABBR[SEASONS[q][1][0] - 1]}-{MONTH_ABBR[SEASONS[q][1][-1] - 1]}).",
        f"Crop: {cname}, {stage}." + (f" It will use about {use:.0f} cm of water this season." if use else ""),
        f"Weather this season: rain {w['rain_mm']:.0f} mm, average high {w['tmax_c']:.0f} C, "
        f"{w['heat_days']} days above 35 C, {w['frost_days']} frost nights.",
        f"Soil water: {st['moisture']:.1f} of {st['cap']:.1f} cm the soil can hold.",
        f"Soil pH: {st['ph']:.1f} ({ph_note}). Soil nitrogen: {st['n']:.0f}/100 ({n_note}). "
        f"Pest pressure: {st['pests']:.0f}/100 ({p_note}). Crop health: {st['health']:.0f}/100.",
        f"Surface water left in this field's share this year: {st['share_left']:.0f} cm. "
        f"Irrigation beyond that is pumped from the aquifer (farm aquifer {farm['aquifer_cm']:+.1f} cm since the start).",
        f"Farm stock left this year: {s['lime']} lime, {s['synthetic']} synthetic fertilizer, {s['spray_pests']} pesticide, "
        f"{s['cover_crop']} cover seed (one field each). Compost pile: {farm['compost']:.0f} loads, made from the "
        f"herd's manure and crop residue (one load per field).",
        f"Herd: {farm['cows']} cows, fed on crop residue and cover-crop grazing first.",
        f"Farmer priorities: save water {_level(prio.save_water)}, income {_level(prio.income)}, build soil {_level(prio.build_soil)}.",
    ]
    return "\n".join(lines)


# ---- offline stand-in: reads the same text Drex sees ----
_N = r"([-+]?\d+(?:\.\d+)?)"


def rule_answers(state: str) -> dict:
    g = lambda p: float(re.search(p, state).group(1))  # noqa: E731
    bare = "not in the ground" in state
    use = float(m.group(1)) if (m := re.search(rf"use about {_N} cm", state)) else 0.0
    moist, cap = g(rf"Soil water: {_N} of"), g(rf"of {_N} cm the soil can hold")
    rain = g(rf"rain {_N} mm") / 10
    ph, n, pests = g(rf"Soil pH: {_N}"), g(rf"Soil nitrogen: {_N}"), g(rf"Pest pressure: {_N}")
    share = g(rf"share this year: {_N} cm")
    lv = lambda k: {"low": 0, "medium": 0.5, "high": 1}[re.search(rf"{k} (low|medium|high)", state).group(1)]  # noqa: E731
    save_w, income, soil = lv("save water"), lv("income"), lv("build soil")
    deficit = use - moist - 0.7 * rain
    irr = "none" if bare or deficit <= 2 else "light" if deficit <= 10 else "full"
    if irr == "full" and share < 8 and save_w >= 1:
        irr = "light"
    if irr == "light" and share <= 0 and save_w >= 1 and income < 1:
        irr = "none"
    need_n = (not bare) and n < (45 if income >= 1 else 35)
    compost_left = g(rf"Compost pile: {_N} loads")
    fert = "none" if not need_n else ("compost" if compost_left >= 1 and (soil >= 0.5 or n >= 25) else "synthetic")
    lime = ph < 6.0
    spray = (not bare) and pests >= (45 if income >= 1 else 55)
    cover = bare and (n < 60 or soil >= 0.5)
    borderline = (not bare) and abs(deficit - 10) < 1.5
    b = lambda v: {"value": bool(v), "p": 1.0 if v else 0.0}  # noqa: E731
    return {"irrigation": {"value": irr, "probs": {}}, "fertilize": {"value": fert, "probs": {}}, "lime": b(lime),
            "spray_pests": b(spray), "cover_crop": b(cover), "needs_local_review": b(borderline)}


async def farm_rules_decider(state: str):
    return rule_answers(state), 0.0, {}


# ---- simulation ----
def initial_field_state(f: dict, overrides: dict) -> dict:
    o = overrides
    cap = max(4.0, (f.get("soil") or {}).get("aws_cm") or 15.0)
    return {
        "crop": o.get("crops", {}).get(f["id"]) or f.get("crop", "processing_tomato"),
        "cap": round(cap, 1), "moisture": round(cap * 0.5, 1),
        "ph": float(o.get("ph", {}).get(f["id"], (f.get("soil") or {}).get("ph") or 7.0)),
        "n": float(o.get("n", {}).get(f["id"], 55.0)),
        "pests": float(o.get("pests", {}).get(f["id"], 10.0)),
        "health": 100.0, "soil": 50.0,
        "share_year": float(o.get("supply_cm", {}).get(f["id"], 40.0)),
        "share_left": float(o.get("supply_cm", {}).get(f["id"], 40.0)),
    }


def _allocate(results: dict, key: str, stock: int, sev, option=None) -> tuple[set, set]:
    """Give a limited resource to the fields Drex is most sure about (then the worst-off)."""
    if option is None:
        want = [cid for cid, a in results.items() if a and a[key]["value"]]
        conf = lambda cid: results[cid][key].get("p") or 0  # noqa: E731
    else:
        want = [cid for cid, a in results.items() if a and a[key]["value"] == option]
        conf = lambda cid: (results[cid][key].get("probs") or {}).get(option, 0)  # noqa: E731
    want.sort(key=lambda cid: (-conf(cid), -sev(cid)))
    stock = max(0, int(stock))
    return set(want[:stock]), set(want[stock:])


async def iter_seasons(fields: list[dict], monthly: dict, sc, prio, decider: Decider, model_name: str,
                       overrides: dict, stock_per_year: dict, near: str, grace_trend: float, cows: int = 24,
                       n_years: int = 10, concurrency: int = 128):
    years = sorted(monthly)[:n_years]
    wx = scenario_monthly(monthly, years, sc)
    sts = {f["id"]: initial_field_state(f, overrides) for f in fields}
    farm = {"n": len(fields), "aquifer_cm": 0.0, "coins": 0.0, "stock": dict(stock_per_year), "cows": cows,
            "compost": 8.0}
    totals = {"irr": 0.0, "pumped": 0.0, "compost_apps": 0, "synthetic_apps": 0, "waste_made": 0.0,
              "waste_used": 0.0, "crop_value": 0.0, "animal_value": 0.0}
    for year in years:
        farm["stock"] = dict(stock_per_year)
        for st in sts.values():
            st["share_left"] = st["share_year"]
        for q in range(4):
            w = season_weather(wx[year], q)
            items = [(f["id"], build_state(f, sts[f["id"]], farm, year, q, w, prio, near)) for f in fields]
            t0 = time.perf_counter()
            decided = await decide_states(items, decider, model_name, concurrency)
            wall_ms = (time.perf_counter() - t0) * 1000
            res = {r["cell_id"]: r["answers"] for r in decided["results"]}
            errs = {r["cell_id"]: r["error"] for r in decided["results"]}

            # budgets: code, not the model, hands out what the farm actually has
            granted, denied = {}, {}
            sev = {"lime": lambda c: 7 - sts[c]["ph"], "fert": lambda c: 100 - sts[c]["n"],
                   "spray_pests": lambda c: sts[c]["pests"], "cover_crop": lambda c: 100 - sts[c]["n"]}
            for k in ACTION_KEYS:
                granted[k], denied[k] = _allocate(res, k, farm["stock"][k], sev[k])
                farm["stock"][k] -= len(granted[k])
            granted["compost"], denied["compost"] = _allocate(res, "fertilize", farm["compost"], sev["fert"], "compost")
            farm["compost"] -= len(granted["compost"])
            granted["synthetic"], denied["synthetic"] = _allocate(res, "fertilize", farm["stock"]["synthetic"], sev["fert"], "synthetic")
            farm["stock"]["synthetic"] -= len(granted["synthetic"])
            residue, forage = 0.0, 0.0

            pumped_total, recharge_total, records = 0.0, 0.0, {}
            for f in fields:
                cid, st, a = f["id"], sts[f["id"]], res[f["id"]]
                acres = f.get("acres", 40)
                phase = crop_phase(st["crop"], q)
                if phase["planting"]:
                    st["health"] = 100.0
                acts = {k: cid in granted[k] for k in ALL_ACTIONS}
                irr_choice = a["irrigation"]["value"] if a else "none"
                irr = IRRIGATION_CM.get(irr_choice, 0.0)
                pumped = max(0.0, irr - st["share_left"])
                st["share_left"] = max(0.0, st["share_left"] - irr)
                cost = sum(COST[k] for k in ALL_ACTIONS if acts[k]) + pumped * PUMP_COST_PER_CM_ACRE * acres
                totals["irr"] += irr; totals["pumped"] += pumped
                totals["compost_apps"] += acts["compost"]; totals["synthetic_apps"] += acts["synthetic"]

                # water balance
                use = crop_use_cm(st["crop"], phase, w)
                rain_eff = w["rain_mm"] / 10 * (0.7 if phase["in_ground"] or acts["cover_crop"] else 0.5)
                avail = st["moisture"] + rain_eff + irr
                got = min(use, avail)
                stress = (use - got) / use if use > 0 else 0.0
                left = avail - got - (0.0 if phase["in_ground"] else 1.0)
                excess = max(0.0, left - st["cap"])
                st["moisture"] = round(max(0.0, min(st["cap"], left)), 1)
                recharge_total += excess * RECHARGE_SHARE
                pumped_total += pumped

                # soil chemistry and pests
                if acts["lime"]:
                    st["ph"] = max(st["ph"], LIME_TARGET_PH)
                if acts["synthetic"]:
                    st["n"] = min(100.0, st["n"] + FERT_N)
                    st["ph"] = round(st["ph"] - 0.08, 2)
                if acts["compost"]:
                    st["n"] = min(100.0, st["n"] + COMPOST_N)
                    st["soil"] = min(100.0, st["soil"] + 3)
                    st["moisture"] = min(st["cap"], st["moisture"] + 0.5)  # organic matter holds water
                if phase["in_ground"]:
                    st["n"] = max(0.0, st["n"] - 4.0 * phase["months"])
                    st["pests"] = min(100.0, st["pests"] + (5 + 0.9 * w["heat_days"]) * (0.7 + 0.6 * _rnd(hash(cid) % 997, int(year), q)))
                else:
                    st["pests"] *= 0.5
                if acts["cover_crop"] and not phase["in_ground"]:
                    st["n"] = min(100.0, st["n"] + COVER_N)
                    st["soil"] = min(100.0, st["soil"] + 2)
                    forage += FORAGE_LOADS
                elif not phase["in_ground"] and q in (0, 3):
                    st["soil"] = max(0.0, st["soil"] - 1)
                if acts["spray_pests"]:
                    st["pests"] = 5.0

                # crop health and harvest
                hits = []
                if phase["in_ground"]:
                    dh = -45 * stress
                    if stress > 0.15:
                        hits.append("water stress")
                    if st["ph"] < 6.0:
                        dh -= 8; hits.append("acid soil")
                    if st["n"] < 30:
                        dh -= 10; hits.append("low nitrogen")
                    if st["pests"] > 60:
                        dh -= 15; hits.append("pests")
                    if dh == 0:
                        dh = 4
                    st["health"] = max(0.0, min(100.0, st["health"] + dh))
                if st["ph"] < 6.0:
                    st["soil"] = max(0.0, st["soil"] - 2)
                value = 0.0
                if phase["harvest"]:
                    value = PRICE_PER_ACRE.get(st["crop"], 0) * acres * st["health"] / 100
                    residue += RESIDUE_LOADS.get(st["crop"], 0.5) * st["health"] / 100
                    totals["crop_value"] += value
                farm["coins"] += value - cost

                records[cid] = {
                    "year": int(year), "season": SEASONS[q][0], "q": q, "crop": st["crop"], "phase": phase,
                    "actions": {"irrigation": irr_choice, **acts},
                    "wanted": {**{k: bool(a and a[k]["value"]) for k in ACTION_KEYS},
                               "fertilize": a["fertilize"]["value"] if a else "none"},
                    "denied": [k for k in ALL_ACTIONS if cid in denied[k]],
                    "probs": None if a is None else {k: (a[k].get("probs") if FARM_QUESTIONS[k]["type"] == "choice" else a[k].get("p"))
                                                     for k in FARM_QUESTIONS},
                    "review": bool(a and a["needs_local_review"]["value"]),
                    "irrigation_cm": irr, "pumped_cm": round(pumped, 1), "share_left": round(st["share_left"], 1),
                    "use_cm": use, "stress": round(stress, 2), "hits": hits,
                    "moisture": st["moisture"], "cap": st["cap"], "ph": round(st["ph"], 2), "n": round(st["n"], 1),
                    "pests": round(st["pests"], 1), "health": round(st["health"], 1), "soil": round(st["soil"], 1),
                    "harvest_value": round(value), "cost": round(cost), "weather": w, "error": errs[cid],
                }
            farm["aquifer_cm"] = round(farm["aquifer_cm"] + grace_trend / 4 + sc.gw_offset_cm_yr / 4
                                       - pumped_total * PUMP_TO_AQUIFER / len(fields) + recharge_total / len(fields), 2)

            # animals and waste: feed the herd from residue and grazing first, compost the rest
            need = farm["cows"] * FEED_PER_COW
            from_farm = min(need, residue + forage)
            bought = need - from_farm
            leftover_residue = max(0.0, residue - max(0.0, from_farm - forage))
            manure = farm["cows"] * MANURE_PER_COW
            made = manure + leftover_residue * RESIDUE_TO_COMPOST
            room = max(0.0, COMPOST_CAP - farm["compost"])
            farm["compost"] = round(farm["compost"] + min(made, room), 2)
            wasted = max(0.0, made - room)
            milk = farm["cows"] * MILK_PER_COW
            farm["coins"] += milk - bought * FEED_PRICE
            totals["animal_value"] += milk
            totals["waste_made"] += residue + manure
            totals["waste_used"] += residue + manure - wasted

            # scores: sustainable AND productive
            soil_avg = mean(st["soil"] for st in sts.values())
            water_score = 100 * (1 - totals["pumped"] / totals["irr"]) if totals["irr"] else 100.0
            inputs_score = 100 * totals["compost_apps"] / max(1, totals["compost_apps"] + totals["synthetic_apps"]) if (totals["compost_apps"] + totals["synthetic_apps"]) else 100.0
            waste_score = 100 * totals["waste_used"] / totals["waste_made"] if totals["waste_made"] else 100.0
            sustain = round(mean([soil_avg, water_score, inputs_score, waste_score]))
            acres_total = sum(f.get("acres", 40) for f in fields)
            acre_in = totals["irr"] / 2.54 * acres_total / len(fields)
            efficiency = round(totals["crop_value"] / acre_in) if acre_in else None
            yield {"type": "season", "year": int(year), "q": q, "season": SEASONS[q][0],
                   "timing": {"wall_ms": round(wall_ms, 1), "p50_ms": decided["timing"]["p50_ms"],
                              "errors": decided["timing"]["errors"], "n": len(fields)},
                   "farm": {"aquifer_cm": farm["aquifer_cm"], "coins": round(farm["coins"]),
                            "stock_left": dict(farm["stock"]), "pumped_cm": round(pumped_total, 1),
                            "denied": {k: len(denied[k]) for k in ALL_ACTIONS},
                            "compost": farm["compost"], "cows": farm["cows"], "residue": round(residue, 2),
                            "forage": round(forage, 2), "feed_bought": round(bought, 2), "manure": round(manure, 2),
                            "waste_wasted": round(wasted, 2), "milk_value": round(milk),
                            "scores": {"sustainability": sustain, "soil": round(soil_avg), "water": round(water_score),
                                       "renewable_inputs": round(inputs_score), "waste_recycled": round(waste_score),
                                       "efficiency_usd_per_acre_in": efficiency}},
                   "cells": records}
