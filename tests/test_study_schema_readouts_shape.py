"""Schema tests for the readouts shape formalization (Tier-B/B1).

Pre-formalization, readouts.items.status was free-form `type: string` and
index_by was `{type: object, additionalProperties: true}` — anything went.
This pass:

- Requires ``index_by`` to carry both ``type`` (catalog name) and ``value``
  (the key in that catalog). Extra fields still allowed.
- Adds a kebab-case ``pattern`` to ``status`` so typos like ``Avilable`` or
  ``derived_needed`` fail validation. The value space stays free-form so
  workspaces can introduce new states.

Run::

    pytest tests/test_study_schema_readouts_shape.py -v
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


def _study(readouts: list) -> dict:
    return {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "readouts": readouts,
    }


# ---------------------------------------------------------------------------
# index_by: required type + value
# ---------------------------------------------------------------------------


def test_index_by_with_type_and_value_validates(validator):
    spec = _study([
        {
            "name": "dnaA_protein_count",
            "store_path": "agents.0.bulk",
            "index_by": {"type": "bulk_id", "value": "PD03831[c]"},
        }
    ])
    assert list(validator.iter_errors(spec)) == []


def test_index_by_with_integer_value_validates(validator):
    """literal_index lookups carry an integer value."""
    spec = _study([
        {
            "name": "fork_count",
            "store_path": "agents.0.listeners.replisome.fork_pos",
            "index_by": {"type": "literal_index", "value": 0},
        }
    ])
    assert list(validator.iter_errors(spec)) == []


def test_index_by_allows_extra_fields(validator):
    """Forward-compat: dialect-specific extras like `path:` stay legal."""
    spec = _study([
        {
            "name": "r1",
            "store_path": "agents.0.bulk",
            "index_by": {
                "type": "bulk_id",
                "value": "PD03831[c]",
                "path": "monomerCounts",  # extra dialect field
            },
        }
    ])
    assert list(validator.iter_errors(spec)) == []


def test_index_by_missing_value_fails(validator):
    spec = _study([
        {
            "name": "r1",
            "store_path": "agents.0.bulk",
            "index_by": {"type": "bulk_id"},  # no `value`
        }
    ])
    errs = list(validator.iter_errors(spec))
    assert errs, "expected validation failure when `value` is missing"
    assert any("value" in str(e.message) for e in errs)


def test_index_by_missing_type_fails(validator):
    spec = _study([
        {
            "name": "r1",
            "store_path": "agents.0.bulk",
            "index_by": {"value": "PD03831[c]"},  # no `type`
        }
    ])
    errs = list(validator.iter_errors(spec))
    assert errs, "expected validation failure when `type` is missing"
    assert any("type" in str(e.message) for e in errs)


def test_index_by_value_must_be_string_or_int(validator):
    spec = _study([
        {
            "name": "r1",
            "store_path": "agents.0.bulk",
            "index_by": {"type": "bulk_id", "value": ["not", "a", "scalar"]},
        }
    ])
    errs = list(validator.iter_errors(spec))
    assert errs, "value=list should not validate"


def test_readout_without_index_by_still_valid(validator):
    """index_by is optional — readouts on scalar paths don't need it."""
    spec = _study([
        {
            "name": "cell_volume",
            "store_path": "agents.0.global_state.volume",
            "units": "fL",
        }
    ])
    assert list(validator.iter_errors(spec)) == []


# ---------------------------------------------------------------------------
# status: kebab-case pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("good", [
    "available",
    "derived-needed",
    "aspirational",
    "blocked-by-data",  # workspace-specific extension is fine
])
def test_status_accepts_kebab_values(validator, good):
    spec = _study([
        {"name": "r1", "store_path": "p", "status": good}
    ])
    assert list(validator.iter_errors(spec)) == []


@pytest.mark.parametrize("bad", [
    "Available",          # uppercase
    "derived_needed",     # snake_case (typo trap)
    "TBD",                # uppercase
    "1available",         # leading digit
    "",                   # empty
])
def test_status_rejects_non_kebab_values(validator, bad):
    spec = _study([
        {"name": "r1", "store_path": "p", "status": bad}
    ])
    errs = list(validator.iter_errors(spec))
    assert errs, f"expected pattern failure for status={bad!r}"


def test_readout_without_status_still_valid(validator):
    """status is optional — legacy readouts that don't set it still pass."""
    spec = _study([
        {"name": "r1", "store_path": "p"}
    ])
    assert list(validator.iter_errors(spec)) == []
