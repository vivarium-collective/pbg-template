"""SQLite-backed persistence for Composite Explorer runs.

Owns `.pbg/composite-runs.db`. Bootstraps the `runs_meta` table (run-level
metadata) alongside the `history` table that `process_bigraph.emitter.SQLiteEmitter`
owns (per-step state rows, partitioned by `simulation_id`).

A run's `simulation_id` and our `run_id` are the same string by convention:
    `<spec_id>__<unix-epoch-int>__<6-hex-chars>`
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path


_SCHEMA_RUNS_META = """
CREATE TABLE IF NOT EXISTS runs_meta (
    run_id        TEXT PRIMARY KEY,
    spec_id       TEXT NOT NULL,
    label         TEXT,
    params_json   TEXT,
    started_at    REAL NOT NULL,
    completed_at  REAL,
    n_steps       INTEGER,
    status        TEXT NOT NULL
);
"""

_INDEX_RUNS_META = """
CREATE INDEX IF NOT EXISTS idx_runs_meta_spec ON runs_meta(spec_id);
"""


def connect(db_file: str | Path) -> sqlite3.Connection:
    """Open the runs DB and ensure the metadata schema exists."""
    db_file = Path(db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA_RUNS_META)
    conn.execute(_INDEX_RUNS_META)
    conn.commit()
    return conn


def generate_run_id(spec_id: str, params: dict | None = None,
                    now: float | None = None) -> str:
    """Build a deterministic-shape run id: `<spec_id>__<ts>__<hash6>`."""
    ts = int(now if now is not None else time.time())
    payload = json.dumps({"spec_id": spec_id, "params": params or {},
                          "ts": ts}, sort_keys=True)
    short = hashlib.sha1(payload.encode()).hexdigest()[:6]
    return f"{spec_id}__{ts}__{short}"


def save_metadata(conn: sqlite3.Connection, *, spec_id: str, run_id: str,
                  params: dict | None, label: str, started_at: float) -> None:
    """Insert a new run row with status='running'."""
    conn.execute(
        "INSERT INTO runs_meta "
        "(run_id, spec_id, label, params_json, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, spec_id, label, json.dumps(params or {}),
         started_at, "running"),
    )
    conn.commit()


def complete_metadata(conn: sqlite3.Connection, *, run_id: str,
                      n_steps: int, status: str) -> None:
    """Mark an existing run as completed (or failed)."""
    conn.execute(
        "UPDATE runs_meta "
        "SET completed_at=?, n_steps=?, status=? WHERE run_id=?",
        (time.time(), n_steps, status, run_id),
    )
    conn.commit()


def query_runs(conn: sqlite3.Connection, *, spec_id: str) -> list[dict]:
    """List runs for one spec_id, newest first."""
    rows = conn.execute(
        "SELECT run_id, spec_id, label, params_json, started_at, "
        "completed_at, n_steps, status FROM runs_meta "
        "WHERE spec_id=? ORDER BY started_at DESC",
        (spec_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d.pop("params_json") or "{}")
        except json.JSONDecodeError:
            d["params"] = {}
        out.append(d)
    return out


def query_run(conn: sqlite3.Connection, *, run_id: str) -> list[dict]:
    """Return the trajectory `[{step, time, state}, ...]` for one run.

    Reads from the `history` table owned by process_bigraph.emitter.SQLiteEmitter.
    If that table doesn't exist yet (no SQLiteEmitter has ever written to this
    DB), returns an empty list.
    """
    has_history = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
    ).fetchone()
    if not has_history:
        return []
    rows = conn.execute(
        "SELECT step, time, state FROM history WHERE simulation_id=? "
        "ORDER BY step ASC",
        (run_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["state"] = json.loads(d["state"]) if d["state"] else {}
        except json.JSONDecodeError:
            d["state"] = {}
        out.append(d)
    return out


def query_run_state(conn: sqlite3.Connection, *, run_id: str,
                    step: int) -> dict | None:
    """Return the single state dict at one step, or None if missing."""
    has_history = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
    ).fetchone()
    if not has_history:
        return None
    row = conn.execute(
        "SELECT state FROM history WHERE simulation_id=? AND step=?",
        (run_id, step),
    ).fetchone()
    if not row or not row["state"]:
        return None
    try:
        return json.loads(row["state"])
    except json.JSONDecodeError:
        return None
