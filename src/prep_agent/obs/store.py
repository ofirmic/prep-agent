"""SQLite trace store.

Two tables:
- traces      — one row per high-level run (a `research`, `eval`, etc.)
- llm_calls   — one row per LLM call, linked to its trace

Why SQLite:
- Zero infra. File lives next to the project.
- Two tables, simple schema; outgrowing it means moving to Postgres, not adding
  more SQL tricks.
- The decorator pattern means the rest of the code doesn't know about this file.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class TraceRow:
    trace_id: str
    label: str  # company name, or eval case name
    kind: str   # "research" | "eval_case" | etc.
    started_at: float
    ended_at: float | None
    status: Literal["running", "ok", "error"]
    total_tokens: int
    total_cost_usd: float


@dataclass(frozen=True)
class CallRow:
    call_id: str
    trace_id: str
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    ts: float
    prompt_chars: int
    response_chars: int
    error: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL DEFAULT 'running',
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    ts REAL NOT NULL,
    prompt_chars INTEGER NOT NULL,
    response_chars INTEGER NOT NULL,
    error TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
);

CREATE INDEX IF NOT EXISTS idx_calls_trace ON llm_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at DESC);
"""


class TraceStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def start_trace(self, label: str, kind: str = "research") -> str:
        trace_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO traces (trace_id, label, kind, started_at, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            (trace_id, label, kind, time.time()),
        )
        self._conn.commit()
        return trace_id

    def end_trace(
        self, trace_id: str, status: Literal["ok", "error"] = "ok"
    ) -> None:
        # Recompute totals from llm_calls so the trace row always agrees with
        # its children — bookkeeping by accident is how cost dashboards lie.
        row = self._conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0), "
            "       COALESCE(SUM(cost_usd), 0) "
            "FROM llm_calls WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        total_tokens, total_cost = (row or (0, 0.0))
        self._conn.execute(
            "UPDATE traces SET ended_at = ?, status = ?, "
            "  total_tokens = ?, total_cost_usd = ? "
            "WHERE trace_id = ?",
            (time.time(), status, total_tokens, total_cost, trace_id),
        )
        self._conn.commit()

    def record_call(
        self,
        trace_id: str,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        prompt_chars: int,
        response_chars: int,
        error: str | None = None,
    ) -> str:
        call_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO llm_calls (call_id, trace_id, stage, model, "
            "  input_tokens, output_tokens, cost_usd, latency_ms, ts, "
            "  prompt_chars, response_chars, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call_id,
                trace_id,
                stage,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
                time.time(),
                prompt_chars,
                response_chars,
                error,
            ),
        )
        self._conn.commit()
        return call_id

    def list_traces(self, limit: int = 20) -> list[TraceRow]:
        rows = self._conn.execute(
            "SELECT trace_id, label, kind, started_at, ended_at, status, "
            "       total_tokens, total_cost_usd "
            "FROM traces ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            TraceRow(
                trace_id=r[0],
                label=r[1],
                kind=r[2],
                started_at=r[3],
                ended_at=r[4],
                status=r[5],
                total_tokens=r[6],
                total_cost_usd=r[7],
            )
            for r in rows
        ]

    def get_calls(self, trace_id: str) -> list[CallRow]:
        rows = self._conn.execute(
            "SELECT call_id, trace_id, stage, model, input_tokens, "
            "       output_tokens, cost_usd, latency_ms, ts, prompt_chars, "
            "       response_chars, error "
            "FROM llm_calls WHERE trace_id = ? ORDER BY ts",
            (trace_id,),
        ).fetchall()
        return [
            CallRow(
                call_id=r[0],
                trace_id=r[1],
                stage=r[2],
                model=r[3],
                input_tokens=r[4],
                output_tokens=r[5],
                cost_usd=r[6],
                latency_ms=r[7],
                ts=r[8],
                prompt_chars=r[9],
                response_chars=r[10],
                error=r[11],
            )
            for r in rows
        ]

    def get_trace(self, trace_id: str) -> TraceRow | None:
        row = self._conn.execute(
            "SELECT trace_id, label, kind, started_at, ended_at, status, "
            "       total_tokens, total_cost_usd "
            "FROM traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if row is None:
            return None
        return TraceRow(
            trace_id=row[0],
            label=row[1],
            kind=row[2],
            started_at=row[3],
            ended_at=row[4],
            status=row[5],
            total_tokens=row[6],
            total_cost_usd=row[7],
        )
