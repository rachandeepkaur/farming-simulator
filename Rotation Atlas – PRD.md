# Rotation Atlas – PRD

Nov 14, 2026 · @Rachandeep

## Summary

Rotation Atlas is a county-scale map of California's Central Valley where every field gets a crop rotation suggestion, grounded in NASA climate and water data and crop-guide facts, and decided by Drex in milliseconds. Drag a climate slider and the whole valley is re-decided live, something a frontier LLM cannot do at interactive speed.

- **Track:** Apex Predator (Drex vs. the Giants), with NDI bonus and Best Use of Adobe.
- **Team:** Rachan and Arpan.
- **Inspiration:** the NASA challenge on crop rotation decision support (compare at least three strategies, show evidence, gaps and risks, support rather than replace farmer judgment).

## Problem and why Drex

Farmers choosing a new rotation must weigh rainfall, frost, heat, groundwater and soil against water use, income and soil health. The data exists (NASA POWER, GRACE, extension guides) but is scattered across satellites and PDFs, and a change in one assumption changes the answer for every field.

The interesting question is not one field but "what if": what happens to the whole valley in a dry decade or a hotter summer. Answering that means re-deciding hundreds of fields every time an assumption moves.

- **NDI** turns messy crop guides, conservation sheets and seed catalogs into structured crop facts, each with its source page.
- **Drex** makes one grounded decision per field in milliseconds, so the map re-decides while the slider moves.
- **A frontier LLM** making the same decisions takes seconds per field, so the map goes stale. That gap is the Apex Predator measurement.

## Goals, non-goals and success metrics

**Goals for demo day**

1. Re-decide every field on the map in about a second when a climate or priority slider moves, using Drex.
2. Show, for any field, three strategies (the existing rotation, a winter cover crop, a drought-tolerant rotation) with evidence, benefits, risks and data gaps.
3. Measure Drex against a frontier LLM on the same requests, and report the numbers honestly.
4. Use NDI for crop facts and Adobe for visuals and the deck.

**Non-goals**

- Telling a farmer what to plant. The tool suggests; the farmer and a local advisor decide.
- Claiming agronomic accuracy. There is no ground truth for the best rotation.
- Field-level precision. The map works on a coarse grid, not property boundaries.

**Success metrics**

| Metric | How we measure it |
| --- | --- |
| Full-map re-decision time | Wall-clock time to decide every grid cell, Drex vs. LLM, same parallelism |
| Agreement with guide rules | Share of picks consistent with rules NDI extracted from the extension guides |
| Consistency | Same field and inputs give the same answer across repeated runs |
| Review flags | Share of fields flagged for local review, with the reason shown |

## Users and user stories

The primary user is a farmer with little geospatial experience; the secondary user is the extension advisor who reviews suggestions with them. The hackathon judges are the demo audience.

- As a farmer, I want to see which rotation fits my field and why, in plain words, so I can discuss it with my advisor.
- As a farmer, I want to set what matters to me (saving water, income, soil health) and see the suggestion change.
- As a farmer, I want to see which months my field sits bare and what would fill them.
- As an advisor, I want every suggestion to show its data sources and flag where data is thin, so I know what to check on site.
- As a planner, I want to drag a "dry decade" scenario and see how suggestions shift across the whole valley.

## Features and requirements

P0 items must work live on stage; P1 items are added if time allows.

| Feature | Requirement | Priority |
| --- | --- | --- |
| Valley map | Grid of about 500 cells over the Central Valley, colored by suggested strategy, with review-flagged cells outlined | P0 |
| Climate sliders | Rainfall, temperature and groundwater sliders plus presets (Today, Dry decade, Hotter summers, Wet years) re-decide every cell | P0 |
| Priority sliders | Save water, income and build soil weights change each decision | P0 |
| Field card | Three strategies side by side: fit, 12-month timeline, water-budget fit, benefits, risks, evidence with sources, review reason | P0 |
| Drex vs. LLM toggle | Same requests sent to either decision-maker; timing shown live and logged | P0 |
| Crop cards | Facts NDI extracted from the guides, each with its source page | P0 |
| Benchmark export | CSV of per-request latency and answers for both models | P1 |
| SMAP and MODIS layers | Soil moisture and vegetation index as extra evidence | P1 |
| Request viewer | The exact Drex request for the selected field | P1 |

## System architecture

&#91;embedded content: Rotation Atlas system architecture · owners by color\]

Rachan's NASA pipeline and Arpan's NDI ingestion run once before the demo; on every slider move the router sends one state per cell to Drex or the LLM, and the frontend redraws from the answers.

## Data sources and Drex request

All climate inputs are precomputed per grid cell before the demo; only the scenario adjustments are applied live.

| Source | What we take per cell | Priority |
| --- | --- | --- |
| NASA POWER | Annual rainfall, frost days, days above 35 °C (multi-year average) | P0 |
| GRACE / GRACE-FO | Water storage trend in cm/yr, regridded to the cell | P0 |
| Extension guides, NRCS sheets, seed catalogs (via NDI) | Crop water need, frost tolerance, nitrogen fixing, root depth, source page | P0 |
| SMAP | Soil moisture anomaly | P1 |
| MODIS / Landsat | Vegetation index, to find bare-field months | P1 |

One Drex call per cell. The `state` is a fixed-format sentence built from the cell's evidence, the scenario and the farmer's priorities. The questions:

| Question | Type | Options |
| --- | --- | --- |
| fits\_water\_budget | bool | For the recommended strategy |
| frost\_risk | choice | low, moderate, high |
| soil\_benefit | choice | nitrogen, organic matter, erosion control, none |
| recommended | choice | existing rotation, winter cover crop, drought-tolerant rotation |
| needs\_local\_review | bool | Borderline call or thin data |

The LLM baseline receives the same state and questions and must return JSON with the same keys.

## Work split

Rachan owns the data and decision side (NASA layers, Drex, benchmark); Arpan owns the document and product side (NDI, backend, map UI, visuals). The shared contract between them is the per-cell JSON and the Drex request format, agreed in the first hour.

| # | Task | Owner | Output | Depends on |
| --- | --- | --- | --- | --- |
| 1 | Agree the cell JSON and Drex request format | Rachan and Arpan | One shared schema file | — |
| 2 | Test a Drex call and measure real round-trip time | Rachan | Latency number, confirmed question types | 1 |
| 3 | Build the grid and pull NASA POWER rainfall, frost and heat per cell | Rachan | cells.json | 1 |
| 4 | Regrid the GRACE water storage trend onto the grid | Rachan | GRACE field in cells.json | 3 |
| 5 | Run crop guides and NRCS sheets through NDI | Arpan | crops.json with source pages | 1 |
| 6 | Write the state builder and Drex question set | Rachan | build\_state() and decide() | 2, 3, 5 |
| 7 | Backend endpoint that decides all cells for a scenario, in parallel, and returns timing | Arpan | /decide API | 6 |
| 8 | LLM baseline with the same state and questions | Rachan | Same API, LLM mode | 6 |
| 9 | Port the prototype map to real cells and the /decide API | Arpan | Live map, sliders, field card | 3, 7 |
| 10 | Crop cards and the field-card evidence from real data | Arpan | Crop panel, evidence rows | 5, 9 |
| 11 | Benchmark runs: latency, agreement with guide rules, consistency | Rachan | Results table and CSV | 7, 8 |
| 12 | Firefly crop illustrations and title visual | Arpan | Images for crop cards and deck | — |
| 13 | Deck in Adobe Express with results slide | Rachan and Arpan (Rachan: story and numbers; Arpan: design) | 5–6 slide deck | 11, 12 |
| 14 | Record a backup demo video | Arpan | 60-second screen recording | 9 |
| 15 | Rehearse the pitch twice | Rachan and Arpan | Timed run-through | 13, 14 |

## Timeline

&#91;embedded content: Hackathon day plan · two lanes, two gates\]

Nothing past setup starts until the schema is agreed, and features freeze before the final hour so it goes to the deck, backup video and two rehearsals. Shift the hour ranges to match the event's submission time.

## Risks and open questions

| Risk | Mitigation | Owner |
| --- | --- | --- |
| Drex round-trip or rate limits too slow for live full-map re-decision | Measure in hour 1; cache decisions per scenario preset; reduce grid size if needed | Rachan |
| GRACE regridding takes longer than planned | Fall back to a smooth north–south trend fitted to the GRACE basin values | Rachan |
| NDI extraction from crop guides is incomplete | Hand-check the five crops used; keep source pages visible | Arpan |
| Wi-Fi fails during the live demo | Backup video and cached scenario results | Arpan |
| Judges ask "is the recommendation correct?" | State non-goals plainly; show agreement and consistency, not accuracy | Rachan |

**Open questions**

- What is Drex's real latency and rate limit for this account?
- Which extension guides and NRCS sheets do we use, and are they cleared for the demo?
- What are the hackathon's submission time and demo slot length?
