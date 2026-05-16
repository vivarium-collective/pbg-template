# Workspace-as-v2ecoli-branch + Open-PR top-bar action

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat each pbg-template workspace as a working branch checkout of an upstream repo (default: `vivarium-collective/v2ecoli`). Replace the "Create GitHub repo" flow with "Link to upstream branch". Surface "Open PR" as a top-bar primary action.

**Architecture:**
- New endpoint `POST /api/work-link-branch {upstream_repo?, branch_name?}` — sets `origin` and pushes current branch.
- Repurpose the existing `_post_work_create_github_repo` handler — it stays for backwards compat but the dashboard UI no longer surfaces it. The new handler replaces it as the primary path.
- The existing `_post_work_create_pr` (server.py:3636) is unchanged — it already runs `gh pr create --base main --head <active_branch>`.
- Workspace.yaml gains an optional `upstream_repo:` field. Default is auto-detected from `external/v2ecoli/.git/config` if present, else `vivarium-collective/v2ecoli`.
- Top-bar gains a permanent "Open PR" button next to the workspace name.

**Tech stack:** Python stdlib HTTPServer, `gh` CLI, vanilla JS, Jinja2.

---

## Task 1: Backend — `POST /api/work-link-branch`

**Files:**
- Modify: `vivarium_dashboard/server.py` (add route + handler)
- Create: `tests/test_work_link_branch.py`

- [ ] **Step 1: Verify upstream-detection helper exists.** Look at `vivarium_dashboard/lib/report.py::_detect_github_repo` (called from `_post_work_create_pr`). If it returns `owner/name` strings, reuse it.

- [ ] **Step 2: Add route entry to `_POST_ROUTE_MAP`**:

```python
        "/api/work-link-branch": "_post_work_link_branch",
```

- [ ] **Step 3: Add the handler** (near `_post_work_create_github_repo`, server.py:3557):

```python
    def _post_work_link_branch(self, body: dict):
        """Link the workspace to an upstream branch.

        Body: {upstream_repo?: "owner/name", branch_name?: str, push?: bool=True}.

        - Sets git origin to the upstream (https://github.com/<repo>.git) if absent.
        - Pushes the current branch (or `branch_name`, after renaming if provided).
        - Marks workstream as pushed.
        """
        _ws_add_to_sys_path()
        from vivarium_dashboard.lib.work_state import load_state, save_state
        state = load_state()
        current_branch = state.get("active_branch")
        if not current_branch:
            return self._json({"error": "no active workstream — Start one first so the push has a target"}, 409)

        if not shutil.which("gh"):
            return self._json({"error": "gh CLI not installed. Install via `brew install gh` then `gh auth login`."}, 500)
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if auth.returncode != 0:
            return self._json({"error": "gh not authenticated. Run `gh auth login`."}, 500)

        upstream_repo = (body.get("upstream_repo") or "").strip() or self._default_upstream_repo()
        if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", upstream_repo):
            return self._json({"error": f"upstream_repo must look like owner/name; got {upstream_repo!r}"}, 400)

        # Optional rename of the current branch before pushing.
        target_branch = (body.get("branch_name") or "").strip() or current_branch
        if not re.match(r"^[A-Za-z0-9._/-]+$", target_branch):
            return self._json({"error": "invalid branch name"}, 400)
        if target_branch != current_branch:
            r = subprocess.run(["git", "branch", "-m", current_branch, target_branch],
                               cwd=WORKSPACE, capture_output=True, text=True)
            if r.returncode != 0:
                return self._json({"error": f"branch rename failed: {(r.stderr or r.stdout)[:300]}"}, 500)

        # Set origin if not present (or replace if it points elsewhere).
        upstream_url = f"https://github.com/{upstream_repo}.git"
        existing = subprocess.run(["git", "remote", "get-url", "origin"],
                                  cwd=WORKSPACE, capture_output=True, text=True)
        if existing.returncode != 0:
            r = subprocess.run(["git", "remote", "add", "origin", upstream_url],
                               cwd=WORKSPACE, capture_output=True, text=True)
            if r.returncode != 0:
                return self._json({"error": f"git remote add origin failed: {(r.stderr or r.stdout)[:300]}"}, 500)
        else:
            # If origin already points somewhere else, refuse rather than silently overwriting.
            current_url = (existing.stdout or "").strip()
            if current_url and current_url != upstream_url and current_url != upstream_url.replace("https://github.com/", "git@github.com:"):
                return self._json({
                    "error": f"origin already configured to {current_url}; refusing to overwrite",
                    "current_origin": current_url,
                }, 409)

        # Push the current branch to origin.
        if body.get("push", True):
            r = subprocess.run(["git", "push", "-u", "origin", target_branch],
                               cwd=WORKSPACE, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return self._json({"error": f"git push failed: {(r.stderr or r.stdout)[:500]}"}, 500)

        state["pushed"] = True
        save_state(state)

        return self._json({
            "ok": True,
            "upstream_repo": upstream_repo,
            "branch": target_branch,
            "branch_url": f"https://github.com/{upstream_repo}/tree/{target_branch}",
        }, 200)

    def _default_upstream_repo(self) -> str:
        """Auto-detect upstream repo from workspace.yaml or external/v2ecoli/.git/config.

        Falls back to ``vivarium-collective/v2ecoli`` if nothing else is configured.
        """
        ws_path = WORKSPACE / "workspace.yaml"
        if ws_path.exists():
            try:
                ws_data = yaml.safe_load(ws_path.read_text()) or {}
                ur = (ws_data.get("upstream_repo") or "").strip()
                if ur:
                    return ur
            except yaml.YAMLError:
                pass
        # Try external/v2ecoli's origin.
        external = WORKSPACE / "external" / "v2ecoli"
        if external.is_dir():
            r = subprocess.run(["git", "remote", "get-url", "origin"],
                               cwd=external, capture_output=True, text=True)
            if r.returncode == 0:
                url = r.stdout.strip()
                # https://github.com/owner/name.git or git@github.com:owner/name.git
                m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
                if m:
                    return m.group(1)
        return "vivarium-collective/v2ecoli"
```

- [ ] **Step 4: Tests.** Write `tests/test_work_link_branch.py` that exercises the happy path and the conflict cases (origin already set, no active workstream, invalid repo name). Use a tmp_path workspace + git stub. Reuse the `dashboard_client` fixture.

```python
"""Tests for /api/work-link-branch."""
import subprocess
from pathlib import Path
import yaml
import pytest


def _init_workspace(tmp_path: Path) -> Path:
    """Create a minimal git workspace + workstream state."""
    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    (ws / "workspace.yaml").write_text("name: test-ws\nupstream_repo: vivarium-collective/v2ecoli\n")
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature-branch"], cwd=ws, check=True, capture_output=True)
    # Create .pbg/work/active_branch.json so load_state returns active_branch
    (ws / ".pbg" / "work").mkdir(parents=True)
    (ws / ".pbg" / "work" / "active_branch.json").write_text(
        '{"branch": "feature-branch", "base": "main", "pushed": false}'
    )
    return ws


def test_link_branch_requires_active_workstream(tmp_path, dashboard_client):
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "workspace.yaml").write_text("name: test-ws\n")
    subprocess.run(["git", "init", "-b", "main"], cwd=ws, check=True, capture_output=True)
    client = dashboard_client(workspace=ws)
    resp = client.post("/api/work-link-branch", json={})
    assert resp.status_code == 409, resp.text
    assert "active workstream" in resp.json()["error"].lower()


def test_link_branch_invalid_repo_name(tmp_path, dashboard_client):
    ws = _init_workspace(tmp_path)
    client = dashboard_client(workspace=ws)
    resp = client.post("/api/work-link-branch", json={"upstream_repo": "no-slash"})
    assert resp.status_code == 400, resp.text


def test_link_branch_refuses_overwriting_existing_origin(tmp_path, dashboard_client):
    ws = _init_workspace(tmp_path)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/foo/bar.git"],
                   cwd=ws, check=True)
    client = dashboard_client(workspace=ws)
    resp = client.post("/api/work-link-branch", json={"upstream_repo": "vivarium-collective/v2ecoli", "push": False})
    assert resp.status_code == 409, resp.text
    assert "refusing to overwrite" in resp.json()["error"]
```

Skip the actual push test (would require network or a local bare repo to push to — overkill for this task).

- [ ] **Step 5: Verify.**
```bash
cd /Users/eranagmon/code/vivarium-dashboard-tests-investigations
pytest tests/test_work_link_branch.py -v
```

- [ ] **Step 6: Commit.**
```bash
git add vivarium_dashboard/server.py tests/test_work_link_branch.py
git commit -m "feat(server): POST /api/work-link-branch for upstream-branch workflow"
```

---

## Task 2: UI — replace "Create GitHub repo" modal with "Link to upstream branch"

**Files:**
- Modify: `vivarium_dashboard/templates/index.html.j2` (modal markup + label changes)
- Modify: `vivarium_dashboard/static/walkthrough.js` (`_submitCreateGithubRepo` → `_submitLinkBranch`)

- [ ] **Step 1:** Find the existing modal at `templates/index.html.j2:1125` (`<div id="modal-create-github-repo">`). Replace its body. The button that opens the modal is somewhere else (search for `openModal('modal-create-github-repo')`).

The new modal:

```html
<div id="modal-link-branch" class="modal-overlay">
  <div class="modal-content">
    <button class="modal-close" onclick="closeModal('modal-link-branch')">&times;</button>
    <h3>Link to upstream branch</h3>
    <p class="muted">Push the current workstream branch to a branch on the upstream repo.</p>
    <form id="form-link-branch" onsubmit="event.preventDefault(); _submitLinkBranch(this);">
      <label>Upstream repo:
        <input name="upstream_repo" value="{{ upstream_repo or 'vivarium-collective/v2ecoli' }}"
               pattern="[A-Za-z0-9._-]+/[A-Za-z0-9._-]+" required>
      </label>
      <label>Branch name (optional — defaults to current branch):
        <input name="branch_name" placeholder="leave blank to keep current">
      </label>
      <div class="form-actions">
        <button type="submit" class="action-btn">Push branch</button>
        <button type="button" class="action-btn--secondary" onclick="closeModal('modal-link-branch')">Cancel</button>
      </div>
    </form>
  </div>
</div>
```

Rename every reference: `modal-create-github-repo` → `modal-link-branch` (search index.html.j2 + walkthrough.js). Rename the button label from "Create GitHub repo" to "Link branch to upstream".

- [ ] **Step 2:** In `walkthrough.js`, find `_submitCreateGithubRepo`. Replace with:

```javascript
  function _submitLinkBranch(form) {
    var fd = new FormData(form);
    var body = {
      upstream_repo: (fd.get('upstream_repo') || '').trim(),
      branch_name:   (fd.get('branch_name')   || '').trim(),
    };
    var submitBtn = form.querySelector('button[type=submit]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Pushing…'; }
    fetch('/api/work-link-branch', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }).then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
      .then(function (pair) {
        var ok = pair[0], j = pair[1];
        if (!ok) {
          alert('Push failed: ' + (j.error || 'unknown error'));
          return;
        }
        closeModal('modal-link-branch');
        var url = j.branch_url || '#';
        var msg = 'Branch pushed: ' + j.branch + ' → ' + j.upstream_repo;
        alert(msg + '\n\nOpen in browser: ' + url);
        // Refresh workstream state UI if there is one.
        if (typeof _refreshWorkstreamState === 'function') _refreshWorkstreamState();
      })
      .catch(function (e) { alert('Push failed: ' + e.message); })
      .finally(function () {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Push branch'; }
      });
  }
  window._submitLinkBranch = _submitLinkBranch;
```

You may leave `_submitCreateGithubRepo` in place as a deprecated alias that calls `_submitLinkBranch` — keeps backwards compat for any cached HTML.

- [ ] **Step 3:** Commit.
```bash
git add vivarium_dashboard/templates/index.html.j2 vivarium_dashboard/static/walkthrough.js
git commit -m "feat(ui): replace 'Create GitHub repo' with 'Link to upstream branch' modal"
```

---

## Task 3: Top-bar "Open PR" primary action

**Files:**
- Modify: `vivarium_dashboard/templates/index.html.j2` (top-bar markup)
- Modify: `vivarium_dashboard/static/walkthrough.js` (PR open handler)
- Modify: `vivarium_dashboard/static/style.css` (button styling)

- [ ] **Step 1:** Find the top header bar in `index.html.j2`. Look for the workspace title element (probably `<h1>` or similar near the top of `<body>`). Search for `workspace_name` or `<header` or the `viv-rail-link-label-workspace`-style elements.

- [ ] **Step 2:** Add an "Open PR" button next to the workspace title:

```html
<div class="topbar-actions">
  <button id="btn-open-pr" class="action-btn" onclick="_openPRDialog()" title="Open PR for current branch">
    Open PR ↗
  </button>
</div>
```

The button should be visible always; click → modal dialog with title + body fields → POSTs to `/api/work-create-pr`.

- [ ] **Step 3:** Add a small Open-PR modal:

```html
<div id="modal-open-pr" class="modal-overlay">
  <div class="modal-content">
    <button class="modal-close" onclick="closeModal('modal-open-pr')">&times;</button>
    <h3>Open Pull Request</h3>
    <p class="muted">Opens a PR from the current branch into <code id="pr-base-display">main</code>.</p>
    <form id="form-open-pr" onsubmit="event.preventDefault(); _submitOpenPR(this);">
      <label>Title:
        <input name="title" required>
      </label>
      <label>Body:<br>
        <textarea name="body" rows="6" placeholder="Summary, what changed, test plan..."></textarea>
      </label>
      <div class="form-actions">
        <button type="submit" class="action-btn">Create PR</button>
        <button type="button" class="action-btn--secondary" onclick="closeModal('modal-open-pr')">Cancel</button>
      </div>
    </form>
  </div>
</div>
```

- [ ] **Step 4:** JS in walkthrough.js:

```javascript
  function _openPRDialog() {
    // Prefill title from active branch.
    fetch('/api/state').then(function (r) { return r.json(); }).then(function (state) {
      var branch = (state && state.active_branch) || '';
      var base = (state && state.base) || 'main';
      var titleField = document.querySelector('#form-open-pr input[name=title]');
      if (titleField && branch && !titleField.value) titleField.value = 'Workstream: ' + branch;
      var baseDisp = document.getElementById('pr-base-display');
      if (baseDisp) baseDisp.textContent = base;
      openModal('modal-open-pr');
    });
  }
  window._openPRDialog = _openPRDialog;

  function _submitOpenPR(form) {
    var fd = new FormData(form);
    var body = {
      title: (fd.get('title') || '').trim(),
      body: (fd.get('body') || '').trim(),
    };
    var submit = form.querySelector('button[type=submit]');
    if (submit) { submit.disabled = true; submit.textContent = 'Creating…'; }
    fetch('/api/work-create-pr', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }).then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
      .then(function (pair) {
        var ok = pair[0], j = pair[1];
        if (!ok) {
          var msg = j.error || 'unknown error';
          if (j.manual_url) msg += '\n\nManual URL: ' + j.manual_url;
          alert('PR create failed: ' + msg);
          return;
        }
        closeModal('modal-open-pr');
        alert('PR created: ' + (j.pr_url || ''));
        window.open(j.pr_url, '_blank');
      })
      .finally(function () {
        if (submit) { submit.disabled = false; submit.textContent = 'Create PR'; }
      });
  }
  window._submitOpenPR = _submitOpenPR;
```

- [ ] **Step 5:** CSS — append to `style.css`:

```css
.topbar-actions { display: inline-flex; gap: 0.5rem; margin-left: 1rem; vertical-align: middle; }
#btn-open-pr { padding: 0.4rem 0.8rem; font-weight: 500; }
```

- [ ] **Step 6:** Commit.
```bash
git add vivarium_dashboard/templates/index.html.j2 vivarium_dashboard/static/walkthrough.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): top-bar 'Open PR' primary action wired to /api/work-create-pr"
```

---

## Task 4: Migrate v2ecoli-workspace to link to vivarium-collective/v2ecoli

**Manual (one-time) — don't put in code:**

- [ ] **Step 1:** Verify v2ecoli-workspace is clean.
```bash
cd /Users/eranagmon/code/v2ecoli-workspace
git status --short  # Make sure all changes are committed or stashed.
```

If there are unrelated stray dirs like `investigations/a` and `investigations/b` (from our earlier exploration), delete them: `rm -rf investigations/a investigations/b`.

- [ ] **Step 2:** Decide on a branch name.
- Current branch: `chromosome`.
- Target name: something descriptive of what's been built. Could keep `chromosome` or pick a new name like `eran/workspace-chromosome` to namespace.

- [ ] **Step 3:** Set up origin + push.
```bash
cd /Users/eranagmon/code/v2ecoli-workspace
git remote add origin https://github.com/vivarium-collective/v2ecoli.git
git push -u origin chromosome --set-upstream
```

The push will create the branch on the upstream. Since the workspace's history doesn't share an ancestor with v2ecoli's main, this is an unrelated-history push — GitHub allows it.

- [ ] **Step 4:** Verify.
```bash
gh pr list --repo vivarium-collective/v2ecoli --head chromosome
git branch -vv  # Should show 'chromosome -> origin/chromosome'
```

---

## Self-review

**Spec coverage:**
- Replace "Create GitHub repo" → "Link branch" ✓ (Task 2)
- Push workspace to a branch on v2ecoli ✓ (Task 1 + Task 4)
- "Open PR" in top menu ✓ (Task 3)

**Out of scope (follow-ups):**
- Automatic origin migration on workspace open (currently the user runs Task 4 manually for v2ecoli-workspace).
- A "Refresh from upstream" / sync flow.
- PR template files (.github/PULL_REQUEST_TEMPLATE.md).
- "Switch branch" — the active-workstream system already handles branch creation; this plan doesn't restructure it.
