"""Build data/cells.json: grid + NASA POWER climate + GRACE trend (tasks 3, 4, 12).

    uv run python scripts/build_cells.py                       # GRACE fallback trend
    uv run python scripts/build_cells.py --grace-file GRC.nc   # regrid real GRACE
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import grace, power, weather  # noqa: E402
from atlas.config import CELL_DEG, CELLS_PATH  # noqa: E402
from atlas.grid import build_grid  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell-deg", type=float, default=CELL_DEG)
    ap.add_argument("--grace-file", help="GRACE mascon NetCDF; omit to use the fallback trend")
    ap.add_argument("--out", default=str(CELLS_PATH))
    args = ap.parse_args()

    cells = build_grid(args.cell_deg)
    print(f"grid: {len(cells)} cells at {args.cell_deg} deg")
    power.attach_climate(cells)

    if args.grace_file:
        grace.regrid_from_file(cells, args.grace_file)
    else:
        grace.attach_fallback(cells)
    n_real = sum(c["grace"]["source"] == "grace" for c in cells)
    print(f"GRACE: {n_real} cells from file, {len(cells) - n_real} from fallback")

    for c in cells:
        c.pop("power_pixel", None)  # kept inside climate
    pixels = sorted({c["climate"]["power_pixel"] for c in cells})
    weather.MONTHLY_PATH.write_text(json.dumps(weather.build_all(pixels), separators=(",", ":")))
    print(f"wrote {weather.MONTHLY_PATH}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cells, indent=1))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
