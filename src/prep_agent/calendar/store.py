"""Processed-events store.

Lives in the same SQLite file as the trace store. One file is simpler than
two for a personal tool, and they don't share tables. The table is purely
"don't re-prep this event" bookkeeping.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessedEventRow:
    event_id: str
    summary: str
    start_iso: str
    company: str | None
    confidence: float
    prep_path: str | None
    trace_id: str | None
    processed_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_calendar_events (
    event_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    start_iso TEXT NOT NULL,
    company TEXT,
    confidence REAL NOT NULL,
    prep_path TEXT,
    trace_id TEXT,
    processed_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_at
    ON processed_calendar_events(processed_at DESC);
"""


class CalendarStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def is_processed(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_calendar_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return row is not None

    def record(
        self,
        event_id: str,
        summary: str,
        start_iso: str,
        company: str | None,
        confidence: float,
        prep_path: str | None,
        trace_id: str | None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO processed_calendar_events "
            "  (event_id, summary, start_iso, company, confidence, prep_path, "
            "   trace_id, processed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                summary,
                start_iso,
                company,
                confidence,
                prep_path,
                trace_id,
                time.time(),
            ),
        )
        self._conn.commit()

    def list_recent(self, limit: int = 20) -> list[ProcessedEventRow]:
        rows = self._conn.execute(
            "SELECT event_id, summary, start_iso, company, confidence, "
            "       prep_path, trace_id, processed_at "
            "FROM processed_calendar_events "
            "ORDER BY processed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ProcessedEventRow(
                event_id=r[0],
                summary=r[1],
                start_iso=r[2],
                company=r[3],
                confidence=r[4],
                prep_path=r[5],
                trace_id=r[6],
                processed_at=r[7],
            )
            for r in rows
        ]
