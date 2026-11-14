"""Build data/farm.json: a 6 x 6 farm (40-acre fields) with SSURGO soil per field.

    uv run python scripts/build_farm.py                     # soil from USDA Soil Data Access
    uv run python scripts/build_farm.py --offline           # labelled soil estimate
    uv run python scripts/build_farm.py --center 36.45,-119.95 --n 6
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import farm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", default=",".join(map(str, farm.FARM_CENTER)))
    ap.add_argument("--n", type=int, default=farm.FARM_N)
    ap.add_argument("--field-m", type=float, default=farm.FIELD_M)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    center = tuple(map(float, a.center.split(",")))
    d = farm.build(center, a.n, a.field_m, a.offline)
    farm.FARM_PATH.write_text(json.dumps(d, indent=1))
    print(f"wrote {farm.FARM_PATH}: {len(d['fields'])} fields, parent cell {d['parent_cell']}, "
          f"SSURGO soil for {d['soil_resolved']}/{len(d['fields'])}")


if __name__ == "__main__":
    main()
