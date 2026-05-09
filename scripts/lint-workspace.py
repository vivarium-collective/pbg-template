#!/usr/bin/env python3
"""Validate workspace.yaml + cross-references. Exit non-zero on failure."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft7Validator, FormatChecker, ValidationError


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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
        if path is not None:
            full = WS_ROOT / path
            if not full.exists():
                _fail(f"dataset '{d['name']}' path missing: {path}")
            elif sha:
                actual = _sha256(full)
                if actual != sha:
                    _fail(f"dataset '{d['name']}' sha256 mismatch (recorded={sha[:16]}…, actual={actual[:16]}…)")
        elif url is not None:
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

    # Expert docs path existence + optional sha256 verification
    for doc in ws.get("expert_docs", []) or []:
        doc_path = doc.get("path", "")
        if doc_path:
            full = WS_ROOT / doc_path
            if not full.exists():
                _fail(
                    f"expert_docs entry '{doc.get('name', '?')}' path missing: {doc_path} "
                    f"(expected at {full})"
                )
            sha = doc.get("sha256")
            if sha:
                actual = _sha256(full)
                if actual != sha:
                    _fail(f"expert_docs '{doc.get('name', '?')}' sha256 mismatch (recorded={sha[:16]}…, actual={actual[:16]}…)")

    # References PDFs: always verify sha256 + bib_key cross-reference
    bib = WS_ROOT / "references" / "papers.bib"
    bib_keys: set = set()
    if bib.exists():
        bib_text = bib.read_text()
        bib_keys = set(re.findall(r"@\w+\{([A-Za-z0-9_:-]+),", bib_text))
    for pdf_entry in ws.get("references_pdfs", []) or []:
        bib_key = pdf_entry.get("bib_key", "")
        pdf_path = pdf_entry.get("path", "")
        sha = pdf_entry.get("sha256", "")
        if bib_key and bib_keys and bib_key not in bib_keys:
            _fail(f"references_pdfs entry '{bib_key}' has no matching entry in papers.bib")
        if pdf_path:
            full = WS_ROOT / pdf_path
            if not full.exists():
                _fail(f"references_pdfs '{bib_key}' path missing: {pdf_path}")
            elif sha:
                actual = _sha256(full)
                if actual != sha:
                    _fail(f"references_pdfs '{bib_key}' sha256 mismatch (recorded={sha[:16]}…, actual={actual[:16]}…)")

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
