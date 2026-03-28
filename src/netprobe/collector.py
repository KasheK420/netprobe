"""SQLite storage for measurement data."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

DB_DIR = Path.home() / ".netprobe"
DB_PATH = DB_DIR / "netprobe.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time REAL NOT NULL,
    end_time REAL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    target_name TEXT NOT NULL,
    target_ip TEXT NOT NULL,
    rtt_ms REAL,
    is_lost INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_measurements_session
    ON measurements(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_measurements_target
    ON measurements(session_id, target_name);
"""


@dataclass
class Measurement:
    timestamp: float
    target_name: str
    target_ip: str
    rtt_ms: float | None
    is_lost: bool


class Collector:
    def __init__(self, db_path: Path = DB_PATH):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._lock = Lock()
        self._session_id: int | None = None

    def start_session(self, note: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (start_time, note) VALUES (?, ?)",
                (time.time(), note),
            )
            self._conn.commit()
            self._session_id = cur.lastrowid
            return self._session_id

    def end_session(self) -> None:
        if self._session_id is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET end_time = ? WHERE id = ?",
                (time.time(), self._session_id),
            )
            self._conn.commit()

    def record(self, m: Measurement) -> None:
        if self._session_id is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO measurements (session_id, timestamp, target_name, target_ip, rtt_ms, is_lost) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self._session_id, m.timestamp, m.target_name, m.target_ip, m.rtt_ms, int(m.is_lost)),
            )
            self._conn.commit()

    def get_sessions(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT s.id, s.start_time, s.end_time, s.note, "
            "COUNT(m.id) as measurement_count "
            "FROM sessions s LEFT JOIN measurements m ON s.id = m.session_id "
            "GROUP BY s.id ORDER BY s.start_time DESC"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_measurements(self, session_id: int) -> list[Measurement]:
        cur = self._conn.execute(
            "SELECT timestamp, target_name, target_ip, rtt_ms, is_lost "
            "FROM measurements WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [
            Measurement(
                timestamp=row["timestamp"],
                target_name=row["target_name"],
                target_ip=row["target_ip"],
                rtt_ms=row["rtt_ms"],
                is_lost=bool(row["is_lost"]),
            )
            for row in cur.fetchall()
        ]

    def get_session(self, session_id: int) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self._conn.close()
