"""Task 4: groundwater storage trend per cell from GRACE / GRACE-FO.

Two paths:

1. `regrid_from_file()` reads a GRACE mascon NetCDF (for example JPL's
   GRCTellus mascon CRI file from PO.DAAC, which needs a free NASA Earthdata
   login), fits a linear trend per mascon pixel over the chosen period, and
   samples it at each cell centre. Needs the optional `grace` extras:
   `uv sync --extra grace`.

2. `fallback_trend()` is the PRD's planned fallback: a smooth north-south
   trend. Its two end values are PLACEHOLDERS until someone reads them off the
   GRACE basin values; they only encode the well-documented pattern that the
   southern (Tulare) basin loses water faster than the northern (Sacramento)
   basin.
"""

from __future__ import annotations

from pathlib import Path

# PLACEHOLDER end values in cm/yr of equivalent water height. Replace with
# numbers read from the GRACE basin series before the demo.
FALLBACK_NORTH_CM_YR = -0.5
FALLBACK_SOUTH_CM_YR = -2.5
FALLBACK_NORTH_LAT = 40.6
FALLBACK_SOUTH_LAT = 35.0


def fallback_trend(lat: float) -> float:
    t = (FALLBACK_NORTH_LAT - lat) / (FALLBACK_NORTH_LAT - FALLBACK_SOUTH_LAT)
    t = min(1.0, max(0.0, t))
    return round(FALLBACK_NORTH_CM_YR + t * (FALLBACK_SOUTH_CM_YR - FALLBACK_NORTH_CM_YR), 2)


def attach_fallback(cells: list[dict]) -> list[dict]:
    for c in cells:
        c["grace"] = {"trend_cm_yr": fallback_trend(c["lat"]), "source": "fallback"}
    return cells


def regrid_from_file(
    cells: list[dict],
    path: str | Path,
    var: str = "lwe_thickness",
    start: str = "2002-04-01",
    end: str = "2024-12-31",
) -> list[dict]:
    """Linear trend (cm/yr) of the GRACE variable, sampled at each cell centre
    with nearest-neighbour lookup. Longitudes in 0-360 files are handled."""
    import numpy as np
    import xarray as xr

    ds = xr.open_dataset(path)
    da = ds[var].sel(time=slice(start, end))
    lon_name = "lon" if "lon" in da.dims else "longitude"
    lat_name = "lat" if "lat" in da.dims else "latitude"
    uses_360 = float(da[lon_name].max()) > 180

    # Trend per pixel, only over the valley's bounding box to keep it quick.
    lats = [c["lat"] for c in cells]
    lons = [c["lon"] for c in cells]
    pad = 1.0
    lon_lo, lon_hi = min(lons) - pad, max(lons) + pad
    if uses_360:
        lon_lo, lon_hi = lon_lo % 360, lon_hi % 360
    lat_axis = da[lat_name]
    lat_slice = (
        slice(min(lats) - pad, max(lats) + pad)
        if float(lat_axis[0]) < float(lat_axis[-1])
        else slice(max(lats) + pad, min(lats) - pad)
    )
    box = da.sel({lat_name: lat_slice, lon_name: slice(lon_lo, lon_hi)})

    # Fit against decimal years so the slope is directly cm/yr (JPL mascon
    # lwe_thickness is in cm).
    t0 = box["time"].values[0]
    dec_years = (box["time"].values - t0) / np.timedelta64(1, "D") / 365.25
    box = box.assign_coords(t_years=("time", dec_years)).swap_dims({"time": "t_years"})
    trend_cm_yr = box.polyfit(dim="t_years", deg=1).polyfit_coefficients.sel(degree=1)

    for c in cells:
        lon = c["lon"] % 360 if uses_360 else c["lon"]
        v = float(trend_cm_yr.sel({lat_name: c["lat"], lon_name: lon}, method="nearest"))
        if np.isnan(v):
            c["grace"] = {"trend_cm_yr": fallback_trend(c["lat"]), "source": "fallback"}
        else:
            c["grace"] = {"trend_cm_yr": round(v, 2), "source": "grace"}
    return cells
