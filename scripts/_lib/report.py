"""Render reports/index.html for the workspace dashboard (Wave 2, v0.1.4).

Per-model dashboards are not included in v0.1.4 — only the workspace report.
Public API: render_workspace_report(ws_root=None, *, today=None) -> Path
"""
from __future__ import annotations

import shutil
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
    out.write_text(tpl.render(
        workspace_name=ws["name"],
        generated_at=today,
        models=ws.get("models", {}),
        imports=ws.get("imports", {}),
        decisions=decisions,
        next_step=hint,
    ))
    return out
