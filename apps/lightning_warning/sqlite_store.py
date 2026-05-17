import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lightning_warning_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            response_time TEXT NOT NULL,
            device_id INTEGER NOT NULL,
            warning_type INTEGER NOT NULL,
            max_val INTEGER NOT NULL,
            min_val INTEGER NOT NULL,
            avg_val INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def save_lightning_warning_rows(
    sqlite_db_path: Path,
    endpoint: str,
    start_time: str,
    end_time: str,
    response_time: str,
    warning_rows: List[Dict[str, Any]],
) -> int:
    if not warning_rows:
        return 0

    sqlite_db_path = Path(sqlite_db_path)
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [
        (
            endpoint,
            str(start_time),
            str(end_time),
            str(response_time),
            int(row.get("device_id", 0)),
            int(row.get("type", 0)),
            int(row.get("max_val", 0)),
            int(row.get("min_val", 0)),
            int(row.get("avg_val", 0)),
            created_at,
        )
        for row in warning_rows
    ]

    with sqlite3.connect(str(sqlite_db_path)) as conn:
        _ensure_table(conn)
        conn.executemany(
            """
            INSERT INTO lightning_warning_result (
                endpoint, start_time, end_time, response_time,
                device_id, warning_type, max_val, min_val, avg_val, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        conn.commit()
    return len(values)
