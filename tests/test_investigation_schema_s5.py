"""S5 schema additions to investigation.schema.json — close-investigation
workflow.

Covers:
- The `status:` enum extends to include "closed" alongside the existing
  values; pre-existing values still validate.
- The new `contributors[]` field accepts the documented shape with both
  human and agent entries; `name` is required, all other sub-fields
  optional.
- The new `closed_at:` and `report_url:` fields validate as strings.
- A v1 spec without any S5 fields still validates unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "template" / ".pbg" / "schemas" / "investigation.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _base() -> dict:
    return {
        "schema_version": 2,
        "name": "my-inv",
        "title": "My Investigation",
    }


class TestStatusEnum:
    @pytest.mark.parametrize("status", [
        "planned", "planning", "running", "ran",
        "complete", "failed", "invalid", "archived", "closed",
    ])
    def test_accepts_known_status(self, validator, status):
        spec = _base() | {"status": status}
        validator.validate(spec)

    def test_rejects_unknown_status(self, validator):
        spec = _base() | {"status": "shipped"}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestContributors:
    def test_empty_contributors_list(self, validator):
        spec = _base() | {"contributors": []}
        validator.validate(spec)

    def test_human_contributor(self, validator):
        spec = _base() | {
            "contributors": [
                {
                    "name": "Eran Agmon",
                    "email": "eran@example.com",
                    "kind": "human",
                    "roles": ["designer", "implementer"],
                    "commits": 42,
                    "notes": "Led the dnaa-replication arc.",
                }
            ]
        }
        validator.validate(spec)

    def test_agent_contributor(self, validator):
        spec = _base() | {
            "contributors": [
                {
                    "name": "Claude Opus 4.7",
                    "kind": "agent",
                    "roles": ["agent_runner", "implementer"],
                    "sessions": ["729bc3ba-d7e1-4530-8e66-9eecd4dac0fc"],
                }
            ]
        }
        validator.validate(spec)

    def test_minimal_contributor(self, validator):
        """Only `name` is required."""
        spec = _base() | {"contributors": [{"name": "Anonymous"}]}
        validator.validate(spec)

    def test_missing_name_rejected(self, validator):
        spec = _base() | {"contributors": [{"email": "x@y.z"}]}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_invalid_kind_rejected(self, validator):
        spec = _base() | {
            "contributors": [{"name": "x", "kind": "robot"}]
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_negative_commits_rejected(self, validator):
        spec = _base() | {
            "contributors": [{"name": "x", "commits": -1}]
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestClosedAtReportUrl:
    def test_closed_at(self, validator):
        spec = _base() | {"closed_at": "2026-05-24T18:30:00"}
        validator.validate(spec)

    def test_report_url(self, validator):
        spec = _base() | {"report_url": "report.html"}
        validator.validate(spec)


class TestBackcompat:
    def test_v1_unchanged(self, validator):
        """A v1 spec without any S5 fields still validates."""
        spec = {
            "schema_version": 1,
            "name": "old-inv",
            "title": "Old Investigation",
            "status": "complete",
        }
        validator.validate(spec)

    def test_fully_populated_close_state(self, validator):
        """A fully closed investigation with all S5 fields populated."""
        spec = _base() | {
            "status": "closed",
            "closed_at": "2026-05-24T18:30:00",
            "report_url": "report.html",
            "contributors": [
                {"name": "Eran", "kind": "human", "roles": ["designer"], "commits": 12},
                {"name": "Claude Opus 4.7", "kind": "agent",
                 "roles": ["agent_runner"], "sessions": ["abc-123"]},
            ],
        }
        validator.validate(spec)
