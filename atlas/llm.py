"""Task 8: frontier LLM baseline (Claude) with the same state and questions.

Same inputs as Drex; the model must return JSON with the same keys, enforced
with structured outputs. No probabilities come back, so bool answers carry
p=None and choice answers carry empty probs.
"""

from __future__ import annotations

import json
import os
import time

import anthropic

from .questions import QUESTIONS

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-opus-5-5")
# Effort is reported alongside every benchmark number. "low" is the fastest
# setting and the right one for a short classification like this; raise it
# to see what more thinking costs in latency.
DEFAULT_EFFORT = os.environ.get("LLM_EFFORT", "low")

SYSTEM = (
    "You are a crop rotation decision assistant for California's Central Valley. "
    "You will be given one field's evidence, a climate scenario and the farmer's priorities, "
    "followed by a list of questions. Answer every question using only the evidence given. "
    "For yes/no questions answer true or false. For choice questions answer with exactly one "
    "of the option keys."
)


class LLMError(RuntimeError):
    pass


def output_schema(questions: dict | None = None) -> dict:
    questions = questions or QUESTIONS
    props = {}
    for key, q in questions.items():
        if q["type"] == "noul":
            props[key] = {"type": "boolean"}
        else:
            props[key] = {"type": "string", "enum": list(q["criteria"])}
    return {
        "type": "object",
        "properties": props,
        "required": list(questions),
        "additionalProperties": False,
    }


def questions_text(questions: dict | None = None) -> str:
    lines = []
    for key, q in (questions or QUESTIONS).items():
        if q["type"] == "noul":
            lines.append(f"- {key} (true/false): {q['instructions']}")
        else:
            opts = "; ".join(f"{k} = {v}" for k, v in q["criteria"].items())
            lines.append(f"- {key} (one of: {opts}): {q['instructions']}")
    return "\n".join(lines)


def make_client() -> anthropic.AsyncAnthropic:
    # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.
    return anthropic.AsyncAnthropic(max_retries=3)


async def decide(
    client: anthropic.AsyncAnthropic,
    state: str,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    questions: dict | None = None,
    system: str | None = None,
) -> tuple[dict, float, dict]:
    """One LLM call. Returns (answers, latency_ms, usage). The farm view passes
    its own `questions` and `system`; the default is the rotation set."""
    qs = questions or QUESTIONS
    t0 = time.perf_counter()
    try:
        resp = await client.beta.messages.create(
            model=model,
            max_tokens=4096,
            system=system or SYSTEM,
            messages=[{"role": "user", "content": f"{state}\n\nQuestions:\n{questions_text(qs)}"}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": output_schema(qs)}},
            # Server-side refusal fallback: routes a declined request to a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        raise LLMError(f"rate limited: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"HTTP {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"network error: {e}") from e
    latency_ms = (time.perf_counter() - t0) * 1000

    if resp.stop_reason == "refusal":
        raise LLMError(f"refused ({resp.stop_details.category if resp.stop_details else 'unknown'})")
    if resp.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens before finishing the JSON")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        raise LLMError("no text block in response")
    raw = json.loads(text)

    answers = {}
    for key, q in qs.items():
        if q["type"] == "noul":
            answers[key] = {"value": bool(raw[key]), "p": None}
        else:
            answers[key] = {"value": raw[key], "probs": {}}
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return answers, latency_ms, usage
