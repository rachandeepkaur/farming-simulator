# Rotation Atlas: farm resource-management god sim (Drexathon, Nov 14 2026)

Team: Rachan (backend, data, Drex) and Arpan (UI, deck). Submissions close 4:30 PM PT; feature freeze 3:30; 5-minute demo.
Tracks: Apex Predator (Drex vs the giants), NDI bonus, Best Use of Adobe.
History of how we got here: https://claude.ai/code/session_01KYxn3ZnzLA5HmA4hqvpSbC

## What the product is now

**One farm, resource management** (not crop rotation, not the whole valley). A 2-square-mile farm near
Fresno, 36 fields of 40 acres, played like Hay Day × WorldBox. Every season, for 10 years of real NASA
weather (2012-2021), **Drex decides each field's actions**:
irrigation (none/light/full), fertilize (none/compost/synthetic), lime, spray pests, cover crop, local review.
**Code (not the model) enforces budgets**: per-field surface-water share (beyond it = pumped from the
aquifer), yearly lime / synthetic N / pesticide / cover seed. Circular farm: cows eat crop residue and
cover-crop grazing; manure + leftover residue → compost → fields. Two scores: **sustainability**
(soil, water from surface vs pumped, renewable inputs, waste recycled) and **efficiency** ($ crop per
acre-inch irrigated). The pitch: keep the farm sustainable while it keeps producing.

## Run

```bash
uv sync                                         # or: pip install fastapi uvicorn httpx anthropic pypdf
uv run python scripts/build_farm.py             # SSURGO soil + pH per field (needs internet); --offline = estimate
uv run uvicorn server.app:app --port 8000       # restart after any backend change (no --reload)
cd web && npm install && npm run dev            # http://localhost:5173 (Vite proxies /api to :8000)
uv run pytest                                   # 34 pass, 1 skipped
```
Env: `DEEPINFRA_API_KEY` (Drex, model `nace-ai/drex-v2.0`), `ANTHROPIC_API_KEY` (LLM baseline),
`NACE_API_KEY` (NDI). Without keys the UI runs on the rule-based stand-in ("Rules" button).

## Where things are

| Path | What |
|---|---|
| `atlas/farm_actions.py` | The farm engine: `FARM_QUESTIONS`, fixed-format `build_state`, offline `rule_answers`, budgets (`_allocate`), season loop `iter_seasons` (water balance, pH, N, pests, health, harvest, herd, compost, scores). All $ and herd numbers are ILLUSTRATIVE. |
| `atlas/farm.py`, `scripts/build_farm.py`, `data/farm.json` | 6×6 field grid inside valley cell `r041c024`, SSURGO soil (aws, pH) or labelled estimate, crop plan per field. |
| `server/app.py` | `POST /api/farm/run` (NDJSON, one line per season), `GET /api/farm`, `GET /api/farm/questions`. Older valley endpoints still there. |
| `atlas/drex.py`, `atlas/llm.py`, `atlas/decide.py` | Drex (DeepInfra `/v1/decisions`) and Claude baseline clients; both take a `questions=` set. `DeciderPool("drex", questions=FARM_QUESTIONS)`. |
| `web/src/App.jsx` | Game shell: scenarios, tools (inspect, select area, plant, ±water), resource sliders, herd, weather, priorities, HUD, field card (`ActionCard`, `Gauges`), season strip. |
| `web/src/components/FarmMap.jsx` | Canvas pixel map: fields per month, sprinklers, badges, health bars, box select, tractors/sprayers/harvesters (`apiRef.dispatch(kind, fieldId)`), cows/sheep/hens, compost pile. |
| `web/src/components/FieldStage.jsx` | Teammate's side-view (sky, soil, well, aquifer), reused in the field card. |
| Valley rotation pipeline (`atlas/simulate.py`, `atlas/questions.py`, `atlas/rules.py`, `scripts/run_*`) | Original single-field/valley work. Keep it working; tests cover it. |

## Rules of the road

- Drex decides; code enforces budgets and does the bookkeeping. Never let the model "spend" stock directly.
- The state sentence is fixed-format: same inputs → same text (consistency metric depends on it).
- Anything not from a source is labelled illustrative/estimate in the UI. Don't present mock or rules numbers as Drex numbers.
- Same parallelism for Drex and the LLM in any benchmark; say so on the slide.

## Status and next

- Only tested end to end with the rule-based stand-in. **First: run a real Drex call on `FARM_QUESTIONS`** (docs/CURSOR_TASKS.md #1).
- Remaining work is split into independent tasks with paste-ready prompts in `docs/CURSOR_TASKS.md`
  (Drex check, farm benchmark, Race mode UI, "What Drex saw" viewer, farm guide rules, SSURGO pull, sprites, sourced economics, deck).
