# Cursor task board (farm resource-management view)

Each task is independent and touches different files, so several Cursor agents
can run in parallel without merge conflicts. Paste the **Prompt** into Cursor
(Agent mode) from the repo root. Run `uv run pytest` before marking a task done.

Context for every agent: read `README.md` ("Farm view") and `atlas/farm_actions.py`
first. The farm view decides **field actions per season** (irrigation, compost or
synthetic fertilizer, lime, pest spray, cover crop) with Drex, and code enforces
the farm's budgets. Do not change the valley rotation pipeline (`atlas/simulate.py`,
`atlas/questions.py`) unless the task says so.

| # | Task | Owner | Files | Priority |
|---|---|---|---|---|
| 1 | Real Drex check on the farm questions | Rachan + Cursor | `scripts/farm_latency.py` (new) | P0, do first |
| 2 | Farm benchmark: Drex vs LLM vs rules | Cursor | `scripts/farm_benchmark.py` (new), `atlas/farm_benchmark.py` (new) | P0 |
| 3 | Race mode in the UI (replayed LLM timer) | Cursor | `web/src/components/Race.jsx` (new), small hook in `App.jsx` | P0 |
| 4 | "What Drex saw" request viewer | Cursor | `server/app.py` (new endpoint), `web/src/components/RequestViewer.jsx` (new) | P1 |
| 5 | Farm guide rules (agreement metric) | Cursor | `atlas/farm_rules.py` (new), `tests/test_farm_rules.py` (new) | P1 |
| 6 | Pull real SSURGO soil + pH | Rachan (laptop, internet) | `atlas/farm.py`, `data/farm.json` | P1 |
| 7 | Sprites from Firefly | Arpan + Cursor | `web/public/sprites/*`, `web/src/components/FarmMap.jsx` | P2 |
| 8 | Sourced farm economics | Cursor | `data/farm_economics.json` (new), `atlas/farm_actions.py` constants | P2 |
| 9 | Deck + 60 s backup video | Both | Adobe Express | P0 at 3:30 |

---

## 1. Real Drex check on the farm questions (P0)

**Done when:** one real Drex call on a farm state parses, and the script prints the
wall time for deciding all 36 fields of one season at concurrency 36 and 128.

**Prompt:**
> Create `scripts/farm_latency.py`. It loads the farm with `atlas.farm.load()`, builds the
> 36 field states for one season with `atlas.farm_actions.build_state` (use
> `initial_field_state`, the farm's monthly weather from `atlas.weather.for_cell(atlas.farm.farm_cells()[0])`,
> year "2014", season index 2, `Priorities()`, near "Fresno", and a farm dict
> `{"n":36,"aquifer_cm":0,"stock":DEFAULT_STOCK,"compost":8,"cows":24}`). Open
> `DeciderPool("drex", questions=FARM_QUESTIONS)` from `atlas.decide`, print one state and its
> parsed answers, then run `decide_states` for all 36 states at concurrency 36 and 128 and print
> wall_ms, p50_ms, p95_ms and errors. Needs `DEEPINFRA_API_KEY`. Fail with a clear message if any
> answer is missing a question key. Don't change other files.

## 2. Farm benchmark: Drex vs LLM vs rules (P0)

**Done when:** `uv run python scripts/farm_benchmark.py --models drex,llm,rules --seasons 4 --yes`
writes `results/farm_benchmark_<time>.json` and `.md` with, per model: wall time per season (36
fields), p50/p95 latency, input tokens and estimated cost, agreement with Drex per action key,
and consistency (same answers over 5 repeats of the same 36 states).

**Prompt:**
> Add `atlas/farm_benchmark.py` and `scripts/farm_benchmark.py`, modelled on the existing
> `atlas/benchmark.py` and `scripts/run_benchmark.py`, but for the farm view. Use the exact same
> 36 field states per season for every model (build them once from the rules run of
> `atlas.farm_actions.iter_seasons`, so field conditions are realistic; capture the states by
> wrapping the decider). Models: drex via `DeciderPool("drex", questions=FARM_QUESTIONS)`,
> llm via `DeciderPool("llm", questions=FARM_QUESTIONS, system=FARM_SYSTEM)`, rules via
> `farm_rules_decider`. Same concurrency for all. Report per-action agreement with Drex
> (irrigation, fertilize, lime, spray_pests, cover_crop), consistency over 5 repeats, wall time
> per season, tokens and cost (read prices from env vars, print "n/a" if unset). Ask for
> confirmation before paid LLM calls unless `--yes`. Write JSON and a markdown table for the slide.
> Add a small test using a fake decider.

## 3. Race mode in the UI (P0)

**Done when:** a "Race" button in the top bar runs the same farm season with Drex and with the
LLM side by side, showing two timers and how many field decisions each finished; if no LLM
key is set, it replays the recorded numbers from the latest farm benchmark JSON (and says
"replayed").

**Prompt:**
> In `web/`, add `src/components/Race.jsx`: a modal with two columns (Drex, LLM). On open it POSTs
> to `/api/farm/run` twice with `years: 1` and the current settings (`model: "drex"` and
> `model: "llm", confirm_paid: true`), streaming both, and shows a running timer and a counter of
> seasons received for each. When the LLM isn't configured (`meta.models.llm` false), fetch
> `/api/farm/benchmark/latest` (add this small endpoint in `server/app.py` that returns the newest
> `results/farm_benchmark_*.json`) and animate the LLM timer to its recorded per-season wall time,
> labelled "replayed from benchmark". Add a "Race" button next to the model switch in `App.jsx`.
> Match the pixel styles in `src/pixel.css` (`px-panel`, `px-btn`, `px-title`).

## 4. "What Drex saw" request viewer (P1)

**Done when:** the field card has a collapsible section showing the exact state text and
questions Drex got for that field and season.

**Prompt:**
> In `atlas/farm_actions.py` `iter_seasons`, include each field's state text in its record under
> `"state"` (it's already built in `items`). In `web/src/App.jsx` `ActionCard`, add a
> `<details>` "What Drex saw" that shows `rec.state` in a `<pre>` and the question keys from
> `GET /api/farm/questions`. Keep the pixel styling. Check the NDJSON stays under ~3 MB for 10 years
> (36 fields × 40 seasons); if it's bigger, send state only when the request has
> `include_state: true` and fetch it lazily for the selected field.

## 5. Farm guide rules (agreement metric) (P1)

**Prompt:**
> Create `atlas/farm_rules.py` with a `RULES` list like `atlas/rules.py`, but for the farm state
> text from `atlas.farm_actions.build_state`: lime only when pH < 6.0; no irrigation and no pest
> spray when the field is bare; cover crop only when bare; fertilize when nitrogen < 30 and a crop
> is in the ground; prefer compost over synthetic when the compost pile has loads and "build soil"
> is medium or high. Add `check(state, answers)` returning pass/fail per applicable rule, and use it
> in the farm benchmark (task 2) as "guide-rule agreement". Each rule gets a `source` string that
> points at the crop-guide fact it comes from (`data/crops.json` evidence) or says
> "placeholder" if none. Add tests.

## 6. Pull real SSURGO soil + pH (P1, needs internet: run on a laptop)

> Run `uv run python scripts/build_farm.py`. If Soil Data Access returns errors, print the raw
> response for one field and fix the SQL in `atlas.farm.fetch_soil` (the pH sub-select over
> `component` and `chorizon`). Done when `soil_resolved` ≥ 30 of 36 and `data/farm.json` has real
> `aws_cm` and `ph` values. Commit `data/farm.json`.

## 7. Sprites from Firefly (P2)

> Put 16×16 or 32×32 PNG sprites (cow, sheep, chicken, tractor, sprayer, harvester, compost pile,
> each crop at 3 growth stages) in `web/public/sprites/`. In `FarmMap.jsx`, load them once with
> `new Image()` and draw them with `ctx.drawImage` in place of the procedural shapes when loaded,
> keeping the procedural fallback. Keep `imageSmoothingEnabled = false`.

## 8. Sourced farm economics (P2)

> Replace the illustrative numbers in `atlas/farm_actions.py` (`PRICE_PER_ACRE`, `COST`,
> `PUMP_COST_PER_CM_ACRE`, `FEED_PRICE`, `MILK_PER_COW`) with values loaded from a new
> `data/farm_economics.json`, each with a `source` (UC Davis cost-and-return studies for processing
> tomatoes, wheat and safflower in the San Joaquin Valley). Keep the current numbers as the
> fallback, marked `"placeholder": true`, and show "illustrative" in the UI when any are placeholders.
