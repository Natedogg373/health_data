#!/usr/bin/env python3
"""Build static index.html for GitHub Pages from training.db."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dashboard.queries import fetch_dashboard_data  # noqa: E402
from parse.config import DB_PATH  # noqa: E402
from parse.db import get_connection  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "index.html"
TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"


def build_html(data: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"))
    return template.replace("__DASHBOARD_DATA__", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static training dashboard")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Days of daily charts to include (default: 365)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output HTML path (default: repo root index.html)",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Error: database not found at {DB_PATH}")
        print("Run `python run.py` first to import Apple Health data.")
        return 1

    conn = get_connection()
    try:
        data = fetch_dashboard_data(conn, days=args.days)
    finally:
        conn.close()

    data["meta"]["built_at"] = datetime.now(timezone.utc).isoformat()
    html = build_html(data)
    args.output.write_text(html, encoding="utf-8")
    print(f"Wrote {args.output} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
