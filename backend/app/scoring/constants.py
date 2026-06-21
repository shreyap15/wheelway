"""
WheelWay — ADA / PROWAG-derived constants for accessibility scoring.

Sources (researched against current federal guidance, June 2026):

1. U.S. Access Board, "Final Rule: Accessibility Guidelines for Pedestrian
   Facilities in the Public Right-of-Way" (PROWAG), published Aug 8 2023,
   effective Oct 7 2023. https://www.access-board.gov/prowag/
   - R302.5 Grade (running slope): pedestrian access routes (PAR) not in a
     street/highway right-of-way -> 5% max running slope.
   - R302.6 Cross Slope: PAR cross slope -> 2% max (5% max only at
     uncontrolled street crossings, a narrow exception).
   - R302.7 Surfaces: must be "firm, stable, and slip resistant."
   - R304 Curb ramps: running slope up to 8.33% (1:12) max, cross slope 2% max,
     min clear width 4 ft (1.22 m) excluding flares.
   - R407 Ramps (non-curb): running slope 8.33% (1:12) max, cross slope 2% max.

2. ADA Standards for Accessible Design (2010), 403.5.1: minimum clear width
   of an accessible route = 36 in (0.91 m), with passing-space requirements
   every 200 ft for routes narrower than 60 in (1.52 m).

3. State DOT supplements (e.g. MoDOT EPG 642.8) converge on: sidewalks 5 ft
   (1.52 m) preferred width, cross slope 1-2%, running slope as flat as
   possible up to 5% max.

These numbers are the best available *minimums* — agencies can exceed them.
WheelWay treats them as hard/soft thresholds for scoring, not as legal
compliance determinations.
"""

# --- Running slope (grade), in percent ---
SLOPE_IDEAL_MAX = 5.0          # PROWAG R302.5 — standard PAR max running slope
SLOPE_RAMP_MAX = 8.33          # PROWAG R304/R407 — max for short curb ramps/ramps (1:12)
SLOPE_HARD_CAP = 8.33          # beyond this, treat as effectively non-traversable for most wheelchair users
SLOPE_SEVERE = 10.0            # above this, score should approach 0 regardless of other factors

# --- Cross slope, in percent ---
CROSS_SLOPE_IDEAL_MAX = 2.0    # PROWAG R302.6 standard max for PAR
CROSS_SLOPE_EXCEPTION_MAX = 5.0  # PROWAG exception at uncontrolled crossings only
CROSS_SLOPE_SEVERE = 6.0       # beyond exception range, heavily penalize

# --- Width, in meters ---
WIDTH_ADA_MIN = 0.91           # 36 in, ADA 2010 403.5.1 absolute minimum
WIDTH_PROWAG_MIN = 1.0         # ~40 in, general PROWAG PAR minimum
WIDTH_PREFERRED = 1.52         # 60 in (5 ft), preferred passing width, no passing-space needed
WIDTH_CURB_RAMP_MIN = 1.22     # 4 ft, PROWAG R304 curb ramp clear width minimum

# --- Surface condition ---
SURFACE_CONDITION_GOOD = 0.8   # >= this is considered "good condition"
SURFACE_CONDITION_POOR = 0.4   # <= this is considered "poor condition," heavy penalty

# --- Confidence / data freshness ---
CONFIDENCE_HALF_LIFE_DAYS = 30.0  # report_confidence decays toward 0.5 baseline with this half-life

# --- Default scoring weights (tunable; sum should be 1.0) ---
DEFAULT_WEIGHTS = {
    "slope": 0.35,
    "cross_slope": 0.25,
    "surface_condition": 0.20,
    "width": 0.10,
    "surface_type": 0.10,
}
