"""Unit tests for scripts._lib.investigations."""
import sys
from pathlib import Path

import pytest

_SCRIPTS_PARENT = Path(__file__).parent.parent
if str(_SCRIPTS_PARENT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_PARENT))

from scripts._lib.investigations import (
    load_spec, expand_simulations, InvestigationSpecError,
)


def _write_spec(tmp_path, text):
    p = tmp_path / "spec.yaml"
    p.write_text(text)
    return p


def test_load_spec_valid(tmp_path):
    p = _write_spec(tmp_path, """
name: minimal
composite: pkg.composites.demo
simulations:
  - name: single
    kind: single
    overrides: {rate: 1.0}
    steps: 5
observables: [level]
""")
    spec = load_spec(p)
    assert spec["name"] == "minimal"
    assert spec["composite"] == "pkg.composites.demo"
    assert len(spec["simulations"]) == 1


def test_load_spec_missing_name(tmp_path):
    p = _write_spec(tmp_path, """
composite: pkg.x
simulations: []
observables: []
""")
    with pytest.raises(InvestigationSpecError, match="name"):
        load_spec(p)


def test_load_spec_missing_composite(tmp_path):
    p = _write_spec(tmp_path, """
name: x
simulations: []
observables: []
""")
    with pytest.raises(InvestigationSpecError, match="composite"):
        load_spec(p)


def test_load_spec_bad_simulation_kind(tmp_path):
    p = _write_spec(tmp_path, """
name: x
composite: pkg.x
simulations:
  - {name: s, kind: bogus, steps: 1}
observables: [a]
""")
    with pytest.raises(InvestigationSpecError, match="kind"):
        load_spec(p)


def test_load_spec_seeds_zero(tmp_path):
    p = _write_spec(tmp_path, """
name: x
composite: pkg.x
simulations:
  - {name: s, kind: seeds, n_seeds: 0, steps: 1, base_overrides: {}}
observables: [a]
""")
    with pytest.raises(InvestigationSpecError, match="n_seeds"):
        load_spec(p)


def test_expand_simulations_single():
    spec = {"simulations": [
        {"name": "s1", "kind": "single",
         "overrides": {"rate": 1.0}, "steps": 5},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 1
    assert runs[0]["sim_name"] == "s1"
    assert runs[0]["overrides"] == {"rate": 1.0}
    assert runs[0]["steps"] == 5
    assert "run_label" in runs[0]


def test_expand_simulations_sweep_1d():
    spec = {"simulations": [
        {"name": "sw", "kind": "sweep",
         "sweep_over": {"rate": [0.1, 0.5, 1.0]},
         "base_overrides": {"unbinding": 0.01},
         "steps": 10},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 3
    assert all(r["sim_name"] == "sw" for r in runs)
    rates = sorted(r["overrides"]["rate"] for r in runs)
    assert rates == [0.1, 0.5, 1.0]
    assert all(r["overrides"]["unbinding"] == 0.01 for r in runs)


def test_expand_simulations_sweep_2d():
    spec = {"simulations": [
        {"name": "grid", "kind": "sweep",
         "sweep_over": {"a": [1, 2], "b": [10, 20, 30]},
         "base_overrides": {}, "steps": 1},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 6  # 2 × 3


def test_expand_simulations_seeds():
    spec = {"simulations": [
        {"name": "rep", "kind": "seeds",
         "n_seeds": 5, "base_overrides": {"rate": 0.1}, "steps": 4},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 5
    seeds = sorted(r["overrides"]["seed"] for r in runs)
    assert seeds == [0, 1, 2, 3, 4]
    assert all(r["overrides"]["rate"] == 0.1 for r in runs)


def test_expand_simulations_mixed():
    spec = {"simulations": [
        {"name": "a", "kind": "single", "overrides": {}, "steps": 1},
        {"name": "b", "kind": "sweep", "sweep_over": {"x": [1, 2]},
         "base_overrides": {}, "steps": 1},
        {"name": "c", "kind": "seeds", "n_seeds": 3,
         "base_overrides": {}, "steps": 1},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 1 + 2 + 3
    names = {r["sim_name"] for r in runs}
    assert names == {"a", "b", "c"}


import json
import sqlite3

from scripts._lib.investigations import gather_results, load_overlays


def _setup_runs_db(tmp_path):
    """Create a minimal runs.db matching the SQLiteEmitter + runs_meta shape."""
    db = tmp_path / "runs.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE runs_meta (
            run_id TEXT PRIMARY KEY, spec_id TEXT, sim_name TEXT,
            label TEXT, params_json TEXT, started_at REAL,
            completed_at REAL, n_steps INTEGER, status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulation_id TEXT, step INTEGER, global_time REAL, state TEXT
        )
    """)
    # one sim "single" with one run, three step rows
    conn.execute(
        "INSERT INTO runs_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("r1", "spec", "single", "single", json.dumps({"rate": 1.0}),
         0.0, 1.0, 3, "completed"),
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO history (simulation_id, step, global_time, state) VALUES (?, ?, ?, ?)",
            ("r1", i, float(i), json.dumps({"level": float(i + 1)})),
        )
    conn.commit()
    conn.close()
    return db


def test_gather_results_one_sim_one_run(tmp_path):
    db = _setup_runs_db(tmp_path)
    spec = {"simulations": [{"name": "single", "kind": "single",
                              "overrides": {"rate": 1.0}, "steps": 3}]}
    results = gather_results(spec, db)
    assert "single" in results
    assert len(results["single"]["runs"]) == 1
    run = results["single"]["runs"][0]
    assert run["run_id"] == "r1"
    assert run["params"] == {"rate": 1.0}
    assert len(run["trajectory"]) == 3
    assert run["trajectory"][2]["state"] == {"level": 3.0}


def test_load_overlays_reference_range(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "reference-range", "y_min": 1.0, "y_max": 5.0,
                          "label": "x"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "reference-range"
    assert payload[0]["y_min"] == 1.0


def test_load_overlays_experimental_points_missing_csv(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "experimental-points",
                          "data": "data/missing.csv",
                          "x_column": "t", "y_column": "v",
                          "label": "experiments"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "warning"
    assert "missing" in payload[0]["message"]


def test_load_overlays_experimental_points_ok(tmp_path):
    inv_dir = tmp_path / "investigations" / "demo"
    inv_dir.mkdir(parents=True)
    data_dir = inv_dir / "data"
    data_dir.mkdir()
    (data_dir / "exp.csv").write_text("t,v\n0,1.0\n1,2.5\n2,3.7\n")
    spec = {}
    viz = {"overlays": [{"kind": "experimental-points",
                          "data": "data/exp.csv",
                          "x_column": "t", "y_column": "v",
                          "label": "exp"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "experimental-points"
    assert payload[0]["points"] == [
        {"x": "0", "y": "1.0"}, {"x": "1", "y": "2.5"}, {"x": "2", "y": "3.7"},
    ]


def test_load_overlays_cross_investigation_missing(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "cross-investigation-series",
                          "investigation": "ghost", "observable": "x",
                          "label": "ghost"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "warning"


from scripts._lib.investigations import (
    update_spec_status, acquire_run_lock, release_run_lock,
)


def test_update_spec_status_writes_status_and_last_run(tmp_path):
    inv_dir = tmp_path / "investigations" / "demo"
    inv_dir.mkdir(parents=True)
    (inv_dir / "spec.yaml").write_text("""
name: demo
composite: pkg.x
simulations: []
observables: []
status: planned
""")
    update_spec_status(tmp_path, "demo", status="complete", last_run="2026-05-12T10:00:00")
    new_text = (inv_dir / "spec.yaml").read_text()
    assert "status: complete" in new_text
    assert "2026-05-12T10:00:00" in new_text


def test_acquire_and_release_run_lock(tmp_path):
    inv_dir = tmp_path / "investigations" / "x"
    inv_dir.mkdir(parents=True)
    assert acquire_run_lock(tmp_path, "x") is True
    # Second acquire on same investigation must fail
    assert acquire_run_lock(tmp_path, "x") is False
    release_run_lock(tmp_path, "x")
    # After release, acquire succeeds again
    assert acquire_run_lock(tmp_path, "x") is True
    release_run_lock(tmp_path, "x")
