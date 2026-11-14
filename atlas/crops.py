"""Crop facts and strategy definitions.

Loads data/crops.json (built from the crop guides by scripts/build_crops.py,
task 5) when it exists, otherwise the placeholder data/crops.sample.json.

A strategy's `pattern` says how its crops share a year:
- "same_year": all its crops grow every year (e.g. tomato + winter cover).
- "alternate": one crop per year in turn (e.g. wheat one year, safflower the
  next), so yearly water use is the average.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .config import CROPS_PATH, CROPS_SAMPLE_PATH

STRATEGIES = ("existing", "cover_crop", "drought_tolerant")


@lru_cache(maxsize=1)
def load() -> dict:
    path = CROPS_PATH if CROPS_PATH.exists() else CROPS_SAMPLE_PATH
    data = json.loads(path.read_text())
    data["_path"] = str(path)
    missing = set(STRATEGIES) - set(data["strategies"])
    if missing:
        raise ValueError(f"{path} is missing strategies: {sorted(missing)}")
    return data


def is_placeholder() -> bool:
    return load()["_path"] == str(CROPS_SAMPLE_PATH)


def _crop_rain_share(crop: dict) -> float:
    from .sim_constants import DEEP_ROOT_BONUS, DEEP_ROOT_CM, RAIN_SHARE_BY_SEASON, RAIN_SHARE_MAX

    share = RAIN_SHARE_BY_SEASON[crop["season"]]
    if crop["root_depth_cm"] >= DEEP_ROOT_CM:
        share += DEEP_ROOT_BONUS
    return min(RAIN_SHARE_MAX, share)


def _heat_factor(heat_days: float) -> float:
    """Hot years raise water need: +0.2% per heat day above 60 (sim_constants)."""
    from .sim_constants import HEAT_DAY_BASE, WATER_NEED_PER_HEAT_DAY

    return 1 + max(0.0, heat_days - HEAT_DAY_BASE) * WATER_NEED_PER_HEAT_DAY


def strategy_water_need_cm(strategy: str, heat_days: float = 0.0) -> float:
    """Yearly crop water use (ET) of a strategy, in cm."""
    d = load()
    s = d["strategies"][strategy]
    needs = [d["crops"][c]["water_need_cm"] for c in s["crops"]]
    base = sum(needs) if s.get("pattern", "same_year") == "same_year" else sum(needs) / len(needs)
    return round(base * _heat_factor(heat_days), 1)


def strategy_rain_share(strategy: str) -> float:
    """Share of annual rain the strategy's crops can use. Same-year: the best
    crop in the year sets it (a winter crop catches the winter rain).
    Alternate: the average over the rotation."""
    d = load()
    s = d["strategies"][strategy]
    shares = [_crop_rain_share(d["crops"][c]) for c in s["crops"]]
    if s.get("pattern", "same_year") == "same_year":
        return round(max(shares), 3)
    return round(sum(shares) / len(shares), 3)


def strategy_irrigation_cm(strategy: str, rain_mm: float, heat_days: float) -> tuple[float, float, float]:
    """(water need, rain used, irrigation needed), all cm/yr."""
    need = strategy_water_need_cm(strategy, heat_days)
    rain_used = min(need, rain_mm / 10 * strategy_rain_share(strategy))
    return need, round(rain_used, 1), round(need - rain_used, 1)


def strategy_summary(strategy: str) -> str:
    d = load()
    s = d["strategies"][strategy]
    joiner = " then " if s.get("pattern") == "alternate" else " + "
    crops = joiner.join(d["crops"][c]["name"] for c in s["crops"])
    if s.get("pattern") == "alternate":
        crops += ", alternating years"
    bare = ", ".join(s["bare_months"]) or "none"
    return f"{s['label']} ({crops}; bare months: {bare})"
