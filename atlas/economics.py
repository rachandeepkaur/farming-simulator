"""Farm prices and costs, loaded from data/farm_economics.json.

Each figure keeps a source string. While any figure is still a placeholder,
the UI says the dollars are illustrative. Missing file: the same round
numbers that used to live in farm_actions.py.
"""

from __future__ import annotations

import json

from .config import DATA_DIR

PATH = DATA_DIR / "farm_economics.json"

_FALLBACK = {
    "placeholder": True,
    "price_per_acre": {
        "processing_tomato": 3500,
        "winter_wheat": 650,
        "safflower": 550,
    },
    "cost": {"synthetic": 2000, "compost": 300, "lime": 1200, "spray_pests": 1500, "cover_crop": 800},
    "pump_cost_per_cm_acre": 14.0,
    "feed_price": 600,
    "milk_per_cow": 900,
}


def _value(node) -> tuple[float, bool]:
    if isinstance(node, dict) and "value" in node:
        return float(node["value"]), bool(node.get("placeholder", False))
    return float(node), True


def load_numbers() -> dict:
    raw = json.loads(PATH.read_text(encoding="utf-8")) if PATH.is_file() else _FALLBACK
    placeholder = bool(raw.get("placeholder", False))
    prices, costs = {}, {}
    for key, node in raw["price_per_acre"].items():
        value, flagged = _value(node)
        prices[key] = value
        placeholder = placeholder or flagged
    for key, node in raw["cost"].items():
        value, flagged = _value(node)
        costs[key] = value
        placeholder = placeholder or flagged
    pump, pump_flag = _value(raw["pump_cost_per_cm_acre"])
    feed, feed_flag = _value(raw["feed_price"])
    milk, milk_flag = _value(raw["milk_per_cow"])
    placeholder = placeholder or pump_flag or feed_flag or milk_flag
    return {
        "price_per_acre": prices,
        "cost": costs,
        "pump_cost_per_cm_acre": pump,
        "feed_price": feed,
        "milk_per_cow": milk,
        "placeholder": placeholder,
    }
