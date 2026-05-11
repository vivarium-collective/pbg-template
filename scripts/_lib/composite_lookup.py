"""Workspace-local composite discovery + loading.

Mirrors pbg_superpowers.composite_spec + composite_discovery for the dashboard's
use. Self-contained: no dependency on pbg-superpowers (which is a Claude Code
plugin, not pip-installable in workspace venvs).

Scans the workspace's own pbg_<slug>/composites/ directory for *.composite.{yaml,json}.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

import yaml


_FULL_PLACEHOLDER = re.compile(r"^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$")
_INLINE_PLACEHOLDER = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def load_spec(path: Path) -> dict:
    text = path.read_text()
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def discover_workspace_composites(ws_root: Path, package_path: str) -> dict[str, dict]:
    """Scan pbg_<slug>/composites/*.composite.{yaml,json}; return {id: spec}."""
    composites_dir = ws_root / package_path / "composites"
    if not composites_dir.is_dir():
        return {}
    out: dict[str, dict] = {}
    for pattern in ("*.composite.yaml", "*.composite.yml", "*.composite.json"):
        for path in composites_dir.glob(pattern):
            stem = path.name
            for suffix in (".composite.yaml", ".composite.yml", ".composite.json"):
                if stem.endswith(suffix):
                    stem = stem[:-len(suffix)]
                    break
            spec_id = f"{package_path}.composites.{stem}"
            try:
                spec = load_spec(path)
                if not isinstance(spec, dict) or "state" not in spec or "name" not in spec:
                    continue
                out[spec_id] = {
                    "id": spec_id,
                    "name": spec.get("name"),
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters") or {},
                    "requires": spec.get("requires") or {},
                    "source": str(path.relative_to(ws_root)),
                    "_state": spec.get("state"),  # internal; used for build
                }
            except Exception:
                pass
    return out


def _cast(value: Any, declared_type: str | None) -> Any:
    if declared_type == "float":
        return float(value)
    if declared_type == "int":
        return int(value)
    if declared_type in ("string", "str"):
        return str(value)
    if declared_type == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)
    return value


def substitute_parameters(state: Any, params: dict, overrides: dict | None = None) -> Any:
    overrides = overrides or {}
    if isinstance(state, dict):
        return {k: substitute_parameters(v, params, overrides) for k, v in state.items()}
    if isinstance(state, list):
        return [substitute_parameters(v, params, overrides) for v in state]
    if isinstance(state, str):
        m = _FULL_PLACEHOLDER.match(state)
        if m:
            pname = m.group(1)
            pdef = params.get(pname, {})
            raw = overrides.get(pname, pdef.get("default"))
            return _cast(raw, pdef.get("type"))
        if _INLINE_PLACEHOLDER.search(state):
            return _INLINE_PLACEHOLDER.sub(
                lambda mm: str(overrides.get(mm.group(1), params.get(mm.group(1), {}).get("default", ""))),
                state,
            )
    return state
