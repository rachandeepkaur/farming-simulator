"""Scenario presets and how a scenario changes one cell's climate inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import DT_STEPS
from .sim_constants import SUSTAINABLE_SUPPLY_CM


@dataclass(frozen=True)
class Scenario:
    name: str = "Today"
    rain_pct: float = 0.0        # -50 .. +50
    temp_delta_c: float = 0.0    # 0 .. 4, snapped to 0.5 steps
    gw_offset_cm_yr: float = 0.0  # -3 .. +3, added to the GRACE trend

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Priorities:
    save_water: float = 0.5
    income: float = 0.5
    build_soil: float = 0.5

    def to_dict(self):
        return asdict(self)


# Preset values are round, illustrative numbers for the demo.
PRESETS = {
    "Today": Scenario("Today"),
    "Dry decade": Scenario("Dry decade", rain_pct=-30, temp_delta_c=0.5, gw_offset_cm_yr=-1.0),
    "Hotter summers": Scenario("Hotter summers", temp_delta_c=2.0),
    "Wet years": Scenario("Wet years", rain_pct=25, gw_offset_cm_yr=0.5),
    # Simulation only: replays real NASA POWER years 2012-2021.
    "Drought replay": Scenario("Drought replay"),
}


def _dt_index(temp_delta_c: float) -> int:
    i = round(temp_delta_c / 0.5)
    return max(0, min(len(DT_STEPS) - 1, i))


def apply(cell: dict, sc: Scenario, year: str | None = None) -> dict:
    """Climate inputs for one cell under a scenario. With `year`, start from
    that year's real POWER values (drought replay) instead of the mean."""
    clim = cell["climate"]
    i = _dt_index(sc.temp_delta_c)
    if year is not None and year in clim.get("years", {}):
        y = clim["years"][year]
        rain, frost, heat = y["rain_mm"], y["frost_days"], y["heat_days"]
        # Shift the real year by the same warming delta the mean would get.
        heat += clim["heat_days_by_dt"][i] - clim["heat_days_by_dt"][0]
        frost += clim["frost_days_by_dt"][i] - clim["frost_days_by_dt"][0]
    else:
        rain = clim["rain_mm"]
        frost = clim["frost_days_by_dt"][i]
        heat = clim["heat_days_by_dt"][i]
    return {
        "rain_mm": round(rain * (1 + sc.rain_pct / 100), 1),
        "frost_days": round(max(0.0, frost), 1),
        "heat_days": round(max(0.0, heat), 1),
        "gw_trend_cm_yr": round(cell["grace"]["trend_cm_yr"] + sc.gw_offset_cm_yr, 2),
        "gw_source": cell["grace"]["source"],
        # Farm fields: surface water allocated to this field (god-mode water
        # allocation) and its soil. Valley cells fall back to the defaults.
        "supply_cm": float(cell.get("supply_cm", SUSTAINABLE_SUPPLY_CM)),
        "soil_aws_cm": (cell.get("soil") or {}).get("aws_cm"),
        "soil_ph": cell.get("ph", (cell.get("soil") or {}).get("ph")),
    }
