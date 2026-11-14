"""Tasks 2 and 6c: Drex client and decide() for one cell.

Drex is served by DeepInfra at POST https://api.deepinfra.com/v1/decisions
with `Authorization: bearer $DEEPINFRA_API_KEY`. Body: {model, state, questions}.
Answers come back keyed by question id: noul -> {"noul": P(yes)},
choice -> {"choice", "probabilities", "confidence"}.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

from .questions import QUESTIONS

DEEPINFRA_URL = "https://api.deepinfra.com/v1/decisions"
DEFAULT_MODEL = os.environ.get("DREX_MODEL", "nace-ai/drex-v2.0")


def endpoint() -> str:
    """DREX_BASE_URL + DREX_PATH when set, otherwise the DeepInfra decisions API."""
    base = os.environ.get("DREX_BASE_URL", "").strip().rstrip("/")
    if not base:
        return DEEPINFRA_URL
    path = os.environ.get("DREX_PATH", "/v1/decisions").strip() or "/v1/decisions"
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def api_key() -> str:
    return os.environ.get("DEEPINFRA_API_KEY") or os.environ.get("DREX_API_KEY") or ""


def model_name() -> str:
    return os.environ.get("DREX_MODEL", "nace-ai/drex-v2.0")


class DrexError(RuntimeError):
    pass


def make_client(max_connections: int = 256) -> httpx.AsyncClient:
    key = api_key()
    if not key:
        raise DrexError("DEEPINFRA_API_KEY is not set (DREX_API_KEY in rotation-atlas/.env also works)")
    return httpx.AsyncClient(
        headers={"Authorization": f"bearer {key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
    )


def normalise(raw_answers: dict, questions: dict | None = None) -> dict:
    """Drex answers -> the shared decision-result shape (schema/README.md §4)."""
    out = {}
    for key, q in (questions or QUESTIONS).items():
        a = raw_answers.get(key)
        if a is None:
            raise DrexError(f"Drex response missing answer for {key!r}")
        if q["type"] == "noul":
            p = float(a["noul"])
            out[key] = {"value": p >= 0.5, "p": round(p, 4)}
        else:
            out[key] = {
                "value": a["choice"],
                "probs": {k: round(float(v), 4) for k, v in a.get("probabilities", {}).items()},
            }
    return out


async def decide(
    client: httpx.AsyncClient,
    state: str,
    model: str | None = None,
    retries: int = 3,
    questions: dict | None = None,
) -> tuple[dict, float, dict]:
    """One Drex call. Returns (answers, latency_ms of the successful attempt, usage).
    `questions` defaults to the rotation question set; the farm view passes its own."""
    qs = questions or QUESTIONS
    model = model or model_name()
    body = {"model": model, "state": state, "questions": qs}
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            r = await client.post(endpoint(), json=body)
        except httpx.TransportError as e:
            if attempt == retries:
                raise DrexError(f"network error: {e}") from e
            await asyncio.sleep(0.5 * 2**attempt)
            continue
        latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                raise DrexError(f"HTTP {r.status_code}: {r.text[:200]}")
            retry_after = r.headers.get("retry-after")
            await asyncio.sleep(float(retry_after) if retry_after else 0.5 * 2**attempt)
            continue
        if r.status_code != 200:
            raise DrexError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        return normalise(data["answers"], qs), latency_ms, data.get("usage", {})
    raise AssertionError("unreachable")
