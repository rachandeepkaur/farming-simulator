# Rotation Atlas

Crop rotation suggestions for every field in California's Central Valley, decided by Drex. See [Rotation Atlas – PRD.md](Rotation%20Atlas%20–%20PRD.md) for the plan and [schema/README.md](schema/README.md) for the data contract between the pipeline and the map.

## Setup

```bash
uv sync                      # add --extra grace to regrid a real GRACE file
export DEEPINFRA_API_KEY=... # Drex
export ANTHROPIC_API_KEY=... # LLM baseline and crop-fact extraction (or `ant auth login`)
export NACE_API_KEY=...      # NDI document parsing
```

## Pipeline (Rachan's tasks)

| Task | Command | Output |
| --- | --- | --- |
| 3, 12: grid + NASA POWER climate | `uv run python scripts/build_cells.py` | `data/cells.json` (516 cells) |
| 4: GRACE trend | `uv run python scripts/build_cells.py --grace-file <mascon.nc>` | `grace` field in `cells.json` |
| 5: crop facts from guides (NDI) | `uv run python scripts/build_crops.py --yes` | `data/crops.json` with a page and quote per fact |
| 2: Drex latency and throughput | `uv run python scripts/drex_latency.py` | Table printed |
| 11: benchmark | `uv run python scripts/run_benchmark.py --models drex,llm --yes` | `results/benchmark_*.json`, `.csv` |
| 13: simulation | `uv run python scripts/run_simulation.py --model drex` | `results/simulations/*.json` |
| Tests | `uv run pytest` | |

Pass `--model rules` or `--models rules` to any script to run offline with the rule-based decider, which needs no API keys.

## Farm view (the demo): one farm, resource management

One 2-square-mile farm near Fresno, 36 fields of 40 acres, run like a god sim (Hay Day × WorldBox).
Every season for 10 years of real NASA weather, **Drex decides each field's actions**: how much to
irrigate, whether to fertilize (with the farm's own **compost** or bought **synthetic** nitrogen),
lime, spray for pests, or sow a cover crop. **Code enforces the budgets**: each field's surface-water
share (beyond it, water is pumped from the aquifer), and the year's lime, synthetic N, pesticide and
cover seed. The farm is circular: cows eat crop residue and cover-crop grazing, and their manure plus
leftover residue becomes compost that goes back on the fields. Two scores: **sustainability**
(soil, water from surface not aquifer, renewable inputs, waste recycled) and **efficiency**
(crop $ per acre-inch of irrigation).

```bash
uv run python scripts/build_farm.py            # SSURGO soil + pH per field (needs internet; --offline = estimate)
uv run uvicorn server.app:app --port 8000
cd web && npm install && npm run dev            # http://localhost:5173
```

- God tools: scenarios, select an area, replant, paint water shares, per-year resource budgets,
  herd size, weather powers, farmer priorities. Every change re-decides the whole farm.
- API: `POST /api/farm/run` streams one NDJSON line per season (`atlas/farm_actions.py`);
  `GET /api/farm`, `GET /api/farm/questions`.
- All prices, costs and herd/compost numbers are round illustrative values (see `docs/CURSOR_TASKS.md` #8).
- Remaining work, split for Cursor agents: [docs/CURSOR_TASKS.md](docs/CURSOR_TASKS.md).

## Single-field simulation UI (original)

Two terminals:

```bash
uv run uvicorn server.app:app --port 8000     # API (reads the same env keys as above)
cd web && npm install && npm run dev            # http://localhost:5173
```

The page simulates one field on its own: the real 2012–2021 NASA weather, one Drex decision per year (the rule-based stand-in when `DEEPINFRA_API_KEY` isn't set), and month-by-month crop growth, irrigation, groundwater and soil health. Click the valley map to switch fields, or the season timeline to jump to a month.

## For the backend (task 7, task 14)

```python
from atlas.decide import DeciderPool, decide_all
from atlas.scenario import Scenario, Priorities
from atlas import simulate

async with DeciderPool("drex") as pool:          # or "llm"
    out = await decide_all(cells, Scenario(**req["scenario"]), Priorities(**req["priorities"]), pool, "drex")
    sim = await simulate.run(cells, scenario, priorities, pool, "drex", n_years=10)
```

`out` and `sim` already match the `/decide` and `/simulate` response shapes in the schema.

## Placeholders to replace before the demo

- `data/crops.sample.json`: rough crop numbers. `scripts/build_crops.py` writes `data/crops.json`, which takes over automatically. Any fact the guides don't state keeps its sample value and is marked `placeholder: true`.
- `atlas/rules.py`: guide rules for the agreement metric. Replace them with rules taken from the guides.
- `atlas/grace.py`: the fallback trend's end values. Use the real GRACE file if you can (it needs a free NASA Earthdata login).
- `atlas/sim_constants.py`: water budget and simulation numbers. They're illustrative, not calibrated.
