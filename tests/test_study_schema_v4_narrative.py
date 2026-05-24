"""v4 narrative-spine validation tests for study.schema.json.

Covers the dnaa-investigation-derived second-layer narrative fields added
in the schema v3->v4 bump:

  * runtime{} (subprocess_timeout_s, default_emitter, max_generations,
    post_run_scripts)
  * enforced_params (flat or wrapped shape)
  * conditions{} (baseline, variants, model_settings[], expert_inputs[])
  * report{} (verdict, confidence, evidence_quality, key_metrics[])
  * study_card{} (goal, mechanism, why_before_next, expected_result,
    main_expert_question)
  * biological_summary (multi-paragraph prose)
  * literature_anchors[] (expectation + model_observable + status_in_workspace)
  * design_pivot_required[] (id, status, alternatives, requested_response)
  * conclusion_verdicts{} (regression_compatibility, biological_validation,
    explanatory_gain each {result, basis})
  * follow_up_of (sibling-marker)

All v4 fields are OPTIONAL. A v3 spec with schema_version: 3 and no v4
fields must still validate. A v4 spec with all fields populated must also
validate.

Run:
    pytest tests/test_study_schema_v4_narrative.py -v
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


def _base_v4_study() -> dict:
    return {
        "schema_version": 4,
        "name": "test-study",
        "baseline": [
            {"name": "b", "composite": "pkg.composites.foo"},
        ],
    }


class TestSchemaVersion:
    def test_v3_still_validates(self, validator):
        spec = _base_v4_study() | {"schema_version": 3}
        validator.validate(spec)

    def test_v4_validates(self, validator):
        validator.validate(_base_v4_study())

    def test_v2_rejected(self, validator):
        spec = _base_v4_study() | {"schema_version": 2}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestRuntime:
    def test_empty_runtime(self, validator):
        spec = _base_v4_study() | {"runtime": {}}
        validator.validate(spec)

    def test_full_runtime(self, validator):
        spec = _base_v4_study() | {
            "runtime": {
                "subprocess_timeout_s": 7200,
                "default_emitter": "xarray",
                "max_generations": 12,
                "post_run_scripts": ["v2ecoli.library.xarray_run.run_multigen"],
            }
        }
        validator.validate(spec)

    def test_default_emitter_enum(self, validator):
        spec = _base_v4_study() | {"runtime": {"default_emitter": "redis"}}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestEnforcedParams:
    def test_flat_shape(self, validator):
        spec = _base_v4_study() | {
            "enforced_params": {"dnaA_intrinsic_hydrolysis_rate_per_min": 0.046}
        }
        validator.validate(spec)

    def test_wrapped_shape(self, validator):
        spec = _base_v4_study() | {
            "enforced_params": {
                "params": {"dnaA_intrinsic_hydrolysis_rate_per_min": 0.046},
                "source": "Boesen 2024 PNAS",
            }
        }
        validator.validate(spec)


class TestConditions:
    def test_baseline_and_variants(self, validator):
        spec = _base_v4_study() | {
            "conditions": {
                "baseline": {
                    "composite": "v2ecoli.composites.baseline_recipes.dnaa_02",
                    "params": {"seed": 0, "mechanism": "intrinsic"},
                },
                "variants": [
                    {"name": "no-hydrolysis", "diff_from_baseline": "rate=0"}
                ],
            }
        }
        validator.validate(spec)

    def test_model_settings_with_range(self, validator):
        spec = _base_v4_study() | {
            "conditions": {
                "model_settings": [
                    {
                        "name": "hydrolysis_rate_per_min",
                        "default": 0.046,
                        "current": 0.046,
                        "range": [0.001, 1.0],
                        "cites": ["Boesen2024"],
                    }
                ]
            }
        }
        validator.validate(spec)


class TestReport:
    def test_empty_report(self, validator):
        spec = _base_v4_study() | {"report": {}}
        validator.validate(spec)

    def test_full_report(self, validator):
        spec = _base_v4_study() | {
            "report": {
                "title": "DnaA ATP/ADP intrinsic hydrolysis",
                "verdict": "failing-bio",
                "confidence": "high",
                "evidence_quality": "calibrated",
                "objective": "Test whether a minimal intrinsic-hydrolysis Step alone...",
                "conclusion": "Intrinsic hydrolysis alone cannot hold the band...",
                "main_insight": "Only DnaA-ATP drives initiation...",
                "caveat": "The band failure is the expected intrinsic-only control...",
                "key_metrics": [
                    {"label": "atp_fraction (intrinsic-only)", "value": 0.997, "status": "fail"},
                    "target band [0.2, 0.5]",
                ],
            }
        }
        validator.validate(spec)

    def test_confidence_enum(self, validator):
        spec = _base_v4_study() | {"report": {"confidence": "perfect"}}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestStudyCard:
    def test_full(self, validator):
        spec = _base_v4_study() | {
            "study_card": {
                "goal": "Split DnaA into apo/ATP/ADP species.",
                "mechanism": "New bulk species + a first-order hydrolysis Step.",
                "why_before_next": "dnaa-03 needs to know which nucleotide form.",
                "expected_result": "DnaA-ATP / total in [0.2, 0.5].",
                "main_expert_question": "Should we reuse MONOMER0-160_RXN?",
            }
        }
        validator.validate(spec)


class TestLiteratureAnchors:
    def test_minimal_anchor(self, validator):
        spec = _base_v4_study() | {
            "literature_anchors": [
                {
                    "expectation": "DnaA-ATP / total DnaA ≈ 20-50%",
                    "model_observable": "bulk[DnaA_ATP] / bulk[DnaA_total]",
                    "source": "Boesen 2024",
                    "status_in_workspace": "Not yet measurable",
                }
            ]
        }
        validator.validate(spec)


class TestDesignPivot:
    def test_full(self, validator):
        spec = _base_v4_study() | {
            "design_pivot_required": [
                {
                    "id": "dnaa-02-EQ-04",
                    "status": "superseded-by-dnaa-02f",
                    "question": "How do we make hydrolysis stick?",
                    "alternatives": [
                        "A. Add a locked species",
                        "B. Patch the stoichMatrix",
                    ],
                    "requested_response": "Expert opinion on (A) vs (B)",
                }
            ]
        }
        validator.validate(spec)

    def test_id_pattern(self, validator):
        spec = _base_v4_study() | {
            "design_pivot_required": [{"id": "has space", "question": "x"}]
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestConclusionVerdicts:
    def test_three_tracks(self, validator):
        spec = _base_v4_study() | {
            "conclusion_verdicts": {
                "regression_compatibility": {"result": "PASS", "basis": "Builds cleanly."},
                "biological_validation": {"result": "MIXED", "basis": "atp_fraction outside band."},
                "explanatory_gain": {"result": "POSITIVE", "basis": "Three findings worth keeping."},
            }
        }
        validator.validate(spec)

    def test_invalid_result_enum(self, validator):
        spec = _base_v4_study() | {
            "conclusion_verdicts": {
                "biological_validation": {"result": "OK"},
            }
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestBiologicalSummary:
    def test_string(self, validator):
        spec = _base_v4_study() | {
            "biological_summary": "In a real cell, DnaA exists in three states..."
        }
        validator.validate(spec)


class TestFollowUpOf:
    def test_slug(self, validator):
        spec = _base_v4_study() | {"follow_up_of": "dnaa-02-atp-hydrolysis"}
        validator.validate(spec)

    def test_bad_slug(self, validator):
        spec = _base_v4_study() | {"follow_up_of": "Has Spaces"}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestFullV4Composition:
    def test_all_v4_fields_together(self, validator):
        """A maximally-populated v4 spec must validate as a whole."""
        spec = _base_v4_study() | {
            "runtime": {"subprocess_timeout_s": 7200, "default_emitter": "sqlite"},
            "enforced_params": {
                "params": {"k": 0.046},
                "source": "Boesen2024",
            },
            "conditions": {
                "baseline": {"composite": "pkg.composites.foo"},
                "variants": [{"name": "no-k"}],
                "model_settings": [
                    {"name": "k", "default": 0.046, "current": 0.046,
                     "range": [0.01, 0.1], "cites": ["Boesen2024"]}
                ],
            },
            "report": {"verdict": "passing", "confidence": "high"},
            "study_card": {"goal": "Test the thing."},
            "biological_summary": "DnaA cycles between states.",
            "literature_anchors": [
                {"expectation": "x", "model_observable": "y", "source": "z"}
            ],
            "design_pivot_required": [
                {"id": "P-01", "question": "A or B?", "alternatives": ["A", "B"]}
            ],
            "conclusion_verdicts": {
                "regression_compatibility": {"result": "PASS", "basis": "ok"},
                "biological_validation": {"result": "PASS", "basis": "ok"},
                "explanatory_gain": {"result": "POSITIVE", "basis": "ok"},
            },
            "follow_up_of": "parent-study",
        }
        validator.validate(spec)
