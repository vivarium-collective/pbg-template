#!/usr/bin/env python3
"""Validate the scaffold YAML that viva-template renders into new workspaces.

viva-template ships its real content under ``template/`` as scaffold files that
``template-init.sh`` renders into a fresh workspace. Several of those are YAML
(GitHub workflows, ``workspace.yaml``, ``decisions.yaml``, ``claims.yaml``, …),
some as Jinja-ish ``*.yml.j2`` / ``*.yaml.j2`` templates. A malformed scaffold
ships broken YAML into every new workspace, so this script parses each one and
fails if any is invalid.

``.j2`` files are trivially rendered first: ``{{ token }}`` mustache
placeholders are replaced with a literal so the surrounding structure can be
parsed as YAML (this is a structural check, not a full Jinja render).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "template"
PLACEHOLDER_RE = re.compile(r"{{\s*[\w.]+\s*}}")


def main() -> int:
    if not TEMPLATE_DIR.is_dir():
        print(f"ERROR: template dir not found: {TEMPLATE_DIR}", file=sys.stderr)
        return 1

    checked: list[str] = []
    errors: list[str] = []

    for path in sorted(TEMPLATE_DIR.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        rel = path.relative_to(TEMPLATE_DIR.parent)
        if name.endswith((".yml.j2", ".yaml.j2")):
            text = PLACEHOLDER_RE.sub("placeholder", path.read_text())
            label = f"{rel} (rendered)"
        elif path.suffix in {".yml", ".yaml"}:
            text = path.read_text()
            label = str(rel)
        else:
            continue
        try:
            list(yaml.safe_load_all(text))
            checked.append(label)
        except yaml.YAMLError as exc:
            errors.append(f"{label}: {exc}")

    print(f"checked {len(checked)} scaffold YAML files")
    for label in checked:
        print(f"  ok  {label}")

    if errors:
        print("\nFAILURES:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if not checked:
        print("ERROR: no scaffold YAML files found to validate", file=sys.stderr)
        return 1

    print("template scaffold YAML: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
