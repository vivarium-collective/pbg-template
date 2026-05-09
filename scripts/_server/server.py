"""Local HTTP server: serves reports/, exposes /api/state, /api/events SSE, /api/guidance.

v0.1.7: adds mutating POST endpoints with auto-branch/commit, /api/branches, /api/run-tests,
and /api/render for post-action page reload.
v0.1.9: drag-drop file uploads (base64) + sha256 reproducibility for datasets, references PDFs,
and expert docs.
v0.1.10: PDF-first reference flow (/api/reference-pdf); legacy BibTeX paste renamed to
/api/reference-bibtex; BibTeX auto-generated from typed metadata via _lib.bibtex.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

import yaml


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

def _submodule_paths() -> set[str]:
    """Return the set of submodule paths declared in .gitmodules (if any)."""
    gm = WORKSPACE / ".gitmodules"
    if not gm.exists():
        return set()
    paths = set()
    for line in gm.read_text().splitlines():
        line = line.strip()
        if line.startswith("path = "):
            paths.add(line.split("=", 1)[1].strip())
    return paths


def _dirty_excluding_submodules() -> str:
    """Return the porcelain status with submodule-pointer/internal lines stripped.

    Submodule pointer changes ('M models/foo' or ' M models/foo') and submodule
    internal-content changes (' m models/foo') don't block a workspace-level
    action — that action doesn't touch the submodule. Only return tracked-file
    or untracked-file changes that the action might collide with.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    submodules = _submodule_paths()
    if not submodules:
        return status
    kept = []
    for raw in status.splitlines():
        # porcelain format: XY <space> path; X = staged, Y = working
        if len(raw) < 4:
            continue
        path = raw[3:]
        if path in submodules:
            continue
        kept.append(raw)
    return "\n".join(kept)


def _branched_action(branch_name: str, commit_message: str, action_fn) -> tuple[dict, int]:
    """Run action_fn on a fresh branch off main; commit; return to main.

    Returns (response_dict, http_status_code).

    The pre-flight check ignores submodule pointer/internal changes — workspace-
    level actions don't touch submodules, so a stale submodule pointer (common
    after model-level actions) shouldn't block them. Submodule-level actions use
    a separate helper that DOES enforce submodule cleanliness.
    """
    # Pre-flight: refuse if dirty (excluding submodule lines).
    status = _dirty_excluding_submodules()
    if status.strip():
        return {"error": f"working tree dirty (uncommitted changes): {status[:300]}"}, 409

    # Refuse if branch already exists.
    existing = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    if existing.strip():
        return {
            "error": f"branch '{branch_name}' already exists; resolve in terminal first"
        }, 409

    try:
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=WORKSPACE, check=True,
                       capture_output=True)
        action_fn()  # raises on validation/lint failure

        subprocess.run(["git", "add", "-A"], cwd=WORKSPACE, check=True, capture_output=True)
        # Unstage any submodule pointer/internal changes — workspace-level actions
        # don't own submodules and shouldn't sweep their pointer drift into this
        # commit.
        for sub in _submodule_paths():
            subprocess.run(["git", "reset", "HEAD", "--", sub],
                           cwd=WORKSPACE, check=False, capture_output=True)
        # No-op-commit guard: if action_fn made no changes, abort cleanly.
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        if not diff.strip():
            subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=True,
                           capture_output=True)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=WORKSPACE, check=True,
                           capture_output=True)
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
        # Return to main so the next action also branches off main.
        subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=True,
                       capture_output=True)
        return {
            "branch": branch_name,
            "commit": commit_sha[:7],
            "message": commit_message,
        }, 200
    except subprocess.CalledProcessError as e:
        _cleanup_branch(branch_name)
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return {"error": f"git error: {stderr[:300]}"}, 500
    except Exception as e:
        _cleanup_branch(branch_name)
        return {"error": str(e)}, 500


def _branched_action_submodule(
    branch_name: str,
    commit_message: str,
    action_fn,
    submodule_path: str,
) -> tuple[dict, int]:
    """Like _branched_action but for changes inside a git submodule.

    Commits inside the submodule first, then updates the submodule pointer
    in the workspace repo on a feature branch.

    submodule_path: path relative to WORKSPACE (e.g. 'models/chromosome-rep1')
    """
    sub_dir = WORKSPACE / submodule_path

    # Pre-flight: workspace root must be clean.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    if status.strip():
        return {"error": f"working tree dirty (uncommitted changes): {status[:300]}"}, 409

    # Pre-flight: submodule must be clean too.
    sub_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=sub_dir, capture_output=True, text=True, check=True,
    ).stdout
    if sub_status.strip():
        return {
            "error": f"submodule '{submodule_path}' has uncommitted changes: {sub_status[:300]}"
        }, 409

    # Refuse if branch already exists in workspace.
    existing = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    if existing.strip():
        return {
            "error": f"branch '{branch_name}' already exists; resolve in terminal first"
        }, 409

    try:
        # Run the action (writes files inside the submodule).
        action_fn()

        # Commit inside the submodule.
        subprocess.run(["git", "add", "-A"], cwd=sub_dir, check=True, capture_output=True)
        sub_diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=sub_dir, capture_output=True, text=True, check=True,
        ).stdout
        if not sub_diff.strip():
            # Nothing actually changed in the submodule.
            return {"error": "action made no changes (already at this state?)"}, 409

        subprocess.run([
            "git", "-c", "user.email=pbg-template@local",
                   "-c", "user.name=pbg-template",
                   "commit", "-m", commit_message,
        ], cwd=sub_dir, check=True, capture_output=True)
        sub_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=sub_dir, capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Now update the workspace repo: create branch, stage submodule pointer, commit.
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=WORKSPACE, check=True,
                       capture_output=True)
        subprocess.run(["git", "add", submodule_path], cwd=WORKSPACE, check=True,
                       capture_output=True)
        subprocess.run([
            "git", "-c", "user.email=pbg-template@local",
                   "-c", "user.name=pbg-template",
                   "commit", "-m", commit_message,
        ], cwd=WORKSPACE, check=True, capture_output=True)
        ws_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout.strip()

        subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=True,
                       capture_output=True)
        # Restore submodule to what main's pointer expects.
        subprocess.run(["git", "submodule", "update", "--", submodule_path],
                       cwd=WORKSPACE, check=False, capture_output=True)

        return {
            "branch": branch_name,
            "commit": ws_sha[:7],
            "submodule_commit": sub_sha[:7],
            "message": commit_message,
        }, 200

    except subprocess.CalledProcessError as e:
        # Best-effort cleanup.
        _cleanup_submodule_branch(branch_name, sub_dir, submodule_path)
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return {"error": f"git error: {stderr[:300]}"}, 500
    except Exception as e:
        _cleanup_submodule_branch(branch_name, sub_dir, submodule_path)
        return {"error": str(e)}, 500


def _branched_action_submodule_with_ws(
    branch_name: str,
    commit_message: str,
    action_fn,
    ws_action_fn,
    submodule_path: str,
) -> tuple[dict, int]:
    """Like _branched_action_submodule but also runs ws_action_fn (updates workspace.yaml).

    action_fn: writes files inside the submodule.
    ws_action_fn: updates workspace.yaml (run AFTER the workspace branch is created).
    """
    sub_dir = WORKSPACE / submodule_path

    # Pre-flight: workspace root must be clean.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    if status.strip():
        return {"error": f"working tree dirty (uncommitted changes): {status[:300]}"}, 409

    # Pre-flight: submodule must be clean.
    sub_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=sub_dir, capture_output=True, text=True, check=True,
    ).stdout
    if sub_status.strip():
        return {
            "error": f"submodule '{submodule_path}' has uncommitted changes: {sub_status[:300]}"
        }, 409

    existing = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=WORKSPACE, capture_output=True, text=True, check=True,
    ).stdout
    if existing.strip():
        return {
            "error": f"branch '{branch_name}' already exists; resolve in terminal first"
        }, 409

    try:
        action_fn()  # writes files inside the submodule

        # Commit inside the submodule.
        subprocess.run(["git", "add", "-A"], cwd=sub_dir, check=True, capture_output=True)
        sub_diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=sub_dir, capture_output=True, text=True, check=True,
        ).stdout
        if not sub_diff.strip():
            return {"error": "action made no changes in submodule (already at this state?)"}, 409

        subprocess.run([
            "git", "-c", "user.email=pbg-template@local",
                   "-c", "user.name=pbg-template",
                   "commit", "-m", commit_message,
        ], cwd=sub_dir, check=True, capture_output=True)
        sub_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=sub_dir, capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Create workspace branch; run ws_action_fn; stage everything; commit.
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=WORKSPACE, check=True,
                       capture_output=True)
        ws_action_fn()  # updates workspace.yaml
        subprocess.run(["git", "add", "-A"], cwd=WORKSPACE, check=True, capture_output=True)
        subprocess.run([
            "git", "-c", "user.email=pbg-template@local",
                   "-c", "user.name=pbg-template",
                   "commit", "-m", commit_message,
        ], cwd=WORKSPACE, check=True, capture_output=True)
        ws_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout.strip()

        subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=True,
                       capture_output=True)
        # Restore submodule to what main's pointer expects.
        subprocess.run(["git", "submodule", "update", "--", submodule_path],
                       cwd=WORKSPACE, check=False, capture_output=True)
        return {
            "branch": branch_name,
            "commit": ws_sha[:7],
            "submodule_commit": sub_sha[:7],
            "message": commit_message,
        }, 200

    except subprocess.CalledProcessError as e:
        _cleanup_submodule_branch(branch_name, sub_dir, submodule_path)
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return {"error": f"git error: {stderr[:300]}"}, 500
    except Exception as e:
        _cleanup_submodule_branch(branch_name, sub_dir, submodule_path)
        return {"error": str(e)}, 500


def _cleanup_submodule_branch(branch_name: str, sub_dir: Path, submodule_path: str) -> None:
    """Best-effort cleanup for submodule-branched actions."""
    subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=False,
                   capture_output=True)
    subprocess.run(["git", "branch", "-D", branch_name], cwd=WORKSPACE, check=False,
                   capture_output=True)
    # Restore submodule to what main's pointer expects.
    subprocess.run(["git", "submodule", "update", "--", submodule_path],
                   cwd=WORKSPACE, check=False, capture_output=True)


def _cleanup_branch(branch_name: str) -> None:
    """Best-effort: return to main and delete the branch."""
    subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=False,
                   capture_output=True)
    subprocess.run(["git", "branch", "-D", branch_name], cwd=WORKSPACE, check=False,
                   capture_output=True)


def _safe_slug(s: str) -> str:
    """Convert a string to a safe branch name component."""
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40]


def _model_submodule_path(model: str) -> str:
    """Return the submodule path for a model (relative to workspace root).

    Checks workspace.yaml for submodule_path; falls back to 'models/<model>'.
    The returned value is always relative to WORKSPACE.
    """
    try:
        ws = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        m_data = (ws.get("models") or {}).get(model, {})
        sub_path = m_data.get("submodule_path", "")
        if sub_path:
            return sub_path
    except Exception:
        pass
    return f"models/{model}"


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
        rel = self.path.lstrip("/")
        # Refuse path traversal and absolute paths.
        if ".." in rel.split("/") or rel.startswith("/"):
            self.send_response(403); self.end_headers(); return
        # Resolve under the workspace root so per-model reports
        # (e.g. /models/<name>/reports/index.html) are reachable.
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
            "/api/dataset":            self._post_dataset,
            "/api/reference-pdf":      self._post_reference_pdf,
            "/api/reference-bibtex":   self._post_reference,
            # Legacy alias kept for backward compat (v0.1.9 and earlier).
            "/api/reference":          self._post_reference,
            "/api/expert-doc":         self._post_expert_doc,
            "/api/acceptance":         self._post_acceptance,
            "/api/phase-plan":         self._post_phase_plan,
            "/api/phase-start":        self._post_phase_start,
            "/api/phase-gate":         self._post_phase_gate,
            "/api/run-tests":          self._post_run_tests,
            "/api/render":             self._post_render,
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
        name = body.get("name", "").strip()
        source = body.get("source", "").strip()
        ref = body.get("ref", "").strip()
        mode = body.get("mode", "").strip()
        description = body.get("description", "").strip() or None

        if not all([name, source, ref, mode]):
            return self._json({"error": "name, source, ref, mode are required"}, 400)
        if mode not in ("reference", "fork-source", "in-place"):
            return self._json({"error": "mode must be one of: reference, fork-source, in-place"}, 400)
        if re.search(r'[^\w\-.]', name):
            return self._json({"error": "name must contain only word chars, hyphens, dots"}, 400)

        import time as _time
        epoch = int(_time.time())
        branch = f"stage/0.5-import-{_safe_slug(name)}-{epoch}"
        commit_msg = f"feat(0.5): register import '{name}' (mode={mode})"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.imports import register_import
            register_import(
                WORKSPACE, name=name, source=source, ref=ref, mode=mode,
                description=description,
            )

        resp, code = _branched_action(branch, commit_msg, action)
        if code == 200:
            # Add guidance about submodule step.
            if mode in ("reference",):
                resp["next_terminal_step"] = f"git submodule add {source} external/{name}"
            elif mode == "in-place":
                resp["next_terminal_step"] = f"git submodule add {source} models/{name}"
            else:
                resp["next_terminal_step"] = "(fork-source: no submodule needed until you run /pbg-add-model --from-import)"
            resp["note"] = (
                "git submodule add is NOT performed by the server (requires terminal for network/auth). "
                "Run 'next_terminal_step' from your workspace root to complete the import."
            )
        return self._json(resp, code)

    def _post_dataset(self, body: dict):
        name = body.get("name", "").strip()
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
        filename = body.get("filename", "").strip()
        path = body.get("path", "").strip()
        url = body.get("url", "").strip()

        if file_b64:
            # Drag-drop upload mode.
            if not filename:
                return self._json({"error": "filename is required when file_b64 is provided"}, 400)
            dest_rel = f"datasets/{_safe_slug(name)}/{filename}"
            entry["path"] = dest_rel
            # sha256 computed in action() after write
        elif path:
            entry["path"] = path
        elif url:
            entry["url"] = url
            sha256 = body.get("sha256", "").strip()
            if sha256:
                entry["sha256"] = sha256
        else:
            return self._json({"error": "either file_b64, path, or url is required"}, 400)

        import time as _time
        epoch = int(_time.time())
        branch = f"stage/4-dataset-{_safe_slug(name)}-{epoch}"
        commit_msg = f"feat(4): register dataset '{name}'"

        def action():
            nonlocal entry
            if file_b64:
                dest = WORKSPACE / entry["path"]
                sha = _save_upload(file_b64, dest)
                entry["sha256"] = sha
            elif path and not file_b64:
                # Legacy source_path copy: also compute sha256.
                import shutil as _shutil
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
            # Avoid duplicate names.
            for existing in datasets:
                if isinstance(existing, dict) and existing.get("name") == name:
                    raise ValueError(f"dataset '{name}' already registered")
            datasets.append(entry)
            save_workspace(ws_file, ws)

        return self._json(*_branched_action(branch, commit_msg, action))

    def _post_reference_pdf(self, body: dict):
        """Primary PDF-first reference flow (v0.1.10).

        Required: bib_key, title, authors, year, pdf_b64, pdf_filename.
        Optional: journal, doi, claim_mappings (list of claim IDs).
        Auto-generates BibTeX from typed metadata; saves PDF to
        references/papers/<bib_key>.pdf; appends entry to papers.bib and
        references_pdfs in workspace.yaml.
        """
        bib_key = body.get("bib_key", "").strip()
        title = body.get("title", "").strip()
        authors = body.get("authors", "").strip()
        year_raw = body.get("year")
        journal = body.get("journal", "").strip() or None
        doi = body.get("doi", "").strip() or None
        pdf_b64 = body.get("pdf_b64", "").strip()
        pdf_filename = body.get("pdf_filename", "").strip()
        claim_mappings_raw = body.get("claim_mappings", [])

        # Validate required fields.
        if not bib_key:
            return self._json({"error": "bib_key is required"}, 400)
        if not re.match(r"^[A-Za-z0-9_:\-]+$", bib_key):
            return self._json({"error": "bib_key must match ^[A-Za-z0-9_:-]+$"}, 400)
        if not title:
            return self._json({"error": "title is required"}, 400)
        if not authors:
            return self._json({"error": "authors is required"}, 400)
        if year_raw is None:
            return self._json({"error": "year is required"}, 400)
        try:
            year = int(year_raw)
        except (ValueError, TypeError):
            return self._json({"error": "year must be an integer"}, 400)
        if not pdf_b64:
            return self._json({"error": "pdf_b64 is required (drop a PDF first)"}, 400)
        if not pdf_filename:
            return self._json({"error": "pdf_filename is required"}, 400)

        # Normalise claim_mappings: accept list of claim IDs or comma-separated string.
        if isinstance(claim_mappings_raw, str):
            claim_ids: list[str] = [c.strip() for c in claim_mappings_raw.split(",") if c.strip()]
        elif isinstance(claim_mappings_raw, list):
            claim_ids = [str(c).strip() for c in claim_mappings_raw if str(c).strip()]
        else:
            claim_ids = []

        import time as _time
        epoch = int(_time.time())
        branch = f"stage/5-reference-{_safe_slug(bib_key)}-{epoch}"
        commit_msg = f"feat(5): add reference '{bib_key}' (PDF + auto-generated BibTeX)"

        def action():
            bib_file = WORKSPACE / "references" / "papers.bib"
            claims_file = WORKSPACE / "references" / "claims.yaml"
            pdf_dest_rel = f"references/papers/{bib_key}.pdf"
            pdf_dest = WORKSPACE / pdf_dest_rel

            # Validate bib_key uniqueness.
            if bib_file.exists():
                existing_text = bib_file.read_text()
                if f"{{{bib_key}," in existing_text or f"{{{bib_key} " in existing_text:
                    raise ValueError(f"BibTeX key '{bib_key}' already exists in papers.bib")

            # Save PDF.
            sha = _save_upload(pdf_b64, pdf_dest)

            # Build and append BibTeX.
            _ws_add_to_sys_path()
            from scripts._lib.bibtex import render_bibtex
            bibtex_entry = render_bibtex(
                bib_key=bib_key, title=title, authors=authors, year=year,
                journal=journal, doi=doi,
            )
            bib_file.parent.mkdir(parents=True, exist_ok=True)
            with bib_file.open("a") as f:
                f.write("\n" + bibtex_entry)

            # Append to references_pdfs in workspace.yaml.
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            refs_pdfs = ws.setdefault("references_pdfs", [])
            if refs_pdfs is None:
                refs_pdfs = []
                ws["references_pdfs"] = refs_pdfs
            if not any(e.get("bib_key") == bib_key for e in refs_pdfs):
                refs_pdfs.append({"bib_key": bib_key, "path": pdf_dest_rel, "sha256": sha})
            save_workspace(ws_file, ws)

            # Update claims.yaml if claim IDs provided.
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

        return self._json(*_branched_action(branch, commit_msg, action))

    def _post_reference(self, body: dict):
        """Legacy BibTeX-paste reference flow (now also served as /api/reference-bibtex)."""
        bibtex_text = body.get("bibtex_text", "").strip()
        claim_mappings_raw = body.get("claim_mappings", {})
        pdf_b64 = body.get("pdf_b64", "").strip()
        pdf_filename = body.get("pdf_filename", "").strip()

        if not bibtex_text:
            return self._json({"error": "bibtex_text is required"}, 400)

        # Parse bib key from @Type{key, ...}
        m = re.search(r"@\w+\{([^,\s]+)", bibtex_text)
        if not m:
            return self._json({"error": "could not parse BibTeX key from bibtex_text"}, 400)
        bibkey = m.group(1).strip()

        # Parse claim_mappings: accept dict or "claim:key, claim:key" string.
        if isinstance(claim_mappings_raw, str):
            claim_mappings: dict = {}
            for pair in claim_mappings_raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    cid, bkey = pair.split(":", 1)
                    claim_mappings[cid.strip()] = bkey.strip()
        else:
            claim_mappings = dict(claim_mappings_raw) if claim_mappings_raw else {}

        import time as _time
        epoch = int(_time.time())
        branch = f"stage/5-reference-{_safe_slug(bibkey)}-{epoch}"
        commit_msg = f"feat(5): add reference '{bibkey}'"

        def action():
            bib_file = WORKSPACE / "references" / "papers.bib"
            claims_file = WORKSPACE / "references" / "claims.yaml"

            # Check bib key uniqueness.
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

            # Optional: save the accompanying PDF.
            if pdf_b64:
                pdf_dest_rel = f"references/papers/{bibkey}.pdf"
                pdf_dest = WORKSPACE / pdf_dest_rel
                sha = _save_upload(pdf_b64, pdf_dest)

                # Append to references_pdfs in workspace.yaml.
                _ws_add_to_sys_path()
                from scripts._lib.workspace_yaml import load_workspace, save_workspace
                ws_file = WORKSPACE / "workspace.yaml"
                ws = load_workspace(ws_file)
                refs_pdfs = ws.setdefault("references_pdfs", [])
                if refs_pdfs is None:
                    refs_pdfs = []
                    ws["references_pdfs"] = refs_pdfs
                # Avoid duplicates.
                if not any(e.get("bib_key") == bibkey for e in refs_pdfs):
                    refs_pdfs.append({"bib_key": bibkey, "path": pdf_dest_rel, "sha256": sha})
                save_workspace(ws_file, ws)

        return self._json(*_branched_action(branch, commit_msg, action))

    def _post_expert_doc(self, body: dict):
        """Register an expert document (PDF, lab notes, etc.) in workspace.yaml.

        Body fields (v0.1.9: accepts either file_b64+filename OR source_path):
          name         (required) — short label, used as filename stem
          file_b64     (new) — base64-encoded file content (drag-drop upload)
          filename     (new) — original filename, used to derive extension
          source_path  (legacy) — absolute or workspace-relative path to file on disk
          description  (optional)
          contributor  (optional)
          claims_supported (optional list or comma-separated string)
        """
        import shutil as _shutil
        import time as _time

        name = body.get("name", "").strip()
        file_b64 = body.get("file_b64", "").strip()
        filename = body.get("filename", "").strip()
        source_path_raw = body.get("source_path", "").strip()
        description = body.get("description", "").strip() or None
        contributor = body.get("contributor", "").strip() or None
        claims_raw = body.get("claims_supported", [])

        if not name:
            return self._json({"error": "name is required"}, 400)
        if not file_b64 and not source_path_raw:
            return self._json({"error": "either file_b64+filename or source_path is required"}, 400)

        # Parse claims_supported.
        if isinstance(claims_raw, str):
            claims_supported = [c.strip() for c in claims_raw.split(",") if c.strip()]
        elif isinstance(claims_raw, list):
            claims_supported = list(claims_raw)
        else:
            claims_supported = []

        if file_b64:
            # Drag-drop upload mode: derive extension from filename.
            if not filename:
                return self._json({"error": "filename is required when file_b64 is provided"}, 400)
            ext = Path(filename).suffix if Path(filename).suffix else ".pdf"
            dest_rel = f"references/expert/{_safe_slug(name)}{ext}"
            source_path = None
        else:
            # Legacy source_path copy mode.
            source_path = Path(source_path_raw)
            if not source_path.is_absolute():
                source_path = WORKSPACE / source_path
            if not source_path.exists():
                return self._json({"error": f"source_path does not exist: {source_path}"}, 400)
            if not source_path.is_file():
                return self._json({"error": f"source_path is not a regular file: {source_path}"}, 400)
            ext = source_path.suffix if source_path.suffix else ".pdf"
            dest_rel = f"references/expert/{_safe_slug(name)}{ext}"

        epoch = int(_time.time())
        branch = f"stage/5-expert-doc-{_safe_slug(name)}-{epoch}"
        commit_msg = f"feat(5): add expert document '{name}'"

        def action():
            dest = WORKSPACE / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if file_b64:
                sha = _save_upload(file_b64, dest)
            else:
                _shutil.copy2(str(source_path), str(dest))
                # Compute sha256 for legacy copies too.
                import hashlib as _hashlib
                h = _hashlib.sha256()
                with dest.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                sha = h.hexdigest()

            # Update workspace.yaml.
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            expert_docs = ws.setdefault("expert_docs", [])
            if expert_docs is None:
                expert_docs = []
                ws["expert_docs"] = expert_docs
            # Avoid duplicate names.
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

        return self._json(*_branched_action(branch, commit_msg, action))

    def _post_acceptance(self, body: dict):
        model = body.get("model", "").strip()
        test_id = body.get("test_id", "").strip()
        statement = body.get("statement", "").strip()
        perturbation = body.get("perturbation", "").strip()
        observable = body.get("observable", "").strip()

        if not all([model, test_id, statement]):
            return self._json({"error": "model, test_id, statement are required"}, 400)

        submodule_path = _model_submodule_path(model)
        import time as _time
        epoch = int(_time.time())
        branch = f"stage/6-acceptance-{_safe_slug(model)}-{_safe_slug(test_id)}-{epoch}"
        commit_msg = f"feat(6): add acceptance test '{test_id}' for model '{model}'"

        def action():
            import yaml as _yaml
            acceptance_file = WORKSPACE / "models" / model / "expert" / "acceptance.yaml"
            acceptance_file.parent.mkdir(parents=True, exist_ok=True)
            existing: list = []
            if acceptance_file.exists():
                try:
                    existing = _yaml.safe_load(acceptance_file.read_text()) or []
                except Exception:
                    existing = []
            # Check for duplicate test_id.
            for t in existing:
                if isinstance(t, dict) and t.get("id") == test_id:
                    raise ValueError(f"acceptance test '{test_id}' already defined")
            entry: dict = {
                "id": test_id,
                "desc": statement,
                "status": "pending",
            }
            if perturbation:
                entry["perturbation"] = perturbation
            if observable:
                entry["observable"] = observable
            existing.append(entry)
            acceptance_file.write_text(_yaml.safe_dump(existing, sort_keys=False))

        return self._json(*_branched_action_submodule(branch, commit_msg, action, submodule_path))

    def _post_phase_plan(self, body: dict):
        model = body.get("model", "").strip()
        phases_input = body.get("phases", [])

        if not model:
            return self._json({"error": "model is required"}, 400)
        if not isinstance(phases_input, list) or not phases_input:
            return self._json({"error": "phases must be a non-empty list"}, 400)

        # Normalise phases list.
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

        submodule_path = _model_submodule_path(model)
        import time as _time
        epoch = int(_time.time())
        branch = f"stage/8-phase-plan-{_safe_slug(model)}-{epoch}"
        commit_msg = f"feat(8): plan phases for model '{model}' (N={len(phases)})"

        # Phase plan touches both the submodule (phase-*.md files) and workspace.yaml.
        # Strategy: write submodule files + workspace.yaml, commit submodule, then
        # create workspace branch that updates workspace.yaml + submodule pointer.
        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_files import create_initial_plan

            phases_dir = WORKSPACE / "models" / model / "phases"
            create_initial_plan(phases_dir, model, phases)

        def ws_action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            models_map = ws.setdefault("models", {})
            if model not in models_map:
                raise ValueError(f"model '{model}' not found in workspace.yaml")
            # Store minimal phase list in workspace.yaml.
            models_map[model]["phases"] = [
                {"n": p["n"], "name": p["name"], "status": "planned"}
                for p in phases
            ]
            save_workspace(ws_file, ws)

        # Use the submodule variant for the submodule-level changes,
        # then also update workspace.yaml on the same workspace branch.
        sub_dir = WORKSPACE / submodule_path

        # Pre-flight checks.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        if status.strip():
            return self._json({"error": f"working tree dirty: {status[:300]}"}, 409)
        sub_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=sub_dir, capture_output=True, text=True, check=True,
        ).stdout
        if sub_status.strip():
            return self._json({"error": f"submodule '{submodule_path}' dirty: {sub_status[:300]}"}, 409)
        existing = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        if existing.strip():
            return self._json({"error": f"branch '{branch}' already exists"}, 409)

        try:
            action()  # writes phase-*.md into submodule

            # Commit in submodule.
            subprocess.run(["git", "add", "-A"], cwd=sub_dir, check=True, capture_output=True)
            sub_diff = subprocess.run(
                ["git", "diff", "--cached", "--stat"],
                cwd=sub_dir, capture_output=True, text=True, check=True,
            ).stdout
            if not sub_diff.strip():
                return self._json({"error": "no phase files written to submodule"}, 409)
            subprocess.run([
                "git", "-c", "user.email=pbg-template@local",
                       "-c", "user.name=pbg-template",
                       "commit", "-m", commit_msg,
            ], cwd=sub_dir, check=True, capture_output=True)

            # Create workspace branch, update workspace.yaml + submodule pointer.
            subprocess.run(["git", "checkout", "-b", branch], cwd=WORKSPACE, check=True,
                           capture_output=True)
            ws_action()  # updates workspace.yaml
            subprocess.run(["git", "add", "-A"], cwd=WORKSPACE, check=True, capture_output=True)
            subprocess.run([
                "git", "-c", "user.email=pbg-template@local",
                       "-c", "user.name=pbg-template",
                       "commit", "-m", commit_msg,
            ], cwd=WORKSPACE, check=True, capture_output=True)
            ws_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout.strip()
            subprocess.run(["git", "checkout", "main"], cwd=WORKSPACE, check=True,
                           capture_output=True)
            # Restore submodule to what main's pointer expects.
            subprocess.run(["git", "submodule", "update", "--", submodule_path],
                           cwd=WORKSPACE, check=False, capture_output=True)
            return self._json({"branch": branch, "commit": ws_sha[:7], "message": commit_msg}, 200)

        except subprocess.CalledProcessError as e:
            _cleanup_submodule_branch(branch, sub_dir, submodule_path)
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            return self._json({"error": f"git error: {stderr[:300]}"}, 500)
        except Exception as e:
            _cleanup_submodule_branch(branch, sub_dir, submodule_path)
            return self._json({"error": str(e)}, 500)

    def _post_phase_start(self, body: dict):
        model = body.get("model", "").strip()
        n = body.get("n")

        if not model or n is None:
            return self._json({"error": "model and n are required"}, 400)
        n = int(n)

        submodule_path = _model_submodule_path(model)
        import time as _time
        epoch = int(_time.time())
        branch = f"stage/9-phase-{_safe_slug(model)}-{n}-start-{epoch}"
        commit_msg = f"feat(9): start phase {n} for model '{model}'"

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_md import parse_phase_md, render_phase_md
            from scripts._lib.phase_gate import generate_test_module

            phases_dir = WORKSPACE / "models" / model / "phases"
            phase_file = phases_dir / f"phase-{n}.md"
            if not phase_file.exists():
                raise FileNotFoundError(f"phase-{n}.md not found for model '{model}'")

            fm, body_text = parse_phase_md(phase_file.read_text())

            # Gate: refuse if phase n-1 hasn't passed (for n > 1).
            if n > 1:
                prev_file = phases_dir / f"phase-{n-1}.md"
                if prev_file.exists():
                    prev_fm, _ = parse_phase_md(prev_file.read_text())
                    if not prev_fm.get("gate_passed", False):
                        raise ValueError(
                            f"phase {n-1} has not passed its gate "
                            f"(gate_passed={prev_fm.get('gate_passed')}). "
                            "Evaluate the gate for the previous phase first."
                        )

            fm["status"] = "in_progress"
            phase_file.write_text(render_phase_md(fm, body_text))

            # Generate test stubs.
            test_out = WORKSPACE / "models" / model / "tests" / "test_phases.py"
            generate_test_module(fm, test_out)

        def ws_action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            for phase_entry in (ws.get("models", {}).get(model, {}).get("phases") or []):
                if phase_entry.get("n") == n:
                    phase_entry["status"] = "in_progress"
                    break
            save_workspace(ws_file, ws)

        return self._json(*_branched_action_submodule_with_ws(
            branch, commit_msg, action, ws_action, submodule_path
        ))

    def _post_phase_gate(self, body: dict):
        model = body.get("model", "").strip()
        n = body.get("n")

        if not model or n is None:
            return self._json({"error": "model and n are required"}, 400)
        n = int(n)

        submodule_path = _model_submodule_path(model)
        import time as _time
        epoch = int(_time.time())
        branch = f"stage/9-phase-{_safe_slug(model)}-{n}-gate-{epoch}"
        commit_msg = f"feat(9): evaluate gate for phase {n} of '{model}'"

        gate_status = {"status": "gate_pending"}  # mutable container for status

        def action():
            _ws_add_to_sys_path()
            from scripts._lib.phase_md import parse_phase_md, render_phase_md
            from scripts._lib.phase_gate import evaluate_gate

            phases_dir = WORKSPACE / "models" / model / "phases"
            phase_file = phases_dir / f"phase-{n}.md"
            if not phase_file.exists():
                raise FileNotFoundError(f"phase-{n}.md not found for model '{model}'")

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

        def ws_action():
            _ws_add_to_sys_path()
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            for phase_entry in (ws.get("models", {}).get(model, {}).get("phases") or []):
                if phase_entry.get("n") == n:
                    phase_entry["status"] = gate_status["status"]
                    break
            save_workspace(ws_file, ws)

        resp, code = _branched_action_submodule_with_ws(
            branch, commit_msg, action, ws_action, submodule_path
        )
        if code == 200:
            resp["gate_status"] = gate_status["status"]
        return self._json(resp, code)

    def _post_run_tests(self, body: dict):
        """Run pytest for a model. Returns JSON with returncode, stdout, stderr."""
        model = body.get("model", "").strip()
        if not model:
            return self._json({"error": "model is required"}, 400)

        test_dir = WORKSPACE / "models" / model / "tests"
        cmd = [sys.executable, "-m", "pytest", "-v", str(test_dir)]
        try:
            result = subprocess.run(
                cmd, cwd=WORKSPACE,
                capture_output=True, text=True, timeout=120,
            )
            return self._json({
                "model": model,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }, 200)
        except subprocess.TimeoutExpired:
            return self._json({"error": "pytest timed out after 120s"}, 500)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _post_render(self, body: dict):
        """Re-render workspace + all model dashboards. Used as post-action refresh trigger."""
        try:
            _ws_add_to_sys_path()
            from scripts._lib.report import render_workspace_report, render_model_report
            import yaml as _yaml
            render_workspace_report(WORKSPACE)
            ws = _yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
            for model_name in (ws.get("models") or {}):
                try:
                    render_model_report(model_name, WORKSPACE)
                except Exception as e:
                    # Non-fatal — log and continue.
                    print(f"[render] model '{model_name}' error: {e}", flush=True)
            return self._json({"ok": True}, 200)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------

    def _serve_branches(self):
        """Return list of stage/* branches with last-commit info."""
        try:
            # Get all branches starting with stage/
            raw = subprocess.run(
                ["git", "branch", "--list", "stage/*"],
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout
            stage_branches = [b.strip().lstrip("* ") for b in raw.splitlines() if b.strip()]

            # Get current branch.
            current = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=WORKSPACE, capture_output=True, text=True, check=True,
            ).stdout.strip()

            branches = []
            for bname in stage_branches:
                try:
                    # Get last commit sha, subject, date.
                    log = subprocess.run(
                        ["git", "log", "-1", "--format=%H|%s|%ci", bname],
                        cwd=WORKSPACE, capture_output=True, text=True, check=True,
                    ).stdout.strip()
                    parts = log.split("|", 2)
                    sha = parts[0] if parts else ""
                    subject = parts[1] if len(parts) > 1 else ""
                    date_str = parts[2] if len(parts) > 2 else ""

                    # Commits ahead of main.
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
    scripts_parent = str(WORKSPACE)  # so `import scripts._lib.*` works
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
