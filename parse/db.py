"""Database helpers."""

import sqlite3
from pathlib import Path

from parse.config import DB_PATH, REPO_ROOT


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection, fresh: bool = False) -> None:
    schema_path = REPO_ROOT / "schema" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    if fresh:
        conn.execute("PRAGMA foreign_keys = OFF")
        objects = conn.execute(
            """
            SELECT name, type FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY CASE type WHEN 'view' THEN 0 ELSE 1 END
            """
        ).fetchall()
        for row in objects:
            conn.execute(f"DROP {row['type'].upper()} IF EXISTS [{row['name']}]")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(schema_sql)
    conn.commit()


def get_or_create_source(conn: sqlite3.Connection, name: str, version: str | None) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, version) VALUES (?, ?)",
        (name, version),
    )
    row = conn.execute(
        "SELECT id FROM sources WHERE name = ? AND version IS ?",
        (name, version),
    ).fetchone()
    return row["id"]
