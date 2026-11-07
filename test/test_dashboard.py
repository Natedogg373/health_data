#!/usr/bin/env python3
"""Unit tests for training-progress dashboard queries."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dashboard.queries import (  # noqa: E402
    assign_zone,
    classify_week_status,
    fetch_dashboard_data,
    goal_score,
    is_easy,
    is_quality,
    qualifies_easy_aerobic,
    sec_per_mile_per_bpm,
)
from dashboard.training_config import (  # noqa: E402
    CARDIO_MAX_HR_CEILING,
    CARDIO_MIN_SAMPLES,
    EASY_HR_CEILING,
    GOAL_PACE_MAX,
    QUALITY_AVG_HR_MIN,
)
from parse.db import init_schema  # noqa: E402

AS_OF = date(2026, 11, 6)  # Friday
METERS = 1609.344


def _run(
    conn: sqlite3.Connection,
    wid: str,
    day: date,
    miles: float,
    pace: float,
    avg_hr: float | None,
    max_hr: float | None = None,
) -> None:
    distance_m = miles * METERS
    duration_sec = pace * miles * 60
    start = f"{day.isoformat()}T12:00:00+00:00"
    end = f"{day.isoformat()}T13:00:00+00:00"
    conn.execute(
        """
        INSERT INTO workouts (
            id, activity_type, start_at, end_at, start_date_local, local_date,
            duration_sec, distance_m, energy_kcal, source_id, device, route_file, creation_date
        ) VALUES (?, 'HKWorkoutActivityTypeRunning', ?, ?, ?, ?, ?, ?, ?, 1, 'Watch', NULL, ?)
        """,
        (wid, start, end, f"{day.isoformat()} 07:00:00 -0500", day.isoformat(),
         duration_sec, distance_m, miles * 110, start),
    )
    if avg_hr is not None:
        conn.execute(
            """
            INSERT INTO workout_statistics (
                workout_id, stat_type, avg_value, max_value, unit
            ) VALUES (?, 'HKQuantityTypeIdentifierHeartRate', ?, ?, 'count/min')
            """,
            (wid, avg_hr, max_hr or avg_hr + 12),
        )


def build_plan_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn, fresh=True)
    conn.execute(
        """
        INSERT INTO user_profile (id, date_of_birth, biological_sex, export_date)
        VALUES (1, '1990-05-01', 'HKBiologicalSexMale', '2026-11-06 12:00:00 -0500')
        """
    )
    conn.execute("INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0')")

    # W40 (Sep 28–Oct 4): on-track easy volume
    _run(conn, "w40a", date(2026, 9, 28), 4.0, 10.4, 140)
    _run(conn, "w40b", date(2026, 9, 30), 4.0, 10.3, 138)
    _run(conn, "w40c", date(2026, 10, 2), 5.0, 9.4, 159, 174)  # Friday quality
    _run(conn, "w40d", date(2026, 10, 3), 4.0, 10.5, 141)
    # W41: similar
    _run(conn, "w41a", date(2026, 10, 5), 5.05, 10.15, 144)  # best easy ~5 mi, still ~0:45 off 9:30
    _run(conn, "w41b", date(2026, 10, 7), 3.5, 10.2, 139)
    _run(conn, "w41c", date(2026, 10, 9), 4.5, 9.15, 158, 172)
    _run(conn, "w41d", date(2026, 10, 10), 4.0, 10.4, 142)
    # W42: light
    _run(conn, "w42a", date(2026, 10, 12), 3.0, 10.6, 140)
    _run(conn, "w42b", date(2026, 10, 14), 4.0, 10.5, 143)
    # W43: GAP — no runs
    # W44: too hard (several quality / high HR)
    _run(conn, "w44a", date(2026, 10, 26), 4.0, 9.1, 162, 178)
    _run(conn, "w44b", date(2026, 10, 28), 4.0, 9.0, 165, 180)
    _run(conn, "w44c", date(2026, 10, 30), 5.0, 8.9, 168, 182)
    _run(conn, "w44d", date(2026, 10, 31), 4.0, 9.2, 160, 176)
    # W45 (Nov 2–8, as_of Friday): on-track-ish, one quality
    _run(conn, "w45a", date(2026, 11, 2), 4.0, 10.4, 141)
    _run(conn, "w45b", date(2026, 11, 4), 3.5, 10.3, 139)
    _run(conn, "w45c", date(2026, 11, 5), 3.0, 10.5, 142)
    _run(conn, "w45d", date(2026, 11, 6), 5.0, 9.08, 159, 174)

    for i in range(0, 45):
        day = date(2026, 9, 28) + timedelta(days=i)
        if day > AS_OF:
            break
        conn.execute(
            """
            INSERT INTO daily_metrics (local_date, resting_hr, hrv_sdnn, vo2_max, sleep_total_min, steps)
            VALUES (?, 48, 70, 47.8, 450, 9000)
            """,
            (day.isoformat(),),
        )
    conn.commit()
    return conn


class ZoneHelpersTest(unittest.TestCase):
    def test_assign_zone_bands(self):
        self.assertEqual(assign_zone(125), "Z1")
        self.assertEqual(assign_zone(140), "Z2")
        self.assertEqual(assign_zone(145), "Z2")
        self.assertEqual(assign_zone(148), "Z3")
        self.assertEqual(assign_zone(170), "Z4")
        self.assertEqual(assign_zone(180), "Z5")
        self.assertEqual(assign_zone(110), "Z1")
        self.assertEqual(assign_zone(200), "Z5")
        self.assertIsNone(assign_zone(None))

    def test_easy_vs_quality(self):
        self.assertTrue(is_easy(EASY_HR_CEILING))
        self.assertFalse(is_easy(EASY_HR_CEILING + 1))
        self.assertTrue(is_quality(QUALITY_AVG_HR_MIN))
        self.assertFalse(is_quality(QUALITY_AVG_HR_MIN - 1))

    def test_sec_per_mile_per_bpm(self):
        # 10:00/mi at 140 bpm → 600/140 = 4.286 s/mi/bpm
        ten = sec_per_mile_per_bpm(10.0, 140)
        nine = sec_per_mile_per_bpm(9.25, 140)
        self.assertAlmostEqual(ten, 600 / 140, places=3)
        self.assertLess(nine, ten)
        self.assertIsNone(sec_per_mile_per_bpm(10.0, None))
        self.assertIsNone(sec_per_mile_per_bpm(None, 140))

    def test_qualifying_easy_aerobic_filters(self):
        self.assertTrue(qualifies_easy_aerobic(4.0, 40, 141, 152, 10.2))
        self.assertFalse(qualifies_easy_aerobic(1.5, 16, 140, 148, 10.5))  # short
        self.assertFalse(qualifies_easy_aerobic(5.0, 45, 159, 174, 9.05))  # 4x4-ish
        self.assertFalse(qualifies_easy_aerobic(4.75, 40, 141, 179, 8.5))  # avg easy, max not
        self.assertFalse(qualifies_easy_aerobic(4.0, 40, None, 150, 10.2))  # no HR
        self.assertTrue(qualifies_easy_aerobic(4.0, 40, 141, None, 10.2))  # missing max is ok
        self.assertFalse(qualifies_easy_aerobic(4.0, 40, 141, CARDIO_MAX_HR_CEILING + 1, 10.2))

    def test_goal_score_prefers_easy_five_at_goal_pace(self):
        hit = goal_score(5.0, 9.25, 144)
        miss_hr = goal_score(5.0, 9.25, 160)
        miss_pace = goal_score(5.0, 11.0, 140)
        self.assertGreater(hit, miss_hr)
        self.assertGreater(hit, miss_pace)
        self.assertGreater(hit, 85)
        self.assertIsNone(goal_score(5.0, 9.25, None))

    def test_status_codes(self):
        code, label, _ = classify_week_status(16.5, 0.72, 1, 5)
        self.assertEqual(code, "on_track")
        code, _, _ = classify_week_status(8.0, 0.9, 0, 7)
        self.assertEqual(code, "light")
        code, _, _ = classify_week_status(17.0, 0.3, 3, 7)
        self.assertEqual(code, "too_hard")
        code, _, _ = classify_week_status(0, None, 0, 5)
        self.assertEqual(code, "gap")


class DashboardPayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = build_plan_db()
        cls.data = fetch_dashboard_data(cls.conn, days=365, today=AS_OF)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_progress_this_week(self):
        p = self.data["overview"]["progress"]
        self.assertEqual(p["label"], "This week")
        self.assertEqual(p["week"], "2026-W45")
        self.assertAlmostEqual(p["miles"], 15.5, places=1)
        self.assertEqual(p["quality_count"], 1)
        self.assertGreater(p["easy_share"], 0.6)
        self.assertEqual(p["status"], "on_track")
        self.assertIsNotNone(p["last_quality"])
        self.assertEqual(p["last_quality"]["local_date"], "2026-11-06")

    def test_gap_week_in_consistency(self):
        weeks = {w["week"]: w for w in self.data["volume"]["weekly"]}
        self.assertIn("2026-W43", weeks)
        self.assertTrue(weeks["2026-W43"]["is_gap"])
        self.assertIn("2026-W43", self.data["volume"]["gap_weeks"])

    def test_too_hard_week_zone_mix(self):
        zw = {w["week"]: w for w in self.data["running"]["zone_weekly"]}
        hard = zw["2026-W44"]
        self.assertGreater(hard["zones"]["Z3"] + hard["zones"]["Z4"], hard["zones"]["Z2"])
        self.assertGreaterEqual(hard["quality_count"], 3)

    def test_goal_candidate_includes_easy_five(self):
        dates = [c["local_date"] for c in self.data["overview"]["goal"]["candidates"]]
        self.assertIn("2026-10-05", dates)
        best = self.data["overview"]["goal"]["best_easy_near_5"]
        self.assertEqual(best["local_date"], "2026-10-05")
        self.assertLessEqual(best["avg_hr"], EASY_HR_CEILING)
        self.assertAlmostEqual(best["pace_min_per_mile"], 10.15, places=2)
        self.assertGreater(self.data["overview"]["goal"]["pace_gap_min"], 0)

    def test_scatter_and_cardio_form(self):
        scatter = self.data["running"]["scatter"]
        self.assertTrue(any(p["zone"] == "Z2" for p in scatter))
        self.assertTrue(any(p["quality"] for p in scatter))
        cardio = self.data["running"]["cardio"]
        self.assertEqual(cardio["window"]["status"], "ok")
        self.assertGreaterEqual(cardio["window"]["n"], CARDIO_MIN_SAMPLES)
        self.assertIsNotNone(cardio["window"]["median_pace"])
        self.assertIsNotNone(cardio["window"]["median_sec_per_mi_per_bpm"])
        self.assertTrue(any(w["median_pace"] for w in cardio["weekly"]))
        # Interval / high-HR day must not be a cardio sample.
        recent = {r["local_date"]: r for r in self.data["running"]["recent_runs"]}
        self.assertFalse(recent["2026-11-06"]["cardio_sample"])
        self.assertTrue(recent["2026-11-02"]["cardio_sample"])
        easy = self.data["running"]["easy_trend"]
        self.assertTrue(all(130 <= r["avg_hr"] <= 148 for r in easy))
        self.assertNotIn("vo2", cardio["formula"].lower())
        self.assertIn("apple vo", cardio["limitations"].lower().replace("₂", "2"))
        self.assertIn("not this score", cardio["limitations"].lower())
        self.assertIsNone(self.data["overview"]["progress"]["easy_form"].get("vo2"))

    def test_config_embedded(self):
        cfg = self.data["config"]
        self.assertEqual(cfg["easy_hr_ceiling"], 145)
        names = [z["name"] for z in cfg["zones"]]
        self.assertEqual(names, ["Z1", "Z2", "Z3", "Z4", "Z5"])
        self.assertEqual(cfg["goal"]["pace_max"], GOAL_PACE_MAX)
        self.assertEqual(cfg["cardio"]["min_samples"], CARDIO_MIN_SAMPLES)

    def test_sparse_cardio_has_no_headline(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_schema(conn, fresh=True)
        conn.execute(
            """INSERT INTO user_profile (id, date_of_birth, biological_sex, export_date)
               VALUES (1, '1990-05-01', 'HKBiologicalSexMale', '2026-11-06 12:00:00 -0500')"""
        )
        conn.execute("INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0')")
        _run(conn, "only1", date(2026, 11, 2), 4.0, 10.4, 141, 150)
        _run(conn, "only2", date(2026, 11, 4), 3.5, 10.3, 139, 149)
        conn.commit()
        data = fetch_dashboard_data(conn, days=365, today=AS_OF)
        window = data["running"]["cardio"]["window"]
        self.assertEqual(window["n"], 2)
        self.assertEqual(window["status"], "sparse")
        self.assertIsNone(window["median_pace"])
        self.assertIsNone(window["median_sec_per_mi_per_bpm"])
        conn.close()

    def test_tiny_seed_does_not_crash(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_schema(conn, fresh=True)
        seed = (REPO / "test" / "fixtures" / "seed.sql").read_text(encoding="utf-8")
        conn.executescript(seed)
        data = fetch_dashboard_data(conn, days=365, today=date(2026, 1, 15))
        self.assertGreaterEqual(data["overview"]["run_count"], 2)
        self.assertIn("progress", data["overview"])
        self.assertTrue(data["running"]["recent_runs"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
