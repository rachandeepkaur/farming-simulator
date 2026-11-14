"""Task 5, step 3: read the selected guide pages and pull out crop facts with
Claude, as structured JSON with a verbatim quote and page for each fact.
ndi.verify() then checks every quote against the PDF text."""

from __future__ import annotations

import json
import os

import anthropic

MODEL = os.environ.get("NDI_EXTRACT_MODEL", "claude-opus-5-5")

SYSTEM = (
    "You extract crop facts from agricultural extension guides for a California Central Valley "
    "planning tool. Use only the guide text you are given, never outside knowledge. For each fact, "
    "copy a verbatim quote of one or two sentences (under 300 characters) from the page that states "
    "it, exactly as written including any odd spacing, and give that page's n attribute and the "
    "guide id. If the guides do not state a fact, set found to false and leave the other fields null. "
    "Do not infer a fact from general statements about other crops."
)

FACT_INSTRUCTIONS = """Facts to extract for {crop_name}:
- water_use: total seasonal crop water use (crop evapotranspiration, ETc) for this crop in California. Prefer a California or Central Valley figure. Give low/high for a stated range and typical only if a single typical or average value is stated. unit is the unit as written (in, cm or mm).
- frost_tolerance: how well the crop tolerates frost. low = frost damages or kills it; moderate = tolerates light frost or frost damage depends on stage or cultivar; high = winter hardy.
- heat_tolerance: how well it tolerates high summer temperatures. low, moderate or high.
- nitrogen_fixing: whether the crop fixes atmospheric nitrogen (true for legumes with rhizobia).
- root_depth: maximum rooting depth stated. value and unit as written (in, ft, cm or m)."""


def _src(extra: dict) -> dict:
    base = {"found": {"type": "boolean"},
            "guide_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "page": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
    props = {**base, **extra}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def output_schema() -> dict:
    level = _nullable({"type": "string", "enum": ["low", "moderate", "high"]})
    num = _nullable({"type": "number"})
    props = {
        "water_use": _src({"low": num, "high": num, "typical": num,
                           "unit": _nullable({"type": "string", "enum": ["in", "cm", "mm"]})}),
        "frost_tolerance": _src({"value": level}),
        "heat_tolerance": _src({"value": level}),
        "nitrogen_fixing": _src({"value": _nullable({"type": "boolean"})}),
        "root_depth": _src({"value": num,
                            "unit": _nullable({"type": "string", "enum": ["in", "ft", "cm", "m"]})}),
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class ClaudeExtractor:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL, effort: str = "medium"):
        self.client = client or anthropic.Anthropic(max_retries=3)
        self.model = model
        self.effort = effort

    def __call__(self, crop_key: str, crop_name: str, guides_text: str) -> dict:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": (
                f"{guides_text}\n\n{FACT_INSTRUCTIONS.format(crop_name=crop_name)}"
            )}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": output_schema()}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{crop_key}: extraction refused")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"{crop_key}: extraction hit max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError(f"{crop_key}: no text in extraction response")
        return json.loads(text)
