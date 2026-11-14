"""Monthly weather per NASA POWER pixel for the replay years, for the
single-field simulation view (rain, mean max temperature, frost and heat
days per month). Built from the same daily POWER data as cells.json."""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache

from .config import CACHE_DIR, DATA_DIR, FROST_C, HEAT_C, REPLAY_YEARS

MONTHLY_PATH = DATA_DIR / "weather_monthly.json"
FILL = -999.0


def monthly_from_daily(daily: dict) -> dict:
    """{year: [12 x {rain_mm, tmax_c, frost_days, heat_days}]} for REPLAY_YEARS."""
    acc = defaultdict(lambda: {"rain": 0.0, "tmax": 0.0, "n": 0, "frost": 0, "heat": 0})
    tmax, tmin, prec = daily["T2M_MAX"], daily["T2M_MIN"], daily["PRECTOTCORR"]
    for day, hi in tmax.items():
        y, m = int(day[:4]), int(day[4:6])
        if y not in REPLAY_YEARS:
            continue
        lo, p = tmin.get(day, FILL), prec.get(day, FILL)
        if FILL in (hi, lo, p):
            continue
        a = acc[(y, m)]
        a["rain"] += p
        a["tmax"] += hi
        a["n"] += 1
        a["frost"] += lo < FROST_C
        a["heat"] += hi > HEAT_C
    out = {}
    for y in REPLAY_YEARS:
        months = []
        for m in range(1, 13):
            a = acc.get((y, m))
            if not a or not a["n"]:
                months.append(None)
                continue
            months.append({"rain_mm": round(a["rain"], 1), "tmax_c": round(a["tmax"] / a["n"], 1),
                           "frost_days": a["frost"], "heat_days": a["heat"]})
        out[str(y)] = months
    return out


def build_all(pixels: list[str]) -> dict:
    """Monthly series for each POWER pixel, from the daily cache."""
    out = {}
    for key in pixels:
        lat, lon = (float(x) for x in key.split("_"))
        path = CACHE_DIR / f"power_{lat}_{lon}.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run scripts/build_cells.py first")
        out[key] = monthly_from_daily(json.loads(path.read_text()))
    return out


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(MONTHLY_PATH.read_text())


def for_cell(cell: dict) -> dict:
    return load()[cell["climate"]["power_pixel"]]
