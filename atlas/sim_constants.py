"""All tunable numbers for the water budget and the simulation, in one place.

These are ILLUSTRATIVE, not calibrated. Each has a short note on where the
value came from; the demo must say the simulation is a what-if, not a
forecast. Sanity-check against the GRACE basin trend before the demo.
"""

# --- Water need ----------------------------------------------------------
# Crop water need rises on hot years: +0.2% per heat day above 60 days.
# Round number chosen so a +2 C summer adds roughly 5-10% to demand.
HEAT_DAY_BASE = 60.0
WATER_NEED_PER_HEAT_DAY = 0.002

# --- Water budget ----------------------------------------------------------
# Share of annual rain a crop can use depends on when it grows: most rain
# falls Nov-Mar, so a winter crop uses it directly, a spring crop uses what
# the soil stored, and a summer crop after a bare winter gets little of it.
# Deep roots reach more stored water. Round numbers.
RAIN_SHARE_BY_SEASON = {"winter": 0.8, "spring": 0.6, "summer": 0.3}
DEEP_ROOT_CM = 180.0
DEEP_ROOT_BONUS = 0.1
RAIN_SHARE_MAX = 0.9
# Pumping a cell can sustain each year without drawing down storage, in cm of
# water applied. Round number standing in for surface-water deliveries plus
# sustainable yield. Set so the south is over budget, matching the valley's
# documented groundwater overdraft; this is what makes strategy choice move
# groundwater in the simulation.
SUSTAINABLE_SUPPLY_CM = 40.0

# --- Groundwater update ----------------------------------------------------
# Applied as a difference from "existing rotation, today's climate", because
# the GRACE trend already contains today's pumping (see simulate.simulate_year).
# Both terms are storage change in cm over the whole cell, like GRACE.
# About half of each cell is irrigated cropland (round number), so pumping and
# recharge on the crop area count at half weight.
IRRIGATED_FRACTION = 0.5
# Share of rain the crop doesn't use that percolates to the aquifer.
RECHARGE_SHARE = 0.15 * IRRIGATED_FRACTION
# Storage lost per cm pumped beyond the sustainable supply; ~30% of applied
# water returns to the aquifer.
PUMP_TO_STORAGE = 0.7 * IRRIGATED_FRACTION
# Below this cumulative change (cm) the cell is flagged for groundwater stress.
STRESS_THRESHOLD_CM = -25.0

# --- Soil score (0-100) ----------------------------------------------------
SOIL_START = 50.0
SOIL_DELTA = {
    "existing": -1.0,        # bare winters, repeated cropping
    "cover_crop": +3.0,      # winter cover, nitrogen fixing
    "drought_tolerant": +1.0,  # deeper roots, more residue
}
SOIL_REPEAT_PENALTY = -1.0  # same strategy as last year
