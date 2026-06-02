"""Export compact training summaries for LLM coaching review."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from parse.config import SUMMARIES_DIR


def _meters_to_miles(m: float | None) -> float | None:
    return round(m / 1609.344, 2) if m else None


def _sec_to_pace(sec_per_meter: float | None) -> str | None:
    if not sec_per_meter or sec_per_meter <= 0:
        return None
    sec_per_mile = sec_per_meter * 1609.344
    minutes = int(sec_per_mile // 60)
    seconds = int(sec_per_mile % 60)
    return f"{minutes}:{seconds:02d}"


def export_summary(
    conn: sqlite3.Connection,
    weeks: int = 4,
    output_dir: Path = SUMMARIES_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    end = date.today()
    start = end - timedelta(weeks=weeks)
    start_str = start.isoformat()

    runs = conn.execute(
        """
        SELECT w.local_date, w.duration_sec, w.distance_m, w.start_at,
               ws.avg_value AS avg_hr
        FROM workouts w
        LEFT JOIN workout_statistics ws
          ON ws.workout_id = w.id
         AND ws.stat_type = 'HKQuantityTypeIdentifierHeartRate'
        WHERE w.activity_type = 'HKWorkoutActivityTypeRunning'
          AND w.local_date >= ?
        ORDER BY w.start_at
        """,
        (start_str,),
    ).fetchall()

    weekly = conn.execute(
        """
        SELECT week, run_count, run_distance_m, run_duration_sec
        FROM v_weekly_training
        WHERE week >= strftime('%Y-W%W', ?)
        ORDER BY week
        """,
        (start_str,),
    ).fetchall()

    daily = conn.execute(
        """
        SELECT local_date, resting_hr, hrv_sdnn, vo2_max,
               sleep_total_min, run_distance_m, steps
        FROM daily_metrics
        WHERE local_date >= ?
        ORDER BY local_date
        """,
        (start_str,),
    ).fetchall()

    def trend(values: list[float | None]) -> str | None:
        clean = [v for v in values if v is not None]
        if len(clean) < 2:
            return None
        return f"{clean[0]:.1f} → {clean[-1]:.1f}"

    resting = [r["resting_hr"] for r in daily]
    hrv = [r["hrv_sdnn"] for r in daily]
    vo2 = [r["vo2_max"] for r in daily]
    sleep = [r["sleep_total_min"] for r in daily if r["sleep_total_min"]]

    total_run_m = sum(r["distance_m"] or 0 for r in runs)
    total_run_sec = sum(r["duration_sec"] or 0 for r in runs)
    avg_hr_values = [r["avg_hr"] for r in runs if r["avg_hr"]]

    summary = {
        "period": {"start": start_str, "end": end.isoformat(), "weeks": weeks},
        "runs": {
            "count": len(runs),
            "total_miles": _meters_to_miles(total_run_m),
            "avg_pace_per_mile": _sec_to_pace(
                total_run_sec / total_run_m if total_run_m else None
            ),
            "avg_hr": round(sum(avg_hr_values) / len(avg_hr_values), 1)
            if avg_hr_values
            else None,
        },
        "trends": {
            "resting_hr": trend(resting),
            "hrv_sdnn": trend(hrv),
            "vo2_max": trend(vo2),
            "sleep_hours_avg": round(sum(sleep) / len(sleep) / 60, 1) if sleep else None,
        },
        "weekly": [
            {
                "week": w["week"],
                "runs": w["run_count"],
                "miles": _meters_to_miles(w["run_distance_m"]),
            }
            for w in weekly
        ],
        "recent_runs": [
            {
                "date": r["local_date"],
                "miles": _meters_to_miles(r["distance_m"]),
                "duration_min": round((r["duration_sec"] or 0) / 60, 1),
                "avg_hr": r["avg_hr"],
            }
            for r in runs[-10:]
        ],
    }

    out_path = output_dir / f"training_summary_{end.isoformat()}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out_path
