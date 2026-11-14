"""Tasks 3b and 12: rainfall, frost and heat per cell from NASA POWER daily data.

One daily request per POWER pixel (2001-2025), cached to disk. From the daily
series we compute the multi-year means, the per-year values for the drought
replay, and frost/heat counts under +0 to +4 C warming for the slider.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict

import httpx

from .config import (
    CACHE_DIR,
    DT_STEPS,
    FROST_C,
    HEAT_C,
    POWER_END,
    POWER_PERIOD,
    POWER_START,
    REPLAY_YEARS,
)

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = "T2M_MAX,T2M_MIN,PRECTOTCORR"
FILL = -999.0


def fetch_pixel(lat: float, lon: float, client: httpx.Client, retries: int = 3) -> dict:
    """Daily POWER series for one pixel, from the disk cache if present."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"power_{lat}_{lon}.json"
    if path.exists():
        return json.loads(path.read_text())

    params = {
        "parameters": PARAMS,
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": POWER_START,
        "end": POWER_END,
        "format": "JSON",
    }
    for attempt in range(retries):
        try:
            r = client.get(POWER_URL, params=params, timeout=120)
            r.raise_for_status()
            data = r.json()["properties"]["parameter"]
            path.write_text(json.dumps(data))
            return data
        except (httpx.HTTPError, KeyError) as e:
            if attempt == retries - 1:
                raise RuntimeError(f"POWER fetch failed for {lat},{lon}: {e}") from e
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def summarise(daily: dict) -> dict:
    """Turn a daily POWER series into the cell's climate block."""
    tmax, tmin, prec = daily["T2M_MAX"], daily["T2M_MIN"], daily["PRECTOTCORR"]

    by_year: dict[int, dict] = defaultdict(
        lambda: {"rain_mm": 0.0, "frost_days": 0, "heat_days": 0, "days": 0,
                 "heat_dt": [0] * len(DT_STEPS), "frost_dt": [0] * len(DT_STEPS)}
    )
    for day, hi in tmax.items():
        lo, p = tmin.get(day, FILL), prec.get(day, FILL)
        if FILL in (hi, lo, p):
            continue
        y = by_year[int(day[:4])]
        y["days"] += 1
        y["rain_mm"] += p  # PRECTOTCORR is mm/day
        y["frost_days"] += lo < FROST_C
        y["heat_days"] += hi > HEAT_C
        for i, dt in enumerate(DT_STEPS):
            y["heat_dt"][i] += hi + dt > HEAT_C
            y["frost_dt"][i] += lo + dt < FROST_C

    # Only full-ish years count toward the means.
    full = {yr: v for yr, v in by_year.items() if v["days"] >= 360}
    if not full:
        raise ValueError("no complete years in POWER series")
    n = len(full)

    def mean(key):
        return round(sum(v[key] for v in full.values()) / n, 1)

    def mean_list(key):
        return [round(sum(v[key][i] for v in full.values()) / n, 1) for i in range(len(DT_STEPS))]

    return {
        "rain_mm": mean("rain_mm"),
        "frost_days": mean("frost_days"),
        "heat_days": mean("heat_days"),
        "heat_days_by_dt": mean_list("heat_dt"),
        "frost_days_by_dt": mean_list("frost_dt"),
        "years": {
            str(yr): {
                "rain_mm": round(full[yr]["rain_mm"], 1),
                "frost_days": full[yr]["frost_days"],
                "heat_days": full[yr]["heat_days"],
            }
            for yr in REPLAY_YEARS
            if yr in full
        },
        "period": POWER_PERIOD,
    }


def attach_climate(cells: list[dict], log=print) -> list[dict]:
    """Fetch each unique POWER pixel once and copy its climate onto its cells."""
    pixels = sorted({c["power_pixel"] for c in cells})
    log(f"{len(cells)} cells share {len(pixels)} NASA POWER pixels")
    summaries = {}
    with httpx.Client(headers={"User-Agent": "rotation-atlas/0.1"}) as client:
        for i, key in enumerate(pixels, 1):
            lat, lon = (float(x) for x in key.split("_"))
            summaries[key] = summarise(fetch_pixel(lat, lon, client))
            log(f"  [{i}/{len(pixels)}] {key}: rain {summaries[key]['rain_mm']} mm, "
                f"frost {summaries[key]['frost_days']} d, heat {summaries[key]['heat_days']} d")
    for c in cells:
        c["climate"] = {**summaries[c["power_pixel"]], "power_pixel": c["power_pixel"]}
    return cells
