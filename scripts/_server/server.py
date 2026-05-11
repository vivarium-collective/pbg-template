"""Local HTTP server: serves reports/, exposes /api/state, /api/events SSE, /api/guidance.

v0.1.7: adds mutating POST endpoints with auto-branch/commit, /api/branches, /api/run-tests,
and /api/render for post-action page reload.
v0.1.9: drag-drop file uploads (base64) + sha256 reproducibility for datasets, references PDFs,
and expert docs.
v0.1.10: PDF-first reference flow (/api/reference-pdf); legacy BibTeX paste renamed to
/api/reference-bibtex; BibTeX auto-generated from typed metadata via _lib.bibtex.
v0.1.12: /api/reference-pdf is now drop-and-go; pypdf extracts metadata from the PDF so no
typed fields are required. Auto-generates bib_key. Sets _metadata_pending flag when extraction
is incomplete.
v0.3.0: schema v2 — workspace IS the model. All endpoints drop model scoping.
  /api/observable, /api/visualization, /api/phase-plan, /api/phase-start, /api/phase-gate,
  /api/run-tests now operate on top-level workspace state directly. Pending-visibility helper
  added: unmerged stage/* branches surface entries with a "(pending review)" badge.
v0.3.7-A: /api/import-install — pip-install an import into the workspace venv; marks
  installed=True + install_path in workspace.yaml; invalidates registry cache.
v0.4.1: /api/catalog (GET) + /api/catalog-install (POST) — Registry as package manager.
  Catalog browsing + one-click submodule add + pip install + pyproject.toml edit.
v0.4.2: Visualization lifecycle — Create/Add/Commit.
  /api/visualization-create (POST), /api/visualization-status (GET),
  /api/visualization-add-to-project (POST), /api/visualization-commit-batch (POST).
  description becomes the only required field alongside name; structured fields optional.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

import yaml


# ---------------------------------------------------------------------------
# Registry cache (module-level, shared across requests)
# ---------------------------------------------------------------------------

_REGISTRY_CACHE: dict = {"data": None, "ts": 0.0}
_REGISTRY_TTL = 30.0  # seconds


def _get_registry_data(bypass_cache: bool = False) -> dict:
    """Return registry data from build_core() subprocess, with 30s caching.

    Always returns {processes: [...], types: [...]} plus optional 'error' key.
    Never raises.
    """
    global _REGISTRY_CACHE
    now = time.time()
    if not bypass_cache and _REGISTRY_CACHE["data"] is not None:
        if now - _REGISTRY_CACHE["ts"] < _REGISTRY_TTL:
            return _REGISTRY_CACHE["data"]

    try:
        ws_yaml = WORKSPACE / "workspace.yaml"
        ws_data = yaml.safe_load(ws_yaml.read_text())
        slug = ws_data.get("name", "")
        # Support explicit package_path in workspace.yaml (most reliable).
        package_name = ws_data.get("package_path") or ("pbg_" + slug.replace("-", "_"))

        py = sys.executable
        script = textwrap.dedent(f"""
import json, sys
try:
    from {package_name}.core import build_core
    core = build_core()

    # Processes (and other linkable components) live in core.link_registry,
    # a dict keyed by both short names ('Composite') and fully-qualified
    # names ('process_bigraph.composite.Composite'). Dedupe by class identity
    # and prefer the short name.
    processes = []
    seen_classes = {{}}
    link_reg = getattr(core, 'link_registry', {{}}) or {{}}
    for name, cls in link_reg.items():
        cls_id = id(cls)
        is_qualified = '.' in name
        if cls_id in seen_classes:
            # already saw this class; only update if current name is shorter (preferred)
            existing = seen_classes[cls_id]
            if not is_qualified and '.' in processes[existing]['name']:
                processes[existing]['aliases'].append(processes[existing]['name'])
                processes[existing]['name'] = name
            else:
                processes[existing]['aliases'].append(name)
            continue
        try:
            addr = f"{{cls.__module__}}.{{cls.__qualname__}}"
        except Exception:
            addr = str(cls)
        schema_preview = ""
        if hasattr(cls, 'config_schema'):
            try:
                schema_preview = json.dumps(cls.config_schema, default=str)[:200]
            except Exception:
                schema_preview = ""
        seen_classes[cls_id] = len(processes)
        processes.append({{
            "name": name,
            "address": addr,
            "schema_preview": schema_preview,
            "aliases": [],
        }})
    # Re-sort by name so output is deterministic; promote short names.
    processes.sort(key=lambda p: ('.' in p['name'], p['name']))

    # Types: core.registry is a dict of registered type schemas.
    types = []
    type_reg = getattr(core, 'registry', {{}}) or {{}}
    for name in sorted(type_reg.keys()):
        try:
            td = core.access(name)
            preview = str(td)[:200] if td is not None else ""
        except Exception as e:
            preview = f"<error: {{e}}>"
        types.append({{"name": name, "schema_preview": preview}})

    print(json.dumps({{"processes": processes, "types": types}}))
except ImportError as e:
    print(json.dumps({{"error": f"could not import {package_name}.core: {{e}}", "processes": [], "types": []}}))
except Exception as e:
    print(json.dumps({{"error": f"build_core() failed: {{e}}", "processes": [], "types": []}}))
""")
        result = subprocess.run(
            [py, "-c", script],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            data: dict = {
                "error": f"subprocess failed: {(result.stderr or '').strip()[:300]}",
                "processes": [],
                "types": [],
            }
        else:
            try:
                last_line = result.stdout.strip().split("\n")[-1]
                data = json.loads(last_line)
            except (json.JSONDecodeError, IndexError):
                data = {
                    "error": f"invalid output: {result.stdout[:300]}",
                    "processes": [],
                    "types": [],
                }
    except Exception as e:
        data = {"error": str(e), "processes": [], "types": []}

    _REGISTRY_CACHE["data"] = data
    _REGISTRY_CACHE["ts"] = now
    return data


def _save_upload(file_b64: str, target_path: Path) -> str:
    """Decode base64-encoded file content, write to target_path, return sha256."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(file_b64)
    target_path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


WORKSPACE: Path = Path("/")  # set by main()
LOCK = Lock()


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _is_generated_path(path: str) -> bool:
    """True if `path` is a generated report file (the dashboard rebuilds these
    on every page load, so they're chronically dirty and shouldn't block actions).
    """
    return path.startswith("reports/")


def _submodule_paths() -> set[str]:
    """Read .gitmodules and return the set of registered submodule paths.

    Submodule pointer movements show up as `M <path>` in `git status --porcelain`
    even when the user has only updated the submodule's HEAD (e.g., `git submodule
    update --remote`). These shouldn't block workspace-level actions.
    """
    gm = WORKSPACE / ".gitmodules"
    if not gm.exists():
        return set()
    paths: set[str] = set()
    for line in gm.read_text().splitlines():
        line = line.strip()
        if line.startswith("path"):
            _, _, val = line.partition("=")
            val = val.strip()
            if val:
                paths.add(val)
    return paths


def _has_origin_remote() -> bool:
    """True if a git remote named 'origin' is configured."""
    r = subprocess.run(
        ["git", "remote"],
        cwd=WORKSPACE, capture_output=True, text=True, check=False,
    )
    return "origin" in (r.stdout or "").split()


def _diagnose_push_error(err: str) -> dict | None:
    """Return a structured diagnosis for known push failure patterns, else None."""
    if not err:
        return None
    if "does not appear to be a git repository" in err or "Could not read from remote repository" in err:
        return {
            "category": "no_origin",
            "summary": "Push failed because no GitHub remote is configured.",
            "suggestion": "Click `Create GitHub repo` in the workstream strip to create one and push in one step.",
        }
    if "Permission to" in err and "denied" in err:
        return {
            "category": "auth",
            "summary": "Push denied — your git credential doesn't have write access.",
            "suggestion": "Run `gh auth login` (or check your SSH key / token) and try again.",
        }
    if "rejected" in err and ("non-fast-forward" in err or "behind" in err):
        return {
            "category": "behind",
            "summary": "Remote has commits your local branch doesn't.",
            "suggestion": "Pull/rebase first: `git pull --rebase origin <branch>`, then push.",
        }
    return None


def _dirty_workspace() -> str:
    """Return the porcelain status excluding generated reports + submodule pointers."""
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    submodules = _submodule_paths()
    kept = []
    for raw in status.splitlines():
        if len(raw) < 4:
            continue
        path = raw[3:]
        if _is_generated_path(path):
            continue
        if path in submodules:
            continue
        kept.append(raw)
    return "\n".join(kept)


def _safe_slug(s: str) -> str:
    """Convert a string to a safe branch name component."""
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40]


def _active_branch_action(commit_message: str, action_fn) -> tuple[dict, int]:
    """Run action_fn on the active workstream branch; commit; stay on it."""
    _ws_add_to_sys_path()
    from scripts._lib.work_state import load_state, save_state
    state = load_state()
    branch = state.get("active_branch")
    if not branch:
        return {"error": "no active workstream — click Start workstream at the top of the dashboard"}, 409

    # Make sure we're on the active branch (auto-recover from drift)
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if current != branch:
        r = subprocess.run(["git", "checkout", branch], cwd=WORKSPACE, capture_output=True, text=True)
        if r.returncode != 0:
            return {"error": f"could not check out workstream branch '{branch}': {r.stderr[:200]}"}, 500

    if _dirty_workspace().strip():
        return {"error": f"working tree dirty: {_dirty_workspace()[:300]}"}, 409

    try:
        action_fn()
        subprocess.run(["git", "add", "-A"], cwd=WORKSPACE, check=True, capture_output=True)
        subprocess.run(["git", "reset", "HEAD", "--", "reports/"], cwd=WORKSPACE, check=False, capture_output=True)
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        if not diff.strip():
            return {"error": "action made no changes (already at this state?)"}, 409
        subprocess.run([
            "git", "-c", "user.email=pbg-template@local",
                  "-c", "user.name=pbg-template",
                  "commit", "-m", commit_message,
        ], cwd=WORKSPACE, check=True, capture_output=True)
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Reload state (action_fn may have side-effects) and keep file fresh
        state = load_state()
        if state.get("active_branch") == branch:
            save_state(state)

        return {"branch": branch, "commit": commit_sha[:7], "message": commit_message}, 200
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return {"error": f"git operation failed: {stderr[:300]}"}, 500
    except Exception as e:
        return {"error": str(e)}, 500


# ---------------------------------------------------------------------------
# Pending visibility helper
# ---------------------------------------------------------------------------

def _pending_entries() -> dict:
    """Walk unmerged stage/* branches; diff against main's workspace.yaml.

    Returns a dict keyed by panel name, each value a list of
    {"entry": <dict>, "branch": <str>} objects for entries not on main.

    Panels: observables, visualizations, phases, datasets, references_pdfs,
            expert_docs, imports.
    """
    try:
        main_text = subprocess.run(
            ["git", "show", "main:workspace.yaml"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        main_ws = yaml.safe_load(main_text) or {}
    except Exception:
        return {}

    # Build uniqueness-key sets for main.
    def _key_set(items, key):
        return {item.get(key) for item in (items or []) if isinstance(item, dict)}

    main_obs_names = _key_set(main_ws.get("observables"), "name")
    main_viz_names = _key_set(main_ws.get("visualizations"), "name")
    main_phase_ns = {p.get("n") for p in (main_ws.get("phases") or []) if isinstance(p, dict)}
    main_ds_names = _key_set(main_ws.get("datasets"), "name")
    main_pdf_keys = _key_set(main_ws.get("references_pdfs"), "bib_key")
    main_edoc_names = _key_set(main_ws.get("expert_docs"), "name")
    main_import_names = set((main_ws.get("imports") or {}).keys())

    # Get all stage/* branches.
    try:
        raw = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/stage/"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
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
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout
            branch_ws = yaml.safe_load(branch_text) or {}
        except Exception:
            continue

        # Find new observables.
        for item in (branch_ws.get("observables") or []):
            if isinstance(item, dict) and item.get("name") not in main_obs_names:
                pending["observables"].append({"entry": item, "branch": branch})

        # Find new visualizations.
        for item in (branch_ws.get("visualizations") or []):
            if isinstance(item, dict) and item.get("name") not in main_viz_names:
                pending["visualizations"].append({"entry": item, "branch": branch})

        # Find new phases.
        for item in (branch_ws.get("phases") or []):
            if isinstance(item, dict) and item.get("n") not in main_phase_ns:
                pending["phases"].append({"entry": item, "branch": branch})

        # Find new datasets.
        for item in (branch_ws.get("datasets") or []):
            if isinstance(item, dict) and item.get("name") not in main_ds_names:
                pending["datasets"].append({"entry": item, "branch": branch})

        # Find new reference PDFs.
        for item in (branch_ws.get("references_pdfs") or []):
            if isinstance(item, dict) and item.get("bib_key") not in main_pdf_keys:
                pending["references_pdfs"].append({"entry": item, "branch": branch})

        # Find new expert docs.
        for item in (branch_ws.get("expert_docs") or []):
            if isinstance(item, dict) and item.get("name") not in main_edoc_names:
                pending["expert_docs"].append({"entry": item, "branch": branch})

        # Find new imports.
        for imp_name, imp_val in (branch_ws.get("imports") or {}).items():
            if imp_name not in main_import_names:
                pending["imports"].append({"entry": {"name": imp_name, **imp_val}, "branch": branch})

    return pending


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):  # silence default request logging
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._serve_file(WORKSPACE / "reports" / "index.html", "text/html")
        if self.path.startswith("/api/state"):
            return self._serve_state()
        if self.path.startswith("/api/events"):
            return self._serve_events_sse()
        if self.path.startswith("/api/guidance"):
            return self._serve_guidance()
        if self.path.startswith("/api/branches"):
            return self._serve_branches()
        if self.path.startswith("/api/branch-diff"):
            return self._get_branch_diff()
        if self.path.startswith("/api/pending"):
            return self._serve_pending()
        if self.path.startswith("/api/registry"):
            return self._get_registry()
        if self.path.startswith("/api/catalog"):
            return self._get_catalog()
        if self.path.startswith("/api/work-status"):
            return self._get_work_status()
        if self.path.startswith("/api/visualization-status"):
            return self._get_visualization_status()
        rel = self.path.lstrip("/")
        # Refuse path traversal and absolute paths.
        if ".." in rel.split("/") or rel.startswith("/"):
            self.send_response(403); self.end_headers(); return
        primary = WORKSPACE / rel
        if primary.is_file():
            return self._serve_file(primary, self._guess_mime(rel))
        fallback = WORKSPACE / "reports" / rel
        return self._serve_file(fallback, self._guess_mime(rel))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode()) if length else {}
        except json.JSONDecodeError as e:
            return self._json({"error": f"invalid JSON: {e}"}, 400)

        route_map = {
            "/api/click":              self._post_click,
            "/api/import":             self._post_import,
            "/api/import-install":     self._post_import_install,
            "/api/dataset":            self._post_dataset,
            "/api/reference-pdf":      self._post_reference_pdf,
            "/api/reference-bibtex":   self._post_reference,
            # Legacy alias kept for backward compat (v0.1.9 and earlier).
            "/api/reference":          self._post_reference,
            "/api/expert-doc":         self._post_expert_doc,
            "/api/phase-plan":         self._post_phase_plan,
            "/api/phase-start":        self._post_phase_start,
            "/api/phase-gate":         self._post_phase_gate,
            "/api/observable":         self._post_observable,
            "/api/visualization":                self._post_visualization,
            "/api/visualization-create":         self._post_visualization_create,
            "/api/visualization-add-to-project": self._post_visualization_add_to_project,
            "/api/visualization-commit-batch":   self._post_visualization_commit_batch,
            "/api/simulation":                   self._post_simulation,
            "/api/run-tests":          self._post_run_tests,
            "/api/render":             self._post_render,
            "/api/work-start":         self._post_work_start,
            "/api/work-push":          self._post_work_push,
            "/api/work-create-github-repo": self._post_work_create_github_repo,
            "/api/work-create-pr":     self._post_work_create_pr,
            "/api/work-end":           self._post_work_end,
            "/api/catalog-install":    self._post_catalog_install,
        }
        handler_fn = route_map.get(self.path)
        if handler_fn is None:
            return self._json({"error": "not found"}, 404)
        handler_fn(body)

    def do_DELETE(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode()) if length else {}
        except json.JSONDecodeError as e:
            return self._json({"error": f"invalid JSON: {e}"}, 400)

        route_map = {
            "/api/simulation":    self._delete_simulation,
            "/api/visualization": self._delete_visualization,
        }
        handler_fn = route_map.get(self.path)
        if handler_fn is None:
            return self._json({"error": "not found"}, 404)
        handler_fn(body)

    # ------------------------------------------------------------------
    # POST handlers
    # ------------------------------------------------------------------

    def _post_click(self, body: dict):
        with LOCK:
            events = WORKSPACE / ".pbg" / "server" / "state" / "events"
            events.parent.mkdir(parents=True, exist_ok=True)
            with events.open("a") as f:
                f.write(json.dumps(body) + "\n")
        self.send_response(204)
        self.end_headers()

    def _post_import(self, body: dict):
        """Register an import in the catalog (workspace.yaml.imports).

        NOTE: git submodule add is NOT performed here. Submodule operations
        require terminal access for network/auth reasons. After this call,
        run from your terminal:
          git submodule add <source> external/<name>   # for reference / in-place
        The response includes the exact command to run.
        """
        name = (body.get("name") or "").strip()
        source = (body.get("source") or "").strip()
        ref = (body.get("ref") or "").strip()
        mode = (body.get("mode") or "").strip()
        description = (body.get("description") or "").strip() or None

        if not all([name, source, ref, mode]):
            return self._json({"error": "name, source, ref, mode are required"}, 400)
        if mode not in ("reference", "fork-source", "in-place"):
            return self._json({"error": "mode must be one of: reference, fork-source, in-place"}, 400)
        if re.search(r'[^\w\-.]', name):
            return self._json({"error": "name must contain only word chars, hyphens, dots"}, 400)

        commit_msg = f"feat(0.5): register import '{name}' (mode={mode})"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.imports import register_import
            register_import(
                WORKSPACE, name=name, source=source, ref=ref, mode=mode,
                description=description,
            )

        resp, code = _active_branch_action(commit_msg, action)
        if code == 200:
            # Add guidance about submodule step.
            if mode in ("reference",):
                resp["next_terminal_step"] = f"git submodule add {source} external/{name}"
            elif mode == "in-place":
                resp["next_terminal_step"] = f"git submodule add {source} external/{name}"
            else:
                resp["next_terminal_step"] = "(fork-source: no submodule needed)"
            resp["note"] = (
                "git submodule add is NOT performed by the server (requires terminal for network/auth). "
                "Run 'next_terminal_step' from your workspace root to complete the import."
            )
        return self._json(resp, code)

    def _post_dataset(self, body: dict):
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)
        claims_raw = body.get("claims", "")
        if isinstance(claims_raw, str):
            claims = [c.strip() for c in claims_raw.split(",") if c.strip()]
        elif isinstance(claims_raw, list):
            claims = list(claims_raw)
        else:
            claims = []

        entry: dict = {"name": name, "claims": claims}

        file_b64 = body.get("file_b64", "").strip()
        filename = (body.get("filename") or "").strip()
        path = (body.get("path") or "").strip()
        url = (body.get("url") or "").strip()

        if file_b64:
            if not filename:
                return self._json({"error": "filename is required when file_b64 is provided"}, 400)
            dest_rel = f"datasets/{_safe_slug(name)}/{filename}"
            entry["path"] = dest_rel
        elif path:
            entry["path"] = path
        elif url:
            entry["url"] = url
            sha256 = body.get("sha256", "").strip()
            if sha256:
                entry["sha256"] = sha256
        else:
            return self._json({"error": "either file_b64, path, or url is required"}, 400)

        commit_msg = f"feat(4): register dataset '{name}'"

        def action():
            nonlocal entry
            if file_b64:
                dest = WORKSPACE / entry["path"]
                sha = _save_upload(file_b64, dest)
                entry["sha256"] = sha
            elif path and not file_b64:
                src = Path(path)
                if not src.is_absolute():
                    src = WORKSPACE / path
                if src.exists() and src.is_file():
                    import hashlib as _hashlib
                    h = _hashlib.sha256()
                    with src.open("rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h.update(chunk)
                    entry["sha256"] = h.hexdigest()

            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            datasets = ws.setdefault("datasets", [])
            if datasets is None:
                datasets = []
                ws["datasets"] = datasets
            for existing in datasets:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"dataset '{name}' already registered")
            datasets.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_reference_pdf(self, body: dict):
        """Drop-and-go PDF reference flow (v0.1.12)."""
        pdf_b64 = body.get("pdf_b64", "").strip()
        if not pdf_b64:
            return self._json({"error": "pdf_b64 is required"}, 400)

        import base64 as _base64
        raw_pdf = _base64.b64decode(pdf_b64)
        _ws_add_to_sys_path()
        from scripts._lib.pdf_metadata import extract_pdf_metadata, auto_bib_key, build_bibtex
        extracted = extract_pdf_metadata(raw_pdf)

        title = (body.get("title") or "").strip() or extracted.get("title", "")
        authors_input = (body.get("authors") or "").strip()
        if authors_input:
            authors = [a.strip() for a in re.split(r"[;|]| and ", authors_input) if a.strip()]
        else:
            authors = extracted.get("authors", [])
        year_raw = body.get("year")
        if year_raw is not None:
            try:
                year: int | None = int(year_raw)
            except (ValueError, TypeError):
                year = extracted.get("year")
        else:
            year = extracted.get("year")
        journal = (body.get("journal") or "").strip() or None
        doi = (body.get("doi") or "").strip() or None

        bib_key = (body.get("bib_key") or "").strip()
        if not bib_key:
            bib_key = auto_bib_key(authors, year)
        if not re.match(r"^[A-Za-z0-9_:\-]+$", bib_key):
            return self._json({"error": f"invalid bib_key: '{bib_key}'"}, 400)

        metadata_pending = (
            not title or not authors or not year or bib_key.startswith("_pending")
        )

        claim_mappings_raw = body.get("claim_mappings", [])
        if isinstance(claim_mappings_raw, str):
            claim_ids: list[str] = [c.strip() for c in claim_mappings_raw.split(",") if c.strip()]
        elif isinstance(claim_mappings_raw, list):
            claim_ids = [str(c).strip() for c in claim_mappings_raw if str(c).strip()]
        else:
            claim_ids = []

        commit_msg = f"feat(5): add reference '{bib_key}'"
        if metadata_pending:
            commit_msg += " (metadata pending)"

        def action():
            bib_file = WORKSPACE / "references" / "papers.bib"
            claims_file = WORKSPACE / "references" / "claims.yaml"
            pdf_dest_rel = f"references/papers/{bib_key}.pdf"
            pdf_dest = WORKSPACE / pdf_dest_rel

            if bib_file.exists():
                existing_text = bib_file.read_text()
                if re.search(rf"@\w+\{{{re.escape(bib_key)},", existing_text):
                    raise ValueError(f"BibTeX key '{bib_key}' already exists in papers.bib")

            sha = _save_upload(pdf_b64, pdf_dest)

            bibtex_entry = build_bibtex(bib_key, title, authors, year, journal, doi)
            bib_file.parent.mkdir(parents=True, exist_ok=True)
            existing_bib = bib_file.read_text() if bib_file.exists() else ""
            with bib_file.open("a") as f:
                if existing_bib and not existing_bib.endswith("\n"):
                    f.write("\n")
                f.write(bibtex_entry + "\n")

            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            refs_pdfs = ws.setdefault("references_pdfs", [])
            if refs_pdfs is None:
                refs_pdfs = []
                ws["references_pdfs"] = refs_pdfs
            if not any(e.get("bib_key") == bib_key for e in refs_pdfs):
                entry = {"bib_key": bib_key, "path": pdf_dest_rel, "sha256": sha}
                if metadata_pending:
                    entry["_metadata_pending"] = True
                refs_pdfs.append(entry)
            save_workspace(ws_file, ws)

            if claim_ids:
                import yaml as _yaml
                existing_claims: dict = {}
                if claims_file.exists():
                    try:
                        existing_claims = _yaml.safe_load(claims_file.read_text()) or {}
                    except Exception:
                        existing_claims = {}
                for claim_id in claim_ids:
                    existing_claims.setdefault(claim_id, [])
                    if bib_key not in existing_claims[claim_id]:
                        existing_claims[claim_id].append(bib_key)
                claims_file.parent.mkdir(parents=True, exist_ok=True)
                claims_file.write_text(_yaml.safe_dump(existing_claims, sort_keys=False))

        response, status = _active_branch_action(commit_msg, action)
        response["bib_key"] = bib_key
        response["metadata_pending"] = metadata_pending
        response["extracted"] = {k: v for k, v in extracted.items() if k != "raw"}
        return self._json(response, status)

    def _post_reference(self, body: dict):
        """Legacy BibTeX-paste reference flow (now also served as /api/reference-bibtex)."""
        bibtex_text = (body.get("bibtex_text") or "").strip()
        claim_mappings_raw = body.get("claim_mappings", {})
        pdf_b64 = body.get("pdf_b64", "").strip()

        if not bibtex_text:
            return self._json({"error": "bibtex_text is required"}, 400)

        m = re.search(r"@\w+\{([^,\s]+)", bibtex_text)
        if not m:
            return self._json({"error": "could not parse BibTeX key from bibtex_text"}, 400)
        bibkey = m.group(1).strip()

        if isinstance(claim_mappings_raw, str):
            claim_mappings: dict = {}
            for pair in claim_mappings_raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    cid, bkey = pair.split(":", 1)
                    claim_mappings[cid.strip()] = bkey.strip()
        else:
            claim_mappings = dict(claim_mappings_raw) if claim_mappings_raw else {}

        commit_msg = f"feat(5): add reference '{bibkey}'"

        def action():
            bib_file = WORKSPACE / "references" / "papers.bib"
            claims_file = WORKSPACE / "references" / "claims.yaml"

            if bib_file.exists():
                existing_text = bib_file.read_text()
                if f"{{{bibkey}," in existing_text or f"{{{bibkey} " in existing_text:
                    raise ValueError(f"BibTeX key '{bibkey}' already exists in papers.bib")

            bib_file.parent.mkdir(parents=True, exist_ok=True)
            with bib_file.open("a") as f:
                f.write("\n" + bibtex_text + "\n")

            if claim_mappings:
                import yaml as _yaml
                existing_claims: dict = {}
                if claims_file.exists():
                    try:
                        existing_claims = _yaml.safe_load(claims_file.read_text()) or {}
                    except Exception:
                        existing_claims = {}
                for claim_id, bkey in claim_mappings.items():
                    existing_claims.setdefault(claim_id, [])
                    if bkey not in existing_claims[claim_id]:
                        existing_claims[claim_id].append(bkey)
                claims_file.parent.mkdir(parents=True, exist_ok=True)
                claims_file.write_text(_yaml.safe_dump(existing_claims, sort_keys=False))

            if pdf_b64:
                pdf_dest_rel = f"references/papers/{bibkey}.pdf"
                pdf_dest = WORKSPACE / pdf_dest_rel
                sha = _save_upload(pdf_b64, pdf_dest)

                _ws_add_to_sys_path()
                from scripts._lib.workspace_yaml import load_workspace, save_workspace
                ws_file = WORKSPACE / "workspace.yaml"
                ws = load_workspace(ws_file)
                refs_pdfs = ws.setdefault("references_pdfs", [])
                if refs_pdfs is None:
                    refs_pdfs = []
                    ws["references_pdfs"] = refs_pdfs
                if not any(e.get("bib_key") == bibkey for e in refs_pdfs):
                    refs_pdfs.append({"bib_key": bibkey, "path": pdf_dest_rel, "sha256": sha})
                save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_expert_doc(self, body: dict):
        """Register an expert document in workspace.yaml."""
        import shutil as _shutil

        name = (body.get("name") or "").strip()
        file_b64 = body.get("file_b64", "").strip()
        filename = (body.get("filename") or "").strip()
        source_path_raw = (body.get("source_path") or "").strip()
        description = (body.get("description") or "").strip() or None
        contributor = (body.get("contributor") or "").strip() or None
        claims_raw = body.get("claims_supported", [])

        if not name:
            return self._json({"error": "name is required"}, 400)
        if not file_b64 and not source_path_raw:
            return self._json({"error": "either file_b64+filename or source_path is required"}, 400)

        if isinstance(claims_raw, str):
            claims_supported = [c.strip() for c in claims_raw.split(",") if c.strip()]
        elif isinstance(claims_raw, list):
            claims_supported = list(claims_raw)
        else:
            claims_supported = []

        if file_b64:
            if not filename:
                return self._json({"error": "filename is required when file_b64 is provided"}, 400)
            ext = Path(filename).suffix if Path(filename).suffix else ".pdf"
            dest_rel = f"references/expert/{_safe_slug(name)}{ext}"
            source_path = None
        else:
            source_path = Path(source_path_raw)
            if not source_path.is_absolute():
                source_path = WORKSPACE / source_path
            if not source_path.exists():
                return self._json({"error": f"source_path does not exist: {source_path}"}, 400)
            if not source_path.is_file():
                return self._json({"error": f"source_path is not a regular file: {source_path}"}, 400)
            ext = source_path.suffix if source_path.suffix else ".pdf"
            dest_rel = f"references/expert/{_safe_slug(name)}{ext}"

        commit_msg = f"feat(5): add expert document '{name}'"

        def action():
            dest = WORKSPACE / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if file_b64:
                sha = _save_upload(file_b64, dest)
            else:
                _shutil.copy2(str(source_path), str(dest))
                import hashlib as _hashlib
                h = _hashlib.sha256()
                with dest.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                sha = h.hexdigest()

            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            expert_docs = ws.setdefault("expert_docs", [])
            if expert_docs is None:
                expert_docs = []
                ws["expert_docs"] = expert_docs
            for existing in expert_docs:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"expert doc '{name}' already registered")
            entry: dict = {"name": name, "path": dest_rel, "sha256": sha}
            if description:
                entry["description"] = description
            if contributor:
                entry["contributor"] = contributor
            if claims_supported:
                entry["claims_supported"] = claims_supported
            expert_docs.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_phase_plan(self, body: dict):
        """Plan phases for the workspace (v0.3.0: no model param).

        Body: {phases: [{n, name, objective?, prereq_phases?, acceptance_tests?}, ...]}
        """
        phases_input = body.get("phases", [])

        if not isinstance(phases_input, list) or not phases_input:
            return self._json({"error": "phases must be a non-empty list"}, 400)

        phases: list[dict] = []
        for p in phases_input:
            if not isinstance(p, dict):
                return self._json({"error": "each phase must be a JSON object"}, 400)
            n = p.get("n")
            name = str(p.get("name", "")).strip()
            objective = str(p.get("objective", "")).strip()
            if n is None or not name:
                return self._json({"error": "each phase must have n and name"}, 400)
            phases.append({
                "n": int(n),
                "name": name,
                "objective": objective,
                "prereq_phases": p.get("prereq_phases", []),
                "acceptance_tests": p.get("acceptance_tests", []),
                "status": "planned",
            })

        commit_msg = f"feat(8): plan phases (N={len(phases)})"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_files import create_initial_plan
            from scripts._lib.workspace_yaml import load_workspace, save_workspace

            # Write phase-*.md files at workspace root phases/.
            phases_dir = WORKSPACE / "phases"
            create_initial_plan(phases_dir, "workspace", phases)

            # Update top-level phases[] in workspace.yaml.
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            ws["phases"] = [
                {"n": p["n"], "name": p["name"], "status": "planned"}
                for p in phases
            ]
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_phase_start(self, body: dict):
        """Start a phase for the workspace (v0.3.0: no model param).

        Body: {n: <int>}
        """
        n = body.get("n")
        if n is None:
            return self._json({"error": "n is required"}, 400)
        n = int(n)

        commit_msg = f"feat(9): start phase {n}"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_md import parse_phase_md, render_phase_md
            from scripts._lib.phase_gate import generate_test_module
            from scripts._lib.workspace_yaml import load_workspace, save_workspace

            phases_dir = WORKSPACE / "phases"
            phase_file = phases_dir / f"phase-{n}.md"
            if not phase_file.exists():
                raise FileNotFoundError(f"phase-{n}.md not found at {phase_file}")

            fm, body_text = parse_phase_md(phase_file.read_text())

            # Gate: refuse if phase n-1 hasn't passed (for n > 1).
            if n > 1:
                prev_file = phases_dir / f"phase-{n-1}.md"
                if prev_file.exists():
                    prev_fm, _ = parse_phase_md(prev_file.read_text())
                    if not prev_fm.get("gate_passed", False):
                        raise ValueError(
                            f"phase {n-1} has not passed its gate. "
                            "Evaluate the gate for the previous phase first."
                        )

            fm["status"] = "in_progress"
            phase_file.write_text(render_phase_md(fm, body_text))

            # Generate test stubs at workspace root tests/.
            test_out = WORKSPACE / "tests" / "test_phases.py"
            generate_test_module(fm, test_out)

            # Update workspace.yaml top-level phases[].
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            for phase_entry in (ws.get("phases") or []):
                if phase_entry.get("n") == n:
                    phase_entry["status"] = "in_progress"
                    break
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_phase_gate(self, body: dict):
        """Evaluate a phase gate for the workspace (v0.3.0: no model param).

        Body: {n: <int>}
        """
        n = body.get("n")
        if n is None:
            return self._json({"error": "n is required"}, 400)
        n = int(n)

        commit_msg = f"feat(9): evaluate gate for phase {n}"

        gate_status = {"status": "gate_pending"}

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_md import parse_phase_md, render_phase_md
            from scripts._lib.phase_gate import evaluate_gate
            from scripts._lib.workspace_yaml import load_workspace, save_workspace

            phases_dir = WORKSPACE / "phases"
            phase_file = phases_dir / f"phase-{n}.md"
            if not phase_file.exists():
                raise FileNotFoundError(f"phase-{n}.md not found at {phase_file}")

            fm, body_text = parse_phase_md(phase_file.read_text())
            result = evaluate_gate(fm)

            if result.passed:
                fm["status"] = "complete"
                fm["gate_passed"] = True
            else:
                fm["status"] = "gate_pending"
                fm["gate_passed"] = False

            gate_status["status"] = fm["status"]
            phase_file.write_text(render_phase_md(fm, body_text))

            # Update workspace.yaml.
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            for phase_entry in (ws.get("phases") or []):
                if phase_entry.get("n") == n:
                    phase_entry["status"] = gate_status["status"]
                    break
            save_workspace(ws_file, ws)

        resp, code = _active_branch_action(commit_msg, action)
        if code == 200:
            resp["gate_status"] = gate_status["status"]
        return self._json(resp, code)

    def _post_observable(self, body: dict):
        """Register an observable in workspace.yaml (v0.3.0: top-level, no model).

        Body: {name, store_path, units?, description?}
        """
        name = (body.get("name") or "").strip()
        store_path = (body.get("store_path") or "").strip()
        units = (body.get("units") or "").strip() or None
        description = (body.get("description") or "").strip() or None

        if not all([name, store_path]):
            return self._json({"error": "name and store_path are required"}, 400)

        commit_msg = f"feat(setup): add observable '{name}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            observables = ws.setdefault("observables", [])
            if observables is None:
                observables = []
                ws["observables"] = observables
            for existing in observables:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"observable '{name}' already registered")
            entry: dict = {"name": name, "store_path": store_path}
            if units:
                entry["units"] = units
            if description:
                entry["description"] = description
            observables.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_visualization(self, body: dict):
        """Register a visualization in workspace.yaml (v0.4.2: name+description primary path).

        Body (description-first, v0.4.2):
            {name, description?}
        Body (structured, legacy / backward-compat):
            {name, type, observables, config?, phases?, simulation?}

        Only `name` is required. When `type`/`observables` are omitted the visualization
        enters the description-first lifecycle (Create → /pbg-viz skill → Add → Commit).
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)
        if not re.match(r"^[a-zA-Z0-9_-]+$", name):
            return self._json({"error": "name must match ^[a-zA-Z0-9_-]+$"}, 400)

        description = (body.get("description") or "").strip() or None
        viz_type = (body.get("type") or "").strip() or None
        obs_list = body.get("observables") or []
        config = body.get("config") or {}
        phases_raw = body.get("phases") or []
        simulation_name = (body.get("simulation") or "").strip() or None

        # Structured path: if type or observables are provided, validate them fully.
        if viz_type or obs_list:
            if not viz_type:
                return self._json({"error": "type is required when observables are specified"}, 400)
            if viz_type not in ("time-series", "phase-space", "heatmap", "histogram"):
                return self._json({"error": "type must be one of: time-series, phase-space, heatmap, histogram"}, 400)
            if not isinstance(obs_list, list) or not obs_list:
                return self._json({"error": "observables must be a non-empty list"}, 400)

        if not isinstance(phases_raw, list):
            return self._json({"error": "phases must be a list of integers"}, 400)
        try:
            phases_list = [int(p) for p in phases_raw]
        except (TypeError, ValueError):
            return self._json({"error": "phases must be a list of integers"}, 400)

        commit_msg = f"feat(setup): add visualization '{name}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)

            # Only validate observable references when structured fields are provided.
            if obs_list:
                registered_obs = {
                    o.get("name") for o in (ws.get("observables") or [])
                    if isinstance(o, dict)
                }
                missing = [o for o in obs_list if o not in registered_obs]
                if missing:
                    raise ValueError(
                        f"observables not registered: {missing}. "
                        "Register them first via /api/observable."
                    )

            # Validate phase references if phases provided.
            if phases_list:
                registered_phases = {
                    p.get("n") for p in (ws.get("phases") or [])
                    if isinstance(p, dict)
                }
                missing_phases = [n for n in phases_list if n not in registered_phases]
                if missing_phases:
                    raise ValueError(
                        f"phases not registered: {missing_phases}. "
                        "Register them first via /api/phase-plan."
                    )

            # Validate simulation reference if provided.
            if simulation_name:
                registered_sims = {
                    s.get("name") for s in (ws.get("simulations") or [])
                    if isinstance(s, dict)
                }
                if simulation_name not in registered_sims:
                    raise ValueError(
                        f"simulation '{simulation_name}' not registered. "
                        "Register it first via /api/simulation."
                    )

            visualizations = ws.setdefault("visualizations", [])
            if visualizations is None:
                visualizations = []
                ws["visualizations"] = visualizations
            for existing in visualizations:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"visualization '{name}' already registered")
            entry: dict = {"name": name}
            if description:
                entry["description"] = description
            if viz_type:
                entry["type"] = viz_type
            if obs_list:
                entry["observables"] = list(obs_list)
            if config:
                entry["config"] = config
            if phases_list:
                entry["phases"] = phases_list
            if simulation_name:
                entry["simulation"] = simulation_name
            visualizations.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_visualization_create(self, body: dict):
        """Write a .pbg/viz-requests/<name>.md file with the description and workspace context.

        Body: {name: str}
        Returns: {ok, request_path, skill_command, instructions}
        """
        name = (body.get("name") or "").strip()
        if not name or not re.match(r"^[a-zA-Z0-9_-]+$", name):
            return self._json({"error": "invalid name"}, 400)

        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        viz = next((v for v in (ws_data.get("visualizations") or []) if v.get("name") == name), None)
        if not viz:
            return self._json({"error": f"visualization '{name}' not registered (Add it first)"}, 404)

        description = viz.get("description") or ""
        if not description.strip():
            return self._json({"error": "visualization has no description — edit it first"}, 400)

        req_dir = WORKSPACE / ".pbg" / "viz-requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_path = req_dir / f"{name}.md"

        # Build context for the skill
        observables = ws_data.get("observables", []) or []
        simulations = ws_data.get("simulations", []) or []
        phases = ws_data.get("phases", []) or []
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))

        obs_lines = "\n".join(
            f'  - `{o["name"]}` (path: `{o["store_path"]}`'
            + (f', units: {o["units"]}' if o.get("units") else "")
            + ")"
            for o in observables
        ) or "  (none)"
        sim_lines = "\n".join(
            f'  - `{s["name"]}`: t={s["t_start"]}→{s["t_end"]}'
            for s in simulations
        ) or "  (none)"
        phase_lines = "\n".join(
            f'  - {p["n"]}: {p["name"]} ({p.get("status","planned")})'
            for p in phases
        ) or "  (none)"

        content = f"""# Visualization request: {name}

## Description (from user)

{description}

## Workspace context

- Workspace package: `{pkg}`
- Available observables:
{obs_lines}
- Available simulations:
{sim_lines}
- Phases:
{phase_lines}

## Instructions for the agent

Write a Python function and save it to `.pbg/viz-responses/{name}.py`. The function:

- Should be named `visualize` (no name suffix — the file path identifies it)
- Takes one argument: `results: dict` — emitter output keyed by emitter path tuple, with values being lists of dicts `{{observable_name: value, ...}}`
- Returns: HTML string (Plotly preferred) OR a base64 PNG (matplotlib fallback)
- Must include a `_demo()` helper that returns the visualization run on synthetic data, so the dashboard preview can call it without real simulation results
- Should pick the visualization library that best fits the description (Plotly for interactive, matplotlib for static)

Output file structure:

```python
\"\"\"Generated visualization: {name}\"\"\"
import plotly.graph_objects as go  # or matplotlib.pyplot, etc.

def visualize(results: dict) -> str:
    # ... build figure from results ...
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

def _demo() -> str:
    # Synthetic data matching the observable shape
    fake_results = {{('emitter',): [{{...}}, ...]}}
    return visualize(fake_results)

if __name__ == "__main__":
    import sys
    sys.stdout.write(_demo())
```
"""
        req_path.write_text(content)

        return self._json({
            "ok": True,
            "request_path": str(req_path.relative_to(WORKSPACE)),
            "skill_command": f"/pbg-viz {name}",
            "instructions": (
                f"Open Claude Code in this workspace and run `/pbg-viz {name}`. "
                f"The skill will read {req_path.relative_to(WORKSPACE)}, generate a function, "
                f"and save it to .pbg/viz-responses/{name}.py. "
                f"Click Refresh below when ready."
            ),
        }, 200)

    def _get_visualization_status(self):
        """Return lifecycle status for a viz: described | requested | created | added | committed."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        name = (qs.get("name") or [""])[0]
        if not name:
            return self._json({"error": "missing name"}, 400)

        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        viz = next((v for v in (ws_data.get("visualizations") or []) if v.get("name") == name), None)
        if not viz:
            return self._json({"status": "missing", "name": name}, 200)

        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        response_path = WORKSPACE / ".pbg" / "viz-responses" / f"{name}.py"
        staged_path = WORKSPACE / ".pbg" / "visualizations-staged" / f"{name}.py"
        committed_path = WORKSPACE / pkg / "visualizations" / f"{name}.py"
        request_path = WORKSPACE / ".pbg" / "viz-requests" / f"{name}.md"

        if committed_path.exists():
            status = "committed"
        elif staged_path.exists():
            status = "added"
        elif response_path.exists():
            status = "created"
        elif request_path.exists():
            status = "requested"
        else:
            status = "described"

        return self._json({
            "status": status,
            "name": name,
            "has_request": request_path.exists(),
            "has_response": response_path.exists(),
            "has_staged": staged_path.exists(),
            "has_committed": committed_path.exists(),
        }, 200)

    def _post_visualization_add_to_project(self, body: dict):
        """Copy .pbg/viz-responses/<name>.py to .pbg/visualizations-staged/<name>.py.

        Does NOT commit (Commit is a separate action). Working tree stays clean
        because both source and dest are gitignored.
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "missing name"}, 400)
        src = WORKSPACE / ".pbg" / "viz-responses" / f"{name}.py"
        if not src.exists():
            return self._json({"error": f"no skill response yet — run /pbg-viz {name} first"}, 404)
        dest_dir = WORKSPACE / ".pbg" / "visualizations-staged"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name}.py"
        shutil.copy2(src, dest)
        return self._json({"ok": True, "staged_path": str(dest.relative_to(WORKSPACE))}, 200)

    def _post_visualization_commit_batch(self, body: dict):
        """Move all staged visualizations to the workspace package + commit on active branch.

        Body: {names?: list[str]} — if omitted, commits all staged.
        """
        staged_dir = WORKSPACE / ".pbg" / "visualizations-staged"
        if not staged_dir.is_dir():
            return self._json({"error": "no staged visualizations"}, 404)

        requested = body.get("names")
        available = sorted(p.stem for p in staged_dir.glob("*.py"))
        if requested:
            names = [n for n in requested if n in available]
        else:
            names = available
        if not names:
            return self._json({"error": "no staged visualizations match"}, 404)

        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        target_dir = WORKSPACE / pkg / "visualizations"

        moved_names = list(names)  # captured for closure

        def action():
            target_dir.mkdir(parents=True, exist_ok=True)
            # Ensure __init__.py exists
            init = target_dir / "__init__.py"
            if not init.exists():
                init.write_text("")
            for n in moved_names:
                src = staged_dir / f"{n}.py"
                dest = target_dir / f"{n}.py"
                shutil.copy2(src, dest)
                src.unlink()  # remove staged copy

        commit_msg = (
            f"feat(viz): commit {len(moved_names)} visualization(s): {', '.join(moved_names)}"
            if len(moved_names) > 1
            else f"feat(viz): commit {moved_names[0]}"
        )
        resp, code = _active_branch_action(commit_msg, action)

        if code == 200:
            resp["ok"] = True
            resp["committed"] = moved_names
        return self._json(resp, code)

    def _post_simulation(self, body: dict):
        """Register a simulation in workspace.yaml.

        Body: {name, description?, t_start, t_end, initial_state?, parameter_overrides?,
               emitter_config?, phases?, processes?}
        """
        import re as _re
        name = (body.get("name") or "").strip()
        description = (body.get("description") or "").strip() or None
        t_start = body.get("t_start")
        t_end = body.get("t_end")
        initial_state = body.get("initial_state") or None
        parameter_overrides = body.get("parameter_overrides") or None
        emitter_config = body.get("emitter_config") or None
        phases_raw = body.get("phases", [])
        processes_raw = body.get("processes", [])

        if not name:
            return self._json({"error": "name is required"}, 400)
        if not _re.match(r"^[a-zA-Z0-9_-]+$", name):
            return self._json({"error": "name must match ^[a-zA-Z0-9_-]+$"}, 400)
        if t_start is None or t_end is None:
            return self._json({"error": "t_start and t_end are required"}, 400)
        try:
            t_start = float(t_start)
            t_end = float(t_end)
        except (TypeError, ValueError):
            return self._json({"error": "t_start and t_end must be numbers"}, 400)
        if t_start < 0:
            return self._json({"error": "t_start must be >= 0"}, 400)
        if t_end <= t_start:
            return self._json({"error": "t_end must be > t_start"}, 400)
        if not isinstance(phases_raw, list):
            return self._json({"error": "phases must be a list of integers"}, 400)
        try:
            phases_list = [int(p) for p in phases_raw]
        except (TypeError, ValueError):
            return self._json({"error": "phases must be a list of integers"}, 400)

        # Validate processes list.
        if not isinstance(processes_raw, list):
            return self._json({"error": "processes must be a list of strings"}, 400)
        processes_list = [str(p).strip() for p in processes_raw if str(p).strip()]

        # Validate process names against registry (best-effort; skip if registry unavailable).
        if processes_list:
            try:
                reg = _get_registry_data()
                if not reg.get("error"):
                    registered_proc_names = {p["name"] for p in (reg.get("processes") or [])}
                    for proc_name in processes_list:
                        if proc_name not in registered_proc_names:
                            return self._json(
                                {"error": f"process '{proc_name}' not in registry"}, 400
                            )
            except Exception as reg_err:
                # Registry call failed — warn but don't block.
                import logging
                logging.warning("Registry validation skipped: %s", reg_err)

        commit_msg = f"feat(setup): add simulation '{name}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)

            # Validate phase references if provided.
            if phases_list:
                registered_phases = {
                    p.get("n") for p in (ws.get("phases") or [])
                    if isinstance(p, dict)
                }
                missing_phases = [n for n in phases_list if n not in registered_phases]
                if missing_phases:
                    raise ValueError(
                        f"phases not registered: {missing_phases}. "
                        "Register them first via /api/phase-plan."
                    )

            simulations = ws.setdefault("simulations", [])
            if simulations is None:
                simulations = []
                ws["simulations"] = simulations
            for existing in simulations:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"simulation '{name}' already registered")
            entry: dict = {"name": name, "t_start": t_start, "t_end": t_end}
            if description:
                entry["description"] = description
            if initial_state is not None:
                entry["initial_state"] = initial_state
            if parameter_overrides is not None:
                entry["parameter_overrides"] = parameter_overrides
            if emitter_config is not None:
                entry["emitter_config"] = emitter_config
            if phases_list:
                entry["phases"] = phases_list
            if processes_list:
                entry["processes"] = processes_list
            simulations.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _delete_simulation(self, body: dict):
        """Remove a simulation from workspace.yaml.

        Body: {name}
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)

        commit_msg = f"feat(setup): remove simulation '{name}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            simulations = ws.get("simulations") or []
            new_sims = [s for s in simulations if not (isinstance(s, dict) and s.get("name") == name)]
            if len(new_sims) == len(simulations):
                raise ValueError(f"simulation '{name}' not found")
            if new_sims:
                ws["simulations"] = new_sims
            else:
                ws.pop("simulations", None)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _delete_visualization(self, body: dict):
        """Remove a visualization from workspace.yaml.

        Body: {name}
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)

        commit_msg = f"feat(setup): remove visualization '{name}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            visualizations = ws.get("visualizations") or []
            new_vizs = [v for v in visualizations if not (isinstance(v, dict) and v.get("name") == name)]
            if len(new_vizs) == len(visualizations):
                raise ValueError(f"visualization '{name}' not found")
            if new_vizs:
                ws["visualizations"] = new_vizs
            else:
                ws.pop("visualizations", None)
            save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, action))

    def _post_run_tests(self, body: dict):
        """Run pytest for the workspace (v0.3.0: no model param).

        Returns JSON with returncode, stdout, stderr.
        """
        test_dir = WORKSPACE / "tests"
        cmd = [sys.executable, "-m", "pytest", "-v", str(test_dir)]
        try:
            result = subprocess.run(
                cmd, cwd=WORKSPACE,
                capture_output=True, text=True, timeout=120,
            )
            return self._json({
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }, 200)
        except subprocess.TimeoutExpired:
            return self._json({"error": "pytest timed out after 120s"}, 500)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _post_import_install(self, body: dict):
        """Pip-install an import into the workspace venv.

        Body: {name: str, target?: str}.
        `target` overrides the default install path (workspace.yaml.imports[name].path).
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "missing name"}, 400)
        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        imports = ws_data.get("imports", {})
        if name not in imports:
            return self._json({"error": f"import '{name}' not registered"}, 404)

        entry = imports[name]
        target = (body.get("target") or "").strip() or entry.get("path") or ""
        if not target:
            return self._json({"error": "no install target — set 'path' in import or pass 'target' in body"}, 400)

        # Resolve path relative to workspace (unless it's a URL/VCS spec).
        if not target.startswith(("http://", "https://", "git+")):
            abs_target = (WORKSPACE / target).resolve()
            if not abs_target.exists():
                return self._json({"error": f"path does not exist: {abs_target}"}, 404)
            target = str(abs_target)

        # Pick installer: prefer pip in the venv; fall back to system `uv` when
        # the venv has no pip (created via `uv venv`). Both produce the same
        # editable install in the venv's site-packages.
        venv_pip = WORKSPACE / ".venv" / "bin" / "pip"
        venv_py = WORKSPACE / ".venv" / "bin" / "python3"
        if venv_pip.exists():
            cmd = [str(venv_pip), "install", "-e", target]
        else:
            uv_path = shutil.which("uv")
            if uv_path and venv_py.exists():
                cmd = [uv_path, "pip", "install", "--python", str(venv_py), "-e", target]
            else:
                hint = (
                    "neither .venv/bin/pip nor `uv` found. "
                    "Create a venv with pip (`python -m venv .venv && .venv/bin/pip install --upgrade pip`) "
                    "or install uv (`brew install uv`)."
                )
                return self._json({"error": hint}, 500)

        # Run install (outside the branch action so errors surface before git work).
        try:
            result = subprocess.run(
                cmd,
                cwd=WORKSPACE, capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return self._json({"error": f"{cmd[0]} install timed out after 120s"}, 500)
        except Exception as pip_err:
            return self._json({"error": f"install error: {pip_err}"}, 500)

        log_excerpt = (result.stdout + "\n" + result.stderr).strip()[-3000:]
        if result.returncode != 0:
            _ws_add_to_sys_path()
            from scripts._lib.install_errors import diagnose as _diagnose_install
            diag = _diagnose_install(log_excerpt)
            resp = {
                "error": "install failed",
                "log": log_excerpt[-1000:],
            }
            if diag:
                resp["diagnosis"] = diag.as_dict()
            return self._json(resp, 500)

        # Mark installed in workspace.yaml on a stage branch.
        install_target = target  # captured for closure

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            ws.setdefault("imports", {}).setdefault(name, {})["installed"] = True
            ws["imports"][name]["install_path"] = install_target
            save_workspace(ws_file, ws)

        commit_msg = f"chore(import): pip install {name} into venv"

        resp, code = _active_branch_action(commit_msg, action)

        # Invalidate registry cache so next /api/registry call sees fresh data.
        global _REGISTRY_CACHE
        _REGISTRY_CACHE["data"] = None

        # The pip install itself succeeded; if the metadata mutation was a
        # no-op (workspace.yaml already has installed=True on main), that's
        # not an error — surface it as a clean re-install acknowledgment.
        if code == 409 and "no changes" in (resp.get("error") or ""):
            return self._json({
                "ok": True,
                "already_installed": True,
                "message": "Package re-installed; workspace.yaml already marks it installed.",
                "log": log_excerpt[-500:],
            }, 200)

        if code == 200:
            resp["ok"] = True
            resp["log"] = log_excerpt[-500:]

        return self._json(resp, code)

    # ------------------------------------------------------------------
    # Work-stream endpoints (v0.4.0b)
    # ------------------------------------------------------------------

    def _post_work_start(self, body: dict):
        """Create a new working branch from base; set active in state."""
        branch = (body.get("branch") or "").strip()
        base = (body.get("base") or "main").strip()
        if not branch or not re.match(r"^[A-Za-z0-9._/-]+$", branch) or len(branch) > 100:
            return self._json({"error": "invalid branch name"}, 400)

        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state, save_state
        state = load_state()
        if state.get("active_branch"):
            return self._json({"error": f"already on workstream '{state['active_branch']}'. End it first."}, 409)
        if _dirty_workspace().strip():
            return self._json({"error": "working tree dirty — commit or stash first"}, 409)

        # Verify base exists
        r = subprocess.run(["git", "rev-parse", "--verify", base], cwd=WORKSPACE, capture_output=True, text=True)
        if r.returncode != 0:
            return self._json({"error": f"base branch '{base}' not found"}, 404)

        # Verify branch doesn't already exist locally
        r = subprocess.run(["git", "rev-parse", "--verify", branch], cwd=WORKSPACE, capture_output=True, text=True)
        if r.returncode == 0:
            return self._json({"error": f"branch '{branch}' already exists. Pick a different name or delete the old one."}, 409)

        subprocess.run(["git", "checkout", base], cwd=WORKSPACE, check=True, capture_output=True)
        r = subprocess.run(["git", "checkout", "-b", branch], cwd=WORKSPACE, capture_output=True, text=True)
        if r.returncode != 0:
            return self._json({"error": f"branch create failed: {r.stderr[:300]}"}, 500)

        save_state({"active_branch": branch, "base": base, "pushed": False, "pr_number": None, "pr_url": None})
        return self._json({"ok": True, "branch": branch, "base": base}, 200)

    def _post_work_push(self, body: dict):
        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state, save_state
        state = load_state()
        branch = state.get("active_branch")
        if not branch:
            return self._json({"error": "no active workstream"}, 409)

        # Pre-flight: refuse cleanly when no origin remote exists (the common
        # confusion on fresh workspaces). Surface a structured diagnosis the
        # JS layer can render as a clickable Create-GitHub-repo prompt.
        if not _has_origin_remote():
            return self._json({
                "error": "no GitHub remote configured",
                "diagnosis": {
                    "category": "no_origin",
                    "summary": "This workspace has no `origin` remote yet.",
                    "suggestion": "Click `Create GitHub repo` in the workstream strip to create one in your account and push in a single step.",
                },
            }, 409)

        r = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip()
            diag = _diagnose_push_error(err)
            resp = {"error": f"push failed: {err[:300]}"}
            if diag:
                resp["diagnosis"] = diag
            return self._json(resp, 500)
        state["pushed"] = True
        save_state(state)
        return self._json({"ok": True, "branch": branch, "log": r.stdout[-300:]}, 200)

    def _post_work_create_github_repo(self, body: dict):
        """gh repo create + set origin + initial push, in one shot.

        Body: {visibility?: "public"|"private", name?: str, description?: str}.
        Defaults: visibility=private, name=<workspace_name>, description=workspace.yaml.description.
        """
        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state, save_state
        state = load_state()
        branch = state.get("active_branch")
        if not branch:
            return self._json({"error": "no active workstream — Start one first so the initial push has commits"}, 409)

        if not shutil.which("gh"):
            return self._json({
                "error": "gh CLI not installed",
                "diagnosis": {
                    "category": "gh_missing",
                    "summary": "GitHub CLI (`gh`) is not installed.",
                    "suggestion": "Install gh (`brew install gh` on macOS), then run `gh auth login`. After that, click Create GitHub repo again.",
                },
            }, 500)

        # Verify gh is authenticated
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if auth.returncode != 0:
            return self._json({
                "error": "gh not authenticated",
                "diagnosis": {
                    "category": "gh_auth",
                    "summary": "GitHub CLI isn't logged in.",
                    "suggestion": "Run `gh auth login` in your terminal, then click Create GitHub repo again.",
                },
            }, 500)

        if _has_origin_remote():
            return self._json({"error": "origin remote already configured — use Push instead"}, 409)

        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        default_name = ws_data.get("name", WORKSPACE.name)
        repo_name = (body.get("name") or "").strip() or default_name
        if not re.match(r"^[A-Za-z0-9._-]+$", repo_name):
            return self._json({"error": "invalid repo name (must match [A-Za-z0-9._-]+)"}, 400)
        visibility = (body.get("visibility") or "private").strip().lower()
        if visibility not in ("public", "private", "internal"):
            return self._json({"error": "visibility must be one of: public, private, internal"}, 400)
        description = (body.get("description") or "").strip()
        if not description:
            description = ws_data.get("description") or f"Process-bigraph workspace: {repo_name}"

        # gh repo create <name> --<visibility> --source=. --remote=origin --push --description "..."
        # NOTE: --push pushes the current branch to the new remote.
        cmd = [
            "gh", "repo", "create", repo_name,
            "--" + visibility,
            "--source=.",
            "--remote=origin",
            "--push",
            "--description", description,
        ]
        r = subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return self._json({
                "error": "gh repo create failed",
                "log": (r.stderr or r.stdout).strip()[-500:],
            }, 500)

        # Successful: gh pushed the current branch. Mark workstream pushed.
        state["pushed"] = True
        save_state(state)

        url = r.stdout.strip().splitlines()[-1] if r.stdout else ""
        return self._json({
            "ok": True,
            "repo_url": url,
            "visibility": visibility,
            "branch": branch,
        }, 200)

    def _post_work_create_pr(self, body: dict):
        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state, save_state
        state = load_state()
        branch = state.get("active_branch")
        if not branch:
            return self._json({"error": "no active workstream"}, 409)
        if not state.get("pushed"):
            return self._json({"error": "push to origin first (Push button)"}, 409)
        if state.get("pr_url"):
            return self._json({"error": f"PR already exists: {state['pr_url']}", "pr_url": state["pr_url"]}, 409)

        base = state.get("base") or "main"
        title = (body.get("title") or "").strip() or f"Workstream: {branch}"
        body_text = (body.get("body") or "").strip() or "Created via pbg-template dashboard."

        if not shutil.which("gh"):
            try:
                from scripts._lib.report import _detect_github_repo
            except ImportError:
                _detect_github_repo = lambda *a: None
            repo = _detect_github_repo(WORKSPACE)
            manual = f"https://github.com/{repo}/compare/{base}...{branch}?expand=1" if repo else None
            return self._json({
                "error": "gh CLI not installed. Open manually:",
                "manual_url": manual,
            }, 500)

        r = subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", branch,
             "--title", title, "--body", body_text],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return self._json({"error": f"gh pr create failed: {(r.stderr or r.stdout)[:300]}"}, 500)
        pr_url = r.stdout.strip().splitlines()[-1] if r.stdout else ""
        m = re.search(r"/pull/(\d+)", pr_url)
        if m:
            state["pr_url"] = pr_url
            state["pr_number"] = int(m.group(1))
            save_state(state)
        return self._json({"ok": True, "pr_url": pr_url, "pr_number": state.get("pr_number")}, 200)

    def _get_work_status(self):
        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state
        state = load_state()
        if not state.get("active_branch"):
            return self._json({"active": False}, 200)
        branch = state["active_branch"]
        base = state.get("base", "main")

        # commits ahead of base
        r = subprocess.run(["git", "rev-list", "--count", f"{base}..{branch}"],
                           cwd=WORKSPACE, capture_output=True, text=True)
        commits_ahead = int(r.stdout.strip() or 0) if r.returncode == 0 else 0

        # unpushed commits
        if state.get("pushed"):
            r2 = subprocess.run(["git", "rev-list", "--count", f"origin/{branch}..{branch}"],
                                cwd=WORKSPACE, capture_output=True, text=True)
            unpushed = int(r2.stdout.strip() or 0) if r2.returncode == 0 else commits_ahead
        else:
            unpushed = commits_ahead

        return self._json({
            "active": True,
            "branch": branch,
            "base": base,
            "commits_ahead": commits_ahead,
            "unpushed": unpushed,
            "pushed": state.get("pushed", False),
            "has_origin": _has_origin_remote(),
            "gh_available": shutil.which("gh") is not None,
            "pr_number": state.get("pr_number"),
            "pr_url": state.get("pr_url"),
        }, 200)

    def _post_work_end(self, body: dict):
        _ws_add_to_sys_path()
        from scripts._lib.work_state import load_state, clear_state
        state = load_state()
        if not state.get("active_branch"):
            return self._json({"error": "no active workstream"}, 409)
        if _dirty_workspace().strip():
            return self._json({"error": "uncommitted changes — commit or stash before ending"}, 409)
        base = state.get("base", "main")
        subprocess.run(["git", "checkout", base], cwd=WORKSPACE, check=True, capture_output=True)
        clear_state()
        return self._json({"ok": True}, 200)

    def _post_render(self, body: dict):
        """Re-render workspace dashboard."""
        try:
            _ws_add_to_sys_path()
            from scripts._lib.report import render_workspace_report
            render_workspace_report(WORKSPACE)
            return self._json({"ok": True}, 200)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------

    def _serve_branches(self):
        """Return list of stage/* branches with last-commit info."""
        try:
            raw = subprocess.run(
                ["git", "branch", "--list", "stage/*"],
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout
            stage_branches = [b.strip().lstrip("* ") for b in raw.splitlines() if b.strip()]

            current = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout.strip()

            branches = []
            for bname in stage_branches:
                try:
                    log = subprocess.run(
                        ["git", "log", "-1", "--format=%H|%s|%ci", bname],
                        cwd=WORKSPACE, capture_output=True, text=True, check=True,
                    ).stdout.strip()
                    parts = log.split("|", 2)
                    sha = parts[0] if parts else ""
                    subject = parts[1] if len(parts) > 1 else ""
                    date_str = parts[2] if len(parts) > 2 else ""

                    ahead_raw = subprocess.run(
                        ["git", "rev-list", "--count", f"main..{bname}"],
                        cwd=WORKSPACE, capture_output=True, text=True,
                    ).stdout.strip()
                    ahead = int(ahead_raw) if ahead_raw.isdigit() else 0

                    branches.append({
                        "name": bname,
                        "last_commit": {
                            "sha": sha[:7],
                            "subject": subject,
                            "date": date_str,
                        },
                        "ahead_of_main": ahead,
                    })
                except Exception:
                    branches.append({"name": bname, "last_commit": {}, "ahead_of_main": 0})

            return self._json({"branches": branches, "current": current}, 200)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _serve_pending(self):
        """Return pending entries from unmerged stage/* branches."""
        try:
            return self._json(_pending_entries(), 200)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _get_branch_diff(self):
        """Return a short diff summary for ?branch=<name>."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        branch = (qs.get("branch") or [""])[0]
        if not branch or not re.match(r"^[A-Za-z0-9./_-]+$", branch) or ".." in branch:
            return self._json({"error": "invalid branch name"}, 400)
        log = subprocess.run(
            ["git", "log", "--oneline", f"main..{branch}"],
            cwd=WORKSPACE, capture_output=True, text=True, check=False,
        )
        diff_stat = subprocess.run(
            ["git", "diff", "--stat", f"main...{branch}"],
            cwd=WORKSPACE, capture_output=True, text=True, check=False,
        )
        return self._json({
            "branch": branch,
            "log": log.stdout,
            "diff_stat": diff_stat.stdout,
        }, 200)

    def _get_registry(self):
        """GET /api/registry — live introspection of build_core(); cached 30s.

        Query param: ?refresh=1 to bypass cache.
        Never returns 500 — always returns {processes, types} (with optional 'error').
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        bypass = qs.get("refresh", ["0"])[0] == "1"
        try:
            data = _get_registry_data(bypass_cache=bypass)
        except Exception as e:
            data = {"error": str(e), "processes": [], "types": []}
        return self._json(data, 200)

    def _get_catalog(self):
        """GET /api/catalog — return the curated module catalog with installed annotations."""
        catalog_path = WORKSPACE / "scripts" / "_catalog" / "modules.json"
        if not catalog_path.exists():
            return self._json({"modules": [], "error": "catalog not found"}, 200)
        try:
            modules = json.loads(catalog_path.read_text())
            # Annotate with installed status from workspace.yaml imports.
            ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
            installed = ws_data.get("imports", {}) or {}
            for m in modules:
                m["installed"] = m["name"] in installed
            return self._json({"modules": modules}, 200)
        except Exception as e:
            return self._json({"modules": [], "error": str(e)}, 500)

    def _post_catalog_install(self, body: dict):
        """POST /api/catalog-install — install a catalog module.

        Steps: submodule add + pip install + pyproject.toml edit + workspace.yaml + commit.
        Requires an active workstream (uses _active_branch_action).
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "missing name"}, 400)

        # Load catalog entry.
        catalog_path = WORKSPACE / "scripts" / "_catalog" / "modules.json"
        if not catalog_path.exists():
            return self._json({"error": "catalog not found"}, 404)
        try:
            modules = json.loads(catalog_path.read_text())
        except Exception as e:
            return self._json({"error": f"catalog parse failed: {e}"}, 500)
        entry = next((m for m in modules if m["name"] == name), None)
        if not entry:
            return self._json({"error": f"module '{name}' not in catalog"}, 404)

        target_path = f"external/{name}"
        abs_target = (WORKSPACE / target_path).resolve()

        # Determine pip command upfront (before the action closure).
        venv_pip = WORKSPACE / ".venv" / "bin" / "pip"
        venv_py = WORKSPACE / ".venv" / "bin" / "python3"
        if venv_pip.exists():
            pip_cmd_base = [str(venv_pip), "install", "-e"]
        else:
            uv_path = shutil.which("uv")
            if uv_path and venv_py.exists():
                pip_cmd_base = [uv_path, "pip", "install", "--python", str(venv_py), "-e"]
            else:
                return self._json({"error": "neither pip nor uv available"}, 500)

        # Steps 1+2+3+4: all run inside the action closure so .gitmodules changes
        # are staged and committed atomically on the active branch.
        package_name = entry.get("package", name)
        catalog_entry = entry  # captured for closure
        log_holder: list[str] = []

        def action():
            # Step 1: submodule add if directory not already present.
            if not abs_target.exists():
                r = subprocess.run(
                    ["git", "submodule", "add", "-b", catalog_entry["ref"],
                     catalog_entry["source"], target_path],
                    cwd=WORKSPACE, capture_output=True, text=True, timeout=120,
                )
                if r.returncode != 0:
                    raise RuntimeError(
                        f"submodule add failed: {(r.stderr or r.stdout)[:300]}"
                    )

            # Step 2: pip install -e.
            try:
                result = subprocess.run(
                    pip_cmd_base + [str(abs_target)],
                    cwd=WORKSPACE, capture_output=True, text=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("pip install timed out after 180s")

            excerpt = (result.stdout + "\n" + result.stderr).strip()[-2000:]
            log_holder.append(excerpt)
            if result.returncode != 0:
                raise RuntimeError(f"pip install failed:\n{excerpt[-500:]}")

            # Step 3: workspace.yaml.
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            from scripts._lib.pyproject_edit import add_dependency

            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            ws.setdefault("imports", {})[name] = {
                "source": catalog_entry["source"],
                "ref": catalog_entry["ref"],
                "mode": "reference",
                "path": f"external/{name}",
                "description": catalog_entry.get("description", ""),
                "installed": True,
                "install_path": str(abs_target),
                "package": package_name,
            }
            save_workspace(ws_file, ws)

            # Step 4: pyproject.toml [project.dependencies].
            try:
                add_dependency(WORKSPACE / "pyproject.toml", package_name)
            except Exception as e:
                # Don't fail the whole install if pyproject edit fails — log it.
                log_dir = WORKSPACE / ".pbg"
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / "catalog-install.log").write_text(
                    f"pyproject edit failed for {name}: {e}\n"
                )

        commit_msg = f"feat(catalog): install {name}"
        resp, code = _active_branch_action(commit_msg, action)
        log_excerpt = log_holder[0] if log_holder else ""

        # Invalidate registry cache.
        global _REGISTRY_CACHE
        _REGISTRY_CACHE["data"] = None

        if code == 200:
            resp["ok"] = True
            resp["module"] = name
            resp["log"] = log_excerpt[-500:]
        elif code == 409 and "no changes" in (resp.get("error") or ""):
            # The pip install ran; metadata might already be in workspace.yaml.
            return self._json({
                "ok": True,
                "already_installed": True,
                "module": name,
                "log": log_excerpt[-500:],
            }, 200)
        elif code == 500 and log_excerpt:
            # pip install failed inside action() — add structured diagnosis if available.
            _ws_add_to_sys_path()
            from scripts._lib.install_errors import diagnose as _diagnose_install
            diag = _diagnose_install(log_excerpt)
            resp["log"] = log_excerpt[-1000:]
            if diag:
                resp["diagnosis"] = diag.as_dict()

        return self._json(resp, code)

    def _serve_file(self, path: Path, mime: str):
        if not path.exists() or not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_state(self):
        ws_file = WORKSPACE / "workspace.yaml"
        if not ws_file.exists():
            self.send_response(404)
            self.end_headers()
            return
        ws = yaml.safe_load(ws_file.read_text())
        body = json.dumps(ws).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_guidance(self):
        content_dir = WORKSPACE / ".pbg" / "server" / "content"
        if not content_dir.exists():
            self.send_response(204)
            self.end_headers()
            return
        files = sorted(content_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            self.send_response(204)
            self.end_headers()
            return
        return self._serve_file(files[0], "text/html")

    def _serve_events_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last_state = None
        ws_file = WORKSPACE / "workspace.yaml"
        try:
            while True:
                if ws_file.exists():
                    text = ws_file.read_text()
                    if text != last_state:
                        try:
                            payload = json.dumps(yaml.safe_load(text))
                        except Exception:
                            payload = json.dumps({"_error": "yaml parse"})
                        self.wfile.write(b"event: state\ndata: ")
                        self.wfile.write(payload.encode())
                        self.wfile.write(b"\n\n")
                        self.wfile.flush()
                        last_state = text
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _json(self, data: dict, code: int):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _guess_mime(rel: str) -> str:
        if rel.endswith(".css"): return "text/css"
        if rel.endswith(".js"): return "application/javascript"
        if rel.endswith(".json"): return "application/json"
        if rel.endswith(".png"): return "image/png"
        if rel.endswith(".svg"): return "image/svg+xml"
        if rel.endswith(".html"): return "text/html"
        return "text/plain"


# ---------------------------------------------------------------------------
# Sys-path injection helper
# ---------------------------------------------------------------------------

def _ws_add_to_sys_path() -> None:
    """Ensure workspace scripts/ is importable (for scripts._lib.* imports)."""
    scripts_parent = str(WORKSPACE)
    if scripts_parent not in sys.path:
        sys.path.insert(0, scripts_parent)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global WORKSPACE
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True, type=Path)
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()
    WORKSPACE = args.workspace.resolve()
    _ws_add_to_sys_path()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
