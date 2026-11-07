"""Query training.db for dashboard charts and tables."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import mean

from dashboard.training_config import (
    CARDIO_MAX_HR_CEILING,
    CARDIO_MIN_DURATION_MIN,
    CARDIO_MIN_MILES,
    CARDIO_MIN_SAMPLES,
    CARDIO_ROLLING_WEEKS,
    CONSISTENCY_WEEKS,
    EASY_HR_BAND,
    EASY_HR_CEILING,
    GOAL_DISTANCE_MI,
    GOAL_HR_MAX,
    GOAL_LOOKBACK_WEEKS,
    GOAL_PACE_MAX,
    GOAL_PACE_MIN,
    GOAL_STATEMENT,
    HR_ZONES,
    OVERVIEW_WEEKS,
    QUALITY_AVG_HR_MIN,
    WEEKLY_MILES_TARGET,
)

METERS_PER_MILE = 1609.344
ZONE_NAMES = [name for name, _lo, _hi in HR_ZONES]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def iso_week_label(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def iso_week_start(d: date) -> date:
    return d - timedelta(days=d.isocalendar()[2] - 1)


def assign_zone(avg_hr: float | None) -> str | None:
    """Map a workout-average HR to Z1–Z5. Values below Z1 clip to Z1; above Z5 to Z5."""
    if avg_hr is None:
        return None
    hr = float(avg_hr)
    lo0 = HR_ZONES[0][1]
    hiN = HR_ZONES[-1][2]
    if hr < lo0:
        return HR_ZONES[0][0]
    if hr > hiN:
        return HR_ZONES[-1][0]
    for name, lo, hi in HR_ZONES:
        if lo <= hr <= hi:
            return name
    return None


def is_easy(avg_hr: float | None) -> bool:
    return avg_hr is not None and float(avg_hr) <= EASY_HR_CEILING


def is_quality(avg_hr: float | None) -> bool:
    return avg_hr is not None and float(avg_hr) >= QUALITY_AVG_HR_MIN


def in_easy_band(avg_hr: float | None) -> bool:
    if avg_hr is None:
        return False
    lo, hi = EASY_HR_BAND
    return lo <= float(avg_hr) <= hi


def pace_min_per_mile(distance_m: float | None, duration_sec: float | None) -> float | None:
    if not distance_m or distance_m <= 0 or not duration_sec or duration_sec <= 0:
        return None
    miles = distance_m / METERS_PER_MILE
    return round(duration_sec / miles / 60.0, 2)


def sec_per_mile_per_bpm(pace_min_per_mile: float | None, avg_hr: float | None) -> float | None:
    """Seconds per mile per bpm. Lower = more economical at that effort.

    Replaces the old mph/avg_hr×1000 index (arbitrary scale, mean-of-means,
    and it treated short jogs and high-max surges as easy aerobic work).
    """
    if pace_min_per_mile is None or avg_hr is None or avg_hr <= 0 or pace_min_per_mile <= 0:
        return None
    return round((float(pace_min_per_mile) * 60.0) / float(avg_hr), 3)


def qualifies_easy_aerobic(
    miles: float | None,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    pace_min_per_mile: float | None,
) -> bool:
    """Steady easy samples for aerobic-form tracking. Not a clinical test."""
    if miles is None or miles < CARDIO_MIN_MILES:
        return False
    if duration_min is None or duration_min < CARDIO_MIN_DURATION_MIN:
        return False
    if pace_min_per_mile is None or pace_min_per_mile <= 0:
        return False
    if avg_hr is None or avg_hr > EASY_HR_CEILING:
        return False
    if max_hr is not None and float(max_hr) > CARDIO_MAX_HR_CEILING:
        return False
    return True


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        chunk = [v for v in values[max(0, i + 1 - window) : i + 1] if v is not None]
        out.append(round(mean(chunk), 2) if chunk else None)
    return out


def classify_week_status(
    miles: float,
    easy_share: float | None,
    quality_count: int,
    weekday: int,
) -> tuple[str, str, str]:
    """Return (code, label, detail) for the week being summarized.

    weekday is ISO (1=Mon … 7=Sun) of as_of when this is the current week,
    or 7 when summarizing a completed past week.
    """
    if miles <= 0:
        return "gap", "Gap week", "No runs logged this week."

    target_lo, target_hi = WEEKLY_MILES_TARGET
    hard = (easy_share is not None and easy_share < 0.55) or quality_count >= 3
    if hard and miles >= 8:
        share_txt = f"{easy_share:.0%} easy" if easy_share is not None else "easy share unknown"
        return (
            "too_hard",
            "Too hard",
            f"{share_txt}, {quality_count} quality session(s). Most miles should stay in Z2.",
        )
    if miles > target_hi + 4:
        return (
            "too_hard",
            "High volume",
            f"{miles:.1f} mi is above the {target_lo:.0f}–{target_hi:.0f} mpw band — watch shins on concrete.",
        )

    late_week = weekday >= 5
    if late_week and miles < 12:
        return "light", "Light week", f"{miles:.1f} mi vs {target_lo:.0f}–{target_hi:.0f} target."
    if weekday <= 3 and miles < 3:
        return "light", "Light week", "Quiet start; room to add easy miles."
    if 14 <= miles <= target_hi + 2:
        share_txt = f", {easy_share:.0%} easy" if easy_share is not None else ""
        return "on_track", "On track", f"{miles:.1f} mi toward {target_lo:.0f}–{target_hi:.0f} mpw{share_txt}."
    if miles >= 12:
        return "on_track", "On track", f"{miles:.1f} mi — close to the {target_lo:.0f}–{target_hi:.0f} band."
    return "light", "Light week", f"{miles:.1f} mi vs {target_lo:.0f}–{target_hi:.0f} target."


def goal_score(miles: float | None, pace: float | None, avg_hr: float | None) -> float | None:
    """0–100 closeness to 5 mi @ 9:00–9:30 with avg HR ≤ 145."""
    if miles is None or pace is None:
        return None
    dist = max(0.0, 1.0 - abs(miles - GOAL_DISTANCE_MI) / GOAL_DISTANCE_MI)
    mid = (GOAL_PACE_MIN + GOAL_PACE_MAX) / 2.0
    if GOAL_PACE_MIN <= pace <= GOAL_PACE_MAX:
        pace_s = 1.0
    else:
        pace_s = max(0.0, 1.0 - abs(pace - mid) / 2.5)
    if avg_hr is None:
        return None
    if avg_hr <= GOAL_HR_MAX:
        hr_s = 1.0
    else:
        hr_s = max(0.0, 1.0 - (avg_hr - GOAL_HR_MAX) / 25.0)
    return round(100.0 * (0.3 * dist + 0.4 * pace_s + 0.3 * hr_s), 1)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _enrich_run(row: dict) -> dict:
    distance_m = row.get("distance_m")
    duration_sec = row.get("duration_sec")
    miles = (distance_m / METERS_PER_MILE) if distance_m else None
    avg_hr = row.get("avg_hr")
    if avg_hr is not None:
        avg_hr = round(float(avg_hr), 1)
    max_hr = row.get("max_hr")
    if max_hr is not None:
        max_hr = round(float(max_hr), 0)
    pace = pace_min_per_mile(distance_m, duration_sec)
    duration_min = _round((duration_sec or 0) / 60.0, 1) if duration_sec else None
    indoor_raw = row.get("indoor")
    indoor = str(indoor_raw).strip() in {"1", "true", "True"} if indoor_raw is not None else None
    cardio_ok = qualifies_easy_aerobic(miles, duration_min, avg_hr, max_hr, pace)
    run_date = _parse_date(row.get("local_date"))
    return {
        "id": row.get("id"),
        "local_date": row.get("local_date"),
        "week": iso_week_label(run_date) if run_date else None,
        "miles": _round(miles, 2),
        "duration_min": duration_min,
        "pace_min_per_mile": pace,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "energy_kcal": _round(row.get("energy_kcal"), 0),
        "has_route": 1 if row.get("route_file") else 0,
        "indoor": indoor,
        "zone": assign_zone(avg_hr),
        "easy": is_easy(avg_hr),
        "quality": is_quality(avg_hr),
        "easy_band": in_easy_band(avg_hr),
        "cardio_sample": cardio_ok,
        "sec_per_mi_per_bpm": sec_per_mile_per_bpm(pace, avg_hr) if cardio_ok else None,
        "goal_score": goal_score(miles, pace, avg_hr) if miles and pace else None,
    }


def _week_payload(week_start: date, runs: list[dict]) -> dict:
    miles = sum(r["miles"] or 0 for r in runs)
    hours = sum((r["duration_min"] or 0) / 60.0 for r in runs)
    hr_runs = [r for r in runs if r["avg_hr"] is not None]
    easy_miles = sum(r["miles"] or 0 for r in hr_runs if r["easy"])
    hr_miles = sum(r["miles"] or 0 for r in hr_runs)
    quality_count = sum(1 for r in runs if r["quality"])
    zones = {name: 0.0 for name in ZONE_NAMES}
    unknown = 0.0
    for r in runs:
        m = r["miles"] or 0
        if r["zone"] in zones:
            zones[r["zone"]] += m
        else:
            unknown += m
    easy_share = round(easy_miles / hr_miles, 3) if hr_miles else None
    return {
        "week": iso_week_label(week_start),
        "week_start": week_start.isoformat(),
        "run_count": len(runs),
        "miles": round(miles, 2),
        "hours": round(hours, 2),
        "easy_miles": round(easy_miles, 2),
        "easy_share": easy_share,
        "quality_count": quality_count,
        "hr_run_count": len(hr_runs),
        "is_gap": len(runs) == 0,
        "zones": {k: round(v, 2) for k, v in zones.items()},
        "unknown_miles": round(unknown, 2),
    }


CARDIO_LIMITATIONS = (
    "Easy aerobic form uses workout-average HR, so hills, heat, treadmill vs outdoor, "
    "and 4x4s with a low average can still distort a week. Short jogs and high-max "
    "surges are excluded. Apple VO₂ max is a separate Health app estimate — it is not "
    "this score. Empty weeks stay empty; no interpolation."
)


def _cardio_from_runs(samples: list[dict]) -> dict:
    paces = [r["pace_min_per_mile"] for r in samples if r.get("pace_min_per_mile") is not None]
    hrs = [r["avg_hr"] for r in samples if r.get("avg_hr") is not None]
    ratios = [r["sec_per_mi_per_bpm"] for r in samples if r.get("sec_per_mi_per_bpm") is not None]
    indoor_n = sum(1 for r in samples if r.get("indoor") is True)
    outdoor_n = sum(1 for r in samples if r.get("indoor") is False)
    n = len(samples)
    if n == 0:
        status = "none"
    elif n < CARDIO_MIN_SAMPLES:
        status = "sparse"
    else:
        status = "ok"
    median_pace = _round(_median(paces), 2) if paces else None
    return {
        "n": n,
        "status": status,
        "median_pace": median_pace,
        "median_hr": _round(_median(hrs), 0) if hrs else None,
        "median_sec_per_mi_per_bpm": _round(_median(ratios), 3) if ratios else None,
        "indoor_n": indoor_n,
        "outdoor_n": outdoor_n,
        "unknown_surface_n": n - indoor_n - outdoor_n,
        "pace_gap_vs_930": (
            round(median_pace - GOAL_PACE_MAX, 2) if median_pace is not None else None
        ),
    }


def fetch_dashboard_data(
    conn: sqlite3.Connection,
    days: int = 365,
    today: date | None = None,
) -> dict:
    """Return all dashboard payload sections.

    `today` is injectable so tests can freeze the calendar. Progress uses the
    current ISO week when it has runs; otherwise the latest logged week.
    """
    as_of = today or date.today()
    cutoff = (as_of - timedelta(days=days)).isoformat()

    profile = _one(conn, "SELECT date_of_birth, biological_sex, export_date FROM user_profile WHERE id = 1")
    date_range = _one(
        conn,
        """
        SELECT MIN(local_date) AS start_date, MAX(local_date) AS end_date
        FROM daily_metrics
        """,
    )

    run_totals = _one(
        conn,
        """
        SELECT
            COUNT(*) AS run_count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS total_miles,
            ROUND(SUM(duration_sec) / 3600.0, 1) AS total_hours
        FROM workouts
        WHERE activity_type = 'HKWorkoutActivityTypeRunning'
          AND distance_m IS NOT NULL AND distance_m > 0
        """,
    )

    workout_totals = _one(conn, "SELECT COUNT(*) AS workout_count FROM workouts")

    latest_recovery = _one(
        conn,
        """
        SELECT resting_hr, hrv_sdnn, vo2_max, body_mass_kg, local_date
        FROM daily_metrics
        WHERE resting_hr IS NOT NULL OR hrv_sdnn IS NOT NULL OR vo2_max IS NOT NULL
        ORDER BY local_date DESC
        LIMIT 1
        """,
    )

    raw_runs = _rows(
        conn,
        """
        SELECT
            w.id,
            w.local_date,
            w.start_at,
            w.distance_m,
            w.duration_sec,
            w.energy_kcal,
            w.route_file,
            ws.avg_value AS avg_hr,
            ws.max_value AS max_hr,
            wm.value AS indoor
        FROM workouts w
        LEFT JOIN workout_statistics ws
          ON ws.workout_id = w.id
         AND ws.stat_type = 'HKQuantityTypeIdentifierHeartRate'
        LEFT JOIN workout_metadata wm
          ON wm.workout_id = w.id
         AND wm.key = 'HKIndoorWorkout'
        WHERE w.activity_type = 'HKWorkoutActivityTypeRunning'
          AND w.distance_m IS NOT NULL AND w.distance_m > 0
        ORDER BY w.start_at
        """,
    )
    runs = [_enrich_run(r) for r in raw_runs]
    runs_by_week: dict[str, list[dict]] = {}
    for run in runs:
        if run["week"]:
            runs_by_week.setdefault(run["week"], []).append(run)

    last_run_date = _parse_date(runs[-1]["local_date"]) if runs else None
    first_run_date = _parse_date(runs[0]["local_date"]) if runs else None
    data_end = _parse_date(date_range["end_date"] if date_range else None) or last_run_date or as_of
    training_anchor = last_run_date or as_of

    current_week_start = iso_week_start(as_of)
    last_run_week_start = iso_week_start(last_run_date) if last_run_date else current_week_start
    if last_run_week_start == current_week_start:
        progress_week_start = current_week_start
        progress_label = "This week"
    else:
        progress_week_start = last_run_week_start
        progress_label = f"Week of {progress_week_start.isoformat()}"

    def weeks_ending(end: date, count: int) -> list[date]:
        end_start = iso_week_start(end)
        starts = []
        cursor = end_start - timedelta(weeks=count - 1)
        while cursor <= end_start:
            starts.append(cursor)
            cursor += timedelta(days=7)
        return starts

    def week_rows(starts: list[date]) -> list[dict]:
        return [_week_payload(ws, runs_by_week.get(iso_week_label(ws), [])) for ws in starts]

    # Volume chart: last N weeks through the latest logged run (zeros = gaps).
    consistency_starts = weeks_ending(training_anchor, CONSISTENCY_WEEKS)
    if first_run_date:
        earliest = iso_week_start(first_run_date)
        consistency_starts = [ws for ws in consistency_starts if ws >= earliest]
    consistency = week_rows(consistency_starts)
    for week, rolling in zip(consistency, rolling_mean([w["miles"] for w in consistency], 4)):
        week["rolling_4w"] = rolling

    # Weeks that actually have runs, in chronological order (no 10-year zero fill).
    seen_weeks: list[str] = []
    seen_set: set[str] = set()
    for run in runs:
        label = run["week"]
        if label and label not in seen_set:
            seen_set.add(label)
            seen_weeks.append(label)
    weekly_with_runs = []
    for label in seen_weeks:
        sample = _parse_date(runs_by_week[label][0]["local_date"])
        if sample:
            weekly_with_runs.append(_week_payload(iso_week_start(sample), runs_by_week[label]))

    overview_weeks = week_rows(weeks_ending(progress_week_start + timedelta(days=6), OVERVIEW_WEEKS))
    for week, rolling in zip(overview_weeks, rolling_mean([w["miles"] for w in overview_weeks], 4)):
        week["rolling_4w"] = rolling

    progress_week = _week_payload(progress_week_start, runs_by_week.get(iso_week_label(progress_week_start), []))
    weekday = as_of.isocalendar()[2] if progress_week_start == current_week_start else 7
    status, status_label, status_detail = classify_week_status(
        progress_week["miles"],
        progress_week["easy_share"],
        progress_week["quality_count"],
        weekday,
    )
    if last_run_date and progress_week_start != current_week_start:
        days_ago = (as_of - last_run_date).days
        if days_ago >= 14:
            status_detail = f"{status_detail} No runs in the last {days_ago} days."
    last_quality = next((r for r in reversed(runs) if r["quality"]), None)
    rolling_4w = overview_weeks[-1]["rolling_4w"] if overview_weeks else None

    lookback_start = training_anchor - timedelta(weeks=GOAL_LOOKBACK_WEEKS)
    scatter_cutoff = as_of - timedelta(days=days)
    scatter = [
        {
            "local_date": r["local_date"],
            "miles": r["miles"],
            "pace_min_per_mile": r["pace_min_per_mile"],
            "avg_hr": r["avg_hr"],
            "zone": r["zone"],
            "easy": r["easy"],
            "quality": r["quality"],
            "recent": bool(_parse_date(r["local_date"]) and _parse_date(r["local_date"]) >= as_of - timedelta(weeks=OVERVIEW_WEEKS)),
        }
        for r in runs
        if r["avg_hr"] is not None
        and r["pace_min_per_mile"] is not None
        and _parse_date(r["local_date"])
        and _parse_date(r["local_date"]) >= scatter_cutoff
    ]

    easy_trend = [
        {
            "local_date": r["local_date"],
            "pace_min_per_mile": r["pace_min_per_mile"],
            "avg_hr": r["avg_hr"],
            "miles": r["miles"],
        }
        for r in runs
        if r["easy_band"] and r["pace_min_per_mile"] is not None
        and _parse_date(r["local_date"])
        and _parse_date(r["local_date"]) >= scatter_cutoff
    ]

    effort_starts = weeks_ending(progress_week_start + timedelta(days=6), CONSISTENCY_WEEKS)
    cardio_window_start = progress_week_start - timedelta(weeks=CARDIO_ROLLING_WEEKS - 1)
    cardio_samples = [
        r
        for r in runs
        if r.get("cardio_sample")
        and _parse_date(r.get("local_date"))
        and cardio_window_start <= _parse_date(r["local_date"]) <= (progress_week_start + timedelta(days=6))
    ]
    cardio_window = _cardio_from_runs(cardio_samples)
    cardio_window["window_weeks"] = CARDIO_ROLLING_WEEKS
    cardio_window["window_start"] = cardio_window_start.isoformat()
    cardio_window["min_samples"] = CARDIO_MIN_SAMPLES
    if cardio_window["status"] != "ok":
        cardio_window["median_pace"] = None
        cardio_window["median_hr"] = None
        cardio_window["median_sec_per_mi_per_bpm"] = None
        cardio_window["pace_gap_vs_930"] = None

    cardio_weekly = []
    for ws in effort_starts:
        week_samples = [
            r for r in runs_by_week.get(iso_week_label(ws), []) if r.get("cardio_sample")
        ]
        summary = _cardio_from_runs(week_samples)
        # Weekly points may show n=1; the rolling headline still requires min samples.
        roll_start = ws - timedelta(weeks=CARDIO_ROLLING_WEEKS - 1)
        roll_end = ws + timedelta(days=6)
        roll_samples = [
            r
            for r in runs
            if r.get("cardio_sample")
            and _parse_date(r.get("local_date"))
            and roll_start <= _parse_date(r["local_date"]) <= roll_end
        ]
        roll = _cardio_from_runs(roll_samples)
        cardio_weekly.append(
            {
                "week": iso_week_label(ws),
                "week_start": ws.isoformat(),
                "n": summary["n"],
                "median_pace": summary["median_pace"],
                "median_hr": summary["median_hr"],
                "median_sec_per_mi_per_bpm": summary["median_sec_per_mi_per_bpm"],
                "indoor_n": summary["indoor_n"],
                "outdoor_n": summary["outdoor_n"],
                "rolling_n": roll["n"],
                "rolling_pace": roll["median_pace"] if roll["status"] == "ok" else None,
                "rolling_sec_per_mi_per_bpm": (
                    roll["median_sec_per_mi_per_bpm"] if roll["status"] == "ok" else None
                ),
            }
        )

    candidates_src = [
        r
        for r in runs
        if r["miles"]
        and r["miles"] >= 3.0
        and r["pace_min_per_mile"]
        and _parse_date(r["local_date"])
        and _parse_date(r["local_date"]) >= lookback_start
    ]
    candidates_src.sort(key=lambda r: (r["goal_score"] is None, -(r["goal_score"] or 0)))
    candidates = [
        {
            "local_date": r["local_date"],
            "miles": r["miles"],
            "pace_min_per_mile": r["pace_min_per_mile"],
            "avg_hr": r["avg_hr"],
            "zone": r["zone"],
            "easy": r["easy"],
            "goal_score": r["goal_score"],
        }
        for r in candidates_src[:8]
    ]
    easy_near_5 = [
        r
        for r in runs
        if r["easy"] and r["miles"] and r["miles"] >= 3.5 and r["pace_min_per_mile"]
        and _parse_date(r["local_date"])
        and _parse_date(r["local_date"]) >= lookback_start
    ]
    best_easy_5 = None
    if easy_near_5:
        easy_five = [r for r in easy_near_5 if (r["miles"] or 0) >= 4.5]
        pool = easy_five or easy_near_5
        pick = max(pool, key=lambda r: r["goal_score"] or 0)
        best_easy_5 = {
            "local_date": pick["local_date"],
            "miles": pick["miles"],
            "pace_min_per_mile": pick["pace_min_per_mile"],
            "avg_hr": pick["avg_hr"],
        }
    pace_gap = None
    if best_easy_5 and best_easy_5["pace_min_per_mile"] is not None:
        pace_gap = round(best_easy_5["pace_min_per_mile"] - GOAL_PACE_MAX, 2)

    monthly_runs = _rows(
        conn,
        """
        SELECT
            strftime('%Y-%m', local_date) AS month,
            COUNT(*) AS run_count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS miles
        FROM workouts
        WHERE activity_type = 'HKWorkoutActivityTypeRunning'
          AND distance_m IS NOT NULL
        GROUP BY month
        ORDER BY month
        """,
    )

    daily_recovery = _rows(
        conn,
        """
        SELECT
            local_date,
            resting_hr,
            hrv_sdnn,
            vo2_max,
            ROUND(sleep_total_min / 60.0, 2) AS sleep_hours,
            ROUND(sleep_deep_min / 60.0, 2) AS sleep_deep_hours,
            ROUND(sleep_rem_min / 60.0, 2) AS sleep_rem_hours,
            body_mass_kg
        FROM daily_metrics
        WHERE local_date >= ?
          AND (resting_hr IS NOT NULL OR hrv_sdnn IS NOT NULL
               OR vo2_max IS NOT NULL OR sleep_total_min IS NOT NULL)
        ORDER BY local_date
        """,
        (cutoff,),
    )

    daily_activity = _rows(
        conn,
        """
        SELECT
            dm.local_date,
            dm.steps,
            dm.active_energy_kcal,
            dm.run_count,
            ROUND(dm.run_distance_m / 1609.344, 2) AS run_miles,
            a.exercise_min,
            a.exercise_goal,
            a.stand_hours,
            a.stand_goal,
            a.active_energy_goal
        FROM daily_metrics dm
        LEFT JOIN activity_summaries a ON a.local_date = dm.local_date
        WHERE dm.local_date >= ?
        ORDER BY dm.local_date
        """,
        (cutoff,),
    )

    workout_types = _rows(
        conn,
        """
        SELECT
            activity_type,
            COUNT(*) AS count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS miles,
            ROUND(SUM(duration_sec) / 3600.0, 1) AS hours
        FROM workouts
        GROUP BY activity_type
        ORDER BY count DESC
        """,
    )

    recent_runs = list(reversed(runs[-40:]))
    gap_weeks = [w["week"] for w in consistency if w["is_gap"]]

    config = {
        "zones": [{"name": name, "lo": lo, "hi": hi} for name, lo, hi in HR_ZONES],
        "easy_hr_ceiling": EASY_HR_CEILING,
        "easy_hr_band": {"lo": EASY_HR_BAND[0], "hi": EASY_HR_BAND[1]},
        "quality_avg_hr_min": QUALITY_AVG_HR_MIN,
        "weekly_miles_target": {"min": WEEKLY_MILES_TARGET[0], "max": WEEKLY_MILES_TARGET[1]},
        "goal": {
            "statement": GOAL_STATEMENT,
            "distance_mi": GOAL_DISTANCE_MI,
            "pace_min": GOAL_PACE_MIN,
            "pace_max": GOAL_PACE_MAX,
            "hr_max": GOAL_HR_MAX,
        },
        "cardio": {
            "rolling_weeks": CARDIO_ROLLING_WEEKS,
            "min_samples": CARDIO_MIN_SAMPLES,
            "min_miles": CARDIO_MIN_MILES,
            "min_duration_min": CARDIO_MIN_DURATION_MIN,
            "max_hr_ceiling": CARDIO_MAX_HR_CEILING,
            "easy_hr_ceiling": EASY_HR_CEILING,
            "formula": (
                "Median pace and sec/mi per bpm on runs with avg HR ≤ 145, "
                f"max HR ≤ {CARDIO_MAX_HR_CEILING} (if recorded), "
                f"≥ {CARDIO_MIN_MILES} mi and ≥ {int(CARDIO_MIN_DURATION_MIN)} min. "
                f"Headline needs {CARDIO_MIN_SAMPLES}+ samples in {CARDIO_ROLLING_WEEKS} weeks."
            ),
            "limitations": CARDIO_LIMITATIONS,
        },
        "zone_note": (
            "Zones use workout-average HR (not time-in-zone). "
            "Easy share = avg HR ≤ 145. Quality = avg HR ≥ 148 (Z3+). "
            "Easy aerobic form is stricter (distance, duration, max HR)."
        ),
    }

    return {
        "meta": {
            "generated_at": as_of.isoformat(),
            "chart_days": days,
            "export_date": profile["export_date"] if profile else None,
            "data_start": date_range["start_date"] if date_range else None,
            "data_end": date_range["end_date"] if date_range else data_end.isoformat(),
            "as_of": as_of.isoformat(),
            "last_run_date": last_run_date.isoformat() if last_run_date else None,
        },
        "config": config,
        "overview": {
            "run_count": run_totals["run_count"] if run_totals else 0,
            "total_miles": run_totals["total_miles"] if run_totals else 0,
            "total_hours": run_totals["total_hours"] if run_totals else 0,
            "workout_count": workout_totals["workout_count"] if workout_totals else 0,
            "latest_resting_hr": latest_recovery["resting_hr"] if latest_recovery else None,
            "latest_hrv": latest_recovery["hrv_sdnn"] if latest_recovery else None,
            "latest_vo2": latest_recovery["vo2_max"] if latest_recovery else None,
            "latest_recovery_date": latest_recovery["local_date"] if latest_recovery else None,
            "weekly_miles": weekly_with_runs[-26:],
            "recent_weeks": overview_weeks,
            "progress": {
                "label": progress_label,
                "week": progress_week["week"],
                "week_start": progress_week["week_start"],
                "miles": progress_week["miles"],
                "run_count": progress_week["run_count"],
                "easy_miles": progress_week["easy_miles"],
                "easy_share": progress_week["easy_share"],
                "quality_count": progress_week["quality_count"],
                "target_min": WEEKLY_MILES_TARGET[0],
                "target_max": WEEKLY_MILES_TARGET[1],
                "status": status,
                "status_label": status_label,
                "status_detail": status_detail,
                "last_quality": (
                    {
                        "local_date": last_quality["local_date"],
                        "miles": last_quality["miles"],
                        "pace_min_per_mile": last_quality["pace_min_per_mile"],
                        "avg_hr": last_quality["avg_hr"],
                        "max_hr": last_quality["max_hr"],
                        "zone": last_quality["zone"],
                    }
                    if last_quality
                    else None
                ),
                "rolling_4w_miles": rolling_4w,
                "last_run_date": last_run_date.isoformat() if last_run_date else None,
                "easy_form": cardio_window,
            },
            "goal": {
                "statement": GOAL_STATEMENT,
                "candidates": candidates,
                "best_easy_near_5": best_easy_5,
                "pace_gap_min": pace_gap,
            },
        },
        "running": {
            "weekly": weekly_with_runs,
            "monthly": monthly_runs,
            "recent_runs": recent_runs,
            "scatter": scatter,
            "easy_trend": easy_trend,
            "cardio": {
                "window": cardio_window,
                "weekly": cardio_weekly,
                "formula": (
                    "Median of qualifying easy runs; sec/mi per bpm = pace_sec / avg_hr. "
                    "Lower ratio = more economical. Not Apple VO₂ max."
                ),
                "limitations": CARDIO_LIMITATIONS,
            },
            "zone_weekly": week_rows(weeks_ending(progress_week_start + timedelta(days=6), 16)),
        },
        "volume": {
            "weekly": consistency,
            "monthly": monthly_runs[-18:],
            "gap_weeks": gap_weeks,
            "target_min": WEEKLY_MILES_TARGET[0],
            "target_max": WEEKLY_MILES_TARGET[1],
        },
        "recovery": {
            "daily": daily_recovery,
        },
        "activity": {
            "daily": daily_activity,
        },
        "workouts": {
            "by_type": workout_types,
        },
    }
