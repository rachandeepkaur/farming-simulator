"""Farm guide rules and a fake-decider benchmark."""
import pytest

from atlas.farm import load
from atlas.farm_actions import build_state, initial_field_state, rule_answers
from atlas.farm_benchmark import evaluate
from atlas.farm_rules import check
from atlas.scenario import Priorities


def _state(q=2, **kw):
    field = load()["fields"][0]
    st = initial_field_state(field, {})
    st.update(kw)
    farm = {"n": 36, "aquifer_cm": 0.0, "stock": {"lime": 6, "synthetic": 10, "spray_pests": 10, "cover_crop": 12},
            "compost": 8.0, "cows": 24}
    weather = {"rain_mm": 3, "tmax_c": 35, "heat_days": 30, "frost_days": 0}
    return build_state(field, st, farm, "2014", q, weather, Priorities(), "Fresno")


def _names(state, answers):
    return {item["rule"]: item["passed"] for item in check(state, answers)}


def test_every_rule_has_a_source():
    state = _state()
    items = check(state, rule_answers(state))
    assert items
    assert all(item["source"] for item in items)


def test_lime_matches_ph():
    acid = _state(ph=5.2)
    fine = _state(ph=7.2)
    acid_answers = rule_answers(acid)
    fine_answers = rule_answers(fine)
    assert _names(acid, acid_answers)["lime_only_when_ph_below_6"] is True
    assert _names(fine, fine_answers)["lime_only_when_ph_below_6"] is True
    acid_answers["lime"] = {"value": False, "p": 0.0}
    fine_answers["lime"] = {"value": True, "p": 1.0}
    assert _names(acid, acid_answers)["lime_only_when_ph_below_6"] is False
    assert _names(fine, fine_answers)["lime_only_when_ph_below_6"] is False


def test_bare_field_forbids_irrigation_spray_and_limits_cover():
    bare = _state(q=0)
    assert "not in the ground" in bare
    answers = rule_answers(bare)
    names = _names(bare, answers)
    assert names["no_irrigation_when_bare"] is True
    assert names["no_pest_spray_when_bare"] is True
    assert names["cover_crop_only_when_bare"] is True
    answers["irrigation"] = {"value": "full", "probs": {}}
    answers["spray_pests"] = {"value": True, "p": 1.0}
    names = _names(bare, answers)
    assert names["no_irrigation_when_bare"] is False
    assert names["no_pest_spray_when_bare"] is False


def test_fertilize_and_compost_preference():
    hungry = _state(n=20, ph=6.5)
    answers = rule_answers(hungry)
    names = _names(hungry, answers)
    assert names["fertilize_when_nitrogen_low_and_crop_growing"] is True
    assert names["prefer_compost_when_pile_has_loads_and_soil_priority"] is True
    answers["fertilize"] = {"value": "none", "probs": {}}
    assert _names(hungry, answers)["fertilize_when_nitrogen_low_and_crop_growing"] is False
    answers["fertilize"] = {"value": "synthetic", "probs": {}}
    assert _names(hungry, answers)["prefer_compost_when_pile_has_loads_and_soil_priority"] is False


@pytest.mark.asyncio
async def test_benchmark_fake_decider():
    state = _state()

    async def fake(text):
        return rule_answers(text), 1.5, {"input_tokens": 12, "output_tokens": 4}

    report = await evaluate({"rules": fake}, [[state, state]], repeats=5, concurrency=2)
    summary = report["models"]["rules"]
    assert summary["consistency"] == 1
    assert summary["guide_rule_agreement"] == 1
    assert summary["input_tokens"] == 12 * 2 * 5
    assert summary["wall_ms_per_season"] is not None
    assert summary["agreement_with_drex"] is None
    assert summary["cost_usd"] == 0
