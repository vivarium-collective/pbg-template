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
