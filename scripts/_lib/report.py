"""Render reports/index.html for the workspace dashboard.

v0.3.0: workspace IS the model. Single dashboard only — no per-model deep dives.
  Adds _pending_entries() for pending-visibility: unmerged stage/* branches surface
  their new entries in the dashboard with a "(pending review)" badge.

Public API:
  render_workspace_report(ws_root=None, *, today=None) -> Path
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
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
    """Compute a short hint for the wizard panel based on workspace state (v0.3.0: top-level)."""
    imports = ws.get("imports", {}) or {}
    observables = ws.get("observables", []) or []
    visualizations = ws.get("visualizations", []) or []
    phases = ws.get("phases", []) or []

    if not imports and not observables and not visualizations and not phases:
        return {
            "label": "Add workspace inputs — import external models or register datasets, references, expert docs",
            "command": "bash scripts/serve.sh  # open the dashboard and use the + Add buttons",
            "details": "If your project builds on an existing model, register it as an import. Otherwise, start by adding observables (Setup).",
        }
    if not observables:
        return {
            "label": "Add observables (Setup step 1)",
            "command": "(dashboard) + Add observable\n(plugin) /pbg-add-observable",
            "details": "Pick which state variables to track (e.g. chromosome.DnaA_count).",
        }
    if not visualizations:
        return {
            "label": "Add visualizations (Setup step 2)",
            "command": "(dashboard) + Add visualization",
            "details": "Define how to render the observables (time-series, phase-space, heatmap, histogram).",
        }
    if not phases:
        return {
            "label": "Plan mechanism integration phases",
            "command": "bash scripts/add-phase-plan.sh   # or use dashboard + Add phase",
            "details": "Lay out the mechanisms to integrate, each backed by an expert doc or dataset.",
        }
    for p in phases:
        if p.get("status") != "complete":
            return {
                "label": f"Phase {p['n']} ({p['name']}): {p.get('status', '?')}",
                "command": f"bash scripts/start-phase.sh {p['n']}    # then evaluate-phase-gate.sh when done",
                "details": "",
            }
    return {
        "label": "All planned phases complete",
        "command": "Add more phases via the dashboard, or publish the workspace.",
        "details": "",
    }


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


def _load_registry(ws_root: Path, package_path: str | None) -> tuple[dict, str | None]:
    """Try to import the workspace package and call build_core()/registry_snapshot().

    package_path: e.g. 'pbg_chromosome_rep1' (the Python package directory name).
    Returns (registry_dict, warning_or_None).
    """
    if not package_path:
        return {"processes": [], "types": []}, None

    ws_root_str = str(ws_root)
    injected = ws_root_str not in sys.path
    if injected:
        sys.path.insert(0, ws_root_str)
    try:
        core = importlib.import_module(f"{package_path}.core")
        build_core = getattr(core, "build_core", None)
        registry_snapshot = getattr(core, "registry_snapshot", None)
        if build_core is None or registry_snapshot is None:
            return {"processes": [], "types": []}, (
                f"{package_path}.core imported but missing build_core() or registry_snapshot()."
            )
        build_core()
        snap = registry_snapshot()

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
            f"Package '{package_path}' is not importable — registry shown as empty. "
            "Install it in the workspace venv or run /pbg-pull-processes."
        )
        return {"processes": [], "types": []}, warning
    except Exception as exc:
        warning = f"{package_path}.core raised {type(exc).__name__}: {exc}"
        return {"processes": [], "types": []}, warning
    finally:
        if injected and ws_root_str in sys.path:
            sys.path.remove(ws_root_str)


def _load_document(ws_root: Path, package_path: str | None) -> dict:
    """Try to call <package_path>.document.build_document(); return {} on any error."""
    if not package_path:
        return {}
    ws_root_str = str(ws_root)
    injected = ws_root_str not in sys.path
    if injected:
        sys.path.insert(0, ws_root_str)
    try:
        doc_mod = importlib.import_module(f"{package_path}.document")
        build_document = getattr(doc_mod, "build_document", None)
        if build_document is None:
            return {}
        return build_document() or {}
    except Exception:
        return {}
    finally:
        if injected and ws_root_str in sys.path:
            sys.path.remove(ws_root_str)


def _read_phases(ws_root: Path) -> list[dict]:
    """Read all phases/phase-*.md files at workspace root; parse frontmatter; sort by n."""
    phases_dir = ws_root / "phases"
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
            try:
                import re
                text = pf.read_text().replace("\r\n", "\n")
                m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    phases.append(fm)
            except Exception:
                pass

    def _phase_num(p):
        return int(p.get("phase", p.get("n", 0)))

    phases.sort(key=_phase_num)
    for p in phases:
        if "phase" in p and "n" not in p:
            p["n"] = p["phase"]
        elif "n" in p and "phase" not in p:
            p["phase"] = p["n"]
    return phases


def _current_phase(phases: list[dict]) -> dict | None:
    """Pick the 'current' phase: first in_progress, else first non-complete, else last."""
    if not phases:
        return None
    for p in phases:
        if p.get("status") == "in_progress":
            return p
    for p in phases:
        if p.get("status") != "complete":
            return p
    return phases[-1]  # all complete


def _phase_details(ws_root: Path) -> list[dict]:
    """For each phase entry, parse phases/phase-<n>.md to extract body sections."""
    from .phase_md import parse_phase_md
    out = []
    phases_dir = ws_root / "phases"
    if not phases_dir.is_dir():
        return out
    for f in sorted(phases_dir.glob("phase-*.md")):
        try:
            fm, body = parse_phase_md(f.read_text())
        except Exception:
            continue
        out.append({
            "frontmatter": fm,
            "body": body,
            "n": fm.get("phase", fm.get("n")),
        })
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


def _pending_entries(ws_root: Path) -> dict:
    """Walk unmerged stage/* branches; diff against main's workspace.yaml.

    Returns a dict keyed by panel name, each value a list of
    {"entry": <dict>, "branch": <str>} objects for new-on-branch entries.
    """
    try:
        main_text = subprocess.run(
            ["git", "show", "main:workspace.yaml"],
            cwd=ws_root, capture_output=True, text=True, check=True,
        ).stdout
        main_ws = yaml.safe_load(main_text) or {}
    except Exception:
        return {}

    def _key_set(items, key):
        return {item.get(key) for item in (items or []) if isinstance(item, dict)}

    main_obs_names = _key_set(main_ws.get("observables"), "name")
    main_viz_names = _key_set(main_ws.get("visualizations"), "name")
    main_phase_ns = {p.get("n") for p in (main_ws.get("phases") or []) if isinstance(p, dict)}
    main_ds_names = _key_set(main_ws.get("datasets"), "name")
    main_pdf_keys = _key_set(main_ws.get("references_pdfs"), "bib_key")
    main_edoc_names = _key_set(main_ws.get("expert_docs"), "name")
    main_import_names = set((main_ws.get("imports") or {}).keys())

    try:
        raw = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/stage/"],
            cwd=ws_root, capture_output=True, text=True, check=True,
        ).stdout
        stage_branches = [b.strip() for b in raw.splitlines() if b.strip()]
    except Exception:
        return {}

    pending: dict = {
        "observables": [],
        "visualizations": [],
        "phases": [],
        "datasets": [],
        "references_pdfs": [],
        "expert_docs": [],
        "imports": [],
    }

    for branch in stage_branches:
        try:
            branch_text = subprocess.run(
                ["git", "show", f"{branch}:workspace.yaml"],
                cwd=ws_root, capture_output=True, text=True, check=True,
            ).stdout
            branch_ws = yaml.safe_load(branch_text) or {}
        except Exception:
            continue

        for item in (branch_ws.get("observables") or []):
            if isinstance(item, dict) and item.get("name") not in main_obs_names:
                pending["observables"].append({"entry": item, "branch": branch})

        for item in (branch_ws.get("visualizations") or []):
            if isinstance(item, dict) and item.get("name") not in main_viz_names:
                pending["visualizations"].append({"entry": item, "branch": branch})

        for item in (branch_ws.get("phases") or []):
            if isinstance(item, dict) and item.get("n") not in main_phase_ns:
                pending["phases"].append({"entry": item, "branch": branch})

        for item in (branch_ws.get("datasets") or []):
            if isinstance(item, dict) and item.get("name") not in main_ds_names:
                pending["datasets"].append({"entry": item, "branch": branch})

        for item in (branch_ws.get("references_pdfs") or []):
            if isinstance(item, dict) and item.get("bib_key") not in main_pdf_keys:
                pending["references_pdfs"].append({"entry": item, "branch": branch})

        for item in (branch_ws.get("expert_docs") or []):
            if isinstance(item, dict) and item.get("name") not in main_edoc_names:
                pending["expert_docs"].append({"entry": item, "branch": branch})

        for imp_name, imp_val in (branch_ws.get("imports") or {}).items():
            if imp_name not in main_import_names:
                pending["imports"].append({"entry": {"name": imp_name, **(imp_val or {})}, "branch": branch})

    return pending


def render_workspace_report(ws_root: Path | None = None, *, today: str | None = None) -> Path:
    """Build <ws_root>/reports/index.html from workspace.yaml + pending branches."""
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
    imports = ws.get("imports") or {}
    observables = ws.get("observables") or []
    visualizations = ws.get("visualizations") or []
    simulations = ws.get("simulations") or []
    package_path = ws.get("package_path")

    # Read phases from phase-*.md files; fall back to workspace.yaml phases list.
    phases = _read_phases(ws_root)
    if not phases:
        phases = ws.get("phases") or []

    # Load registry from workspace package.
    registry, registry_warning = _load_registry(ws_root, package_path)
    pbg_doc = _load_document(ws_root, package_path)

    # Pending visibility: collect entries from unmerged stage/* branches.
    try:
        pending = _pending_entries(ws_root)
    except Exception:
        pending = {}

    current_phase = _current_phase(phases)
    phase_details = _phase_details(ws_root)

    out.write_text(tpl.render(
        workspace_name=ws["name"],
        workspace_description=ws.get("description", ""),
        generated_at=today,
        imports=imports,
        datasets=datasets,
        references_count=references_count,
        references_pdfs=references_pdfs,
        decisions=decisions,
        next_step=hint,
        expert_docs=expert_docs,
        observables=observables,
        visualizations=visualizations,
        simulations=simulations,
        phases=phases,
        current_phase=current_phase,
        phase_details=phase_details,
        package_path=package_path,
        registry=registry,
        registry_warning=registry_warning,
        pbg_doc_json=json.dumps(pbg_doc, indent=2, default=str),
        pending=pending,
    ))
    return out
