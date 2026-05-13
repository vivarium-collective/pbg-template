# Unified Composite Study + Composite Explorer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two distinct surfaces emerge from the unification:
- **Composite Study** — the per-study workbench (today's Investigation detail viewer + the just-shipped editor's Configure tab, folded into one). Reached by opening a row in Investigations or by clicking Explore on Simulation Setup → Available Composites.
- **Composite Explorer** — a lightweight read-only catalog viewer. Pick a workspace composite → loom-explore renders it → "Start a Composite Study" CTA. No editing.

Plus: derived composites in a Composite Study can be **Promoted to the workspace catalog** so future studies can reuse them.

**Architecture:** No data-model changes — `spec.yaml.{composites,runs,observables,visualizations}` already supports everything. Add 2 endpoints (`create-from-composite`, `promote-to-catalog`). Remove the 7 inline-edit endpoints we just shipped (their pure-logic helpers stay). Major frontend reshuffle of the Composite Explorer + Investigation pages.

**Tech Stack:** Python 3.10+, vanilla JavaScript, Jinja2 templates, pytest.

---

## File Structure

### Modified

| File | Change |
|---|---|
| `template/scripts/_server/server.py` | Add 2 endpoints; remove 7. |
| `template/scripts/_server/walkthrough.js` | Restructure: drop Composite Explorer's editor tabs; rebuild as read-only viewer; reshape Investigation detail into the Composite Study workbench; fold Configure into the Composites tab; add Promote modal + flow; Sim Setup Explore creates a study; Investigations list shows summary stats. |
| `template/scripts/_templates/index.html.j2` | Composite Explorer page → read-only layout; Investigation detail → unified Composite Study layout; new Promote modal markup. |
| `tests/test_visualization_endpoints.py` | Remove 13 tests for the 7 removed endpoints; add 4 tests for the 2 new endpoints. |

### Unchanged but reused

| File | Why |
|---|---|
| `template/scripts/_lib/compose_doc_edit.py` | Pure-logic helpers (`inject_emitter`, `inject_viz_step`, etc.) stay — `/pbg-emit` skill still uses them. |
| `template/scripts/_lib/composite_recipes.py` | Walk + perturb helpers unchanged. |
| `template/scripts/_lib/investigations.py` | Multi-composite orchestrator unchanged. |
| `template/scripts/_lib/investigation_migrate.py` | Legacy-spec migration unchanged. |

---

## Phase A — Endpoint surface

### Task 1: Remove the 7 inline-edit endpoints + their tests

**Files:**
- Modify: `template/scripts/_server/server.py` (delete 7 handler methods + their dispatch entries)
- Modify: `tests/test_visualization_endpoints.py` (remove 13 tests)

The just-shipped editor (`bf336af` spec / `0e34096` last commit) added these endpoints. The unified design no longer needs them. Delete.

- [ ] **Step 1: List the endpoints to remove + their tests**

Endpoints (all under POST except where noted):
1. `POST /api/composite-process-configs`
2. `POST /api/composite-state-tree-doc`
3. `POST /api/compose-doc-inject-emitter`
4. `POST /api/compose-doc-inject-viz`
5. `POST /api/compose-doc-strip-viz`
6. `GET  /api/visualization-class-inputs`
7. `POST /api/investigation-composite-save-sidecar`

Tests to remove (in `tests/test_visualization_endpoints.py`):
- `test_post_composite_process_configs_*` (2 tests)
- `test_post_composite_state_tree_doc_returns_nodes` (1)
- `test_post_compose_doc_inject_emitter_*` (3 tests)
- `test_post_compose_doc_inject_viz_*` (1) + `test_post_compose_doc_strip_viz` (1)
- `test_get_visualization_class_inputs` (1)
- `test_post_save_sidecar_*` (4 tests)

= 13 tests total.

- [ ] **Step 2: Remove the dispatch entries from `server.py`**

In the POST dispatch dict, delete these lines:
```python
"/api/composite-process-configs":           self._post_composite_process_configs,
"/api/composite-state-tree-doc":            self._post_composite_state_tree_doc,
"/api/compose-doc-inject-emitter":          self._post_compose_doc_inject_emitter,
"/api/compose-doc-inject-viz":              self._post_compose_doc_inject_viz,
"/api/compose-doc-strip-viz":               self._post_compose_doc_strip_viz,
"/api/investigation-composite-save-sidecar": self._post_investigation_composite_save_sidecar,
```

In the GET dispatch, delete:
```python
if self.path.startswith("/api/visualization-class-inputs"):
    return self._get_visualization_class_inputs()
```

- [ ] **Step 3: Remove the handler method bodies**

Search for each handler name in `server.py` and delete its `def ...` block (typically 15-30 lines each). Be careful to preserve adjacent unrelated handlers. After:

```bash
grep -n "_post_composite_process_configs\|_post_composite_state_tree_doc\|_post_compose_doc_inject_emitter\|_post_compose_doc_inject_viz\|_post_compose_doc_strip_viz\|_post_investigation_composite_save_sidecar\|_get_visualization_class_inputs" template/scripts/_server/server.py
```

Expected: no matches.

- [ ] **Step 4: Remove the corresponding tests**

In `tests/test_visualization_endpoints.py`, search for each test name and delete the entire `def test_...` block. After:

```bash
grep -n "process_configs\|composite_state_tree_doc\|compose_doc_inject_emitter\|compose_doc_inject_viz\|compose_doc_strip_viz\|visualization_class_inputs\|save_sidecar" tests/test_visualization_endpoints.py
```

Expected: no matches.

- [ ] **Step 5: Run tests, confirm clean**

```bash
cd /Users/eranagmon/code/pbg-template
python -m py_compile template/scripts/_server/server.py && echo "server.py syntax ok"
python -m pytest tests/test_visualization_endpoints.py -v 2>&1 | tail -10
```

The test file should still have its pre-removal-shipped tests (≈18 tests remain — 31 minus 13).

- [ ] **Step 6: Commit**

```bash
git add template/scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "refactor(unified-ce): remove 7 inline-edit endpoints (rolling back the editor)"
```

The walkthrough.js code that calls these endpoints is removed in Phase B (Task 4). Until then the calls are dead — they'll 404 silently when the Composite Explorer's editor tabs are accessed. That's OK as a one-task gap; Phase B rebuilds the page anyway.

---

### Task 2: `POST /api/investigation-create-from-composite`

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing tests**

```python
def test_post_create_from_composite_creates_study(workspace_server):
    """A new investigation directory is created with the source composite
    cloned into composites/<baseline>.yaml + spec.yaml's composites list."""
    # Seed a workspace composite
    pkg_dir = workspace_server.root / 'pbg_testws' / 'composites'
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / 'baseline.composite.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {'x': {'_type': 'integer', '_default': 1}},
    }))

    code, j = _post(
        workspace_server.url + '/api/investigation-create-from-composite',
        {'source_ref': 'pbg_testws.composites.baseline'},
    )
    assert code == 200, j
    study_name = j['study_name']
    assert study_name.startswith('baseline-'), study_name

    inv_dir = workspace_server.root / 'investigations' / study_name
    spec = yaml.safe_load((inv_dir / 'spec.yaml').read_text())
    assert spec['name'] == study_name
    assert len(spec['composites']) == 1
    entry = spec['composites'][0]
    assert entry['name'] == 'baseline'
    assert entry['source'] == 'pbg_testws.composites.baseline'
    assert entry['document'] == './composites/baseline.yaml'
    assert (inv_dir / 'composites' / 'baseline.yaml').is_file()


def test_post_create_from_composite_auto_name_collision_retry(workspace_server):
    """If the auto-name collides, the server appends -2, -3, ... until clean."""
    pkg_dir = workspace_server.root / 'pbg_testws' / 'composites'
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / 'baseline.composite.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc', 'state': {},
    }))

    # First call creates baseline-<ts>
    code1, j1 = _post(
        workspace_server.url + '/api/investigation-create-from-composite',
        {'source_ref': 'pbg_testws.composites.baseline',
         'study_name': 'my-study'},
    )
    assert code1 == 200
    assert j1['study_name'] == 'my-study'

    # Second call with the same explicit study_name collides → suffix
    code2, j2 = _post(
        workspace_server.url + '/api/investigation-create-from-composite',
        {'source_ref': 'pbg_testws.composites.baseline',
         'study_name': 'my-study'},
    )
    assert code2 == 200
    assert j2['study_name'] == 'my-study-2', j2


def test_post_create_from_composite_unknown_source_404(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-create-from-composite',
        {'source_ref': 'pbg_testws.composites.nonexistent'},
    )
    assert code == 404, j


def test_post_create_from_composite_missing_source_ref_400(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-create-from-composite',
        {},
    )
    assert code == 400, j
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest tests/test_visualization_endpoints.py -k create_from_composite -v
```

- [ ] **Step 3: Add the endpoint to `server.py`**

In the POST dispatch:
```python
"/api/investigation-create-from-composite": self._post_investigation_create_from_composite,
```

Handler:

```python
    def _post_investigation_create_from_composite(self, body: dict):
        """POST /api/investigation-create-from-composite
        Body: {source_ref, study_name?}
        Creates a new investigation directory; clones the source composite
        as composites/<baseline>.yaml; writes spec.yaml with one-entry
        composites list. Returns {study_name}.
        """
        import shutil
        from scripts._lib.investigation_migrate import _resolve_composite_source

        source_ref = (body.get("source_ref") or "").strip()
        explicit_name = (body.get("study_name") or "").strip()
        if not source_ref:
            return self._json({"error": "source_ref required"}, 400)

        try:
            source_path, baseline_name = _resolve_composite_source(source_ref, WORKSPACE)
        except (FileNotFoundError, ValueError) as e:
            return self._json({"error": str(e)}, 404)

        # Auto-name (or use explicit), suffix on collision
        candidate = explicit_name or baseline_name
        investigations_root = WORKSPACE / "investigations"
        investigations_root.mkdir(parents=True, exist_ok=True)
        suffix = 1
        chosen = candidate
        while (investigations_root / chosen).exists():
            suffix += 1
            chosen = f"{candidate}-{suffix}"

        commit_msg = f"feat(investigations): create study '{chosen}' from {source_ref}"

        def do_action():
            inv_dir = investigations_root / chosen
            composites_dir = inv_dir / "composites"
            composites_dir.mkdir(parents=True, exist_ok=True)
            sidecar = composites_dir / f"{baseline_name}.yaml"
            shutil.copy2(source_path, sidecar)
            (inv_dir / "spec.yaml").write_text(yaml.safe_dump({
                "name": chosen,
                "composites": [{
                    "name": baseline_name,
                    "source": source_ref,
                    "document": f"./composites/{baseline_name}.yaml",
                }],
                "runs": [],
                "observables": [],
                "visualizations": [],
            }, sort_keys=False))

        try:
            resp, code = _commit_or_run(commit_msg, do_action)
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
        if code in (200, 409):
            # 409 is OK in bare-workspace tests if _commit_or_run runs the
            # action without the git commit; the files are on disk.
            return self._json({"study_name": chosen, **(resp or {})}, 200)
        return self._json(resp, code)
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_visualization_endpoints.py -v 2>&1 | tail -10
git add template/scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "feat(unified-ce): /api/investigation-create-from-composite endpoint"
```

---

### Task 3: `POST /api/composite-promote-to-catalog`

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing tests**

```python
def test_post_promote_to_catalog_copies_sidecar(workspace_server):
    """Promoting a study's sidecar copies it into <pkg>/composites/<name>.composite.yaml + sets description."""
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'tuned.yaml').write_text(yaml.safe_dump({
        'name': 'tuned',
        'state': {'p': {'_type': 'process', 'address': 'local:Foo', 'config': {'r': 2.0}}},
    }))
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'tuned', 'extends': 'baseline',
                         'document': './composites/tuned.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/composite-promote-to-catalog',
        {'investigation': 'demo', 'sidecar_name': 'tuned',
         'catalog_name': 'tuned-baseline',
         'description': 'higher-rate variant promoted from study demo'},
    )
    assert code == 200, j

    catalog_file = workspace_server.root / 'pbg_testws' / 'composites' / 'tuned-baseline.composite.yaml'
    assert catalog_file.is_file()
    doc = yaml.safe_load(catalog_file.read_text())
    assert doc.get('description') == 'higher-rate variant promoted from study demo'
    assert doc['state']['p']['config']['r'] == 2.0  # content preserved

    spec_after = yaml.safe_load((inv / 'spec.yaml').read_text())
    entry = next(c for c in spec_after['composites'] if c['name'] == 'tuned')
    assert entry.get('promoted') is True


def test_post_promote_to_catalog_refuses_duplicate(workspace_server):
    pkg = workspace_server.root / 'pbg_testws' / 'composites'
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / 'taken.composite.yaml').write_text('name: taken\nstate: {}\n')
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'tuned.yaml').write_text('name: tuned\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'tuned', 'extends': 'baseline',
                         'document': './composites/tuned.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/composite-promote-to-catalog',
        {'investigation': 'demo', 'sidecar_name': 'tuned',
         'catalog_name': 'taken', 'description': 'x'},
    )
    assert code == 409, j


def test_post_promote_to_catalog_unknown_sidecar_404(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text('name: demo\ncomposites: []\nruns: []\n')
    code, j = _post(
        workspace_server.url + '/api/composite-promote-to-catalog',
        {'investigation': 'demo', 'sidecar_name': 'nonexistent',
         'catalog_name': 'x', 'description': 'y'},
    )
    assert code == 404, j


def test_post_promote_to_catalog_invalid_catalog_name_400(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'tuned.yaml').write_text('name: tuned\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'tuned', 'document': './composites/tuned.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/composite-promote-to-catalog',
        {'investigation': 'demo', 'sidecar_name': 'tuned',
         'catalog_name': 'has spaces', 'description': 'x'},
    )
    assert code == 400, j
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest tests/test_visualization_endpoints.py -k promote_to_catalog -v
```

- [ ] **Step 3: Add the endpoint to `server.py`**

POST dispatch:
```python
"/api/composite-promote-to-catalog": self._post_composite_promote_to_catalog,
```

Handler:

```python
    def _post_composite_promote_to_catalog(self, body: dict):
        """POST /api/composite-promote-to-catalog
        Body: {investigation, sidecar_name, catalog_name, description, target_pkg?}
        Copies investigations/<inv>/composites/<sidecar>.yaml to
        <pkg>/composites/<catalog_name>.composite.yaml with the given
        description; marks the study's composite entry as promoted: true.
        """
        import shutil

        inv_name = (body.get("investigation") or "").strip()
        sidecar_name = (body.get("sidecar_name") or "").strip()
        catalog_name = (body.get("catalog_name") or "").strip()
        description = (body.get("description") or "").strip()
        target_pkg = (body.get("target_pkg") or "").strip()

        if not (inv_name and sidecar_name and catalog_name):
            return self._json(
                {"error": "investigation, sidecar_name, catalog_name required"}, 400
            )
        if not re.match(r"^[a-zA-Z0-9_-]+$", catalog_name):
            return self._json({"error": "catalog_name must match ^[a-zA-Z0-9_-]+$"}, 400)

        inv_dir = WORKSPACE / "investigations" / inv_name
        spec_path = inv_dir / "spec.yaml"
        sidecar = inv_dir / "composites" / f"{sidecar_name}.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)
        if not sidecar.is_file():
            return self._json({"error": f"sidecar {sidecar_name!r} not found"}, 404)

        # Resolve target package
        if not target_pkg:
            ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text()) or {}
            target_pkg = ws_data.get("package_path") or \
                         ("pbg_" + (ws_data.get("name") or "").replace("-", "_"))
        catalog_dir = WORKSPACE / target_pkg / "composites"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        catalog_file = catalog_dir / f"{catalog_name}.composite.yaml"
        if catalog_file.exists():
            return self._json({
                "error": f"composite {catalog_name!r} already exists in catalog"
            }, 409)

        commit_msg = (f"feat(catalog): promote '{sidecar_name}' from study '{inv_name}' "
                      f"to {target_pkg}.composites.{catalog_name}")

        def do_action():
            # Read the sidecar; inject the description into the document
            doc = yaml.safe_load(sidecar.read_text()) or {}
            if description:
                doc["description"] = description
            catalog_file.write_text(yaml.safe_dump(doc, sort_keys=False))
            # Mark the study's composite entry as promoted
            spec = yaml.safe_load(spec_path.read_text()) or {}
            for entry in (spec.get("composites") or []):
                if entry.get("name") == sidecar_name:
                    entry["promoted"] = True
                    break
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            return self._json(*_commit_or_run(commit_msg, do_action))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_visualization_endpoints.py -v 2>&1 | tail -10
git add template/scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "feat(unified-ce): /api/composite-promote-to-catalog endpoint"
```

---

## Phase B — Composite Study workbench

### Task 4: Workbench layout + drop legacy editor surface

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

The work here has two halves:
- Remove the Composite Explorer page's editor tabs (the 3 just-shipped tabs + Save modal). These are now dead since Phase A removed their endpoints.
- Reshape the Investigation detail viewer into the Composite Study workbench (the 4-tab layout per the spec).

- [ ] **Step 1: Remove the editor tab markup from the Composite Explorer page**

In `template/scripts/_templates/index.html.j2`, find the `#page-composite-explore` section (or wherever the editor's tab strip was added). Remove:

- The `<div>` containing the tab strip with Configure/Observables/Visualization buttons + Save sidecar button.
- The `<div id="ce-panel-configure" class="ce-panel">` (and the other two panels).
- The Save modal markup (`modal-ce-save`).
- The associated CSS rules (`.ce-tab`, `.ce-panel`) — leave them if other parts of the dashboard use the same classes; otherwise remove.

The remaining Composite Explorer page should have just:
- A composite-picker (catalog dropdown or list)
- The loom-explore iframe
- (Phase D adds the "Start a Composite Study" button — placeholder OK now.)

- [ ] **Step 2: Remove the editor JS from walkthrough.js**

Delete these functions:
- `_ceSwitchTab`
- `_cePushDocToLoom`
- `_ceRenderConfigure`, `_ceRenderObservables`, `_ceRenderVisualization`
- `_ceUpdateConfig`
- `_ceObservablesChanged`
- `_ceVizChanged`, `_ceVizRemove`
- `_ceOpenSaveModal`, `_ceSubmitSave`

Plus the `window._composeDoc` / `window._composeDocSourceRef` / `window._ceTabs` globals, and the assignment to `_composeDoc` inside `_ceFetch` (revert `_ceFetch` to its pre-editor state — just fetch + render the legacy SVG/iframe).

- [ ] **Step 3: Reshape the Investigation detail viewer as Composite Study workbench**

In `index.html.j2`, find the existing Investigation detail container (the tab strip with Spec/Runs/Visualizations/Composites/Observables — `investigation-detail-tab` class). Restructure:

```html
<!-- Composite Study workbench: per-study workbench, opened from Investigations list -->
<div id="study-workbench" style="display:none">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
    <a href="#investigations" class="header-btn">← Investigations</a>
    <h2 id="study-workbench-name" style="margin:0;flex:1"></h2>
  </div>

  <iframe id="study-wiring-frame"
          src="/loom-explore/index.html"
          title="Composite wiring"
          style="width:100%;height:480px;border:1px solid #ddd;background:#fff">
  </iframe>

  <div style="display:flex;align-items:center;gap:8px;margin:12px 0">
    <button class="study-tab active" data-tab="composites" onclick="_studySwitchTab('composites')">Composites</button>
    <button class="study-tab"        data-tab="runs"          onclick="_studySwitchTab('runs')">Runs</button>
    <button class="study-tab"        data-tab="observables"   onclick="_studySwitchTab('observables')">Observables</button>
    <button class="study-tab"        data-tab="visualization" onclick="_studySwitchTab('visualization')">Visualization</button>
  </div>

  <div id="study-panel-composites"    class="study-panel"></div>
  <div id="study-panel-runs"          class="study-panel" style="display:none"></div>
  <div id="study-panel-observables"   class="study-panel" style="display:none"></div>
  <div id="study-panel-visualization" class="study-panel" style="display:none"></div>
</div>
```

Add CSS in the inline `<style>` block:

```css
.study-tab {
  padding: 5px 14px; background: #f3f4f6; color: #374151;
  border: 1px solid #d1d5db; border-radius: 4px;
  font-size: 0.88em; cursor: pointer;
}
.study-tab:hover { background: #e5e7eb; }
.study-tab.active { background: #1976d2; color: #fff; border-color: #1976d2; }
.study-panel { border: 1px solid #eee; border-radius: 4px; padding: 12px; background: #fff; }
```

The existing tab-strip + panels for `investigation-detail-tab` / `investigation-detail-panel` — remove the OLD structure once `study-workbench` is wired up. (Task 4 Step 6 below.)

- [ ] **Step 4: Move the existing tab handlers under the new `_study*` names**

In `walkthrough.js`, the existing Composites/Runs/Observables/Visualizations panels are rendered by functions like:
- `_renderInvestigationComposites` (or `_loadInvComposites` from earlier work)
- `_renderInvestigationRuns`
- `_loadInvObservables`
- `_renderInvestigationVisualizations`

Rename references to point at the new container IDs (`#study-panel-composites`, etc.), or wrap them under `_studyRender<Tab>` thin wrappers:

```javascript
  function _studySwitchTab(tab) {
    document.querySelectorAll('.study-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.study-panel').forEach(function(p) {
      p.style.display = p.id === ('study-panel-' + tab) ? '' : 'none';
    });
    if (tab === 'composites')    _studyRenderComposites();
    if (tab === 'runs')          _studyRenderRuns();
    if (tab === 'observables')   _studyRenderObservables();
    if (tab === 'visualization') _studyRenderVisualization();
  }
  window._studySwitchTab = _studySwitchTab;

  function _studyRenderComposites() {
    // delegate to the existing composites-tab renderer with the new container
    if (typeof _loadInvComposites === 'function') {
      _loadInvComposites(window._currentInvestigation, 'study-panel-composites');
    }
  }
  // ... same pattern for the other three ...
```

If the existing renderers hardcode element IDs (e.g., `document.getElementById('inv-composites-sidebar')`), either:
(a) Update them to take a panel-container ID + reflow accordingly, OR
(b) Keep the old IDs in the new panel containers (`<div id="study-panel-composites"><div id="inv-composites-sidebar"></div>...</div>` style).

Pick (b) — less invasive. Keep the inner IDs (`inv-composites-sidebar`, `inv-composite-detail`, etc.) inside the new panels.

- [ ] **Step 5: Wire `_openInvestigation` to show the workbench**

The existing `_openInvestigation(name)` function navigates to the Investigation detail. Update it to:
1. Set `window._currentInvestigation = name`.
2. Hide the Investigations list view.
3. Show `#study-workbench`.
4. Set `#study-workbench-name` text to the study name.
5. Fetch the study's spec (`/api/investigation?name=<...>`) and post the initial composite's document to the loom-explore iframe.
6. Call `_studyRenderComposites()` to populate the Composites tab.

- [ ] **Step 6: Remove the OLD investigation-detail tab strip + panels**

In `index.html.j2`, delete the old `<div class="investigation-detail-tab-strip">` and the `.investigation-detail-panel` divs underneath. The workbench replaces them.

- [ ] **Step 7: Smoke + commit**

```bash
cd /Users/eranagmon/code/pbg-template
node -c template/scripts/_server/walkthrough.js
python -m pytest tests/ -v 2>&1 | tail -10
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Composite Study workbench layout; drop editor surface"
```

---

### Task 5: Configure section inline in the Composites tab

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`

When the user clicks a composite in the Composites tab sidebar, the right pane shows the existing state-tree detail. We're adding the Configure section below it.

- [ ] **Step 1: Locate the existing composite-detail renderer**

```bash
grep -n "_loadInvCompositeDetail\|inv-composite-detail" template/scripts/_server/walkthrough.js | head -10
```

The function that populates `#inv-composite-detail` when a composite is clicked. Read it.

- [ ] **Step 2: Extend it to also render Configure rows**

After fetching the state tree and rendering it, ALSO fetch the parsed composite document via the existing `/api/investigation-composite-doc` endpoint (added in earlier task), walk its `state` for process nodes, and render a per-process Configure section below the state tree.

We can't call the now-deleted `/api/composite-process-configs` — instead, walk the document client-side. Use the in-memory parsed document (just-fetched). For each process node:

```
▼ partitioner                                      (local:ChromosomePartition)
    partition_method   [mukBEF-anchored        ]  default: mukBEF-anchored
    rate               [1.0                    ]  default: 1.0 [1/s]
```

```javascript
  function _renderConfigureSection(doc, containerEl) {
    var state = (doc && doc.state) || {};
    var params = (doc && doc.parameters) || {};
    var processNodes = Object.keys(state).filter(function(k) {
      var n = state[k];
      return n && typeof n === 'object' && n._type === 'process';
    });
    if (processNodes.length === 0) {
      containerEl.innerHTML += '<p class="empty-state">No processes to configure.</p>';
      return;
    }
    var html = '<h4 style="margin:14px 0 6px">Configure</h4>';
    processNodes.forEach(function(name) {
      var node = state[name];
      var configs = node.config || {};
      var rows = Object.keys(configs).map(function(key) {
        var val = configs[key];
        var p = params[key] || {};
        var def = (p.default !== undefined) ? p.default : val;
        var units = p.units || '';
        var inputType = typeof val;
        var inputAttr, valAttr;
        if (inputType === 'number') {
          inputAttr = 'type="number" step="any"';
          valAttr = 'value="' + _esc(String(val)) + '"';
        } else if (inputType === 'boolean') {
          inputAttr = 'type="checkbox"' + (val ? ' checked' : '');
          valAttr = '';
        } else {
          inputAttr = 'type="text"';
          valAttr = 'value="' + _esc(String(val == null ? '' : val)) + '"';
        }
        var unitsBadge = units ? '<span style="color:#888;font-size:0.8em;margin-left:6px">[' + _esc(units) + ']</span>' : '';
        return '<div style="display:grid;grid-template-columns:160px 1fr 200px;gap:8px;padding:3px 0;align-items:center">' +
               '<code>' + _esc(key) + '</code>' +
               '<input ' + inputAttr + ' ' + valAttr + ' data-process="' + _esc(name) + '" data-key="' + _esc(key) + '" onchange="_studyConfigEdit(this)">' +
               '<small style="color:#888">default: ' + _esc(JSON.stringify(def)) + unitsBadge + '</small>' +
               '</div>';
      }).join('');
      html += '<details open style="margin-bottom:10px;border:1px solid #e5e7eb;border-radius:4px;padding:8px">' +
              '<summary style="cursor:pointer;font-weight:600">' + _esc(name) +
              ' <small style="color:#666;font-weight:normal">(' + _esc(node.address || '') + ')</small>' +
              '</summary>' +
              '<div style="margin-top:8px">' + rows + '</div>' +
              '</details>';
    });
    containerEl.innerHTML += html;
  }
  window._renderConfigureSection = _renderConfigureSection;

  function _studyConfigEdit(inputEl) {
    var processName = inputEl.dataset.process;
    var key = inputEl.dataset.key;
    var raw = inputEl.type === 'checkbox' ? inputEl.checked : inputEl.value;
    var value;
    if (inputEl.type === 'number') {
      value = parseFloat(raw); if (isNaN(value)) value = raw;
    } else if (inputEl.type === 'checkbox') {
      value = !!raw;
    } else {
      value = raw;
    }
    // POST a perturb-recipe addition? Or directly modify the sidecar?
    // For Phase B, modify the in-memory currently-loaded doc + post to loom
    // (no persistence). Persistence happens via the existing perturb modal
    // when the user wants to save a tuned variant.
    if (!window._studyCurrentDoc) return;
    var state = window._studyCurrentDoc.state || {};
    var proc = state[processName];
    if (proc && proc.config) {
      proc.config[key] = value;
      // Re-post to the iframe
      var iframe = document.getElementById('study-wiring-frame');
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({
          type: 'composite:load',
          state: window._studyCurrentDoc,
          metadata: { name: 'edited' },
        }, '*');
      }
    }
  }
  window._studyConfigEdit = _studyConfigEdit;
```

Hook `_renderConfigureSection(doc, detailEl)` into `_loadInvCompositeDetail` after the state-tree rendering. Also stash the fetched doc in `window._studyCurrentDoc` so `_studyConfigEdit` can mutate it.

**Note:** the Configure edits are ephemeral (in-memory only) for now. To persist, the user would use the existing Perturb modal — which already lets them name a new derived composite from the current one + apply parameter overrides. A future follow-up could add a "save these edits as a perturb" shortcut. Phase B keeps the edits in-memory + re-posts to loom; that's enough for visual tuning.

- [ ] **Step 3: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Configure section inline in Composites tab"
```

---

## Phase C — Promote action

### Task 6: Promote modal + endpoint wiring

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add the Promote modal**

In `index.html.j2`, near the other modals:

```html
<div id="modal-promote-composite" class="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal('modal-promote-composite')">&times;</button>
    <h3>Promote derived composite to workspace catalog</h3>
    <form id="form-promote-composite"
          onsubmit="event.preventDefault(); _submitPromote(this)">
      <input type="hidden" name="investigation">
      <input type="hidden" name="sidecar_name">
      <label>Target workspace package
        <input name="target_pkg" placeholder="(auto-detect from workspace.yaml)">
      </label>
      <label>Catalog name (becomes <code>&lt;pkg&gt;.composites.&lt;name&gt;</code>)
        <input name="catalog_name" pattern="^[a-zA-Z0-9_-]+$" required>
      </label>
      <label>Description
        <textarea name="description" rows="3" placeholder="What does this variant do? Why is it worth promoting?"></textarea>
      </label>
      <div class="form-error"></div>
      <button type="submit" class="action-btn">Promote</button>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Add Promote button to derived-composite rows**

Find the renderer for the composites sidebar (where each composite has Perturb/Rebuild/Remove buttons). For each composite WITH `extends` set (i.e., derived), add a Promote button:

```javascript
// inside _loadInvComposites or _renderInvComposites:
var promoteBtn = composite.extends
  ? '<button class="btn-mini" onclick="_openPromoteModal(\'' + _esc(invName) + '\',\'' + _esc(composite.name) + '\')">Promote</button>'
  : '';
// ... add `promoteBtn` to the row's button bar ...
```

- [ ] **Step 3: Add JS handlers**

```javascript
  function _openPromoteModal(invName, sidecarName) {
    var form = document.getElementById('form-promote-composite');
    if (!form) return;
    form.elements['investigation'].value = invName;
    form.elements['sidecar_name'].value = sidecarName;
    form.elements['catalog_name'].value = sidecarName;  // default
    form.elements['description'].value = '';
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    openModal('modal-promote-composite');
  }
  window._openPromoteModal = _openPromoteModal;

  function _submitPromote(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var payload = {
      investigation: data.get('investigation'),
      sidecar_name: data.get('sidecar_name'),
      catalog_name: data.get('catalog_name'),
      description: data.get('description'),
    };
    var pkg = (data.get('target_pkg') || '').trim();
    if (pkg) payload.target_pkg = pkg;
    fetch('/api/composite-promote-to-catalog', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'promote failed';
          return;
        }
        closeModal('modal-promote-composite');
        // Re-render the composites sidebar so the entry shows "promoted"
        if (typeof _loadInvComposites === 'function') {
          _loadInvComposites(payload.investigation);
        }
      });
  }
  window._submitPromote = _submitPromote;
```

- [ ] **Step 4: Show a "promoted" badge on the sidebar row**

In the composite-row renderer:

```javascript
var promotedBadge = composite.promoted
  ? '<span style="font-size:0.75em;color:#1f7a3a;margin-left:6px">[promoted]</span>'
  : '';
// ... include in the row markup ...
```

- [ ] **Step 5: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Promote derived composite to workspace catalog"
```

---

## Phase D — Entry points + Composite Explorer rebuild

### Task 7: Simulation Setup Explore button creates a study

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Find the existing Explore button handler**

```bash
grep -n "_exploreComposite\|onclick=\".*explore\|composite-explore" template/scripts/_server/walkthrough.js | head -10
```

The button likely calls `_navigateToCompositeExplorer(<source-ref>)` or similar, which sets `window.location.hash = '#composite-explore?ref=...'` and triggers a fetch.

- [ ] **Step 2: Replace its behavior**

```javascript
  function _launchStudyFromComposite(sourceRef) {
    fetch('/api/investigation-create-from-composite', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ source_ref: sourceRef }),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          alert(j.error || 'failed to create study');
          return;
        }
        // Navigate to the new study's workbench
        window.location.hash = '#investigations';
        if (typeof _openInvestigation === 'function') {
          _openInvestigation(j.study_name);
        }
      });
  }
  window._launchStudyFromComposite = _launchStudyFromComposite;
```

Update Explore button onclick handlers to call `_launchStudyFromComposite(...)` instead of the old navigation function. There may be multiple call sites (catalog rows + maybe an "Explore" link in the catalog browser); update all.

- [ ] **Step 3: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Simulation Setup Explore creates a Composite Study"
```

---

### Task 8: Rebuild Composite Explorer as read-only viewer

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

The `#composite-explore` page is currently a leftover from the editor. Strip it down to: catalog dropdown + loom iframe + "Start a Composite Study" CTA.

- [ ] **Step 1: Rewrite the page section in `index.html.j2`**

Find `<section id="page-composite-explore">` and replace its body:

```html
<section id="page-composite-explore" class="page" data-page="composite-explore">
  <h2 class="page-title">Composite Explorer</h2>
  <p class="page-lead">Browse workspace composites read-only. To edit a
    composite or run a study, click "Start a Composite Study" — that
    creates a new study in <a href="#investigations">Investigations</a>
    with the picked composite as its initial composite.</p>

  <div style="margin-bottom:12px">
    <label>Composite
      <select id="ce-browser-select" onchange="_ceBrowserLoad(this.value)">
        <option value="">— pick a composite —</option>
      </select>
    </label>
  </div>

  <iframe id="ce-browser-frame"
          src="/loom-explore/index.html"
          title="Composite wiring"
          style="width:100%;height:520px;border:1px solid #ddd;background:#fff">
  </iframe>

  <div style="margin-top:12px">
    <button class="action-btn"
            onclick="_ceBrowserStartStudy()"
            id="ce-browser-start-study"
            disabled>Start a Composite Study with this composite</button>
  </div>
</section>
```

Remove the editor tab strip + Save modal entirely (they were already deleted in Task 4 Step 1).

- [ ] **Step 2: Implement the JS**

```javascript
  function _ceBrowserInit() {
    // Populate the catalog dropdown
    fetch('/api/registry').then(function(r) { return r.json(); }).then(function(data) {
      var composites = (data.processes || []).filter(function(p) { return p.kind === 'composite'; });
      // Fallback to /api/composites if the registry response shape differs
      if (composites.length === 0) {
        return fetch('/api/composites').then(function(r2) { return r2.json(); })
          .then(function(d2) { return d2.composites || []; });
      }
      return composites;
    }).then(function(composites) {
      var sel = document.getElementById('ce-browser-select');
      if (!sel) return;
      composites.forEach(function(c) {
        var opt = document.createElement('option');
        opt.value = c.id || c.address || c.name;
        opt.textContent = c.name + (c.description ? '  —  ' + c.description : '');
        sel.appendChild(opt);
      });
    });
  }
  window._ceBrowserInit = _ceBrowserInit;

  function _ceBrowserLoad(ref) {
    var btn = document.getElementById('ce-browser-start-study');
    if (btn) btn.disabled = !ref;
    if (!ref) return;
    window._ceBrowserCurrentRef = ref;
    fetch('/api/composite-state?ref=' + encodeURIComponent(ref))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) { console.error(data.error); return; }
        var iframe = document.getElementById('ce-browser-frame');
        if (!iframe) return;
        var post = function() {
          iframe.contentWindow.postMessage({
            type: 'composite:load',
            state: data.state,
            metadata: { name: ref },
          }, '*');
        };
        // Same ready-handshake pattern as other loom mounts
        if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
          post();
        } else {
          var listener = function(ev) {
            if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
              window._loomExploreReady = window._loomExploreReady || {};
              window._loomExploreReady[iframe.id] = true;
              window.removeEventListener('message', listener);
              post();
            }
          };
          window.addEventListener('message', listener);
        }
      });
  }
  window._ceBrowserLoad = _ceBrowserLoad;

  function _ceBrowserStartStudy() {
    var ref = window._ceBrowserCurrentRef;
    if (!ref) return;
    _launchStudyFromComposite(ref);   // from Task 7
  }
  window._ceBrowserStartStudy = _ceBrowserStartStudy;
```

Wire `_ceBrowserInit()` into the page-load hook that populates the catalog on first visit to the Composite Explorer page. If the existing page-switch logic has a hook like `_switchPage('composite-explore')`, add `_ceBrowserInit()` to that branch (only initialize once — guard with a flag).

- [ ] **Step 3: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Composite Explorer page rebuilt as read-only viewer"
```

---

## Phase E — Investigations index + v2ecoli E2E

### Task 9: Investigations tab as flat study list

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`
- Modify: `template/scripts/_templates/index.html.j2`

- [ ] **Step 1: Restyle the Investigations list rows with summary stats**

In the existing `_renderInvestigations` (or whatever the function is called that builds the Investigations page list), add per-row summary stats — composites count, runs count, visualizations count — from each investigation's spec.yaml.

```bash
grep -n "_renderInvestigations\|investigations.*list\|page-investigations" template/scripts/_server/walkthrough.js template/scripts/_templates/index.html.j2 | head -10
```

Update the row template:

```javascript
function _investigationRowHtml(inv) {
  var composites = inv.composites || [];
  var compCount = composites.length;
  var runCount = (inv.n_simulations !== undefined) ? inv.n_simulations : 0;
  var vizCount = (inv.visualizations || []).length;
  return '<div class="study-row" onclick="_openInvestigation(\'' + _esc(inv.name) + '\')" ' +
         'style="border:1px solid #e5e7eb;border-radius:4px;padding:10px;margin-bottom:8px;cursor:pointer">' +
         '<strong>' + _esc(inv.name) + '</strong>' +
         ' <button class="btn-mini" onclick="event.stopPropagation();_openInvestigation(\'' + _esc(inv.name) + '\')">Open →</button>' +
         '<div style="color:#666;font-size:0.85em;margin-top:4px">' +
         compCount + ' composite' + (compCount === 1 ? '' : 's') + ' · ' +
         runCount + ' run' + (runCount === 1 ? '' : 's') + ' · ' +
         vizCount + ' visualization' + (vizCount === 1 ? '' : 's') +
         '</div></div>';
}
```

- [ ] **Step 2: Add "+ New from Sim Setup" hint**

At the top of the Investigations list page, add:

```html
<p class="panel-lead">Each row is a Composite Study. To start a new study,
   go to <a href="#simulation-setup">Simulation Setup</a> → Available
   Composites → click <strong>Explore</strong>.</p>
```

(Delete the existing "Create Investigation" modal/button if it's still there — studies are now created from Simulation Setup only.)

- [ ] **Step 3: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(unified-ce): Investigations list shows summary stats per study"
```

---

### Task 10: v2ecoli E2E verification

**Files:** (workspace state)

- [ ] **Step 1: Sync files**

```bash
cp /Users/eranagmon/code/pbg-template/template/scripts/_server/server.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp /Users/eranagmon/code/pbg-template/template/scripts/_server/walkthrough.js \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp /Users/eranagmon/code/pbg-template/template/scripts/_templates/index.html.j2 \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2

python3 -c "import ast; ast.parse(open('/Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py').read())" && echo "server.py syntax ok"
node -c /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js 2>&1 | head -3
```

- [ ] **Step 2: Restart server**

```bash
EXISTING=$(python3 -c "import json; print(json.load(open('/Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info'))['port'])" 2>/dev/null || echo '')
[ -n "$EXISTING" ] && lsof -nP -iTCP:$EXISTING -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -I {} kill {} 2>/dev/null
rm -f /Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info
sleep 1
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all 2>&1 | tail -3
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
echo "port: $PORT"
```

- [ ] **Step 3: Endpoint smoke**

```bash
PORT=$(python3 -c "import json; print(json.load(open('/Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info'))['port'])")

echo "--- /api/investigation-create-from-composite ---"
curl -s -X POST "http://localhost:$PORT/api/investigation-create-from-composite" \
  -H 'Content-Type: application/json' \
  -d '{"source_ref":"pbg_chromosome_rep1.composites.chromosome-partition"}' \
  | python3 -m json.tool
echo

echo "--- /api/composite-promote-to-catalog (against an existing sidecar) ---"
curl -s -X POST "http://localhost:$PORT/api/composite-promote-to-catalog" \
  -H 'Content-Type: application/json' \
  -d '{"investigation":"t1","sidecar_name":"high-count","catalog_name":"chromosome-partition-high-count-e2e","description":"E2E test promotion"}' \
  | python3 -m json.tool

echo "--- removed endpoints should now 404 ---"
curl -s -o /dev/null -w "/api/composite-process-configs: %{http_code}\n" \
  -X POST "http://localhost:$PORT/api/composite-process-configs" -d '{}'
curl -s -o /dev/null -w "/api/investigation-composite-save-sidecar: %{http_code}\n" \
  -X POST "http://localhost:$PORT/api/investigation-composite-save-sidecar" -d '{}'
```

Expected:
- create-from-composite: 200 with `{study_name: "chromosome-partition-<n>"}` (where n is whatever the auto-suffix lands on)
- promote-to-catalog: 200 + new file at `pbg_chromosome_rep1/composites/chromosome-partition-high-count-e2e.composite.yaml`
- Removed endpoints: 404 each

- [ ] **Step 4: Open dashboard**

```bash
open "http://127.0.0.1:$PORT/#investigations"
```

User does browser verification:

1. **Investigations tab** → see a flat list of studies. The newly-created `chromosome-partition` study (from Step 3 endpoint test) appears. `t1` shows summary stats (composites/runs/visualizations counts).
2. **Open `t1`** → enters the **Composite Study workbench**. Header shows breadcrumb + study name. Wiring view at top. 4 tabs below (Composites, Runs, Observables, Visualization).
3. **Composites tab** → sidebar shows chromosome-partition, high-count, low-count. Click each → loom-explore + state tree + Configure section update.
4. **Configure section** in the Composites tab → expand `partitioner`, edit `partition_method` field → loom-explore re-renders.
5. **Promote** button on `high-count` → modal opens → fill catalog name + description → Promote → page refreshes; promoted badge appears on the row; catalog file lands.
6. **Switch to Observables tab** → existing path-checkbox UI.
7. **Visualization tab** → existing add-viz flow.
8. **Simulation Setup** → click Explore on `chromosome-partition` → new study created, navigates to its workbench.
9. **Composite Explorer** (top-level menu) → renamed to viewer; catalog dropdown + loom + "Start a Composite Study" button.
10. **Cleanup** any test artifacts: the e2e-test promoted composite at `pbg_chromosome_rep1/composites/chromosome-partition-high-count-e2e.composite.yaml` can be deleted after verification.

- [ ] **Step 5: Cleanup e2e artifacts**

```bash
rm -f /Users/eranagmon/code/v2ecoli-chromosome-rep1/pbg_chromosome_rep1/composites/chromosome-partition-high-count-e2e.composite.yaml
# Also remove the auto-created study from the create-from-composite endpoint test if desired
rm -rf /Users/eranagmon/code/v2ecoli-chromosome-rep1/investigations/chromosome-partition-2 2>/dev/null || true
# Remove promoted: true flag from t1's spec.yaml if it was added
python3 << 'PY'
import yaml
from pathlib import Path
p = Path('/Users/eranagmon/code/v2ecoli-chromosome-rep1/investigations/t1/spec.yaml')
spec = yaml.safe_load(p.read_text()) or {}
for c in (spec.get('composites') or []):
    c.pop('promoted', None)
p.write_text(yaml.safe_dump(spec, sort_keys=False))
PY
```

- [ ] **Step 6: Commit v2ecoli sync (local — push after browser verification)**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
git status --short
git add -A
git commit -m "feat(unified-ce): sync unified Composite Study + Composite Explorer"
```

- [ ] **Step 7: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git log --oneline -12
git push 2>&1 | tail -3
```

---

## Self-review

**Spec coverage:**

- Composite Study workbench (4 tabs: Composites/Runs/Observables/Visualization): Task 4 (layout) + Task 5 (Configure folds into Composites). ✓
- Composite Explorer (read-only viewer): Task 8. ✓
- Investigations tab (flat study index): Task 9. ✓
- New endpoints (`create-from-composite`, `promote-to-catalog`): Tasks 2 + 3. ✓
- Removed endpoints (7 inline-edit): Task 1. ✓
- Sim Setup Explore creates a study: Task 7. ✓
- Promote derived composite: Task 6. ✓
- Workspace catalog membership: handled by the promote-to-catalog endpoint (writes to `<pkg>/composites/`); Sim Setup auto-picks it up via the existing catalog discovery. ✓

**Placeholder scan:** None. The Configure section's "in-memory edits only" note is the one explicit limitation; persistence intentionally falls back on the existing Perturb modal.

**Type consistency:** `_launchStudyFromComposite(source_ref)` consistent across Tasks 7 + 8. `_openInvestigation(name)` consistent — used by Task 4 (workbench mount), Task 6 (post-promote refresh), Task 7 (post-create nav). Endpoint names `/api/investigation-create-from-composite` + `/api/composite-promote-to-catalog` consistent across plan body.

**Risks flagged:**

1. **The Composites tab renderer (`_loadInvCompositeDetail`) is shared between the OLD investigation viewer and the NEW workbench.** Task 4's reshape relies on keeping the inner element IDs (`inv-composite-detail`, `inv-composites-sidebar`) so existing handlers keep working. Implementer must preserve those IDs in the new panel containers.
2. **Promote endpoint requires sidecar to exist + spec.yaml to have its entry.** If the spec.yaml is out of sync (sidecar file exists but entry missing — unlikely but possible), promote will succeed but the `promoted: true` flag will silently no-op. Acceptable.
3. **Configure edits are not persisted.** Users who want to keep their tuning use the existing Perturb modal. The flow is OK for v1; documented in the spec's "Composite Study workbench" section.
4. **The Investigations list previously had a "Create" modal.** Task 9 Step 2 explicitly says to delete it. If any onclick handlers reference deleted IDs, JS errors are silent; nothing crashes.

---

Plan saved. Use superpowers:subagent-driven-development to execute.
