"""Pass 10A validation tests for findings on study.schema.json.

Pass 10A formalizes the findings protocol shape: kind + status become
required enums (in addition to the existing id + statement). Sub-objects
(evidence, expected, expert_reference, provenance) remain optional with
loose internal shapes via ``additionalProperties: true``.

The dnaa-01 study under v2ecoli is the authoritative real-world fixture
— the parallel agent has been building its findings against the working
shape since Pass A. A copy of its ``findings:`` block lives at
``tests/fixtures/findings-cases/dnaa-01-real-findings.yaml`` so this
schema change is locked against regressions on the canonical data.

Run:
    pytest tests/test_study_schema_pass_10a.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "template" / ".pbg" / "schemas" / "study.schema.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "findings-cases"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _study(findings: list) -> dict:
    return {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Required fields: id + kind + status + statement
# ---------------------------------------------------------------------------


def test_minimal_finding_validates(validator):
    """All four required fields present, no optional sub-objects."""
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "v2ecoli reproduces DnaA steady state within tolerance.",
            }
        ]
    )
    validator.validate(spec)


def test_finding_missing_kind_rejected(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "status": "confirms",
                "statement": "Missing kind.",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_missing_status_rejected(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "statement": "Missing status.",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_missing_id_still_rejected(validator):
    """Existing Pass A constraint: id is required."""
    spec = _study(
        [
            {
                "kind": "biological",
                "status": "confirms",
                "statement": "no id here",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_finding_missing_statement_still_rejected(validator):
    """Existing Pass A constraint: statement is required."""
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Enum constraints on kind + status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["biological", "computational", "methodological"])
def test_kind_accepts_canonical_enum(validator, kind):
    spec = _study(
        [{"id": "F-01", "kind": kind, "status": "novel", "statement": "..."}]
    )
    validator.validate(spec)


def test_kind_rejects_invalid_enum(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biology",
                "status": "confirms",
                "statement": "bad kind",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


@pytest.mark.parametrize("status", ["confirms", "partial", "contradicts", "novel"])
def test_status_accepts_canonical_enum(validator, status):
    spec = _study(
        [{"id": "F-01", "kind": "biological", "status": status, "statement": "..."}]
    )
    validator.validate(spec)


def test_status_rejects_invalid_enum(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirmed",
                "statement": "bad status",
            }
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Full finding with all optional sub-objects
# ---------------------------------------------------------------------------


def test_full_finding_with_all_sub_objects_validates(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "contradicts",
                "statement": "DnaA pool is 5x below the literature band.",
                "evidence": {
                    "from_run": "baseline-heavy-tf",
                    "from_test": "dnaA-count-in-range",
                    "observed": 115,
                    "units": "molecules/cell",
                    "window": "second_half",
                    "reduction": "median across 5 seeds",
                    "smoking_gun": "monomer_counts[3861] accumulated linearly.",
                    "discovered_during": "dnaa-01 baseline run.",
                },
                "expected": {
                    "cites": ["Schmidt2016NatBiotechnol", "Sekimizu1991JBacteriol"],
                    "range": [300, 800],
                    "summary": "Mass-spec puts DnaA at 300-800 copies/cell.",
                },
                "expert_reference": {
                    "doc": "chromosome_replication_plan",
                    "section": "§2.1",
                    "quote": "DnaA per-cell count is a layer-1 sanity check.",
                    "note": "Curator gloss.",
                },
                "explanation": "Most likely cause: EG10235 TE is mis-calibrated.",
                "next_action": "Seed calibration_task follow-up.",
                "provenance": {
                    "run_ids": ["baseline-001"],
                    "model_commit_hash": "deadbeef",
                    "random_seeds": [0, 1, 2, 3, 4],
                    "evaluator_version": "v0.4.1",
                },
            }
        ]
    )
    validator.validate(spec)


def test_finding_without_provenance_still_validates(validator):
    """Provenance remains optional (Pass A constraint preserved)."""
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Concentration is stable across the second half.",
                "evidence": {"from_test": "dnaA-concentration-stable"},
                "expected": {"threshold": 0.10, "summary": "CV < 10% per Hansen 2018."},
            }
        ]
    )
    validator.validate(spec)


def test_evidence_extra_fields_allowed(validator):
    """Sub-objects use additionalProperties: true."""
    spec = _study(
        [
            {
                "id": "F-08",
                "kind": "biological",
                "status": "confirms",
                "statement": "TE sweep landed DnaA in band.",
                "evidence": {
                    "from_run": "baseline-te50x",
                    "sweep": {  # extra free-form sub-key authors can experiment with
                        "1x": {"te": 7.23e-05, "median_dnaa": 115},
                        "50x": {"te": 3.62e-03, "median_dnaa": 497},
                    },
                },
            }
        ]
    )
    validator.validate(spec)


def test_expected_extra_fields_allowed(validator):
    spec = _study(
        [
            {
                "id": "F-10",
                "kind": "biological",
                "status": "contradicts",
                "statement": "No single TE multiplier satisfies both tests.",
                "expected": {
                    "summary": "Both tests should pass simultaneously.",
                    "comparator_kind": "joint-criterion",  # author-defined extra key
                },
            }
        ]
    )
    validator.validate(spec)


def test_expert_reference_extra_fields_allowed(validator):
    spec = _study(
        [
            {
                "id": "F-02",
                "kind": "biological",
                "status": "confirms",
                "statement": "Autorepression signature present in 5-seed pool.",
                "expert_reference": {
                    "doc": "replication_initiation_molecular_info",
                    "quote": "DnaA binding at dnaAp1/dnaAp2 represses transcription.",
                    "page": 17,  # author-defined extra key
                },
            }
        ]
    )
    validator.validate(spec)


# ---------------------------------------------------------------------------
# obsoleted_by — append-only chaining
# ---------------------------------------------------------------------------


def test_obsoleted_by_field_validates(validator):
    spec = _study(
        [
            {
                "id": "F-02",
                "kind": "biological",
                "status": "confirms",
                "statement": "Original autorepression result.",
                "obsoleted_by": "F-09",
            }
        ]
    )
    validator.validate(spec)


# ---------------------------------------------------------------------------
# Real-world fixture: every dnaa-01 finding must validate as-is
# ---------------------------------------------------------------------------


def test_dnaa_01_real_findings_all_validate(validator):
    """The 10 worked-example findings under v2ecoli/studies/dnaa-01-... must
    validate against the Pass 10A schema without amendment.

    If this fails, the Pass 10A schema needs widening (or the dnaa-01
    findings need amending — flag, don't auto-edit)."""
    fixture = FIXTURES / "dnaa-01-real-findings.yaml"
    assert fixture.is_file(), f"missing fixture: {fixture}"
    data = yaml.safe_load(fixture.read_text())
    findings = data["findings"]
    assert len(findings) >= 5, "fixture must hold the parallel agent's worked examples"

    spec = _study(findings)
    validator.validate(spec)


def test_dnaa_01_real_findings_each_individually_validates(validator):
    """Per-finding validation makes failure diagnostics narrow."""
    fixture = FIXTURES / "dnaa-01-real-findings.yaml"
    data = yaml.safe_load(fixture.read_text())
    for f in data["findings"]:
        spec = _study([f])
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Combined: a full study with a long findings[] still validates
# ---------------------------------------------------------------------------


def test_study_with_mixed_minimal_and_full_findings_validates(validator):
    spec = _study(
        [
            {
                "id": "F-01",
                "kind": "biological",
                "status": "confirms",
                "statement": "Bare minimum.",
            },
            {
                "id": "F-02",
                "kind": "computational",
                "status": "novel",
                "statement": "Found a wiring bug.",
                "evidence": {"from_run": "baseline", "smoking_gun": "diff -ru..."},
                "explanation": "Listener was accumulating because no overwrite[] wrapper.",
                "next_action": "PR #51 fixes it.",
            },
            {
                "id": "F-03",
                "kind": "methodological",
                "status": "confirms",
                "statement": "Multi-seed pooling unlocks rare-event correlation.",
                "expected": {
                    "summary": "Standard correlation needs O(100+) variance samples.",
                },
            },
        ]
    )
    validator.validate(spec)
