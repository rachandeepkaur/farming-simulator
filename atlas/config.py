"""Shared settings: valley outline, grid size, file paths, NASA POWER period."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CELLS_PATH = DATA_DIR / "cells.json"
CROPS_PATH = DATA_DIR / "crops.json"
CROPS_SAMPLE_PATH = DATA_DIR / "crops.sample.json"

# Rough outline of the Central Valley floor as (lon, lat), clockwise from the
# north tip near Redding. Hand-traced from the valley's known edges (Coast
# Range foothills to the west, Sierra foothills to the east). Good enough for a
# coarse demo grid; swap in a real boundary (e.g. the USGS Central Valley
# aquifer outline) if one is available.
VALLEY_POLYGON: list[tuple[float, float]] = [
    (-122.45, 40.60),  # north tip, near Redding
    (-121.95, 40.20),  # east edge, Red Bluff foothills
    (-121.55, 39.50),  # Oroville
    (-121.10, 38.70),  # Sacramento foothills
    (-120.85, 38.00),  # Stockton east
    (-120.25, 37.40),  # Merced east
    (-119.55, 36.85),  # Fresno east
    (-119.05, 36.25),  # Visalia east
    (-118.75, 35.40),  # Bakersfield east
    (-118.95, 35.00),  # south tip, Grapevine
    (-119.45, 35.05),  # Taft west
    (-119.95, 35.65),  # Kettleman west
    (-120.40, 36.30),  # Coalinga west
    (-121.00, 37.00),  # Los Banos west
    (-121.55, 37.75),  # Tracy, Delta
    (-122.00, 38.40),  # Vacaville
    (-122.30, 39.50),  # Orland west
]

# Grid cell size in degrees. 0.1 gives roughly 500 cells over the polygon.
CELL_DEG = 0.1

# NASA POWER meteorology is on a 0.5 x 0.625 degree grid (MERRA-2), so many
# demo cells share one POWER pixel. We fetch once per pixel.
POWER_LAT_STEP = 0.5
POWER_LON_STEP = 0.625
POWER_START = "20010101"
POWER_END = "20251231"
POWER_PERIOD = "2001-2025"
REPLAY_YEARS = list(range(2012, 2022))  # 2012-2021, covers the 2012-2016 drought

FROST_C = 0.0  # a frost day has a minimum below this
HEAT_C = 35.0  # a heat day has a maximum above this
DT_STEPS = [i * 0.5 for i in range(9)]  # 0 to +4 C, for the temperature slider
