"""Schema tests for the calibration_anchor formalization (Tier-B/B4).

Pre-formalization, behavior_tests.items.calibration_anchor was
`{type: object, additionalProperties: true}` — anything went. This pass
documents and validates the four fields proposed in walkthrough
Finding #28:

- ``observed_value`` (number | string) — measured against live model
- ``literature_target`` (number | string) — from cited literature
- ``divergence_factor`` (number) — auto-computed delta
- ``resolution`` (enum: model | thresholds | concept | unresolved)

Plus a ``cites`` array backing literature_target. `additionalProperties: true`
stays for forward-compat (workspace dialects, intermediate fields, etc.).

Run::

    pytest tests/test_study_schema_calibration_anchor.py -v
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


def _study(calibration_anchor: dict) -> dict:
    return {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "behavior_tests": [
            {
                "name": "dnaA-count-in-range",
                "calibration_anchor": calibration_anchor,
            }
        ],
    }


def test_fully_populated_anchor_validates(validator):
    spec = _study({
        "observed_value": 256299,
        "literature_target": 550,
        "divergence_factor": 466.0,
        "resolution": "model",
        "cites": ["Schmidt2016NatBiotechnol"],
    })
    assert list(validator.iter_errors(spec)) == []


def test_partial_anchor_with_only_target_validates(validator):
    """Hand-authored anchors start with just a literature_target."""
    spec = _study({
        "literature_target": 550,
        "cites": ["Schmidt2016NatBiotechnol"],
    })
    assert list(validator.iter_errors(spec)) == []


def test_empty_anchor_still_valid(validator):
    """Back-compat: an empty calibration_anchor: {} was previously legal."""
    spec = _study({})
    assert list(validator.iter_errors(spec)) == []


def test_anchor_with_extra_fields_validates(validator):
    """Forward-compat: dialect-specific extras stay legal."""
    spec = _study({
        "literature_target": 550,
        "computed_at": "2026-05-17T18:00:00Z",  # dialect field
        "method": "median-second-half",
    })
    assert list(validator.iter_errors(spec)) == []


# Resolution enum -----------------------------------------------------------


@pytest.mark.parametrize("good", ["model", "thresholds", "concept", "unresolved"])
def test_resolution_accepts_enum_values(validator, good):
    spec = _study({"resolution": good})
    assert list(validator.iter_errors(spec)) == []


@pytest.mark.parametrize("bad", ["Model", "TBD", "needs-recal", ""])
def test_resolution_rejects_non_enum_values(validator, bad):
    spec = _study({"resolution": bad})
    errs = list(validator.iter_errors(spec))
    assert errs, f"expected enum failure for resolution={bad!r}"


# Numeric / string typing ---------------------------------------------------


def test_observed_value_accepts_string(validator):
    """Categorical outcomes (e.g. 'oscillating' vs 'steady') are strings."""
    spec = _study({
        "observed_value": "oscillating",
        "literature_target": "steady",
        "resolution": "concept",
    })
    assert list(validator.iter_errors(spec)) == []


def test_divergence_factor_must_be_numeric(validator):
    """divergence_factor is auto-computed; strings are not allowed."""
    spec = _study({"divergence_factor": "high"})
    errs = list(validator.iter_errors(spec))
    assert errs, "divergence_factor: string should fail"


def test_observed_value_array_rejected(validator):
    """Arrays aren't a valid observed_value shape."""
    spec = _study({"observed_value": [1, 2, 3]})
    errs = list(validator.iter_errors(spec))
    assert errs


# Cites array ---------------------------------------------------------------


def test_cites_must_be_array_of_strings(validator):
    spec = _study({"cites": "Schmidt2016"})  # wrong: not an array
    errs = list(validator.iter_errors(spec))
    assert errs
