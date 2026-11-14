"""One farm: a small square of fields inside one valley cell.

Every field inherits its parent cell's NASA POWER climate and GRACE trend
(POWER is ~50 km, so one farm is one climate pixel). Fields differ by:
  * soil: SSURGO available water storage (0-150 cm) from USDA Soil Data Access
  * water allocation: how much surface water the farmer gives each field
    (god-mode resource allocation, sent per request as `supply_cm`)

    uv run python scripts/build_farm.py               # SSURGO soil per field
    uv run python scripts/build_farm.py --offline     # labelled soil estimate
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from functools import lru_cache

from .config import CELLS_PATH, DATA_DIR

FARM_PATH = DATA_DIR / "farm.json"
# A San Joaquin Valley site southwest of Fresno (same spot the single-field
# demo featured). Change with --center.
FARM_CENTER = (36.45, -119.95)
FARM_N = 6            # 6 x 6 fields
FIELD_M = 402.0       # 402 m square = 40 acres
SDA_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"


CROP_MIX = ["processing_tomato", "processing_tomato", "winter_wheat", "safflower"]


def field_grid(center=FARM_CENTER, n=FARM_N, field_m=FIELD_M) -> list[dict]:
    lat0, lon0 = center
    dlat = field_m / 111_320
    dlon = field_m / (111_320 * math.cos(math.radians(lat0)))
    top, left = lat0 + dlat * n / 2, lon0 - dlon * n / 2
    acres = round(field_m * field_m / 4046.86, 1)
    out = []
    for r in range(n):
        for c in range(n):
            s, w = top - (r + 1) * dlat, left + c * dlon
            out.append({"id": f"f{r}{c}", "row": r, "col": c,
                        "lat": round(s + dlat / 2, 5), "lon": round(w + dlon / 2, 5),
                        "bbox": [round(w, 5), round(s, 5), round(w + dlon, 5), round(s + dlat, 5)],
                        "acres": acres,
                        # The farmer's crop plan (blocks of 2 columns); god tools can replant.
                        "crop": CROP_MIX[(c // 2 + r // 3) % len(CROP_MIX)]})
    return out


def nearest_cell(cells: list[dict], lat: float, lon: float) -> dict:
    return min(cells, key=lambda c: (c["lat"] - lat) ** 2 + (c["lon"] - lon) ** 2)


def fetch_soil(lat: float, lon: float) -> dict:
    """SSURGO map unit at a point -> available water storage 0-150 cm (cm),
    drainage class, map unit name."""
    q = ("SELECT mu.mukey, mu.muname, ma.aws0150wta, ma.drclassdcd, "
         "(SELECT TOP 1 ch.ph1to1h2o_r FROM component co INNER JOIN chorizon ch ON ch.cokey = co.cokey "
         " WHERE co.mukey = mu.mukey AND co.majcompflag = 'Yes' ORDER BY co.comppct_r DESC, ch.hzdept_r ASC) AS ph "
         "FROM mapunit mu INNER JOIN muaggatt ma ON ma.mukey = mu.mukey "
         f"WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))")
    req = urllib.request.Request(SDA_URL, data=json.dumps({"query": q, "format": "JSON+COLUMNNAME"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode() or "{}").get("Table") or []
    if len(rows) < 2:
        raise ValueError("no SSURGO map unit here")
    d = dict(zip(rows[0], rows[1]))
    aws = d.get("aws0150wta")
    ph = d.get("ph")
    return {"aws_cm": None if aws in (None, "") else round(float(aws), 1),
            "ph": None if ph in (None, "") else round(float(ph), 1), "name": d.get("muname"),
            "drainage": d.get("drclassdcd"), "mukey": d.get("mukey"), "source": "ssurgo"}


def fallback_soil(row: int, col: int) -> dict:
    """Smooth made-up soil patches so the map isn't uniform offline. Labelled as an estimate."""
    v = 15 + 7 * math.sin(row / 1.7) * math.cos(col / 2.2) + 2.5 * math.sin((row + col) / 2.5)
    ph = 7.4 + 0.5 * math.sin(row / 1.9 + 1) * math.cos(col / 1.6)   # west-side soils run neutral to alkaline
    return {"aws_cm": round(v, 1), "ph": round(ph, 1), "name": None, "drainage": None, "mukey": None, "source": "estimate"}


def build(center=FARM_CENTER, n=FARM_N, field_m=FIELD_M, offline=False) -> dict:
    cells = json.loads(CELLS_PATH.read_text())
    parent = nearest_cell(cells, *center)
    fields = field_grid(center, n, field_m)
    ok = 0
    for f in fields:
        soil = None
        if not offline:
            for attempt in range(3):
                try:
                    soil = fetch_soil(f["lat"], f["lon"])
                    ok += 1
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        print(f"  soil {f['id']}: {e} (using estimate)")
                    time.sleep(1 + attempt)
        f["soil"] = soil or fallback_soil(f["row"], f["col"])
    return {"center": list(center), "n": n, "field_m": field_m, "parent_cell": parent["id"],
            "soil_resolved": ok, "fields": fields}


@lru_cache(maxsize=1)
def load() -> dict:
    if FARM_PATH.exists():
        return json.loads(FARM_PATH.read_text())
    return build(offline=True)


def farm_cells(supply: dict[str, float] | None = None, ph: dict[str, float] | None = None) -> list[dict]:
    """Farm fields in the valley-cell shape the pipeline expects (climate and
    GRACE from the parent cell), with each field's water allocation."""
    farm = load()
    cells = {c["id"]: c for c in json.loads(CELLS_PATH.read_text())}
    parent = cells[farm["parent_cell"]]
    out = []
    for f in farm["fields"]:
        c = {**f, "climate": parent["climate"], "grace": parent["grace"], "parent_cell": parent["id"]}
        if supply and f["id"] in supply:
            c["supply_cm"] = float(supply[f["id"]])
        if ph and f["id"] in ph:
            c["ph"] = float(ph[f["id"]])
        out.append(c)
    return out
