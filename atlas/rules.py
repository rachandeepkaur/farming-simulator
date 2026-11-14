"""Guide rules: used for the "agreement with guide rules" metric (task 11) and
as an offline rule-based decider (no API keys, deterministic, instant).

The rules read the fixed-format state text from state.build_state(), so they
see exactly what Drex and the LLM see.

PLACEHOLDER rule set: these encode common-sense readings of the crop facts.
Replace or extend them with the rules NDI extracts from the extension guides
(task 5), keeping the same RULES list shape.
"""

from __future__ import annotations

import re

from .crops import STRATEGIES

_NUM = r"([-+]?\d+(?:\.\d+)?)"


def facts_from_state(state: str) -> dict:
    def grab(pattern):
        m = re.search(pattern, state)
        if not m:
            raise ValueError(f"state missing {pattern!r}")
        return float(m.group(1))

    def level(name):
        m = re.search(rf"{name} (low|medium|high)", state)
        return {"low": 0.0, "medium": 0.5, "high": 1.0}[m.group(1)]

    irrigation = {s: grab(rf"- {s}: .*?irrigation {_NUM} cm/yr") for s in STRATEGIES}
    soil = re.search(rf"soil health {_NUM}/100", state)
    return {
        "rain_mm": grab(rf"Annual rainfall: {_NUM} mm"),
        "frost_days": grab(rf"Frost days: {_NUM}"),
        "heat_days": grab(rf"Days above 35 C: {_NUM}"),
        "gw_trend": grab(rf"Groundwater storage trend: {_NUM} cm/yr"),
        "gw_fallback": "fallback estimate" in state,
        "supply": grab(rf"Sustainable irrigation supply: {_NUM} cm/yr"),
        "irrigation": irrigation,
        "soil_score": float(soil.group(1)) if soil else None,
        "save_water": level("save water"),
        "income": level("income"),
        "build_soil": level("build soil"),
    }


def _fits(f, s):
    return f["irrigation"][s] <= f["supply"]


# Each rule: (name, applies(facts, answers) -> bool, passes(facts, answers) -> bool)
RULES = [
    (
        "no_existing_when_over_budget",
        lambda f, a: not _fits(f, "existing") and any(_fits(f, s) for s in STRATEGIES),
        lambda f, a: a["recommended"]["value"] != "existing",
    ),
    (
        "fits_water_budget_matches_numbers",
        lambda f, a: True,
        lambda f, a: a["fits_water_budget"]["value"] == _fits(f, a["recommended"]["value"]),
    ),
    (
        "per_strategy_fit_matches_numbers",
        lambda f, a: True,
        lambda f, a: all(a[f"fit_{s}"]["value"] == _fits(f, s) for s in STRATEGIES),
    ),
    (
        "frost_risk_not_low_when_frequent_frost",
        lambda f, a: f["frost_days"] >= 20,
        lambda f, a: a["frost_risk"]["value"] != "low",
    ),
    (
        "cover_crop_gives_nitrogen",
        lambda f, a: a["recommended"]["value"] == "cover_crop",
        lambda f, a: a["soil_benefit"]["value"] == "nitrogen",
    ),
    (
        "review_when_groundwater_falling_fast",
        lambda f, a: f["gw_trend"] <= -3.0,
        lambda f, a: a["needs_local_review"]["value"] is True,
    ),
]


def check(state: str, answers: dict) -> list[dict]:
    f = facts_from_state(state)
    out = []
    for name, applies, passes in RULES:
        if applies(f, answers):
            out.append({"rule": name, "passed": bool(passes(f, answers))})
    return out


def rule_answers(state: str) -> dict:
    """Deterministic decision from the rules, in the shared answer shape."""
    f = facts_from_state(state)
    fits = {s: _fits(f, s) for s in STRATEGIES}

    score = {}
    for s in STRATEGIES:
        # Over-budget strategies lose 1 point per 10 cm of excess irrigation,
        # so when nothing fits the least thirsty one still wins.
        sc = -max(0.0, f["irrigation"][s] - f["supply"]) / 10 - (0.0 if fits[s] else 1.0)
        sc += {"existing": 0.6, "cover_crop": 0.4, "drought_tolerant": 0.1}[s] * f["income"]
        sc += {"existing": 0.0, "cover_crop": 0.3, "drought_tolerant": 0.6}[s] * f["save_water"]
        sc += {"existing": 0.0, "cover_crop": 0.7, "drought_tolerant": 0.3}[s] * f["build_soil"]
        if f["soil_score"] is not None and f["soil_score"] < 40 and s == "cover_crop":
            sc += 0.3
        score[s] = sc
    rec = max(STRATEGIES, key=lambda s: score[s])

    frost = "high" if f["frost_days"] >= 30 else "moderate" if f["frost_days"] >= 10 else "low"
    soil = {"existing": "none", "cover_crop": "nitrogen", "drought_tolerant": "organic_matter"}[rec]
    ranked = sorted(score.values(), reverse=True)
    borderline = ranked[0] - ranked[1] < 0.1
    review = borderline or f["gw_trend"] <= -3.0

    def b(v):
        return {"value": v, "p": 1.0 if v else 0.0}

    def ch(v):
        return {"value": v, "probs": {}}

    return {
        "recommended": ch(rec),
        "fits_water_budget": b(fits[rec]),
        "frost_risk": ch(frost),
        "soil_benefit": ch(soil),
        "needs_local_review": b(review),
        **{f"fit_{s}": b(fits[s]) for s in STRATEGIES},
    }


async def rules_decider(state: str):
    """Decider-compatible wrapper: (answers, latency_ms, usage)."""
    return rule_answers(state), 0.0, {}
