"""Schema tests for cites on readouts[] and tests[] items (band provenance, stage 3a).

Adding cites to readouts[] items and tests[] array items (additive):
- readouts[].cites — bib_keys sourcing the observable band
- tests[].cites — bib_keys sourcing the acceptance band (v4 per-test array shape)

Asserts:
1. A readout/test WITH cites validates.
2. An existing uncited readout/test (back-compat) still validates.
3. cites must be an array of strings (not a bare string).

Run:
    pytest tests/test_study_schema_band_cites.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "template" / ".pbg" / "schemas" / "study.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _study(**kwargs) -> dict:
    base = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# readouts[].cites
# ---------------------------------------------------------------------------


def test_readout_with_cites_validates(validator):
    """A readout that has cites: [...] validates (new field accepted)."""
    spec = _study(readouts=[
        {
            "name": "DnaA-ATP fraction",
            "identifier": "bulk MONOMER0-160[c] / (PD03831[c] + MONOMER0-160[c] + MONOMER0-4565[c])",
            "units": "fraction",
            "status": "primary",
            "notes": "Evaluated vs the Boesen 2024 [0.2, 0.5] band.",
            "cites": ["Boesen2024"],
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_readout_without_cites_still_validates(validator):
    """Back-compat: a readout with no cites field still validates (additive)."""
    spec = _study(readouts=[
        {
            "name": "DnaA-ATP fraction",
            "identifier": "bulk MONOMER0-160[c] / ...",
            "units": "fraction",
            "status": "primary",
            "notes": "Boesen 2024 [0.2, 0.5] band (no cites field yet).",
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_readout_with_multiple_cites_validates(validator):
    """Multiple bib_keys in cites: [...] validates."""
    spec = _study(readouts=[
        {
            "name": "total DnaA",
            "identifier": "bulk PD03831[c] + MONOMER0-160[c] + MONOMER0-4565[c]",
            "units": "molecules/cell",
            "cites": ["Boesen2024", "Sekimizu1991"],
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_readout_cites_must_be_array(validator):
    """cites must be an array, not a bare string."""
    spec = _study(readouts=[
        {
            "name": "r1",
            "store_path": "p",
            "cites": "Boesen2024",  # wrong: should be a list
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors, "expected validation failure when cites is a bare string"


# ---------------------------------------------------------------------------
# tests[] (v4 per-test array) .cites
# ---------------------------------------------------------------------------


def test_tests_array_item_with_cites_validates(validator):
    """A v4 tests[] item (band shape) with cites: [...] validates."""
    spec = _study(tests=[
        {
            "name": "dnaa-atp-fraction-in-band-0.2-0.5",
            "classification": "primary",
            "question": "Is the DnaA-ATP fraction in [0.2, 0.5]?",
            "measure": {
                "kind": "generation_average",
                "path": "MONOMER0-160[c] / (PD03831[c] + MONOMER0-160[c] + MONOMER0-4565[c])",
            },
            "pass_if": {
                "op": "generation_average_in_range",
                "low": 0.2,
                "high": 0.5,
            },
            "status": "passed",
            "cites": ["Boesen2024"],
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_tests_array_item_without_cites_still_validates(validator):
    """Back-compat: a v4 tests[] item WITHOUT cites still validates (additive)."""
    spec = _study(tests=[
        {
            "name": "dnaa-atp-fraction-in-band-0.2-0.5",
            "classification": "primary",
            "measure": {
                "kind": "generation_average",
                "path": "MONOMER0-160[c] / ...",
            },
            "pass_if": {
                "op": "generation_average_in_range",
                "low": 0.2,
                "high": 0.5,
            },
            "status": "passed",
            # no cites — back-compat
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_tests_array_multiple_items_validates(validator):
    """Multiple v4 tests[] items (some with cites, some without) validates."""
    spec = _study(tests=[
        {
            "name": "dnaa-atp-fraction-in-band-0.2-0.5",
            "classification": "primary",
            "pass_if": {"op": "generation_average_in_range", "low": 0.2, "high": 0.5},
            "cites": ["Boesen2024"],
        },
        {
            "name": "total-dnaa-in-band-300-800",
            "classification": "secondary",
            "pass_if": {"op": "generation_average_in_range", "low": 300, "high": 800},
            # no cites
        },
        {
            "name": "periodic-mass-doubling",
            "classification": "primary",
            "pass_if": {"op": "periodic_doubling_every_generation", "tolerance": 0.15},
        },
    ])
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_tests_config_object_still_validates(validator):
    """Back-compat: tests: {auto_discover: true, ...} config-object form still validates."""
    spec = _study(tests={
        "auto_discover": True,
        "data_source": "runs_db",
        "pytest_args": ["-x", "-v"],
    })
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"unexpected errors: {errors}"


def test_tests_array_item_cites_must_be_array(validator):
    """cites on a v4 tests[] item must be an array."""
    spec = _study(tests=[
        {
            "name": "t1",
            "pass_if": {"op": "in_range", "low": 0.2, "high": 0.5},
            "cites": "Boesen2024",  # wrong: should be a list
        }
    ])
    errors = list(validator.iter_errors(spec))
    assert errors, "expected validation failure when tests[].cites is a bare string"
