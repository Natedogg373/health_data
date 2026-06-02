#!/usr/bin/env python3
"""Import Apple Health export into SQLite and build training summaries."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python run.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse.build_daily import build_daily_metrics
from parse.config import DB_PATH, EXPORT_XML
from parse.db import get_connection
from parse.export_summary import export_summary
from parse.parse_export import run_parse
from parse.parse_routes import parse_routes


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Apple Health export into training.db")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Drop and recreate all tables before import",
    )
    parser.add_argument(
        "--skip-routes",
        action="store_true",
        help="Skip GPX route parsing (faster)",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=4,
        help="Weeks of history for summary export (default: 4)",
    )
    args = parser.parse_args()

    if not EXPORT_XML.exists():
        print(f"Error: export.xml not found at {EXPORT_XML}")
        return 1

    print(f"Export: {EXPORT_XML}")
    print(f"Database: {DB_PATH}")

    conn = get_connection()
    started = datetime.now(timezone.utc).isoformat()

    from parse.db import init_schema
    init_schema(conn, fresh=args.fresh)

    cur = conn.execute(
        "INSERT INTO import_runs (started_at, export_xml_path) VALUES (?, ?)",
        (started, str(EXPORT_XML)),
    )
    run_id = cur.lastrowid
    conn.commit()

    print("\n[1/4] Parsing export.xml (streaming)...")
    counts = run_parse(conn, fresh=args.fresh)
    print(f"  Workouts: {counts['workouts']:,}")
    print(f"  Records processed: {counts['records']:,}")
    print(f"  Activity summaries: {counts['activity_summaries']:,}")

    if not args.skip_routes:
        print("\n[2/4] Parsing GPX routes...")
        route_count = parse_routes(conn)
        linked = conn.execute(
            "SELECT COUNT(*) FROM routes WHERE workout_id IS NOT NULL"
        ).fetchone()[0]
        print(f"  Routes: {route_count:,} ({linked:,} linked to workouts)")
    else:
        print("\n[2/4] Skipping GPX routes")

    print("\n[3/4] Building daily metrics...")
    day_count = build_daily_metrics(conn)
    print(f"  Daily metric rows: {day_count:,}")

    print("\n[4/4] Exporting training summary...")
    summary_path = export_summary(conn, weeks=args.weeks)
    print(f"  Summary: {summary_path}")

    conn.execute(
        """
        UPDATE import_runs SET
            finished_at = ?,
            records_parsed = ?,
            workouts_parsed = ?
        WHERE id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), counts["records"], counts["workouts"], run_id),
    )
    conn.commit()
    conn.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
