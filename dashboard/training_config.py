"""Tunable training-goal constants for the static dashboard.

Heart-rate bands are Karvonen estimates from RHR ≈ 48 and HRmax ≈ 190.
Retune here after a new max-HR check, lactate test, or goal change — then
rebuild with `python dashboard/build_dashboard.py`.
"""

from __future__ import annotations

# Inclusive bpm bands. A run is assigned one zone from its workout-average HR
# (Apple Health `HKQuantityTypeIdentifierHeartRate` avg). That is not
# time-in-zone; min/max HR are shown but not split across bands.
HR_ZONES: tuple[tuple[str, int, int], ...] = (
    ("Z1", 119, 133),
    ("Z2", 134, 147),
    ("Z3", 148, 162),
    ("Z4", 163, 176),
    ("Z5", 177, 190),
)

# Easy-run soft ceiling (inside Z2). Avg HR at or below this counts as easy.
EASY_HR_CEILING = 145

# Window for the easy-only pace trend (Z2-ish, a little wider than the ceiling).
EASY_HR_BAND = (130, 148)

# Quality / hard day: workout-average HR at or above Z3.
QUALITY_AVG_HR_MIN = 148

# Weekly mileage target (mpw) and how many weeks of zeros to fill for consistency.
WEEKLY_MILES_TARGET = (17.0, 20.0)
CONSISTENCY_WEEKS = 26
OVERVIEW_WEEKS = 8
GOAL_LOOKBACK_WEEKS = 16

# Easy-aerobic *samples* for descriptive form (median pace + observed HR).
# Not Apple VO2. Max-HR cap is a conservative heuristic, not proof a run was
# steady; runs with no max HR are still included. This is not a speed/HR index.
CARDIO_ROLLING_WEEKS = 6
CARDIO_MIN_SAMPLES = 3
CARDIO_MIN_MILES = 2.0
CARDIO_MIN_DURATION_MIN = 18.0
CARDIO_MAX_HR_CEILING = 160  # drop samples whose recorded max is clearly above easy/Z3

# Goal: 5 miles at 9:00–9:30/mi while staying at easy effort.
GOAL_DISTANCE_MI = 5.0
GOAL_PACE_MIN = 9.0  # min/mi (9:00)
GOAL_PACE_MAX = 9.5  # min/mi (9:30)
GOAL_HR_MAX = EASY_HR_CEILING

GOAL_STATEMENT = "5 mi @ 9:00–9:30/mi with avg HR ≤ 145 (zone 2)"
