# Composite Explorer editor refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Composite Explorer from a viewer into a composite-document editor with three tabs (Configure, Observables, Visualization) + a Save-sidecar button. Edits accumulate in an in-memory doc; the loom-explore iframe re-renders live; Save writes a new sidecar into `investigations/<inv>/composites/`. Plus two Simulation Setup cleanups: rename "Use" → "Explore" and remove the Observables section.

**Architecture:** Pure-logic helper module (`compose_doc_edit.py`) handles the document mutations. A single new endpoint (`/api/investigation-composite-save-sidecar`) persists. Frontend mutates `window._composeDoc`, postMessages updates to the loom iframe per edit. Tab panels share the in-memory doc; Save serializes and POSTs.

**Tech Stack:** Python 3.10+, vanilla JavaScript, Jinja2 templates, pytest.

---

## File Structure

### Created

| File | Responsibility |
|---|---|
| `template/scripts/_lib/compose_doc_edit.py` | Pure logic: `walk_process_configs(doc)`, `apply_config_update(doc, process, key, value)`, `inject_emitter(doc, paths, address)`, `strip_emitter(doc)`, `inject_viz_step(doc, class_name, inputs_map, config)`, `strip_viz_step(doc)`. No I/O. |
| `template/tests/test_compose_doc_edit.py` | Unit tests for the helper. |

### Modified

| File | Change |
|---|---|
| `template/scripts/_server/server.py` | Add `/api/investigation-composite-save-sidecar` endpoint. |
| `template/scripts/_server/walkthrough.js` | Composite Explorer rewrite: tab strip + 3 panels + in-memory doc + Save dialog. Simulation Setup: rename Use→Explore button label, remove Observables section. |
| `template/scripts/_templates/index.html.j2` | Composite Explorer template: tab strip markup + 3 panel containers + Save modal. Simulation Setup: remove Observables section. |
| `template/tests/test_visualization_endpoints.py` | Append tests for the save-sidecar endpoint. |

---

## Phase A — Backend

### Task 1: `compose_doc_edit` pure-logic module + tests

**Files:**
- Create: `template/scripts/_lib/compose_doc_edit.py`
- Create: `template/tests/test_compose_doc_edit.py`

- [ ] **Step 1: Write failing tests** at `template/tests/test_compose_doc_edit.py`

```python
"""Tests for compose_doc_edit helpers — pure logic on composite documents."""
import copy

import pytest

from scripts._lib.compose_doc_edit import (
    walk_process_configs,
    apply_config_update,
    inject_emitter,
    strip_emitter,
    inject_viz_step,
    strip_viz_step,
)


def _doc():
    return {
        'name': 'demo',
        'parameters': {
            'partition_method': {'type': 'string', 'default': 'mukBEF-anchored',
                                  'description': 'partition algorithm'},
            'rate': {'type': 'float', 'default': 1.0, 'units': '1/s'},
        },
        'state': {
            'partitioner': {
                '_type': 'process',
                'address': 'local:ChromosomePartition',
                'config': {'partition_method': 'mukBEF-anchored', 'rate': 1.0},
                'inputs': {'chromosome': ['stores', 'chromosome']},
                'outputs': {'chromosome': ['stores', 'chromosome']},
            },
            'stores': {
                'chromosome': {
                    '_type': 'integer',
                    '_default': 1,
                },
            },
        },
    }


# walk_process_configs --------------------------------------------------

def test_walk_process_configs_yields_one_row_per_process():
    rows = walk_process_configs(_doc())
    assert len(rows) == 1
    row = rows[0]
    assert row['name'] == 'partitioner'
    assert row['address'] == 'local:ChromosomePartition'
    assert {c['key'] for c in row['configs']} == {'partition_method', 'rate'}


def test_walk_process_configs_includes_defaults_and_units_from_parameters_block():
    rows = walk_process_configs(_doc())
    cfg_by_key = {c['key']: c for c in rows[0]['configs']}
    # rate has units defined in the parameters block
    assert cfg_by_key['rate']['units'] == '1/s'
    assert cfg_by_key['rate']['default'] == 1.0
    # partition_method has a default but no units
    assert cfg_by_key['partition_method']['default'] == 'mukBEF-anchored'
    assert cfg_by_key['partition_method'].get('units') is None


def test_walk_process_configs_handles_doc_with_no_processes():
    doc = {'state': {'just_a_store': {'_type': 'integer', '_default': 5}}}
    assert walk_process_configs(doc) == []


# apply_config_update --------------------------------------------------

def test_apply_config_update_mutates_target_config_key():
    doc = _doc()
    apply_config_update(doc, 'partitioner', 'rate', 2.5)
    assert doc['state']['partitioner']['config']['rate'] == 2.5


def test_apply_config_update_unknown_process_raises():
    doc = _doc()
    with pytest.raises(KeyError, match='unknown'):
        apply_config_update(doc, 'unknown_process', 'rate', 2.5)


def test_apply_config_update_unknown_key_raises():
    doc = _doc()
    with pytest.raises(KeyError, match='unknown_key'):
        apply_config_update(doc, 'partitioner', 'unknown_key', 1.0)


# inject_emitter / strip_emitter ---------------------------------------

def test_inject_emitter_adds_step_wired_to_paths():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    em = doc['state']['emitter']
    assert em['_type'] == 'step'
    assert em['address'] == 'local:SQLiteEmitter'
    assert em['inputs']['chromosome'] == ['stores', 'chromosome']
    # type schema captures the leaf's _type when available
    assert em['config']['emit']['chromosome'] == 'integer'


def test_inject_emitter_ram_address():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']], address='local:RAMEmitter')
    assert doc['state']['emitter']['address'] == 'local:RAMEmitter'


def test_inject_emitter_skips_missing_paths():
    doc = _doc()
    inject_emitter(doc, paths=[
        ['stores', 'chromosome'],
        ['stores', 'nonexistent'],
    ])
    em = doc['state']['emitter']
    assert 'chromosome' in em['inputs']
    assert 'nonexistent' not in em['inputs']


def test_inject_emitter_with_no_paths_strips_emitter():
    doc = _doc()
    # First add then re-call with empty
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    assert 'emitter' in doc['state']
    inject_emitter(doc, paths=[])
    assert 'emitter' not in doc['state']


def test_strip_emitter_removes_step():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    strip_emitter(doc)
    assert 'emitter' not in doc['state']


def test_strip_emitter_idempotent():
    doc = _doc()
    assert 'emitter' not in doc['state']
    strip_emitter(doc)  # no-op
    assert 'emitter' not in doc['state']


# inject_viz_step / strip_viz_step -------------------------------------

def test_inject_viz_step_auto_wires_inputs_by_name():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    # Emitter has port 'chromosome'; viz expects input 'chromosome' + 'time'
    inject_viz_step(
        doc,
        class_name='TimeSeriesPlot',
        viz_inputs={'chromosome': 'list[float]', 'time': 'list[float]'},
        config={'title': 'demo'},
    )
    viz = doc['state']['viz']
    assert viz['_type'] == 'step'
    assert viz['address'] == 'local:TimeSeriesPlot'
    assert viz['config'] == {'title': 'demo'}
    # 'chromosome' matches an emitter port → wired
    assert viz['inputs']['chromosome'] == ['emitter', 'chromosome']
    # 'time' has no matching emitter port → omitted from inputs
    assert 'time' not in viz['inputs']


def test_inject_viz_step_without_emitter_inputs_empty():
    doc = _doc()
    # No emitter present at all
    inject_viz_step(
        doc,
        class_name='TimeSeriesPlot',
        viz_inputs={'chromosome': 'list[float]'},
        config={},
    )
    viz = doc['state']['viz']
    assert viz['_type'] == 'step'
    # No emitter to wire to; inputs map empty
    assert viz.get('inputs', {}) == {}


def test_strip_viz_step_removes_step():
    doc = _doc()
    inject_viz_step(doc, 'TimeSeriesPlot', {'x': 'list[float]'}, {})
    strip_viz_step(doc)
    assert 'viz' not in doc['state']


def test_strip_viz_step_idempotent():
    doc = _doc()
    strip_viz_step(doc)  # no-op
    assert 'viz' not in doc['state']
```

- [ ] **Step 2: Confirm fail**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest template/tests/test_compose_doc_edit.py -v
```

Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `template/scripts/_lib/compose_doc_edit.py`**

```python
"""Pure-logic edits to a process-bigraph composite document.

Used by the Composite Explorer editor (live in-memory edits via the
dashboard) and by tests. No I/O — every function mutates the document in
place (or returns the mutated row list, for ``walk_process_configs``).
"""
from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Process / config walking (Configure tab)
# ---------------------------------------------------------------------------

def walk_process_configs(doc: dict) -> list[dict]:
    """Return one row per process with its config keys + defaults + units.

    Row shape:
        {
            'name': '<process node name>',
            'address': '<local:ProcessClass>',
            'configs': [
                {'key': '<config key>', 'value': <current value>,
                 'default': <from parameters block, if any>,
                 'units': <from parameters block, if any>,
                 'description': <from parameters block, if any>},
                ...
            ],
        }
    """
    state = doc.get('state') or {}
    params = doc.get('parameters') or {}
    rows: list[dict] = []
    for name, node in state.items():
        if not isinstance(node, dict) or node.get('_type') != 'process':
            continue
        configs = []
        for key, val in (node.get('config') or {}).items():
            entry: dict = {'key': key, 'value': val}
            p = params.get(key)
            if isinstance(p, dict):
                if 'default' in p:
                    entry['default'] = p['default']
                if 'units' in p:
                    entry['units'] = p['units']
                if 'description' in p:
                    entry['description'] = p['description']
            else:
                # Fall back to the literal value as the "default"
                entry['default'] = val
                entry['units'] = None
            configs.append(entry)
        rows.append({
            'name': name,
            'address': node.get('address', ''),
            'configs': configs,
        })
    return rows


def apply_config_update(doc: dict, process_name: str, key: str, value: Any) -> None:
    """Mutate doc['state'][process_name]['config'][key] = value.

    Raises KeyError if the process or key doesn't exist.
    """
    state = doc.get('state') or {}
    if process_name not in state:
        raise KeyError(f"unknown process {process_name!r}")
    node = state[process_name]
    if not isinstance(node, dict) or node.get('_type') != 'process':
        raise KeyError(f"{process_name!r} is not a process node")
    cfg = node.setdefault('config', {})
    if key not in cfg:
        raise KeyError(f"{process_name!r}.config has no key {key!r}")
    cfg[key] = value


# ---------------------------------------------------------------------------
# Emitter step (Observables tab)
# ---------------------------------------------------------------------------

def _resolve_leaf(state: dict, path: list) -> Any | None:
    """Walk ``state`` following ``path`` segments; return the leaf node or None."""
    node: Any = state
    for seg in path:
        if not isinstance(node, dict) or seg not in node:
            return None
        node = node[seg]
    return node


def inject_emitter(doc: dict, paths: list, address: str = 'local:SQLiteEmitter') -> None:
    """Rewrite ``doc['state']['emitter']`` so it records the given paths.

    Paths not present in the state are skipped silently.
    If ``paths`` is empty, ``emitter`` is removed from state entirely.
    """
    state = doc.setdefault('state', {})
    if not paths:
        state.pop('emitter', None)
        return

    inputs: dict = {}
    emit_schema: dict = {}
    for path in paths:
        leaf = _resolve_leaf(state, path)
        if leaf is None:
            continue
        port_name = path[-1] if path else 'state'
        inputs[port_name] = list(path)
        if isinstance(leaf, dict) and leaf.get('_type'):
            emit_schema[port_name] = leaf['_type']
        else:
            emit_schema[port_name] = 'any'

    if not inputs:
        # All paths missing → no-op (strip any prior emitter)
        state.pop('emitter', None)
        return

    state['emitter'] = {
        '_type': 'step',
        'address': address,
        'config': {'emit': emit_schema},
        'inputs': inputs,
    }


def strip_emitter(doc: dict) -> None:
    """Remove the emitter step from doc['state'] (idempotent)."""
    state = doc.get('state') or {}
    state.pop('emitter', None)


# ---------------------------------------------------------------------------
# Visualization step (Visualization tab)
# ---------------------------------------------------------------------------

def inject_viz_step(
    doc: dict,
    class_name: str,
    viz_inputs: dict,
    config: dict | None = None,
) -> None:
    """Rewrite ``doc['state']['viz']`` to call ``class_name`` with auto-wired inputs.

    Each viz input port is wired to ``[emitter, <port-name>]`` if the
    emitter step has a matching output port; otherwise omitted (a hint to
    the user that the wiring is incomplete).
    """
    state = doc.setdefault('state', {})
    emitter = state.get('emitter') or {}
    emitter_ports: set = set((emitter.get('inputs') or {}).keys())
    # Emitter outputs by name = its input port names (the values it records)

    wired: dict = {}
    for port_name in (viz_inputs or {}):
        if port_name in emitter_ports:
            wired[port_name] = ['emitter', port_name]

    entry: dict = {
        '_type': 'step',
        'address': f'local:{class_name}',
        'config': dict(config or {}),
    }
    if wired:
        entry['inputs'] = wired
    state['viz'] = entry


def strip_viz_step(doc: dict) -> None:
    """Remove the viz step from doc['state'] (idempotent)."""
    state = doc.get('state') or {}
    state.pop('viz', None)
```

- [ ] **Step 4: Confirm pass**

```bash
python -m pytest template/tests/test_compose_doc_edit.py -v
```

All 17 tests must pass.

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_lib/compose_doc_edit.py template/tests/test_compose_doc_edit.py
git commit -m "feat(composer): compose_doc_edit module — walk + apply + inject helpers"
```

---

### Task 2: `/api/investigation-composite-save-sidecar` endpoint

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Append failing tests** to `template/tests/test_visualization_endpoints.py`

```python
def test_post_save_sidecar_writes_yaml_and_updates_spec(workspace_server):
    """Save-sidecar writes investigations/<inv>/composites/<name>.yaml and adds the entry to spec.yaml."""
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [],
    }, sort_keys=False))

    doc = {
        'name': 'tuned',
        'state': {
            'process': {'_type': 'process', 'address': 'local:Foo', 'config': {'rate': 5.0}},
            'stores': {'count': {'_type': 'integer', '_default': 1}},
            'emitter': {'_type': 'step', 'address': 'local:SQLiteEmitter',
                         'config': {'emit': {'count': 'integer'}},
                         'inputs': {'count': ['stores', 'count']}},
        },
    }
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo', 'name': 'tuned-baseline',
         'document': doc, 'source_ref': 'pkg.composites.baseline'},
    )
    assert code in (200, 500), j

    sidecar = inv / 'composites' / 'tuned-baseline.yaml'
    assert sidecar.is_file()
    written = yaml.safe_load(sidecar.read_text())
    assert written['state']['process']['config']['rate'] == 5.0
    assert 'emitter' in written['state']

    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    names = [c['name'] for c in (spec.get('composites') or [])]
    assert 'tuned-baseline' in names
    entry = next(c for c in spec['composites'] if c['name'] == 'tuned-baseline')
    assert entry['source'] == 'pkg.composites.baseline'
    assert entry['document'] == './composites/tuned-baseline.yaml'


def test_post_save_sidecar_rejects_duplicate_name(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'tuned.yaml').write_text('name: tuned\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'tuned', 'source': 'pkg.x',
                         'document': './composites/tuned.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo', 'name': 'tuned', 'document': {'state': {}}},
    )
    assert code == 409, j


def test_post_save_sidecar_rejects_missing_investigation(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'nonexistent', 'name': 'x', 'document': {'state': {}}},
    )
    assert code == 404, j


def test_post_save_sidecar_rejects_missing_fields(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo'},
    )
    assert code == 400, j
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest tests/test_visualization_endpoints.py -k save_sidecar -v
```

- [ ] **Step 3: Add endpoint** to `template/scripts/_server/server.py`

In the POST dispatch dict (near other `/api/investigation-composite-*`):

```python
            "/api/investigation-composite-save-sidecar": self._post_investigation_composite_save_sidecar,
```

Handler (place near `_post_investigation_composite_perturb`):

```python
    def _post_investigation_composite_save_sidecar(self, body: dict):
        """POST /api/investigation-composite-save-sidecar
        Body: {investigation, name, document, source_ref?}
        Writes the document as a new sidecar; appends entry to spec.composites[].
        """
        inv_name = (body.get("investigation") or "").strip()
        comp_name = (body.get("name") or "").strip()
        document = body.get("document")
        source_ref = (body.get("source_ref") or "").strip()
        if not (inv_name and comp_name and isinstance(document, dict)):
            return self._json(
                {"error": "investigation, name, and document required"}, 400
            )
        import re as _re
        if not _re.match(r"^[a-zA-Z0-9_-]+$", comp_name):
            return self._json({"error": "name must match ^[a-zA-Z0-9_-]+$"}, 400)

        inv_dir = WORKSPACE / "investigations" / inv_name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)

        composites_dir = inv_dir / "composites"
        composites_dir.mkdir(parents=True, exist_ok=True)
        sidecar = composites_dir / f"{comp_name}.yaml"
        if sidecar.is_file():
            return self._json({"error": f"composite {comp_name!r} already exists"}, 409)

        # Validate that the document is well-formed (round-trips cleanly)
        try:
            text = yaml.safe_dump(document, sort_keys=False)
            yaml.safe_load(text)
        except Exception as e:
            return self._json({"error": f"document not serialisable: {e}"}, 400)

        commit_msg = f"feat(investigations/{inv_name}): save sidecar composite '{comp_name}'"

        def do_action():
            sidecar.write_text(text)
            spec = yaml.safe_load(spec_path.read_text()) or {}
            composites = spec.setdefault("composites", [])
            entry = {
                "name": comp_name,
                "document": f"./composites/{comp_name}.yaml",
            }
            if source_ref:
                entry["source"] = source_ref
            composites.append(entry)
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            return self._json(*_commit_or_run(commit_msg, do_action))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
```

- [ ] **Step 4: Confirm pass**

```bash
python -m pytest tests/test_visualization_endpoints.py -v 2>&1 | tail -15
```

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "feat(composer): /api/investigation-composite-save-sidecar endpoint"
```

---

## Phase B — Frontend tabs

### Task 3: Composite Explorer layout refactor — tab strip + in-memory doc + live loom

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Inspect the current Composite Explorer markup**

```bash
cd /Users/eranagmon/code/pbg-template
grep -n "page-composite-explore\|composite-explore-frame\|composite-explore-svg" template/scripts/_templates/index.html.j2 | head -10
echo "---"
grep -n "_loadCompositeExplorer\|_ceFetch\|composite-explore" template/scripts/_server/walkthrough.js | head -20
```

The page has a section `#page-composite-explore` with the iframe + legacy SVG container. Below the iframe, add a tab strip and three panel containers.

- [ ] **Step 2: Add the tab strip + panel containers to the template**

In `index.html.j2`, find the closing of the wiring-view container in the Composite Explorer page. Insert after it:

```html
<!-- Composite Explorer editing tabs -->
<div style="margin-top:12px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
    <button class="ce-tab active" data-tab="configure" onclick="_ceSwitchTab('configure')">Configure</button>
    <button class="ce-tab" data-tab="observables" onclick="_ceSwitchTab('observables')">Observables</button>
    <button class="ce-tab" data-tab="visualization" onclick="_ceSwitchTab('visualization')">Visualization</button>
    <span style="flex:1"></span>
    <button class="action-btn" onclick="_ceOpenSaveModal()">Save sidecar</button>
  </div>
  <div id="ce-panel-configure" class="ce-panel"></div>
  <div id="ce-panel-observables" class="ce-panel" style="display:none"></div>
  <div id="ce-panel-visualization" class="ce-panel" style="display:none"></div>
</div>
```

Minimal CSS additions (inside the `<style>` block at the top of the file, near existing tab styles):

```css
.ce-tab {
  padding: 5px 14px;
  background: #f3f4f6;
  color: #374151;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 0.88em;
  cursor: pointer;
}
.ce-tab:hover { background: #e5e7eb; }
.ce-tab.active { background: #1976d2; color: #fff; border-color: #1976d2; }
.ce-panel { border: 1px solid #eee; border-radius: 4px; padding: 12px; background: #fff; }
```

- [ ] **Step 3: Add the in-memory doc + tab-switch JS** to walkthrough.js

Append near the existing Composite Explorer handlers:

```javascript
  /* In-memory composite document, mutated by tab panels. */
  window._composeDoc = null;
  window._composeDocSourceRef = null;

  function _ceSwitchTab(tab) {
    document.querySelectorAll('.ce-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.ce-panel').forEach(function(p) {
      p.style.display = p.id === ('ce-panel-' + tab) ? '' : 'none';
    });
    if (tab === 'configure')      _ceRenderConfigure();
    if (tab === 'observables')    _ceRenderObservables();
    if (tab === 'visualization')  _ceRenderVisualization();
  }
  window._ceSwitchTab = _ceSwitchTab;

  /** Post the current in-memory doc to the loom iframe so wiring re-renders. */
  function _cePushDocToLoom() {
    var iframe = document.getElementById('composite-explore-frame');
    if (!iframe || !window._composeDoc) return;
    var post = function() {
      iframe.contentWindow.postMessage({
        type: 'composite:load',
        state: window._composeDoc,
        metadata: { name: window._composeDocSourceRef || 'edited' },
      }, '*');
    };
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
  }
  window._cePushDocToLoom = _cePushDocToLoom;
```

Modify the existing `_loadCompositeExplorer` (or whatever function loads a composite — Task 6 named it `_ceFetch` per its report) to assign the fetched doc into `window._composeDoc` AND call the tab renderers:

```javascript
  function _loadCompositeExplorer(ref) {
    fetch('/api/composite-state?ref=' + encodeURIComponent(ref))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) { console.error(data.error); return; }
        window._composeDoc = data.state;
        window._composeDocSourceRef = ref;
        _cePushDocToLoom();
        _ceRenderConfigure();      // default-active tab
      });
  }
```

(Stubs `_ceRenderConfigure` / `_ceRenderObservables` / `_ceRenderVisualization` — Tasks 4-6 implement them. For Task 3, define them as no-ops so the tab switching works.)

- [ ] **Step 4: Commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(composer): Composite Explorer tab strip + in-memory doc plumbing"
```

---

### Task 4: Configure tab

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`
- Modify: `template/scripts/_server/server.py` (add a tiny endpoint that exposes `walk_process_configs` server-side)

- [ ] **Step 1: Add a helper endpoint** that returns the parsed Configure rows. Server-side walks are simpler than re-doing the logic in JS.

In `do_GET` dispatch:
```python
        if self.path.startswith("/api/composite-process-configs"):
            return self._get_composite_process_configs()
```

Handler:
```python
    def _get_composite_process_configs(self):
        """POST-only variant would mutate; GET reads. But since we walk a
        document the frontend sends via querystring, we use POST.
        Accept the doc via POST body instead.
        """
        return self._json({"error": "use POST"}, 405)
```

Actually use POST so the doc payload travels in the body:

```python
            "/api/composite-process-configs":  self._post_composite_process_configs,
```

```python
    def _post_composite_process_configs(self, body: dict):
        """POST /api/composite-process-configs {document}
        Returns: {rows: [{name, address, configs: [{key, value, default?, units?, description?}]}, ...]}
        """
        from scripts._lib.compose_doc_edit import walk_process_configs
        doc = body.get("document")
        if not isinstance(doc, dict):
            return self._json({"error": "document required"}, 400)
        return self._json({"rows": walk_process_configs(doc)}, 200)
```

- [ ] **Step 2: Write `_ceRenderConfigure`** in walkthrough.js:

```javascript
  function _ceRenderConfigure() {
    var panel = document.getElementById('ce-panel-configure');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/composite-process-configs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ document: window._composeDoc }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        var rows = data.rows || [];
        if (rows.length === 0) {
          panel.innerHTML = '<p class="empty-state">No processes in this composite.</p>';
          return;
        }
        panel.innerHTML = rows.map(function(row) {
          var configs = (row.configs || []).map(function(c) {
            var inputAttr = '';
            var inputType = typeof c.value;
            if (inputType === 'number') {
              inputAttr = 'type="number" step="any"';
            } else if (inputType === 'boolean') {
              inputAttr = 'type="checkbox"' + (c.value ? ' checked' : '');
            } else {
              inputAttr = 'type="text"';
            }
            var valAttr = (inputType === 'boolean') ? '' : 'value="' + _esc(String(c.value)) + '"';
            var unitsBadge = c.units ? '<span style="color:#888;font-size:0.8em;margin-left:6px">[' + _esc(String(c.units)) + ']</span>' : '';
            var defStr = (c.default !== undefined) ? ('default: ' + JSON.stringify(c.default)) : '';
            return '<div style="display:grid;grid-template-columns:160px 1fr 180px;gap:8px;padding:4px 0">' +
                   '<code>' + _esc(c.key) + '</code>' +
                   '<input ' + inputAttr + ' ' + valAttr +
                       ' onchange="_ceUpdateConfig(\'' + _esc(row.name) + '\',\'' + _esc(c.key) + '\',this)">' +
                   '<small style="color:#888">' + _esc(defStr) + unitsBadge + '</small>' +
                   '</div>';
          }).join('');
          return '<details open style="margin-bottom:10px;border:1px solid #e5e7eb;border-radius:4px;padding:8px">' +
                 '<summary style="cursor:pointer;font-weight:600">' +
                 _esc(row.name) + ' <small style="color:#666;font-weight:normal">(' + _esc(row.address) + ')</small>' +
                 '</summary>' +
                 '<div style="margin-top:8px">' + configs + '</div>' +
                 '</details>';
        }).join('');
      });
  }
  window._ceRenderConfigure = _ceRenderConfigure;

  function _ceUpdateConfig(processName, key, inputEl) {
    if (!window._composeDoc) return;
    var raw = inputEl.type === 'checkbox' ? inputEl.checked : inputEl.value;
    // Best-effort type coercion
    var value;
    if (inputEl.type === 'number') value = parseFloat(raw);
    else if (inputEl.type === 'checkbox') value = !!raw;
    else value = raw;
    var state = window._composeDoc.state || {};
    var proc = state[processName];
    if (!proc || !proc.config) { console.warn('process not found:', processName); return; }
    proc.config[key] = value;
    _cePushDocToLoom();  // wiring view doesn't change visually for config edits but cheap to keep in sync
  }
  window._ceUpdateConfig = _ceUpdateConfig;
```

- [ ] **Step 3: Commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
python -m pytest tests/test_visualization_endpoints.py -v 2>&1 | tail -5
git add template/scripts/_server/walkthrough.js template/scripts/_server/server.py
git commit -m "feat(composer): Configure tab — rows-per-process with config inputs"
```

---

### Task 5: Observables tab

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`
- Modify: `template/scripts/_server/server.py` (add `/api/composite-state-tree` POST variant — walks a doc passed in body, not via investigation lookup)

- [ ] **Step 1: Add the helper endpoint**

```python
            "/api/composite-state-tree-doc":   self._post_composite_state_tree_doc,
```

```python
    def _post_composite_state_tree_doc(self, body: dict):
        """POST /api/composite-state-tree-doc {document}
        Returns: {nodes: [{path, kind, type, default}, ...]} — same shape as
        /api/investigation-state-tree but walks a doc supplied in the body
        (used by the Composite Explorer Observables tab on the in-memory doc).
        """
        from scripts._lib.composite_recipes import walk_state_tree
        doc = body.get("document")
        if not isinstance(doc, dict):
            return self._json({"error": "document required"}, 400)
        return self._json({"nodes": walk_state_tree(doc)}, 200)
```

- [ ] **Step 2: Write `_ceRenderObservables`** in walkthrough.js:

```javascript
  function _ceRenderObservables() {
    var panel = document.getElementById('ce-panel-observables');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/composite-state-tree-doc', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ document: window._composeDoc }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        var leaves = (data.nodes || []).filter(function(n) { return n.kind === 'store'; });
        var existingEmitter = (window._composeDoc.state || {}).emitter;
        var selected = new Set();
        if (existingEmitter && existingEmitter.inputs) {
          Object.values(existingEmitter.inputs).forEach(function(p) {
            selected.add((p || []).join('.'));
          });
        }
        var useRam = existingEmitter && existingEmitter.address === 'local:RAMEmitter';
        var rows = leaves.map(function(n) {
          var key = (n.path || []).join('.');
          var checked = selected.has(key) ? ' checked' : '';
          return '<div style="padding:3px 0"><label>' +
                 '<input type="checkbox" data-path="' + _esc(key) + '"' + checked +
                       ' onchange="_ceObservablesChanged()"> ' +
                 '<code>' + _esc(key) + '</code> ' +
                 '<small style="color:#888">' + _esc(n.type || '') + '</small>' +
                 '</label></div>';
        }).join('');
        panel.innerHTML =
          '<label style="margin-bottom:8px;display:block"><input type="checkbox" id="ce-use-ram"' +
          (useRam ? ' checked' : '') + ' onchange="_ceObservablesChanged()"> ' +
          'Use <code>RAMEmitter</code> (default: SQLiteEmitter)</label>' +
          (rows || '<p class="empty-state">No leaf stores found.</p>');
      });
  }
  window._ceRenderObservables = _ceRenderObservables;

  function _ceObservablesChanged() {
    if (!window._composeDoc) return;
    var panel = document.getElementById('ce-panel-observables');
    var paths = [];
    panel.querySelectorAll('input[type=checkbox][data-path]:checked').forEach(function(cb) {
      paths.push(cb.dataset.path.split('.'));
    });
    var useRam = !!(document.getElementById('ce-use-ram') || {}).checked;
    // Mutate the in-memory doc using the same algorithm as compose_doc_edit.inject_emitter.
    // For simplicity we POST to a tiny helper endpoint that mutates + returns the new doc:
    fetch('/api/compose-doc-inject-emitter', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document: window._composeDoc,
        paths: paths,
        address: useRam ? 'local:RAMEmitter' : 'local:SQLiteEmitter',
      }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.document) {
          window._composeDoc = data.document;
          _cePushDocToLoom();
        }
      });
  }
  window._ceObservablesChanged = _ceObservablesChanged;
```

- [ ] **Step 3: Add the mutation endpoint** server-side. Add to POST dispatch + handler:

```python
            "/api/compose-doc-inject-emitter":  self._post_compose_doc_inject_emitter,
```

```python
    def _post_compose_doc_inject_emitter(self, body: dict):
        """POST /api/compose-doc-inject-emitter
        Body: {document, paths, address}
        Returns: {document: <mutated>}
        Stateless transform — applies inject_emitter() and returns the new doc.
        """
        from scripts._lib.compose_doc_edit import inject_emitter
        doc = body.get("document")
        if not isinstance(doc, dict):
            return self._json({"error": "document required"}, 400)
        paths = body.get("paths") or []
        address = (body.get("address") or "local:SQLiteEmitter").strip()
        import copy
        out = copy.deepcopy(doc)
        try:
            inject_emitter(out, paths=paths, address=address)
        except Exception as e:
            return self._json({"error": f"inject failed: {e}"}, 400)
        return self._json({"document": out}, 200)
```

- [ ] **Step 4: Commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
python -m pytest template/tests/test_compose_doc_edit.py tests/test_visualization_endpoints.py -v 2>&1 | tail -5
git add template/scripts/_server/walkthrough.js template/scripts/_server/server.py
git commit -m "feat(composer): Observables tab — emitter inject via in-memory doc edit"
```

---

### Task 6: Visualization tab

**Files:**
- Modify: `template/scripts/_server/walkthrough.js`
- Modify: `template/scripts/_server/server.py` (mutation endpoint mirror)

- [ ] **Step 1: Add the viz-inject endpoint**

```python
            "/api/compose-doc-inject-viz":  self._post_compose_doc_inject_viz,
            "/api/compose-doc-strip-viz":   self._post_compose_doc_strip_viz,
```

```python
    def _post_compose_doc_inject_viz(self, body: dict):
        """POST /api/compose-doc-inject-viz
        Body: {document, class_name, viz_inputs, config?}
        Returns: {document}
        """
        from scripts._lib.compose_doc_edit import inject_viz_step
        doc = body.get("document")
        if not isinstance(doc, dict):
            return self._json({"error": "document required"}, 400)
        import copy
        out = copy.deepcopy(doc)
        try:
            inject_viz_step(
                out,
                class_name=body.get("class_name") or "",
                viz_inputs=body.get("viz_inputs") or {},
                config=body.get("config") or {},
            )
        except Exception as e:
            return self._json({"error": f"inject failed: {e}"}, 400)
        return self._json({"document": out}, 200)

    def _post_compose_doc_strip_viz(self, body: dict):
        from scripts._lib.compose_doc_edit import strip_viz_step
        doc = body.get("document")
        if not isinstance(doc, dict):
            return self._json({"error": "document required"}, 400)
        import copy
        out = copy.deepcopy(doc)
        strip_viz_step(out)
        return self._json({"document": out}, 200)
```

- [ ] **Step 2: Write `_ceRenderVisualization`** in walkthrough.js:

```javascript
  function _ceRenderVisualization() {
    var panel = document.getElementById('ce-panel-visualization');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/visualization-classes')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var classes = data.classes || [];
        var currentViz = (window._composeDoc.state || {}).viz;
        var currentClass = '';
        if (currentViz && currentViz.address) {
          currentClass = (currentViz.address.split(':')[1] || '').split('.').pop();
        }
        var currentCfg = (currentViz && currentViz.config) ? JSON.stringify(currentViz.config, null, 2) : '{}';
        var emitterPorts = Object.keys(((window._composeDoc.state || {}).emitter || {}).inputs || {});
        var options = '<option value="">— pick a Visualization class —</option>' +
                      classes.map(function(c) {
                        return '<option value="' + _esc(c.name) + '"' +
                               (c.name === currentClass ? ' selected' : '') + '>' +
                               _esc(c.name) + (c.doc ? ' — ' + _esc(c.doc) : '') +
                               '</option>';
                      }).join('');
        var wiringHtml = '';
        if (currentClass) {
          // Fetch the class's inputs() to compute wiring summary
          // (already in /api/visualization-classes? no — needs another endpoint or stash on the option)
          // Simpler: just show emitter ports and let the user infer
          wiringHtml = '<p style="font-size:0.85em;color:#555;margin-top:8px">' +
                       'Auto-wiring: viz inputs that match these emitter ports will be connected: ' +
                       (emitterPorts.length ? emitterPorts.map(function(p){return '<code>'+_esc(p)+'</code>';}).join(', ') : '<em>none — add observables first</em>') +
                       '</p>';
        }
        panel.innerHTML =
          '<label>Visualization class<select id="ce-viz-class" onchange="_ceVizChanged()">' + options + '</select></label>' +
          '<label>Config (JSON)<textarea id="ce-viz-config" rows="4" onchange="_ceVizChanged()">' + _esc(currentCfg) + '</textarea></label>' +
          wiringHtml +
          '<button class="btn-mini" onclick="_ceVizRemove()" style="margin-top:8px">Remove visualization</button>';
      });
  }
  window._ceRenderVisualization = _ceRenderVisualization;

  function _ceVizChanged() {
    if (!window._composeDoc) return;
    var className = document.getElementById('ce-viz-class').value;
    var configRaw = (document.getElementById('ce-viz-config') || {}).value || '{}';
    var config = {};
    try { config = JSON.parse(configRaw); } catch (e) { console.warn('viz config JSON parse:', e); }
    if (!className) {
      // Strip viz
      fetch('/api/compose-doc-strip-viz', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ document: window._composeDoc }),
      }).then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.document) { window._composeDoc = data.document; _cePushDocToLoom(); }
        });
      return;
    }
    // Need the class's declared inputs to do auto-wire. Hit /api/visualization-classes
    // and find the one matching className. (Could be cached.)
    fetch('/api/visualization-classes').then(function(r) { return r.json(); })
      .then(function(data) {
        var cls = (data.classes || []).find(function(c) { return c.name === className; });
        // For auto-wire we need the class's inputs(). visualization-classes only returns name+doc+address.
        // Use /api/visualization-class-inputs?name=<...> — add a tiny endpoint server-side if missing.
        return fetch('/api/visualization-class-inputs?name=' + encodeURIComponent(className))
          .then(function(r) { return r.json(); });
      })
      .then(function(data) {
        var vizInputs = data.inputs || {};
        return fetch('/api/compose-doc-inject-viz', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            document: window._composeDoc,
            class_name: className,
            viz_inputs: vizInputs,
            config: config,
          }),
        });
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.document) { window._composeDoc = data.document; _cePushDocToLoom(); }
      });
  }
  window._ceVizChanged = _ceVizChanged;

  function _ceVizRemove() {
    document.getElementById('ce-viz-class').value = '';
    _ceVizChanged();
  }
  window._ceVizRemove = _ceVizRemove;
```

- [ ] **Step 3: Add `/api/visualization-class-inputs` endpoint** — small helper that returns a class's declared inputs:

```python
        if self.path.startswith("/api/visualization-class-inputs"):
            return self._get_visualization_class_inputs()
```

```python
    def _get_visualization_class_inputs(self):
        """GET /api/visualization-class-inputs?name=<short>
        Returns: {inputs: {<port>: <type>, ...}}
        """
        import urllib.parse
        qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        name = qs.get("name", "").strip()
        if not name:
            return self._json({"error": "name required"}, 400)
        cls, _short = self._resolve_viz_class(f"local:{name}")
        if cls is None:
            return self._json({"error": f"class not found: {name}"}, 404)
        try:
            inst = cls.__new__(cls)
            inputs = inst.inputs() or {}
        except Exception as e:
            return self._json({"error": f"inputs() failed: {e}"}, 500)
        return self._json({"inputs": inputs}, 200)
```

- [ ] **Step 4: Commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
git add template/scripts/_server/walkthrough.js template/scripts/_server/server.py
git commit -m "feat(composer): Visualization tab — class picker + auto-wire to emitter outputs"
```

---

## Phase C — Save dialog

### Task 7: Save sidecar modal + Save flow

**Files:**
- Modify: `template/scripts/_templates/index.html.j2` (modal markup)
- Modify: `template/scripts/_server/walkthrough.js` (Save modal handlers)

- [ ] **Step 1: Add the Save modal** near other modals at the bottom of `index.html.j2`:

```html
<div id="modal-ce-save" class="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal('modal-ce-save')">&times;</button>
    <h3>Save edited composite as sidecar</h3>
    <form id="form-ce-save" onsubmit="event.preventDefault(); _ceSubmitSave(this)">
      <label>Investigation
        <select name="investigation" id="ce-save-investigation" required></select>
      </label>
      <label>Sidecar name
        <input name="name" pattern="^[a-zA-Z0-9_-]+$" required placeholder="e.g. chromosome-partition-tuned">
      </label>
      <div id="ce-save-source-ref" style="margin:8px 0;font-size:0.85em;color:#666"></div>
      <div class="form-error"></div>
      <button type="submit" class="action-btn">Save</button>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Wire `_ceOpenSaveModal` + `_ceSubmitSave`** in walkthrough.js:

```javascript
  function _ceOpenSaveModal() {
    if (!window._composeDoc) {
      alert('No composite to save.');
      return;
    }
    // Populate investigation dropdown
    var sel = document.getElementById('ce-save-investigation');
    sel.innerHTML = '<option value="">— pick an investigation —</option>';
    document.getElementById('ce-save-source-ref').innerHTML =
      window._composeDocSourceRef
        ? 'Source: <code>' + _esc(window._composeDocSourceRef) + '</code>'
        : '';
    fetch('/api/investigations').then(function(r) { return r.json(); })
      .then(function(data) {
        (data.investigations || []).forEach(function(inv) {
          var opt = document.createElement('option');
          opt.value = inv.name;
          opt.textContent = inv.name;
          sel.appendChild(opt);
        });
        openModal('modal-ce-save');
      });
  }
  window._ceOpenSaveModal = _ceOpenSaveModal;

  function _ceSubmitSave(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var payload = {
      investigation: data.get('investigation'),
      name: data.get('name'),
      document: window._composeDoc,
      source_ref: window._composeDocSourceRef || '',
    };
    fetch('/api/investigation-composite-save-sidecar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'save failed';
          return;
        }
        closeModal('modal-ce-save');
        // Nav to investigation's Composites tab
        window.location.hash = '#investigations';
        if (typeof _openInvestigation === 'function') {
          _openInvestigation(payload.investigation);
        }
      });
  }
  window._ceSubmitSave = _ceSubmitSave;
```

- [ ] **Step 3: Commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(composer): Save sidecar modal + POST flow"
```

---

## Phase D — Simulation Setup cleanup

### Task 8: Rename "Use" → "Explore"; remove Observables section

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Find current label**

```bash
cd /Users/eranagmon/code/pbg-template
grep -n "Use\b" template/scripts/_templates/index.html.j2 | grep -i "composite\|simulation" | head -10
echo "---"
grep -n "observables\|Observables" template/scripts/_templates/index.html.j2 | head -20
```

- [ ] **Step 2: Rename "Use" → "Explore" on Available Composites rows**

In the template, find the button text on each composite row in the Available Composites panel. Change "Use" to "Explore". The onclick handler stays the same (it already navigates to Composite Explorer with the picked composite).

If the button text is templated via JS (in walkthrough.js), update the string literal there too.

- [ ] **Step 3: Remove the Observables section from Simulation Setup**

Find the Observables section/panel inside `#page-simulation-setup` (or wherever Simulation Setup's HTML lives). Delete the whole section. If there's any JS that targets element IDs inside that section, remove or stub those handlers.

- [ ] **Step 4: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js 2>&1 | head -3
python -m pytest tests/ -v 2>&1 | tail -10
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "refactor(sim-setup): rename Use→Explore on composites; remove Observables section"
```

---

## Phase E — v2ecoli E2E verification

### Task 9: End-to-end on v2ecoli

**Files:** (workspace state)

- [ ] **Step 1: Sync files**

```bash
cd /Users/eranagmon/code/pbg-template
cp template/scripts/_lib/compose_doc_edit.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/compose_doc_edit.py
cp template/scripts/_server/server.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp template/scripts/_server/walkthrough.js \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp template/scripts/_templates/index.html.j2 \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
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

- [ ] **Step 3: Programmatic endpoint verification**

```bash
PORT=$(python3 -c "import json; print(json.load(open('/Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info'))['port'])")
echo "--- /api/composite-process-configs (POST) ---"
curl -s -X POST "http://localhost:$PORT/api/composite-process-configs" \
  -H 'Content-Type: application/json' \
  -d '{"document":{"state":{"p":{"_type":"process","address":"local:Foo","config":{"rate":1.0}}}}}' \
  | python3 -m json.tool

echo "--- /api/compose-doc-inject-emitter (POST) ---"
curl -s -X POST "http://localhost:$PORT/api/compose-doc-inject-emitter" \
  -H 'Content-Type: application/json' \
  -d '{"document":{"state":{"x":{"_type":"integer","_default":1}}},"paths":[["x"]]}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('has emitter:', 'emitter' in (d.get('document') or {}).get('state', {}))"

echo "--- /api/visualization-class-inputs?name=TimeSeriesPlot ---"
curl -s "http://localhost:$PORT/api/visualization-class-inputs?name=TimeSeriesPlot" | python3 -m json.tool
```

- [ ] **Step 4: Open dashboard**

```bash
open "http://127.0.0.1:$PORT/#composite-explore"
```

Manual verification (user does these in the browser):

1. Pick `chromosome-partition` from Available Composites → click **Explore** (renamed from Use) → Composite Explorer opens with loom-explore showing the wiring (no inline emitter — was stripped earlier).
2. Click **Configure** tab → see `partitioner` row → expand → edit `partition_method` to "mukBEF-free". Wiring iframe doesn't change (config only).
3. Click **Observables** tab → tick `stores.chromosome.count` → loom-explore re-renders with an `emitter` node wired to the store.
4. Click **Visualization** tab → pick `TimeSeriesPlot` → loom-explore re-renders with a `viz` node downstream of the emitter (wiring depends on port matches).
5. Click **Save sidecar** → modal opens, pick investigation `t1`, name `chromosome-partition-tuned`, Save.
6. After save: redirected to Investigations → `t1` → Composites tab → new entry `chromosome-partition-tuned` visible.
7. Click into `chromosome-partition-tuned`'s loom view → confirms the saved doc has emitter + viz + the edited config.
8. Open Simulation Setup → confirm "Use" button is now "Explore"; Observables section is gone.

- [ ] **Step 5: Commit v2ecoli sync (local only — push after verification)**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
git add -A
git commit -m "feat(composer): sync Composite Explorer editor + Simulation Setup cleanup"
```

- [ ] **Step 6: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git log --oneline -10
git push 2>&1 | tail -3
```

---

## Self-review

**Spec coverage:**

- Configure tab (renamed from Parameters, rows-per-process, defaults+units): Task 4 (frontend) + Task 1 (`walk_process_configs`) + Task 2 endpoint integration. ✓
- Observables tab (state-tree + checkboxes + emitter inject): Task 5 (frontend) + Task 1 (`inject_emitter`/`strip_emitter`) + Task 5 step 3 endpoint. ✓
- Visualization tab (class picker + auto-wire + viz inject): Task 6 (frontend) + Task 1 (`inject_viz_step`/`strip_viz_step`) + Task 6 step 1 endpoint. ✓
- Save sidecar (modal + `/api/investigation-composite-save-sidecar`): Task 7 (modal+JS) + Task 2 (endpoint). ✓
- Simulation Setup rename + remove: Task 8. ✓
- Live loom-explore re-render on edit: Task 3 (`_cePushDocToLoom`). ✓

**Placeholder scan:** None. Every step has complete code. Task 8's "find current label" step is inspection-based (the implementer adapts to whatever text/IDs exist today) — common pattern for legacy UI cleanups.

**Type consistency:** `inject_emitter(doc, paths, address)` consistent across Task 1 definition + Task 5 endpoint. `inject_viz_step(doc, class_name, viz_inputs, config)` consistent across Task 1 + Task 6. Endpoint paths consistent: `/api/composite-process-configs`, `/api/composite-state-tree-doc`, `/api/compose-doc-inject-emitter`, `/api/compose-doc-inject-viz`, `/api/compose-doc-strip-viz`, `/api/visualization-class-inputs`, `/api/investigation-composite-save-sidecar`.

**Risks flagged in advance:**

1. **Composite Explorer state survives tab switches.** `window._composeDoc` is a module-level global; switching to a different dashboard page (Investigations, Visualizations) doesn't clear it. If the user navigates back to Composite Explorer for a different composite, JS overwrites `_composeDoc` cleanly. Documented; no extra reset logic needed.
2. **Many small server-side endpoints.** Five new stateless transform endpoints + two read endpoints. They're tiny but tax the endpoint count. Worth a follow-up to consolidate behind a single `/api/compose-doc-transform {op, args}` dispatcher if the count grows.
3. **No JSON-config form for Visualization config.** The viz tab takes config as a raw JSON textarea. Out of scope for this plan; documented in the spec's follow-ups.
4. **Configure tab's auto-coercion (number vs string vs bool) is type-of-current-value.** For a string that looks numeric, the input might be type=text when the user wanted number. Acceptable for v1 — types are inferred from the document's current value, which reflects YAML's parsed types.

---

Plan saved. Use superpowers:subagent-driven-development to execute.
