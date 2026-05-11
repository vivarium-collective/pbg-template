"""Render reports/index.html for the workspace dashboard.

v0.3.0: workspace IS the model. Single dashboard only — no per-model deep dives.
v0.4.1: imports moved to Registry tab; _pending_entries() removed (dead code).

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


# _next_step_hint() removed in v0.4.4. Each tab's page-lead + the workstream
# strip + Build Model's per-phase action buttons carry the "what next" signal
# contextually; a separate top-of-page banner duplicated the information and
# accumulated stale wording.


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


_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def _human_size(n: int) -> str:
    """Render a byte count as e.g. '314 KB' or '1.2 MB'."""
    size = float(n)
    for unit in _SIZE_UNITS:
        if size < 1024.0 or unit == _SIZE_UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}" if size < 10 else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{int(size)} TB"


def _enrich_with_file_info(entries: list[dict], ws_root: Path) -> list[dict]:
    """For each entry with a 'path' field, attach file_exists / size_bytes / size_human / sha256_valid.

    Used to render datasets, expert_docs, references_pdfs with file-presence indicators
    instead of plain links the user has to click to verify.
    """
    out = []
    for raw in entries:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        e = dict(raw)  # don't mutate the original
        path = e.get("path")
        if not path:
            e["file_exists"] = None
            e["size_human"] = None
            e["sha256_valid"] = None
            out.append(e)
            continue
        abs_path = (ws_root / path) if not Path(path).is_absolute() else Path(path)
        if not abs_path.exists():
            e["file_exists"] = False
            e["size_human"] = None
            e["sha256_valid"] = None
            out.append(e)
            continue
        try:
            size = abs_path.stat().st_size
            e["file_exists"] = True
            e["size_bytes"] = size
            e["size_human"] = _human_size(size)
        except OSError:
            e["file_exists"] = None
            e["size_human"] = None
        # sha256 check is optional — only validate if metadata declares one.
        declared = e.get("sha256")
        if declared and e.get("file_exists"):
            try:
                import hashlib as _hashlib
                h = _hashlib.sha256()
                with abs_path.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                e["sha256_valid"] = h.hexdigest() == declared
            except OSError:
                e["sha256_valid"] = None
        else:
            e["sha256_valid"] = None
        out.append(e)
    return out


def _detect_github_repo(ws_root: Path) -> str | None:
    """Parse `git remote get-url origin` and return 'owner/repo' if GitHub, else None."""
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ws_root, capture_output=True, text=True, check=True,
        )
        url = r.stdout.strip()
        # SSH: git@github.com:owner/repo.git
        import re
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


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

    references_count = _count_bib_entries(ws_root)
    datasets = _enrich_with_file_info(ws.get("datasets") or [], ws_root)
    expert_docs = _enrich_with_file_info(ws.get("expert_docs") or [], ws_root)
    references_pdfs = _enrich_with_file_info(ws.get("references_pdfs") or [], ws_root)
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
    ))
    return out
