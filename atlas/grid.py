"""Task 3a: build the demo grid over the Central Valley."""

from __future__ import annotations

import math

from .config import CELL_DEG, POWER_LAT_STEP, POWER_LON_STEP, VALLEY_POLYGON


def point_in_polygon(lon: float, lat: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting test."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def power_pixel(lat: float, lon: float) -> tuple[float, float]:
    """Centre of the NASA POWER (MERRA-2) pixel that contains this point."""
    plat = round(lat / POWER_LAT_STEP) * POWER_LAT_STEP
    plon = round(lon / POWER_LON_STEP) * POWER_LON_STEP
    return round(plat, 4), round(plon, 4)


def build_grid(cell_deg: float = CELL_DEG, poly=VALLEY_POLYGON) -> list[dict]:
    """Cells whose centre falls inside the valley outline, numbered by row
    (north to south) and column (west to east)."""
    lons = [p[0] for p in poly]
    lats = [p[1] for p in poly]
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)
    n_rows = math.ceil((north - south) / cell_deg)
    n_cols = math.ceil((east - west) / cell_deg)

    cells = []
    for r in range(n_rows):
        lat_top = north - r * cell_deg
        lat_c = round(lat_top - cell_deg / 2, 4)
        for c in range(n_cols):
            lon_left = west + c * cell_deg
            lon_c = round(lon_left + cell_deg / 2, 4)
            if not point_in_polygon(lon_c, lat_c, poly):
                continue
            plat, plon = power_pixel(lat_c, lon_c)
            cells.append(
                {
                    "id": f"r{r:03d}c{c:03d}",
                    "row": r,
                    "col": c,
                    "lat": lat_c,
                    "lon": lon_c,
                    "bbox": [
                        round(lon_left, 4),
                        round(lat_top - cell_deg, 4),
                        round(lon_left + cell_deg, 4),
                        round(lat_top, 4),
                    ],
                    "power_pixel": f"{plat}_{plon}",
                }
            )
    return cells
