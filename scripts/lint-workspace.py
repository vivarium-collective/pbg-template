#!/usr/bin/env python3
"""Validate workspace.yaml + cross-references. Exit non-zero on failure."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft7Validator, FormatChecker, ValidationError


WS_ROOT = Path(__file__).resolve().parents[1]
WS_FILE = WS_ROOT / "workspace.yaml"


def _schema(name: str) -> dict:
    p = WS_ROOT / ".pbg" / "schemas" / name
    if not p.exists():
        sys.exit(f"missing schema at {p}; was workspace scaffolded?")
    return json.loads(p.read_text())


def _fail(msg: str) -> None:
    print(f"LINT FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not WS_FILE.exists():
        _fail(f"{WS_FILE} not found — run inside a workspace")
    ws = yaml.safe_load(WS_FILE.read_text())
    Draft7Validator(_schema("workspace.schema.json"), format_checker=FormatChecker()).validate(ws)

    declared = set((ws.get("models") or {}).keys())

    # Submodule integrity (only check if any models are declared)
    gitmodules = WS_ROOT / ".gitmodules"
    if declared:
        if not gitmodules.exists():
            _fail(".gitmodules missing but models declared")
        gm = gitmodules.read_text()
        for m in declared:
            if f"models/{m}" not in gm:
                _fail(f".gitmodules has no entry for models/{m}")
        for m in declared:
            path = WS_ROOT / "models" / m
            if not path.exists():
                _fail(f"declared model '{m}' has no submodule directory at {path}")

    # Datasets
    for d in ws.get("datasets", []):
        path, url, sha = d.get("path"), d.get("url"), d.get("sha256")
        if path:
            full = WS_ROOT / path
            if not full.exists():
                _fail(f"dataset '{d['name']}' path missing: {path}")
        elif url:
            if not sha:
                _fail(f"dataset '{d['name']}' has url but no sha256")
        else:
            _fail(f"dataset '{d['name']}' has neither path nor url")

    # References cross-ref
    refs_yaml = WS_ROOT / "references" / "claims.yaml"
    bib = WS_ROOT / "references" / "papers.bib"
    if refs_yaml.exists() and bib.exists():
        claims = (yaml.safe_load(refs_yaml.read_text()) or {}).get("claims", {}) or {}
        bib_text = bib.read_text()
        bib_keys = set(re.findall(r"@\w+\{([A-Za-z0-9_:-]+),", bib_text))
        for claim, key in claims.items():
            if isinstance(key, list):
                for k in key:
                    if k not in bib_keys:
                        _fail(f"claim '{claim}' references missing bib key '{k}'")
            elif isinstance(key, str):
                if key not in bib_keys:
                    _fail(f"claim '{claim}' references missing bib key '{key}'")

    # Phase frontmatter integrity per model
    phase_validator = Draft7Validator(_schema("phase.schema.json"))
    fm_re = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
    for m_name in declared:
        phases_dir = WS_ROOT / "models" / m_name / "phases"
        if not phases_dir.is_dir():
            continue
        for f in sorted(phases_dir.glob("phase-*.md")):
            text = f.read_text().replace("\r\n", "\n")
            mo = fm_re.match(text)
            if not mo:
                _fail(f"{f} has no YAML frontmatter")
            try:
                fm = yaml.safe_load(mo.group(1)) or {}
                phase_validator.validate(fm)
            except (ValidationError, yaml.YAMLError) as e:
                _fail(f"{f} invalid frontmatter: {e}")

    print("workspace lint: OK")


if __name__ == "__main__":
    main()
