"""Guide rules for the farm view's agreement metric.

These read the same state text Drex sees (farm_actions.build_state). They are
the checklist, not the offline decider. data/crops.json has no extracted
evidence quotes yet, so every source says placeholder.
"""

from __future__ import annotations

import re

_N = r"([-+]?\d+(?:\.\d+)?)"


def facts_from_state(state: str) -> dict:
    def grab(pattern: str) -> float:
        m = re.search(pattern, state)
        if not m:
            raise ValueError(f"farm state missing {pattern!r}")
        return float(m.group(1))

    soil = re.search(r"build soil (low|medium|high)", state)
    if not soil:
        raise ValueError("farm state missing build-soil priority")
    return {
        "bare": "not in the ground" in state,
        "ph": grab(rf"Soil pH: {_N}"),
        "n": grab(rf"Soil nitrogen: {_N}"),
        "compost": grab(rf"Compost pile: {_N} loads"),
        "build_soil": soil.group(1),
    }


def _lime_ok(f, a) -> bool:
    return bool(a["lime"]["value"]) == (f["ph"] < 6.0)


def _no_irrigation_if_bare(f, a) -> bool:
    return a["irrigation"]["value"] == "none"


def _no_spray_if_bare(f, a) -> bool:
    return a["spray_pests"]["value"] is False


def _cover_only_if_bare(f, a) -> bool:
    return (not a["cover_crop"]["value"]) or f["bare"]


def _fertilize_if_hungry(f, a) -> bool:
    return a["fertilize"]["value"] != "none"


def _prefer_compost(f, a) -> bool:
    return a["fertilize"]["value"] == "compost"


# name, applies(facts, answers), passes(facts, answers), source
RULES = [
    (
        "lime_only_when_ph_below_6",
        lambda f, a: "lime" in a,
        _lime_ok,
        "placeholder",
    ),
    (
        "no_irrigation_when_bare",
        lambda f, a: f["bare"],
        _no_irrigation_if_bare,
        "placeholder",
    ),
    (
        "no_pest_spray_when_bare",
        lambda f, a: f["bare"],
        _no_spray_if_bare,
        "placeholder",
    ),
    (
        "cover_crop_only_when_bare",
        lambda f, a: True,
        _cover_only_if_bare,
        "placeholder",
    ),
    (
        "fertilize_when_nitrogen_low_and_crop_growing",
        lambda f, a: (not f["bare"]) and f["n"] < 30,
        _fertilize_if_hungry,
        "placeholder",
    ),
    (
        "prefer_compost_when_pile_has_loads_and_soil_priority",
        lambda f, a: f["compost"] >= 1 and f["build_soil"] in ("medium", "high") and a["fertilize"]["value"] in ("compost", "synthetic"),
        _prefer_compost,
        "placeholder",
    ),
]


def check(state: str, answers: dict) -> list[dict]:
    facts = facts_from_state(state)
    out = []
    for name, applies, passes, source in RULES:
        if applies(facts, answers):
            out.append({"rule": name, "passed": bool(passes(facts, answers)), "source": source})
    return out
