"""Parse and render phase-N.md files (YAML frontmatter + markdown body)."""
from __future__ import annotations
import json
import re
from pathlib import Path
import yaml
from jsonschema import Draft7Validator, ValidationError


class PhaseValidationError(Exception):
    """Raised when phase-N.md frontmatter is invalid."""


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def _schema_path() -> Path:
    from ._root import workspace_root
    return workspace_root() / ".pbg" / "schemas" / "phase.schema.json"


def _validator() -> Draft7Validator:
    return Draft7Validator(json.loads(_schema_path().read_text()))


def parse_phase_md(text: str) -> tuple[dict, str]:
    text = text.replace("\r\n", "\n")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise PhaseValidationError("phase-N.md must start with YAML frontmatter delimited by ---")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise PhaseValidationError(f"YAML parse error in frontmatter: {e}") from e
    try:
        _validator().validate(fm)
    except ValidationError as e:
        raise PhaseValidationError(str(e)) from e
    return fm, m.group(2)


def render_phase_md(frontmatter: dict, body: str) -> str:
    try:
        _validator().validate(frontmatter)
    except ValidationError as e:
        raise PhaseValidationError(str(e)) from e
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).strip()}\n---\n{body.lstrip()}"
