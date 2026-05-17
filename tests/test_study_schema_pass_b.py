"""Pass B infrastructure-feedback validation tests for study.schema.json.

Covers the Pass B addition: structured sweep entries inside ``simulation_set``.

Adds an OPTIONAL ``kind`` discriminator on each ``simulation_set`` array item:

- ``kind: single`` (or absent): existing free-form single-run shape — back-compat.
- ``kind: sweep``: structured Cartesian-product parameter sweep with axes,
  seeds, metrics, pass/fail tests, candidate selection, and post-execution
  populated fields (runs, aggregate_metrics, candidates_selected,
  rejection_reasons).

Run:
    pytest tests/test_study_schema_pass_b.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "template" / ".pbg" / "schemas" / "study.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _study(simulation_set: list | dict) -> dict:
    return {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "simulation_set": simulation_set,
    }


# ---------------------------------------------------------------------------
# Back-compat: existing single-run entries (no `kind:`) still validate
# ---------------------------------------------------------------------------


def test_legacy_single_entry_without_kind_validates(validator):
    """Pre-Pass-B simulation_set entries (no `kind:`) must still validate."""
    spec = _study([
        {
            "name": "baseline",
            "base_model": "pkg.composites.x",
            "perturbation": None,
            "condition": "wild-type",
            "duration_min": 60.0,
            "seeds": [0, 1, 2],
            "readouts": ["dnaA_count"],
            "applies_tests": ["dnaa-steady"],
            "status": "ready",
        }
    ])
    validator.validate(spec)


def test_legacy_single_entry_minimal_validates(validator):
    """The bare-minimum legacy form (just name) still validates."""
    spec = _study([{"name": "baseline"}])
    validator.validate(spec)


def test_explicit_kind_single_validates(validator):
    """Explicit `kind: single` is accepted as a synonym for the legacy form."""
    spec = _study([
        {
            "kind": "single",
            "name": "baseline",
            "base_model": "pkg.composites.x",
            "duration_min": 60.0,
            "seeds": [0],
        }
    ])
    validator.validate(spec)


def test_object_shape_simulation_set_validates(validator):
    """The forward-compat object shape on simulation_set continues to validate."""
    spec = _study({"foo": "bar", "anything": 1})
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Sweep entries: full + minimal + every populated field
# ---------------------------------------------------------------------------


def test_sweep_minimal_validates(validator):
    """Sweep with only the required fields (kind, name, axes) validates."""
    spec = _study([
        {
            "kind": "sweep",
            "name": "te-sweep",
            "axes": [
                {"parameter": "te_multiplier", "values": [1.0, 5.0, 10.0]}
            ],
        }
    ])
    validator.validate(spec)


def test_sweep_full_validates(validator):
    """All optional + post-execution fields populated."""
    spec = _study([
        {
            "name": "te-multiplier-sweep",
            "kind": "sweep",
            "base_model": "pkg.composites.dnaa",
            "axes": [
                {"parameter": "te_multiplier", "values": [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]},
                {"parameter": "rnap_count", "values": [100, 200]},
            ],
            "seeds": [0, 1, 2, 3, 4],
            "duration": 3600,
            "metrics": ["dnaA_steady_count", "autorepression_signal"],
            "pass_fail_tests": ["autorepression-correlation"],
            "candidate_selection": "Top-2 by pass-rate; tiebreak by min |observed - expected|.",
            "runs": [
                {
                    "axis_values": {"te_multiplier": 10.0, "rnap_count": 200},
                    "seed": 1,
                    "run_id": "run-abc",
                    "metrics": {"dnaA_steady_count": 412, "autorepression_signal": 0.81},
                    "test_results": {"autorepression-correlation": "pass"},
                },
                {
                    "axis_values": {"te_multiplier": 1.0, "rnap_count": 100},
                    "seed": 0,
                    "run_id": "run-def",
                    "metrics": {"dnaA_steady_count": 12},
                    "test_results": {"autorepression-correlation": "fail"},
                },
            ],
            "aggregate_metrics": {"pass_rate": 0.4, "candidate_count": 2},
            "candidates_selected": ["run-abc"],
            "rejection_reasons": {"run-def": "below dnaA_steady_count threshold"},
            "artifact_path": "out/sweeps/te-multiplier-sweep.csv",
            "status": "ran",
        }
    ])
    validator.validate(spec)


def test_sweep_multiple_axes_validate(validator):
    """Cartesian-product sweeps with >1 axis are accepted."""
    spec = _study([
        {
            "kind": "sweep",
            "name": "two-axis-sweep",
            "axes": [
                {"parameter": "a", "values": [1, 2]},
                {"parameter": "b", "values": ["x", "y", "z"]},
            ],
        }
    ])
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_sweep_missing_axes_rejected(validator):
    spec = _study([{"kind": "sweep", "name": "broken"}])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_empty_axes_rejected(validator):
    spec = _study([{"kind": "sweep", "name": "broken", "axes": []}])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_missing_name_rejected(validator):
    spec = _study([
        {"kind": "sweep", "axes": [{"parameter": "x", "values": [1]}]}
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_axis_missing_parameter_rejected(validator):
    spec = _study([
        {"kind": "sweep", "name": "broken", "axes": [{"values": [1, 2]}]}
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_axis_missing_values_rejected(validator):
    spec = _study([
        {"kind": "sweep", "name": "broken", "axes": [{"parameter": "x"}]}
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_axis_empty_values_rejected(validator):
    spec = _study([
        {"kind": "sweep", "name": "broken", "axes": [{"parameter": "x", "values": []}]}
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_kind_invalid_rejected(validator):
    spec = _study([
        {"kind": "invalid", "name": "broken", "axes": [{"parameter": "x", "values": [1]}]}
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_sweep_test_result_invalid_enum_rejected(validator):
    spec = _study([
        {
            "kind": "sweep",
            "name": "x",
            "axes": [{"parameter": "p", "values": [1]}],
            "runs": [
                {
                    "axis_values": {"p": 1},
                    "seed": 0,
                    "run_id": "r1",
                    "test_results": {"t1": "maybe"},
                }
            ],
        }
    ])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Mixed: a simulation_set with one single + one sweep entry
# ---------------------------------------------------------------------------


def test_mixed_single_and_sweep_entries_validate(validator):
    spec = _study([
        {"name": "baseline", "base_model": "pkg.composites.x"},
        {
            "kind": "sweep",
            "name": "tweak-sweep",
            "axes": [{"parameter": "te", "values": [1.0, 5.0]}],
            "seeds": [0, 1],
        },
    ])
    validator.validate(spec)
