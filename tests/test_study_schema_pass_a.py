"""Pass A infrastructure-feedback validation tests for study.schema.json.

Covers the three Pass A additions to the study schema:

1. Multi-axis status — six independent optional status axes
   (design_status, implementation_status, simulation_status,
   evaluation_status, gate_status, expert_review_status).
2. ``findings: []`` top-level array, with optional ``provenance`` per entry.
3. Extended ``pipeline_gate.prerequisites`` item shape:
   bare-string OR {study, condition} (existing) OR the Pass A object form
   with ``required_gate_status`` / ``outputs_used`` / ``artifact_hashes``.

All Pass A fields are optional, so v3 studies that set none of them must
continue to validate.

Run:
    pytest tests/test_study_schema_pass_a.py -v
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


def _minimal_v3_study(**overrides) -> dict:
    """The smallest valid v3 study spec — just what the schema requires."""
    base = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Back-compat: a v3 study with only the legacy `status:` field still validates
# ---------------------------------------------------------------------------


def test_legacy_v3_with_only_single_status_validates(validator):
    """A pre-Pass-A study that sets only `status: planned` must still validate."""
    spec = _minimal_v3_study(status="planned")
    validator.validate(spec)


def test_legacy_v3_with_no_status_fields_validates(validator):
    """A pre-Pass-A study with no status whatsoever must still validate."""
    spec = _minimal_v3_study()
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Multi-axis status: all six axes, valid + invalid enum values
# ---------------------------------------------------------------------------


def test_all_six_status_axes_accept_canonical_values(validator):
    spec = _minimal_v3_study(
        design_status="drafted",
        implementation_status="partial",
        simulation_status="running",
        evaluation_status="not_evaluated",
        gate_status="needs_calibration",
        expert_review_status="requested",
    )
    validator.validate(spec)


def test_status_axes_accept_null(validator):
    """Each axis is independently nullable."""
    spec = _minimal_v3_study(
        design_status=None,
        implementation_status=None,
        simulation_status=None,
        evaluation_status=None,
        gate_status=None,
        expert_review_status=None,
    )
    validator.validate(spec)


def test_gate_status_rejects_invalid_enum(validator):
    spec = _minimal_v3_study(gate_status="bogus")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_design_status_rejects_invalid_enum(validator):
    spec = _minimal_v3_study(design_status="kind-of-planned")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_implementation_status_rejects_invalid_enum(validator):
    spec = _minimal_v3_study(implementation_status="mostly")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_expert_review_status_rejects_invalid_enum(validator):
    spec = _minimal_v3_study(expert_review_status="seen-it")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# findings: minimal entry and full-provenance entry both validate
# ---------------------------------------------------------------------------


def test_findings_minimal_entry_validates(validator):
    # Updated for Pass 10A: kind + status are now required alongside id + statement.
    spec = _minimal_v3_study(
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "contradicts",
                "statement": "v2ecoli reproduces the DnaA shortfall.",
            }
        ]
    )
    validator.validate(spec)


def test_findings_with_full_provenance_validates(validator):
    spec = _minimal_v3_study(
        findings=[
            {
                "id": "F-02",
                "kind": "biological",
                "status": "contradicts",
                "statement": "Autorepression is missing.",
                "provenance": {
                    "run_ids": ["run-001", "run-002"],
                    "simulation_config_hash": "sha256:abc...",
                    "model_commit_hash": "deadbeef",
                    "parca_cache_hash": "sha256:def...",
                    "random_seeds": [0, 1, 2],
                    "analysis_script": "scripts/measure_autorepression.py",
                    "evaluator_version": "v0.4.1",
                    "raw_data_artifact": "runs.db",
                    "metric_table_artifact": "out/metrics.csv",
                },
            }
        ]
    )
    validator.validate(spec)


def test_findings_mixed_minimal_and_full_validates(validator):
    spec = _minimal_v3_study(
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Bare-minimum finding.",
            },
            {
                "id": "F-02",
                "kind": "computational",
                "status": "novel",
                "statement": "Finding with provenance.",
                "provenance": {
                    "run_ids": ["run-001"],
                    "model_commit_hash": "deadbeef",
                },
            },
        ]
    )
    validator.validate(spec)


def test_finding_missing_id_rejected(validator):
    spec = _minimal_v3_study(
        findings=[
            {"kind": "biological", "status": "confirms", "statement": "no id here"}
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_missing_statement_rejected(validator):
    spec = _minimal_v3_study(
        findings=[{"id": "F-01", "kind": "biological", "status": "confirms"}]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_extra_fields_allowed(validator):
    """additionalProperties: true on each finding — authors can add fields."""
    spec = _minimal_v3_study(
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "contradicts",
                "statement": "test",
                "evidence": {"from_test": "t1"},
                "expected": {"cites": ["smith2020"]},
                "next_action": "Add listener X.",
            }
        ]
    )
    validator.validate(spec)


# ---------------------------------------------------------------------------
# pipeline_gate.prerequisites: bare-string, legacy object, extended object
# ---------------------------------------------------------------------------


def test_prerequisites_bare_string_validates(validator):
    spec = _minimal_v3_study(
        pipeline_gate={"prerequisites": ["dnaa-01-expression-dynamics"]}
    )
    validator.validate(spec)


def test_prerequisites_legacy_object_form_validates(validator):
    """{study, condition} — the pre-Pass-A object form."""
    spec = _minimal_v3_study(
        pipeline_gate={
            "prerequisites": [
                {"study": "dnaa-01-expression-dynamics", "condition": "tests-passed"}
            ]
        }
    )
    validator.validate(spec)


def test_prerequisites_extended_object_form_validates(validator):
    """Pass A: required_gate_status + outputs_used + artifact_hashes."""
    spec = _minimal_v3_study(
        pipeline_gate={
            "prerequisites": [
                {
                    "study": "dnaa-01-expression-dynamics",
                    "condition": "tests-passed",
                    "required_gate_status": "passed",
                    "outputs_used": ["autorepression_signal", "dnaA_steady_count"],
                    "artifact_hashes": {
                        "model_commit": "deadbeef",
                        "parca_cache": "sha256:abc...",
                        "analysis_script": None,
                    },
                }
            ]
        }
    )
    validator.validate(spec)


def test_prerequisites_mixed_forms_validate(validator):
    """All three forms in one list must coexist."""
    spec = _minimal_v3_study(
        pipeline_gate={
            "prerequisites": [
                "dnaa-00-bootstrap",
                {"study": "dnaa-01-expression-dynamics", "condition": "ran"},
                {
                    "study": "dnaa-02-autorepression",
                    "required_gate_status": "passed",
                    "outputs_used": ["foo"],
                },
            ]
        }
    )
    validator.validate(spec)


def test_prerequisites_extended_required_gate_status_rejects_invalid(validator):
    spec = _minimal_v3_study(
        pipeline_gate={
            "prerequisites": [
                {"study": "x", "required_gate_status": "bogus"}
            ]
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_prerequisites_extended_unknown_top_level_field_rejected(validator):
    """additionalProperties: false on the object form — unknown keys are rejected."""
    spec = _minimal_v3_study(
        pipeline_gate={
            "prerequisites": [
                {"study": "x", "garbage_field": True}
            ]
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Combined: a new-style v3 study using all Pass A features at once
# ---------------------------------------------------------------------------


def test_full_pass_a_study_validates(validator):
    spec = _minimal_v3_study(
        status="planned",          # legacy back-compat
        design_status="approved",
        implementation_status="complete",
        simulation_status="ran",
        evaluation_status="evaluated",
        gate_status="passed",
        expert_review_status="approved",
        pipeline_gate={
            "prerequisites": [
                "dnaa-00-bootstrap",
                {
                    "study": "dnaa-01-expression-dynamics",
                    "condition": "tests-passed",
                    "required_gate_status": "passed",
                    "outputs_used": ["autorepression_signal"],
                    "artifact_hashes": {"model_commit": "deadbeef"},
                },
            ],
            "enables": ["dnaa-03-downstream"],
            "proceed_condition": "primary tests pass.",
        },
        findings=[
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Bare-minimum finding.",
            },
            {
                "id": "F-02",
                "kind": "computational",
                "status": "novel",
                "statement": "Finding with provenance.",
                "provenance": {
                    "run_ids": ["run-001"],
                    "model_commit_hash": "deadbeef",
                    "analysis_script": "scripts/measure.py",
                },
            },
        ],
    )
    validator.validate(spec)
