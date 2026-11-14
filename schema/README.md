# Shared contract (task 1)

This file is the agreement between the data and decision side (Rachan) and the product side (Arpan). Change it only together. `tests/test_pipeline.py` checks `data/cells.json` against section 1.

## 1. Cell (`data/cells.json`)

A list of cells. One cell is one grid square of the Central Valley.

```json
{
  "id": "r012c034",
  "row": 12,
  "col": 34,
  "lat": 36.75,
  "lon": -119.85,
  "bbox": [-119.9, 36.7, -119.8, 36.8],
  "climate": {
    "rain_mm": 270.4,
    "frost_days": 9.1,
    "heat_days": 41.3,
    "heat_days_by_dt": [41.3, 45.0, 49.2, 53.1, 57.8, 62.0, 66.4, 70.9, 75.1],
    "frost_days_by_dt": [9.1, 7.8, 6.6, 5.4, 4.5, 3.7, 3.0, 2.4, 1.9],
    "years": {"2012": {"rain_mm": 180.2, "frost_days": 12, "heat_days": 50}},
    "power_pixel": "36.5_-120.0",
    "period": "2001-2025"
  },
  "grace": {"trend_cm_yr": -1.8, "source": "fallback"}
}
```

- `rain_mm` is mean annual precipitation, `frost_days` is mean days a year with a minimum below 0 °C, and `heat_days` is mean days a year with a maximum above 35 °C. All come from NASA POWER daily data.
- `heat_days_by_dt[i]` and `frost_days_by_dt[i]` are the same counts if every day were `i × 0.5` °C warmer (index 0 is today, index 8 is +4 °C). The temperature slider reads these instead of guessing.
- `years` holds per-year values for the drought replay (2012–2021).
- `grace.source` is `"grace"` when regridded from a GRACE file, or `"fallback"` when it comes from the north–south fallback trend. The UI should say which.

## 2. Scenario and priorities (request to `/decide` and `/simulate`)

```json
{
  "scenario": {"name": "Dry decade", "rain_pct": -30, "temp_delta_c": 0.5, "gw_offset_cm_yr": -1.0},
  "priorities": {"save_water": 0.6, "income": 0.3, "build_soil": 0.5},
  "model": "drex"
}
```

- `rain_pct` runs from -50 to +50, `temp_delta_c` from 0 to 4 (in 0.5 steps), and `gw_offset_cm_yr` from -3 to +3. Each priority is between 0 and 1.
- `model` is `"drex"` or `"llm"`.
- The presets are in `atlas/scenario.py` (`PRESETS`).

## 3. Decision request (one per cell)

The state is a fixed-format sentence built by `atlas.state.build_state()`. The questions are in `atlas.questions.QUESTIONS` and go to Drex (`/v1/decisions`) unchanged. The LLM baseline gets the same state and questions and must return JSON with the same keys.

| Key | Type | Options |
| --- | --- | --- |
| `fits_water_budget` | bool | For the recommended strategy |
| `frost_risk` | choice | `low`, `moderate`, `high` |
| `soil_benefit` | choice | `nitrogen`, `organic_matter`, `erosion_control`, `none` |
| `recommended` | choice | `existing`, `cover_crop`, `drought_tolerant` |
| `needs_local_review` | bool | Borderline call or thin data |
| `fit_existing`, `fit_cover_crop`, `fit_drought_tolerant` | bool | Does each strategy fit the water budget. These are additions to the PRD's five questions: they let the field card show the fit for all three strategies at no extra latency, because they ride in the same call. |

## 4. Decision result (one per cell, from `/decide`)

```json
{
  "cell_id": "r012c034",
  "model": "drex",
  "latency_ms": 184.2,
  "state": "…",
  "answers": {
    "recommended": {"value": "cover_crop", "probs": {"existing": 0.1, "cover_crop": 0.7, "drought_tolerant": 0.2}},
    "fits_water_budget": {"value": true, "p": 0.82},
    "frost_risk": {"value": "low", "probs": {"low": 0.9, "moderate": 0.08, "high": 0.02}},
    "soil_benefit": {"value": "nitrogen", "probs": {}},
    "needs_local_review": {"value": false, "p": 0.21}
  },
  "error": null
}
```

- Bool answers carry `p` (Drex's probability of "yes"). Choice answers carry `probs`. The LLM returns no probabilities, so its `p` is `null` and its `probs` is `{}`.
- A bool is `true` when `p >= 0.5`.
- If a call fails, `answers` is `null` and `error` holds the message. The map draws the cell grey.

The whole `/decide` response is:

```json
{"results": [/* one per cell */], "timing": {"wall_ms": 1043.0, "p50_ms": 180.0, "p95_ms": 410.0, "n": 512, "errors": 0}}
```

## 5. Simulation result (from `/simulate`)

```json
{
  "years": [2012, 2013],
  "cells": {
    "r012c034": [
      {"year": 2012, "strategy": "cover_crop", "groundwater_cm": -2.1, "soil_score": 53.0, "stress": false, "review": false}
    ]
  },
  "timing": [{"year": 2012, "wall_ms": 1100.0, "errors": 0}]
}
```

## 6. Crop facts (`data/crops.json`)

Built from the guides in `data/guides.json` by `scripts/build_crops.py`. The field card reads `crops` for the crop cards and `strategies` for the three strategies.

```json
{
  "crops": {
    "safflower": {
      "name": "Safflower",
      "season": "spring",
      "water_need_cm": 57.1,
      "frost_tolerance": "moderate",
      "nitrogen_fixing": false,
      "root_depth_cm": 305,
      "heat_tolerance": "high",
      "source": "Safflower Production in California (ANR Publication 21565), p. 11; …",
      "evidence": {
        "water_need_cm": {"guide": "Safflower Production in California (ANR Publication 21565)", "publisher": "UC Agriculture and Natural Resources", "url": "https://…", "pdf_page": 11, "quote": "experience indicates that a total of about 20 to 25 inches", "as_written": {"low": 20, "high": 25, "typical": null, "unit": "in"}},
        "heat_tolerance": {"placeholder": true, "reason": "not stated in the guides"}
      }
    }
  },
  "strategies": {
    "drought_tolerant": {"label": "Drought-tolerant rotation", "pattern": "alternate", "crops": ["winter_wheat", "safflower"], "bare_months": ["Jul", "Aug", "Sep", "Oct"], "soil_effect": "organic_matter"}
  }
}
```

- `water_need_cm` is total seasonal crop water use (ET), with rain and irrigation together.
- `pdf_page` is the 1-based page of the PDF file, which can differ from the page number printed on it. A link to `url#page=N` opens the right page in most browsers.
- Show `quote` on the crop card as the evidence. When an entry has `placeholder: true`, show the value as "not from a guide".
- `pattern` is `same_year` (all the crops grow every year) or `alternate` (one crop per year in turn).
