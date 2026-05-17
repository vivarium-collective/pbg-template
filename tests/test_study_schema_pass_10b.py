"""Pass 10B validation tests for ``seeded_from`` on study.schema.json.

Pass 10B extends the ``seeded_from`` provenance object with an optional
``finding:`` sub-field (a finding-id string like ``F-03``) so that a
seeded child can record *which finding* on its parent motivated the
follow-up — in addition to the existing parent study slug + proposal id
captured by Pass 8.

All three sub-fields (``study``, ``proposal_id``, ``finding``) are now
*independently optional*: a Pass-8-shaped seeded_from with only
``study`` + ``proposal_id`` must still validate, and the new shapes
(adds ``finding``, or ``finding`` alone) must validate too.

Run:
    pytest tests/test_study_schema_pass_10b.py -v
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


def _minimal_v3_study(**overrides) -> dict:
    base = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pass 8 back-compat: study + proposal_id without finding still validates
# ---------------------------------------------------------------------------


def test_pass8_seeded_from_without_finding_still_validates(validator):
    """A pre-Pass-10B child stamped only with {study, proposal_id} must validate."""
    spec = _minimal_v3_study(
        seeded_from={
            "study": "dnaa-01-expression-dynamics",
            "proposal_id": "replisome-coupling",
        }
    )
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Pass 10B: full {study, proposal_id, finding} validates
# ---------------------------------------------------------------------------


def test_all_three_seeded_from_fields_validate(validator):
    spec = _minimal_v3_study(
        seeded_from={
            "study": "dnaa-01-expression-dynamics",
            "proposal_id": "calibrate-te-multiplier",
            "finding": "F-03",
        }
    )
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Pass 10B: finding alone validates (edge case)
# ---------------------------------------------------------------------------


def test_finding_only_seeded_from_validates(validator):
    """All three sub-fields are independently optional — finding alone is OK."""
    spec = _minimal_v3_study(seeded_from={"finding": "F-07"})
    validator.validate(spec)


def test_empty_seeded_from_validates(validator):
    """No sub-fields required individually — empty object validates."""
    spec = _minimal_v3_study(seeded_from={})
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Pass 10B: finding pattern is enforced
# ---------------------------------------------------------------------------


def test_finding_rejects_disallowed_characters(validator):
    """The pattern matches finding-id slugs (alnum + `_` + `-`)."""
    spec = _minimal_v3_study(
        seeded_from={"study": "p", "proposal_id": "q", "finding": "bad finding!"}
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_accepts_canonical_F_NN_form(validator):
    for fid in ("F-01", "F-99", "F_01", "finding-7", "Abc123"):
        spec = _minimal_v3_study(seeded_from={"finding": fid})
        validator.validate(spec)
