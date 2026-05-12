"""Unit tests for scripts._lib.composite_runs."""
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_PARENT = Path(__file__).parent.parent
if str(_SCRIPTS_PARENT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_PARENT))

from scripts._lib.composite_runs import (
    connect, save_metadata, complete_metadata, query_runs, query_run,
)


def test_schema_bootstrap(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "runs_meta" in tables


def test_save_and_query_metadata(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(
        conn,
        spec_id="pkg.composites.demo",
        run_id="pkg.composites.demo__1715470512__abc123",
        params={"rate": 0.5},
        label="rate=0.5",
        started_at=1715470512.0,
    )
    runs = query_runs(conn, spec_id="pkg.composites.demo")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "pkg.composites.demo__1715470512__abc123"
    assert runs[0]["label"] == "rate=0.5"
    assert runs[0]["status"] == "running"


def test_complete_metadata_updates_status(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="s", run_id="r1", params={}, label="",
                  started_at=0.0)
    complete_metadata(conn, run_id="r1", n_steps=10, status="completed")
    runs = query_runs(conn, spec_id="s")
    assert runs[0]["status"] == "completed"
    assert runs[0]["n_steps"] == 10
    assert runs[0]["completed_at"] is not None


def test_query_runs_filtered_by_spec_id(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="A", run_id="r1", params={}, label="",
                  started_at=1.0)
    save_metadata(conn, spec_id="B", run_id="r2", params={}, label="",
                  started_at=2.0)
    save_metadata(conn, spec_id="A", run_id="r3", params={}, label="",
                  started_at=3.0)
    runs_a = query_runs(conn, spec_id="A")
    assert sorted(r["run_id"] for r in runs_a) == ["r1", "r3"]


def test_query_runs_returns_newest_first(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="A", run_id="r_old", params={}, label="",
                  started_at=1.0)
    save_metadata(conn, spec_id="A", run_id="r_new", params={}, label="",
                  started_at=10.0)
    runs = query_runs(conn, spec_id="A")
    assert runs[0]["run_id"] == "r_new"


def test_query_run_returns_empty_when_no_history(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    # No SQLiteEmitter ran against this DB yet → history table empty.
    save_metadata(conn, spec_id="s", run_id="r1", params={}, label="",
                  started_at=0.0)
    trajectory = query_run(conn, run_id="r1")
    assert trajectory == []
