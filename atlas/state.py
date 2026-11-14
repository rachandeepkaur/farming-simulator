"""Task 6a: build_state(), the fixed-format sentence sent to Drex and the LLM.

The format is fixed so that the same inputs always give the same text, which
is what makes the consistency metric meaningful.
"""

from __future__ import annotations

from . import crops
from .crops import STRATEGIES
from .scenario import Priorities, Scenario, apply
from .sim_constants import SUSTAINABLE_SUPPLY_CM


def _level(x: float) -> str:
    return "high" if x >= 0.67 else "medium" if x >= 0.34 else "low"


def build_state(
    cell: dict,
    scenario: Scenario,
    priorities: Priorities,
    year: str | None = None,
    sim: dict | None = None,
) -> str:
    """One cell's evidence, scenario and priorities as a fixed-format text.

    `year` uses that year's real POWER climate (drought replay). `sim` carries
    simulation state: {"groundwater_cm", "soil_score", "last_strategy", "year_index"}.
    """
    c = apply(cell, scenario, year)
    lines = [
        f"Field {cell['id']} in California's Central Valley at {cell['lat']:.2f} N, {abs(cell['lon']):.2f} W.",
        f"Scenario: {scenario.name}" + (f", simulated year {year}." if year else "."),
        f"Annual rainfall: {c['rain_mm']:.0f} mm. Frost days: {c['frost_days']:.0f}. "
        f"Days above 35 C: {c['heat_days']:.0f}.",
        f"Groundwater storage trend: {c['gw_trend_cm_yr']:+.1f} cm/yr "
        f"({'GRACE satellite' if c['gw_source'] == 'grace' else 'fallback estimate, not measured here'}).",
        f"Sustainable irrigation supply: {c['supply_cm']:.0f} cm/yr "
        "(more than this draws down groundwater)."
        + (f" Water allocated to this field is {'below' if c['supply_cm'] < SUSTAINABLE_SUPPLY_CM else 'above'} "
           f"the farm's usual {SUSTAINABLE_SUPPLY_CM:.0f} cm." if abs(c['supply_cm'] - SUSTAINABLE_SUPPLY_CM) >= 1 else ""),
        "Strategies this year (crop water use, part covered by rain, irrigation needed):",
    ]
    if c.get("soil_ph") is not None:
        ph = c["soil_ph"]
        note = "acidic, lime recommended" if ph < 6.0 else "alkaline" if ph > 8.4 else "within the usual range"
        lines.insert(-1, f"Soil pH: {ph:.1f} ({note}).")
    if c["soil_aws_cm"] is not None:
        soil = cell.get("soil") or {}
        lines.insert(-1, f"Soil: holds {c['soil_aws_cm'] * 10:.0f} mm of plant-available water in the top 1.5 m "
                         f"({soil.get('name') or 'SSURGO map unit' if soil.get('source') == 'ssurgo' else 'estimate, not measured here'}).")
    for s in STRATEGIES:
        need, rain_used, irr = crops.strategy_irrigation_cm(s, c["rain_mm"], c["heat_days"], c["soil_aws_cm"])
        lines.append(
            f"- {s}: {crops.strategy_summary(s)}; uses {need:.0f} cm/yr, "
            f"rain covers {rain_used:.0f}, irrigation {irr:.0f} cm/yr."
        )
    if sim:
        lines.append(
            f"Simulation so far: groundwater change {sim['groundwater_cm']:+.1f} cm since start, "
            f"soil health {sim['soil_score']:.0f}/100, last year's strategy {sim['last_strategy']}."
        )
    lines.append(
        f"Farmer priorities: save water {_level(priorities.save_water)}, "
        f"income {_level(priorities.income)}, build soil {_level(priorities.build_soil)}."
    )
    return "\n".join(lines)
