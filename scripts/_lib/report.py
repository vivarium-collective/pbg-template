"""Render reports/index.html for the workspace dashboard and per-model deep dives.

v0.1.4: workspace report only.
v0.1.6: adds per-model report (phase tracker, registries, browsable PBG document).

Public API:
  render_workspace_report(ws_root=None, *, today=None) -> Path
  render_model_report(model_name, ws_root=None, *, today=None) -> Path
"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
import warnings
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ._root import workspace_root


def _ws_root() -> Path:
    return workspace_root()


def _next_step_hint(ws: dict) -> dict:
    """Compute a short hint for the wizard panel based on workspace state."""
    models = ws.get("models", {}) or {}
    imports = ws.get("imports", {}) or {}

    if not imports and not models:
        return {
            "label": "Stage 0.5 — Import an existing model (optional) OR jump to Stage 1+2",
            "command": "(plugin) /pbg-import-models <name> --source <url> --ref <ref> --mode reference\n(no-plugin) python3 -c \"...\"  — see NEXT_STEPS.md",
            "details": "If your project builds on an existing model, register it now. Otherwise, scaffold your first model with /pbg-add-model.",
        }
    if not models:
        return {
            "label": "Stage 1+2 — Add your first model",
            "command": "/pbg-add-model <name>  — or scaffold by hand from pbg-superpowers/templates/model/",
            "details": "Each model lives under models/<name>/ as its own git submodule.",
        }

    # Pick the first model with an incomplete stage
    canonical = ["pull_processes", "data", "expert_input", "baseline", "phase_plan"]
    stage_to_script = {
        "data": "scripts/add-dataset.sh + scripts/add-reference.sh",
        "expert_input": "scripts/add-acceptance.sh",
        "phase_plan": "scripts/add-phase-plan.sh",
    }
    for model_name, m in models.items():
        stages = m.get("stages", {})
        for stg in canonical:
            if stages.get(stg, {}).get("status") != "complete":
                hint = {
                    "label": f"Model '{model_name}': Stage {stg.replace('_', '-')}",
                    "command": stage_to_script.get(stg, f"(plugin) /pbg-{stg.replace('_', '-')} {model_name}"),
                    "details": "",
                }
                return hint
        # All canonical stages complete; check phases
        phases = m.get("phases", []) or []
        if not phases:
            return {
                "label": f"Model '{model_name}': Stage 8 — phase plan",
                "command": f"bash scripts/add-phase-plan.sh   # then enter '{model_name}'",
                "details": "Lay out the multi-phase model-extension plan.",
            }
        for p in phases:
            if p["status"] != "complete":
                return {
                    "label": f"Model '{model_name}' phase {p['n']} ({p['name']}): {p['status']}",
                    "command": f"bash scripts/start-phase.sh {model_name} {p['n']}    # then evaluate-phase-gate.sh when done",
                    "details": "",
                }
        return {
            "label": f"Model '{model_name}': all planned phases complete",
            "command": "Edit phases/plan.md to add more phases, or move on to the next model.",
            "details": "",
        }
    return {"label": "(unknown)", "command": "", "details": ""}


def _env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
        keep_trailing_newline=True,
    )


def _copy_assets(target_dir: Path) -> None:
    src = _ws_root() / "scripts" / "_templates" / "_assets"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "render-helpers.js"):
        shutil.copy2(src / name, target_dir / name)
    walkthrough = _ws_root() / "scripts" / "_server" / "walkthrough.js"
    if walkthrough.exists():
        shutil.copy2(walkthrough, target_dir / "walkthrough.js")
    client_js = _ws_root() / "scripts" / "_server" / "client.js"
    if client_js.exists():
        shutil.copy2(client_js, target_dir / "client.js")


def _load_model_registry(slug: str, model_dir: Path) -> tuple[dict, str | None]:
    """Try to import pbg_<slug>.core and call build_core()/registry_snapshot().

    Returns (registry_dict, warning_or_None).
    registry_dict has keys 'processes' (list[str]) and 'types' (list[str]).
    """
    # Ensure model dir is on sys.path so a local (not-installed) package can be found.
    model_dir_str = str(model_dir)
    injected = model_dir_str not in sys.path
    if injected:
        sys.path.insert(0, model_dir_str)
    try:
        core = importlib.import_module(f"pbg_{slug}.core")
        build_core = getattr(core, "build_core", None)
        registry_snapshot = getattr(core, "registry_snapshot", None)
        if build_core is None or registry_snapshot is None:
            return {"processes": [], "types": []}, (
                f"pbg_{slug}.core imported but missing build_core() or registry_snapshot()."
            )
        build_core()
        snap = registry_snapshot()
        # Normalise: accept list of strings or list of dicts with 'name' key.
        def _names(items):
            if not items:
                return []
            if isinstance(items[0], str):
                return list(items)
            return [it.get("name", str(it)) for it in items]
        return {
            "processes": _names(snap.get("processes", [])),
            "types": _names(snap.get("types", [])),
        }, None
    except ModuleNotFoundError:
        warning = (
            f"Package pbg_{slug} is not importable — registry shown as empty. "
            f"Install it in the workspace venv or run /pbg-pull-processes."
        )
        return {"processes": [], "types": []}, warning
    except Exception as exc:
        warning = f"pbg_{slug}.core raised {type(exc).__name__}: {exc}"
        return {"processes": [], "types": []}, warning
    finally:
        if injected and model_dir_str in sys.path:
            sys.path.remove(model_dir_str)


def _load_model_document(slug: str, model_dir: Path) -> dict:
    """Try to call pbg_<slug>.document.build_document(); return {} on any error."""
    model_dir_str = str(model_dir)
    injected = model_dir_str not in sys.path
    if injected:
        sys.path.insert(0, model_dir_str)
    try:
        doc_mod = importlib.import_module(f"pbg_{slug}.document")
        build_document = getattr(doc_mod, "build_document", None)
        if build_document is None:
            return {}
        return build_document() or {}
    except Exception:
        return {}
    finally:
        if injected and model_dir_str in sys.path:
            sys.path.remove(model_dir_str)


def _read_phases(model_dir: Path) -> list[dict]:
    """Read all phases/phase-*.md files; parse frontmatter; sort by phase number."""
    phases_dir = model_dir / "phases"
    if not phases_dir.exists():
        return []
    phase_files = sorted(phases_dir.glob("phase-*.md"))
    phases = []
    for pf in phase_files:
        try:
            from .phase_md import parse_phase_md
            fm, _ = parse_phase_md(pf.read_text())
            phases.append(fm)
        except Exception:
            # If parsing fails (e.g. schema mismatch), fall back to raw YAML
            try:
                import re
                text = pf.read_text().replace("\r\n", "\n")
                m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    phases.append(fm)
            except Exception:
                pass
    # Sort by 'phase' key (int); fall back to 'n' for compatibility.
    def _phase_num(p):
        return int(p.get("phase", p.get("n", 0)))
    phases.sort(key=_phase_num)
    # Normalise key: ensure both 'n' and 'phase' point to the same number.
    for p in phases:
        if "phase" in p and "n" not in p:
            p["n"] = p["phase"]
        elif "n" in p and "phase" not in p:
            p["phase"] = p["n"]
    return phases


def _stage_progression(ws: dict) -> list[dict]:
    """Compute progress for the 9-stage track."""
    steps = [
        {"label": "0 · bootstrap", "key": "workspace_bootstrap"},
        {"label": "0.5 · imports", "key": "imports", "optional": True},
        {"label": "1+2 · model", "key": "models"},
        {"label": "3 · processes", "key": "pull_processes"},
        {"label": "4 · data", "key": "data"},
        {"label": "5 · refs", "key": "data"},  # data = stage 4+5 (combined)
        {"label": "5+ · expert docs", "key": "expert_docs", "optional": True},
        {"label": "6 · expert input", "key": "expert_input"},
        {"label": "7 · baseline", "key": "baseline"},
        {"label": "8+ · phases", "key": "phases"},
    ]
    models = ws.get("models", {}) or {}
    imports = ws.get("imports", {}) or {}
    expert_docs = ws.get("expert_docs", []) or []

    has_models = bool(models)
    bootstrap_done = ws.get("stages", {}).get("workspace_bootstrap", {}).get("status") == "complete"

    def model_stage_done(stage_key):
        if not models:
            return False
        return any(m.get("stages", {}).get(stage_key, {}).get("status") == "complete" for m in models.values())

    def model_stage_partial(stage_key):
        if not models:
            return False
        return any(m.get("stages", {}).get(stage_key, {}).get("status") == "in_progress" for m in models.values())

    out = []
    next_marked = False
    for step in steps:
        key = step["key"]
        if key == "workspace_bootstrap":
            cls = "done" if bootstrap_done else "todo"
        elif key == "imports":
            cls = "done" if imports else "todo"
        elif key == "models":
            cls = "done" if has_models else "todo"
        elif key == "expert_docs":
            cls = "done" if expert_docs else "todo"
        elif key == "phases":
            phases = []
            for m in models.values():
                phases.extend(m.get("phases", []) or [])
            if not phases:
                cls = "todo"
            elif all(p.get("status") == "complete" for p in phases):
                cls = "done"
            else:
                cls = "partial"
        else:
            if model_stage_done(key):
                cls = "done"
            elif model_stage_partial(key):
                cls = "partial"
            else:
                cls = "todo"

        # Promote the first non-done step to "next"
        if cls == "todo" and not next_marked:
            cls = "next"
            next_marked = True

        out.append({"label": step["label"], "cls": cls, "optional": step.get("optional", False)})
    return out


def _count_bib_entries(ws_root: Path) -> int:
    """Count @-entries in references/papers.bib."""
    bib_file = ws_root / "references" / "papers.bib"
    if not bib_file.exists():
        return 0
    try:
        text = bib_file.read_text()
        return sum(1 for line in text.splitlines() if line.strip().startswith("@"))
    except Exception:
        return 0


def render_workspace_report(ws_root: Path | None = None, *, today: str | None = None) -> Path:
    """Build <ws_root>/reports/index.html from workspace.yaml + decisions log."""
    ws_root = ws_root or _ws_root()
    today = today or date.today().isoformat()
    ws = yaml.safe_load((ws_root / "workspace.yaml").read_text())
    decisions_file = ws_root / "docs" / "decisions.yaml"
    decisions = (
        (yaml.safe_load(decisions_file.read_text()) or {}).get("decisions", [])
        if decisions_file.exists() else []
    )
    template_dir = ws_root / "scripts" / "_templates"
    env = _env(template_dir)
    tpl = env.get_template("index.html.j2")
    out = ws_root / "reports" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    _copy_assets(ws_root / "reports" / "assets")
    hint = _next_step_hint(ws)
    references_count = _count_bib_entries(ws_root)
    datasets = ws.get("datasets") or []
    expert_docs = ws.get("expert_docs") or []
    references_pdfs = ws.get("references_pdfs") or []
    stage_progression = _stage_progression(ws)
    out.write_text(tpl.render(
        workspace_name=ws["name"],
        generated_at=today,
        models=ws.get("models", {}),
        imports=ws.get("imports", {}),
        datasets=datasets,
        references_count=references_count,
        references_pdfs=references_pdfs,
        decisions=decisions,
        next_step=hint,
        expert_docs=expert_docs,
        stage_progression=stage_progression,
    ))
    return out


def render_model_report(
    model_name: str,
    ws_root: Path | None = None,
    *,
    today: str | None = None,
) -> Path:
    """Build models/<model_name>/reports/index.html.

    Handles import fallback: if pbg_<slug> can't be imported, renders with an
    empty registry and a visible warning in the HTML.
    """
    ws_root = ws_root or _ws_root()
    today = today or date.today().isoformat()

    ws = yaml.safe_load((ws_root / "workspace.yaml").read_text())
    models = ws.get("models") or {}
    if model_name not in models:
        raise RuntimeError(
            f"Model '{model_name}' not found in workspace.yaml. "
            f"Available models: {list(models.keys())}"
        )

    slug = model_name.replace("-", "_")
    model_dir = ws_root / "models" / model_name

    registry, registry_warning = _load_model_registry(slug, model_dir)
    pbg_doc = _load_model_document(slug, model_dir)

    # Read phases from phase-*.md files; fall back to workspace.yaml phases list.
    phases = _read_phases(model_dir)
    if not phases:
        # Fallback: use whatever is in workspace.yaml (may be an empty list)
        phases = models[model_name].get("phases") or []

    template_dir = ws_root / "scripts" / "_templates"
    env = _env(template_dir)
    tpl = env.get_template("model_index.html.j2")

    out = ws_root / "models" / model_name / "reports" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    _copy_assets(ws_root / "models" / model_name / "reports" / "assets")

    # Load acceptance tests from expert/acceptance.yaml if present.
    acceptance_file = model_dir / "expert" / "acceptance.yaml"
    acceptance_tests: list = []
    if acceptance_file.exists():
        try:
            acceptance_tests = yaml.safe_load(acceptance_file.read_text()) or []
        except Exception:
            acceptance_tests = []

    out.write_text(tpl.render(
        model_name=model_name,
        generated_at=today,
        phases=phases,
        registry=registry,
        registry_warning=registry_warning,
        pbg_doc_json=json.dumps(pbg_doc, indent=2, default=str),
        acceptance_tests=acceptance_tests,
    ))
    return out
