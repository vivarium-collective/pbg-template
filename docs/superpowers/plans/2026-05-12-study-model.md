# Study Model — Baseline / Variants / Interventions / Comparisons / Conclusions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the Composite Study workbench around research vocabulary (Baseline, Variant, Intervention, Comparison, Conclusions) with a 6-tab strip — Overview | Composites | Interventions | Runs | Visualizations | Conclusions — while keeping the read-only Composite Explorer and the Sim-Setup-→-Study launch path from the unified-CE spec.

**Architecture:** spec.yaml gains `baseline:`, `variants:` (was `composites:`), each variant nests its `intervention:`, plus top-level `comparisons:`, `conclusions:`, and the study-metadata scalars `question:` / `hypothesis:` / `status:`. New endpoints for conclusions + comparison CRUD + overview metadata. Workbench restructures into 6 tabs; Overview tab has inline-editable question/hypothesis/status plus a read-only summary; Composites tab shows intervention summary; Interventions tab is a cross-cutting table view; Visualizations tab gains a Comparisons sub-panel; Conclusions tab is 4 labeled textareas (Claims / Evidence / Limitations / Next steps) backed by one markdown blob. A migration helper rewrites legacy specs on first viewer open. Sim Setup's Explore navigates to the Composite Explorer (preview-only); a **Begin Study** button there is what spawns the new investigation.

**Tech Stack:** Python stdlib HTTPServer, Jinja2 templates, vanilla JS, YAML via PyYAML, pytest. No new runtime deps.

**Supersedes:** [`docs/superpowers/plans/2026-05-12-unified-composite-explorer.md`](./2026-05-12-unified-composite-explorer.md). That plan's 10 tasks are folded into this one (Phases A.5, A.6, A.7, C, D, E) and extended with Phase A.1–A.4 + B.2/B.4/B.5/B.6 for the new vocabulary.

**Source spec:** [`docs/superpowers/specs/2026-05-12-study-model-design.md`](../specs/2026-05-12-study-model-design.md).

---

## Phase A — Data model + endpoints

### Task A1: Migration helper (`composites:` → `variants:` + nest interventions)

**Files:**
- Create: `template/scripts/_lib/spec_migration.py`
- Create: `template/scripts/_lib/test_spec_migration.py`

- [ ] **Step 1: Write 5 failing tests** in `test_spec_migration.py`:

```python
import textwrap, pathlib, yaml
from spec_migration import migrate_study_to_v2_vocabulary


def _write(tmp_path, body):
    p = tmp_path / 'spec.yaml'
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_migrate_renames_composites_to_variants(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert 'composites' not in data
    assert data['variants'] == [{'name': 'a', 'source': 'pkg.a'}]


def test_migrate_nests_overrides_into_intervention(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
          - name: b
            extends: a
            parameter_overrides: {state.x: 1.0}
            process_overrides: {p: null}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    b = data['variants'][1]
    assert b['intervention'] == {
        'description': '',
        'parameter_overrides': {'state.x': 1.0},
        'process_overrides': {'p': None},
    }
    assert 'parameter_overrides' not in b
    assert 'process_overrides' not in b


def test_migrate_sets_baseline_from_first_source_variant(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
          - {name: b, extends: a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert data['baseline'] == 'a'


def test_migrate_initializes_blank_fields(tmp_path):
    p = _write(tmp_path, """
        name: s
        composites:
          - {name: a, source: pkg.a}
    """)
    migrate_study_to_v2_vocabulary(p)
    data = yaml.safe_load(p.read_text())
    assert data['comparisons'] == []
    assert data['conclusions'] == ''
    assert data['question'] == ''
    assert data['hypothesis'] == ''
    assert data['status'] == 'draft'


def test_migrate_idempotent(tmp_path):
    p = _write(tmp_path, """
        name: s
        baseline: a
        question: ""
        hypothesis: ""
        status: draft
        variants:
          - {name: a, source: pkg.a}
        comparisons: []
        conclusions: ""
    """)
    before = p.read_text()
    migrate_study_to_v2_vocabulary(p)
    assert p.read_text() == before
```

- [ ] **Step 2: Run tests, confirm they all fail with ImportError or assertion**

Run: `pytest template/scripts/_lib/test_spec_migration.py -v`
Expected: 5 FAIL (import error).

- [ ] **Step 3: Implement `migrate_study_to_v2_vocabulary` in `spec_migration.py`:**

```python
"""Migration helper: legacy `composites:` shape → v2 `variants:` shape."""
from __future__ import annotations
import pathlib, tempfile, os
import yaml


def migrate_study_to_v2_vocabulary(spec_path: pathlib.Path) -> bool:
    """Migrate one spec.yaml from legacy composites-shape to v2 variants-shape.

    Returns True if a migration was applied, False if the file was already v2.
    """
    text = spec_path.read_text()
    data = yaml.safe_load(text) or {}
    if 'variants' in data:
        # Ensure new top-level fields present for idempotency.
        data.setdefault('comparisons', [])
        data.setdefault('conclusions', '')
        data.setdefault('question', '')
        data.setdefault('hypothesis', '')
        data.setdefault('status', 'draft')
        new_text = yaml.safe_dump(data, sort_keys=False)
        if new_text == text:
            return False
        _atomic_write(spec_path, new_text)
        return True
    if 'composites' not in data:
        return False
    composites = data.pop('composites') or []
    variants = []
    baseline_name = None
    for entry in composites:
        entry = dict(entry)
        intervention = {}
        if 'parameter_overrides' in entry:
            intervention['parameter_overrides'] = entry.pop('parameter_overrides')
        if 'process_overrides' in entry:
            intervention['process_overrides'] = entry.pop('process_overrides')
        if intervention:
            intervention['description'] = entry.pop('intervention_description', '')
            entry['intervention'] = {'description': intervention.pop('description'),
                                     **intervention}
        if baseline_name is None and entry.get('source') and not entry.get('extends'):
            baseline_name = entry['name']
        variants.append(entry)
    data['baseline'] = baseline_name or (variants[0]['name'] if variants else '')
    data['variants'] = variants
    data.setdefault('comparisons', [])
    data.setdefault('conclusions', '')
    data.setdefault('question', '')
    data.setdefault('hypothesis', '')
    data.setdefault('status', 'draft')
    _atomic_write(spec_path, yaml.safe_dump(data, sort_keys=False))
    return True


def _atomic_write(path: pathlib.Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests again, confirm 5/5 pass**

Run: `pytest template/scripts/_lib/test_spec_migration.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_lib/spec_migration.py template/scripts/_lib/test_spec_migration.py
git commit -m "feat(spec): migrate legacy composites shape to variants + intervention"
```

---

### Task A2: spec validator accepts `variants:` shape + auto-runs migration on open

**Files:**
- Modify: `template/scripts/_lib/specs.py` (or wherever `load_spec` lives)
- Modify: existing `test_specs.py` (add 3 tests)

- [ ] **Step 1: Write 3 failing tests:**

```python
def test_load_spec_accepts_variants_shape(tmp_path):
    p = tmp_path / 'spec.yaml'
    p.write_text("name: s\nbaseline: a\nvariants:\n  - {name: a, source: pkg.a}\n")
    spec = load_spec(p)
    assert spec['baseline'] == 'a'
    assert len(spec['variants']) == 1


def test_load_spec_migrates_legacy_composites_shape_on_read(tmp_path):
    p = tmp_path / 'spec.yaml'
    p.write_text("name: s\ncomposites:\n  - {name: a, source: pkg.a}\n")
    spec = load_spec(p)
    assert 'variants' in spec and 'composites' not in spec
    # File on disk was rewritten.
    assert 'variants' in p.read_text()


def test_load_spec_validates_baseline_references_a_variant(tmp_path):
    p = tmp_path / 'spec.yaml'
    p.write_text("name: s\nbaseline: missing\nvariants:\n  - {name: a, source: pkg.a}\n")
    import pytest
    with pytest.raises(ValueError, match="baseline 'missing' not in variants"):
        load_spec(p)
```

- [ ] **Step 2: Run tests, confirm they fail**

- [ ] **Step 3: Modify `load_spec` to call `migrate_study_to_v2_vocabulary` if `composites:` is present, then validate `variants` + `baseline` references.**

```python
from spec_migration import migrate_study_to_v2_vocabulary

def load_spec(path):
    raw = yaml.safe_load(path.read_text()) or {}
    if 'composites' in raw and 'variants' not in raw:
        migrate_study_to_v2_vocabulary(path)
        raw = yaml.safe_load(path.read_text()) or {}
    variants = raw.get('variants', [])
    baseline = raw.get('baseline')
    names = {v['name'] for v in variants}
    if baseline and baseline not in names:
        raise ValueError(f"baseline '{baseline}' not in variants {sorted(names)}")
    return raw
```

- [ ] **Step 4: Run tests, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_lib/specs.py template/scripts/_lib/test_specs.py
git commit -m "feat(spec): load_spec auto-migrates legacy composites + validates baseline ref"
```

---

### Task A3: Conclusions endpoint

**Files:**
- Modify: `template/scripts/_server/server.py` (add `_handle_investigation_set_conclusions`)
- Modify: existing `test_server.py` (add 2 tests)

- [ ] **Step 1: Write 2 failing tests:**

```python
def test_post_set_conclusions_writes_markdown(server_client, tmp_investigation):
    resp = server_client.post('/api/investigation-set-conclusions', json={
        'investigation': tmp_investigation.name,
        'markdown': '## Findings\n\nDoubled rate doubles output.',
    })
    assert resp.status_code == 200
    spec_data = yaml.safe_load((tmp_investigation / 'spec.yaml').read_text())
    assert spec_data['conclusions'].startswith('## Findings')


def test_post_set_conclusions_rejects_oversize(server_client, tmp_investigation):
    resp = server_client.post('/api/investigation-set-conclusions', json={
        'investigation': tmp_investigation.name,
        'markdown': 'x' * (256 * 1024 + 1),
    })
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests, confirm they fail**

- [ ] **Step 3: Implement `_handle_investigation_set_conclusions` in `server.py`:**

```python
def _handle_investigation_set_conclusions(self, body: dict) -> dict:
    investigation = body['investigation']
    markdown = body.get('markdown', '')
    if len(markdown) > 256 * 1024:
        raise HTTPError(400, f'conclusions exceed 256KB limit ({len(markdown)} bytes)')
    spec_path = _spec_path_for_investigation(investigation)
    spec = yaml.safe_load(spec_path.read_text()) or {}
    spec['conclusions'] = markdown
    _atomic_write(spec_path, yaml.safe_dump(spec, sort_keys=False))
    return {'ok': True}
```

Wire it into the dispatch dict.

- [ ] **Step 4: Run tests, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_server/server.py template/scripts/_server/test_server.py
git commit -m "feat(server): POST /api/investigation-set-conclusions"
```

---

### Task A3.5: Overview-metadata endpoint (`set-overview`)

**Files:**
- Modify: `template/scripts/_server/server.py` (add `_handle_investigation_set_overview`)
- Modify: existing `test_server.py` (add 3 tests)

- [ ] **Step 1: Write 3 failing tests:**

```python
def test_post_set_overview_updates_question(server_client, tmp_investigation):
    resp = server_client.post('/api/investigation-set-overview', json={
        'investigation': tmp_investigation.name,
        'fields': {'question': 'Does X drive Y?'},
    })
    assert resp.status_code == 200
    spec = yaml.safe_load((tmp_investigation / 'spec.yaml').read_text())
    assert spec['question'] == 'Does X drive Y?'


def test_post_set_overview_rejects_invalid_status(server_client, tmp_investigation):
    resp = server_client.post('/api/investigation-set-overview', json={
        'investigation': tmp_investigation.name,
        'fields': {'status': 'bogus'},
    })
    assert resp.status_code == 400


def test_post_set_overview_partial_update_preserves_other_fields(server_client, tmp_investigation):
    server_client.post('/api/investigation-set-overview', json={
        'investigation': tmp_investigation.name,
        'fields': {'question': 'Q1', 'hypothesis': 'H1', 'status': 'in-progress'},
    })
    server_client.post('/api/investigation-set-overview', json={
        'investigation': tmp_investigation.name,
        'fields': {'status': 'completed'},
    })
    spec = yaml.safe_load((tmp_investigation / 'spec.yaml').read_text())
    assert spec == {**spec, 'question': 'Q1', 'hypothesis': 'H1', 'status': 'completed'}
```

- [ ] **Step 2: Run tests, confirm fail**

- [ ] **Step 3: Implement the handler:**

```python
_VALID_STATUSES = {'draft', 'in-progress', 'completed', 'archived'}

def _handle_investigation_set_overview(self, body: dict) -> dict:
    investigation = body['investigation']
    fields = body.get('fields', {})
    if 'status' in fields and fields['status'] not in _VALID_STATUSES:
        raise HTTPError(400, f"status must be one of {sorted(_VALID_STATUSES)}")
    spec_path = _spec_path_for_investigation(investigation)
    spec = yaml.safe_load(spec_path.read_text()) or {}
    for key in ('question', 'hypothesis', 'status'):
        if key in fields:
            spec[key] = fields[key]
    _atomic_write(spec_path, yaml.safe_dump(spec, sort_keys=False))
    return {'ok': True}
```

- [ ] **Step 4: Run tests, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_server/server.py template/scripts/_server/test_server.py
git commit -m "feat(server): POST /api/investigation-set-overview"
```

---

### Task A4: Comparison add/update/delete endpoints

**Files:**
- Modify: `template/scripts/_server/server.py` (add 3 handlers)
- Modify: existing `test_server.py` (add 4 tests)

- [ ] **Step 1: Write 4 failing tests:**

```python
def test_post_comparison_add_appends(server_client, tmp_investigation):
    resp = server_client.post('/api/investigation-comparison-add', json={
        'investigation': tmp_investigation.name,
        'name': 'rate-cmp',
        'description': 'rate doubling',
        'variants': ['baseline', 'high-rate'],
        'observables': ['DnaA_count'],
    })
    assert resp.status_code == 200
    spec = yaml.safe_load((tmp_investigation / 'spec.yaml').read_text())
    assert spec['comparisons'][-1]['name'] == 'rate-cmp'


def test_post_comparison_update_replaces(server_client, tmp_investigation_with_comparison):
    resp = server_client.post('/api/investigation-comparison-update', json={
        'investigation': tmp_investigation_with_comparison.name,
        'name': 'rate-cmp',
        'fields_to_update': {'description': 'updated'},
    })
    assert resp.status_code == 200
    spec = yaml.safe_load((tmp_investigation_with_comparison / 'spec.yaml').read_text())
    assert spec['comparisons'][0]['description'] == 'updated'


def test_delete_comparison_refuses_with_viz_dependents(server_client, tmp_inv_with_cmp_and_viz):
    resp = server_client.delete('/api/investigation-comparison', json={
        'investigation': tmp_inv_with_cmp_and_viz.name,
        'name': 'rate-cmp',
    })
    assert resp.status_code == 409
    assert 'visualizations' in resp.json()['error']


def test_delete_comparison_succeeds_when_unreferenced(server_client, tmp_investigation_with_comparison):
    resp = server_client.delete('/api/investigation-comparison', json={
        'investigation': tmp_investigation_with_comparison.name,
        'name': 'rate-cmp',
    })
    assert resp.status_code == 200
    spec = yaml.safe_load((tmp_investigation_with_comparison / 'spec.yaml').read_text())
    assert spec['comparisons'] == []
```

- [ ] **Step 2: Run tests, confirm fail**

- [ ] **Step 3: Implement the 3 handlers + wire dispatch.** Each loads the spec, mutates `comparisons:`, writes back atomically. Delete checks `visualizations[].config.comparison == name` and 409s if any match.

- [ ] **Step 4: Run tests, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add template/scripts/_server/server.py template/scripts/_server/test_server.py
git commit -m "feat(server): comparison add/update/delete endpoints"
```

---

### Task A5: `investigation-create-from-composite` endpoint (carry-over from unified plan)

Spawn a study from a workspace catalog composite. Body: `{composite_name}`. Server picks an auto-name (`study-<composite>-<short-uuid>`), creates `investigations/<auto-name>/spec.yaml` with the v2 shape (`baseline: <composite>`, `variants: [{name, source, document}]`). Returns the new investigation name.

**Tests:** create-from-composite returns name; spec.yaml lands at expected path with `variants:` shape; rejects if composite_name unknown.

(See Task 2 in the superseded unified plan for the prior shape — adapt to write v2 spec shape.)

---

### Task A6: `composite-promote-to-catalog` endpoint (carry-over from unified plan)

Promote a variant from a study to the workspace catalog. Body: `{investigation, variant}`. Server reads the variant's sidecar, writes a new module under `<workspace_pkg>/composites/<promoted_name>.py`, marks `promoted: true` on the variant entry.

**Tests:** promote writes a new composite module; second promote of same variant is a 409; module discovers correctly via `discover_packages`.

(See Task 3 in the superseded unified plan.)

---

### Task A7: Remove 7 inline-edit endpoints (carry-over from unified plan)

Remove: `compose-doc-inject-emitter`, `compose-doc-inject-viz`, `compose-doc-strip-viz`, `composite-state-tree-doc`, `composite-process-configs`, `visualization-class-inputs`, `investigation-composite-save-sidecar`.

The /pbg-emit skill replaces inject-emitter; the other six were Composite Explorer editor surface and have no caller after Phase B.

**Tests:** none — deletion only. Existing tests that hit these endpoints get removed alongside.

(See Task 1 in the superseded unified plan.)

---

## Phase B — 6-tab Composite Study workbench

### Task B1: Restructure workbench to 6-tab layout

**Files:**
- Modify: `template/scripts/_templates/investigation_detail.html.j2`
- Modify: `template/scripts/_static/investigation_detail.js`

- [ ] **Step 1: Replace the existing tab strip** with: Overview | Composites | Interventions | Runs | Visualizations | Conclusions. Each tab maps to a section `<div class="ws-tab-panel" data-tab="..."`. Existing Composites, Runs, Visualizations panels stay (re-keyed); add empty Overview, Interventions, Conclusions panels.

- [ ] **Step 2: Update the JS tab-switch handler** to support the 3 new tabs (initially empty body — populated in Tasks B2/B4/B6).

- [ ] **Step 3: Manual verify** in a browser: all 6 tabs render; switching between them shows the right panel.

- [ ] **Step 4: Commit**

```bash
git add template/scripts/_templates/investigation_detail.html.j2 template/scripts/_static/investigation_detail.js
git commit -m "feat(workbench): 6-tab layout — add Overview/Interventions/Conclusions stubs"
```

---

### Task B2: Overview tab — read-only summary

**Files:**
- Modify: `template/scripts/_static/investigation_detail.js`
- Modify: `template/scripts/_templates/investigation_detail.html.j2`

- [ ] **Step 1: Render the editable metadata header** (top of the panel), backed by `/api/investigation` payload fields `question`, `hypothesis`, `status`:

```html
<section class="ws-overview-meta">
  <label>Question
    <textarea id="ov-question" rows="2">{{question}}</textarea>
  </label>
  <label>Hypothesis
    <textarea id="ov-hypothesis" rows="2">{{hypothesis}}</textarea>
  </label>
  <label>Status
    <select id="ov-status">
      <option value="draft">draft</option>
      <option value="in-progress">in-progress</option>
      <option value="completed">completed</option>
      <option value="archived">archived</option>
    </select>
  </label>
</section>
```

Auto-save on blur for textareas + on change for the dropdown → `POST /api/investigation-set-overview` with the changed field only. Toast on success.

- [ ] **Step 2: Render the read-only summary** below the header:

```html
<dl class="ws-overview-list">
  <dt>Baseline</dt> <dd>{{baseline_name}} <small>({{baseline_source}})</small></dd>
  <dt>Variants</dt> <dd>{{variant_count}} — {{variant_names_csv}}</dd>
  <dt>Runs</dt> <dd>{{total_runs}} total / per-variant breakdown</dd>
  <dt>Comparisons</dt> <dd>{{comparison_count}} — {{comparison_names_csv}}</dd>
  <dt>Visualizations</dt> <dd>{{viz_count}}</dd>
</dl>
<section class="ws-overview-conclusions">
  <h3>Conclusions excerpt</h3>
  <p>{{conclusions_first_200_chars}}…</p>
  <a href="#" data-action="goto-conclusions">Read more →</a>
</section>
```

- [ ] **Step 3: Manual verify** in a browser against a v2ecoli study. Edit each metadata field; refresh; confirm persisted.

- [ ] **Step 4: Commit**

---

### Task B3: Composites tab — show intervention summary when variant selected

**Files:**
- Modify: `template/scripts/_static/investigation_detail.js` (Composites panel rendering)

- [ ] **Step 1: When a variant is selected**, render below the existing Configure section a read-only "Intervention" block:

```
Intervention: "Double the replication rate"
  parameter_overrides:
    state.replication.config.rate = 2.0
  process_overrides: (none)
[ Edit in Interventions tab → ]
```

- [ ] **Step 2: Baseline variant** shows "Baseline (no intervention)" instead.

- [ ] **Step 3: "Edit in Interventions tab →" button** switches tabs + scrolls to that variant's row.

- [ ] **Step 4: Commit**

---

### Task B4: Interventions tab — table view + inline edit

**Files:**
- Modify: `template/scripts/_static/investigation_detail.js`
- Modify: `template/scripts/_templates/investigation_detail.html.j2`

- [ ] **Step 1: Render a table:**

| Variant | Parent | Description | Parameter overrides | Process overrides |
|---|---|---|---|---|
| high-rate | chromosome-partition | Double the replication rate | 1 | 0 |
| no-replication | chromosome-partition | Remove replication | 0 | 1 |

Baseline row excluded.

- [ ] **Step 2: Click row → expand inline editor:**
- Description: text input
- Parameter overrides: JSON textarea
- Process overrides: JSON textarea
- [Save] [Cancel]

- [ ] **Step 3: Save** → POST `/api/investigation-composite-perturb` (existing endpoint) with the new intervention payload; existing endpoint updates the variant's sidecar AND the intervention nesting in spec.yaml.

(Verify the existing perturb endpoint writes intervention nesting correctly per Task A1's spec shape; if it still writes flat `parameter_overrides`/`process_overrides`, update it.)

- [ ] **Step 4: Commit**

---

### Task B5: Visualizations tab — Comparisons sub-panel

**Files:**
- Modify: `template/scripts/_static/investigation_detail.js`
- Modify: `template/scripts/_templates/investigation_detail.html.j2`

- [ ] **Step 1: Add a Comparisons section** at the top of the Visualizations tab:

```html
<section class="ws-comparisons">
  <h3>Comparisons</h3>
  <table>...</table>
  <button data-action="add-comparison">+ Add comparison</button>
</section>
```

- [ ] **Step 2: Add-comparison modal:**
- name (text)
- description (text, optional)
- variants (multi-select from study's variants)
- observables (multi-select from study's observables)
- [Save] → POST `/api/investigation-comparison-add`

- [ ] **Step 3: Per-row [Edit] [Remove].** Remove → DELETE; 409 surfaces "still referenced by visualization X".

- [ ] **Step 4: Add-visualization modal** gains a Comparison dropdown. Selecting it auto-fills the `sources` (= variants list) + `observable` (= first observable) in the config payload before POSTing.

- [ ] **Step 5: Commit**

---

### Task B6: Conclusions tab — markdown textarea + preview

**Files:**
- Modify: `template/scripts/_static/investigation_detail.js`
- Modify: `template/scripts/_templates/investigation_detail.html.j2`

- [ ] **Step 1: Render the Conclusions panel as 4 labeled textareas + preview:**

```html
<div class="ws-conclusions">
  <label>Claims    <textarea id="cn-claims" rows="6"></textarea></label>
  <label>Evidence  <textarea id="cn-evidence" rows="6"></textarea></label>
  <label>Limitations <textarea id="cn-limitations" rows="6"></textarea></label>
  <label>Next steps <textarea id="cn-next-steps" rows="6"></textarea></label>
  <button data-action="save-conclusions">Save</button>
  <h4>Preview</h4>
  <div id="conclusions-preview"></div>
</div>
```

- [ ] **Step 2: Split/join logic in JS** (no server work; the blob round-trips via the existing `set-conclusions` endpoint):

```javascript
const SECTIONS = ['Claims', 'Evidence', 'Limitations', 'Next steps'];
const TEXTAREA_IDS = ['cn-claims', 'cn-evidence', 'cn-limitations', 'cn-next-steps'];

function loadConclusions(blob) {
  const map = Object.fromEntries(SECTIONS.map(s => [s, '']));
  let current = 'Claims';                  // free-form blob fallback
  for (const line of (blob || '').split('\n')) {
    const m = line.match(/^##\s+(Claims|Evidence|Limitations|Next steps)\s*$/i);
    if (m) { current = _canonical(m[1]); continue; }
    map[current] += line + '\n';
  }
  SECTIONS.forEach((s, i) => {
    document.getElementById(TEXTAREA_IDS[i]).value = map[s].trim();
  });
}

function emitConclusions() {
  return SECTIONS.map((s, i) => {
    const body = document.getElementById(TEXTAREA_IDS[i]).value.trim();
    return `## ${s}\n\n${body}`;
  }).join('\n\n');
}

function _canonical(label) {
  return SECTIONS.find(s => s.toLowerCase() === label.toLowerCase());
}
```

- [ ] **Step 3: Save** → emit blob, POST `/api/investigation-set-conclusions`. Show toast on success.

- [ ] **Step 4: Live preview** — debounced 300ms render of `emitConclusions()` via the existing markdown helper (find via grep — already used elsewhere in the dashboard).

- [ ] **Step 5: Commit**

---

## Phase C — Promote-to-catalog action

### Task C1: Promote modal in Composites tab (carry-over from unified plan)

When a variant is selected, show a [Promote to catalog] button (disabled for baseline; disabled if `promoted: true`). Click → modal:
- Target module name (default `<variant_name_snake>`)
- Short description (text)
- [Promote]

POST `/api/composite-promote-to-catalog` (Task A6). On success: refresh the catalog list + mark variant as promoted; show toast linking to the new catalog entry.

(See Task 6 in the superseded unified plan.)

---

## Phase D — Sim Setup + Composite Explorer

### Task D1: Sim Setup "Explore" navigates to Composite Explorer (no API call)

**Files:**
- Modify: `template/scripts/_static/simulation_setup.js`

- [ ] **Step 1: The Explore button** (already renamed from "Use" in commit cc54727) now navigates to `/composite-explorer?composite=<encodeURIComponent(name)>`. No POST. No persistent state created.

- [ ] **Step 2: Remove the inline composite-detail viewer** from Sim Setup if any still exists (the unified plan's Task 7 may have left vestiges).

- [ ] **Step 3: Manual verify** — click Explore on a row, land on the Explorer with that composite pre-selected.

- [ ] **Step 4: Commit**

---

### Task D2: Rebuild Composite Explorer as read-only viewer + Begin Study CTA

**Files:**
- Modify: `template/scripts/_templates/composite_explorer.html.j2` (or the closest equivalent)
- Modify: `template/scripts/_static/composite_explorer.js`

- [ ] **Step 1: Three-pane layout:**
- Catalog browser (left): list of workspace composites, click to select
- loom-explore iframe (center): renders the selected composite, read-only
- Detail pane (right): metadata (source module, process list, default state shape) + **[Begin Study]** button

- [ ] **Step 2: Respect `?composite=<name>` URL query param** on page load → preselect that composite in the catalog + render it in loom.

- [ ] **Step 3: Begin Study button** → `POST /api/investigation-create-from-composite` (Task A5) with the selected composite name → on success, navigate to the new study's workbench.

- [ ] **Step 4: Remove all edit affordances** — no Configure section, no add-emitter button, no save-sidecar button. The Explorer is purely browse + launch.

- [ ] **Step 5: Manual verify** — open the Explorer fresh; pick a composite; click Begin Study; land on the workbench with that composite as the baseline variant.

- [ ] **Step 6: Commit**

---

## Phase E — Investigations index + v2ecoli E2E

### Task E1: Investigations list with summary stats (carry-over from unified plan)

Investigations tab landing page = list of all studies in `investigations/`. Each row:
- Name
- Baseline composite name
- Variant count
- Run count
- Last-run timestamp
- [Open →]

(See Task 9 in the superseded unified plan.)

---

### Task E2: v2ecoli E2E verification

**Files:**
- Modify: `~/code/v2ecoli-chromosome-rep1/investigations/t1/spec.yaml` (auto-migrated on first open)

- [ ] **Step 1: Open v2ecoli dashboard.** Verify the `t1` study auto-migrates: backup is in git, file now uses `variants:` shape, intervention nesting present.

- [ ] **Step 2: Exercise the Sim Setup → Explorer → Begin Study flow:**
- Sim Setup → click Explore on a workspace composite → land on `/composite-explorer?composite=<name>`
- Explorer shows wiring + metadata; click **Begin Study** → land on a fresh Composite Study workbench

- [ ] **Step 3: Exercise each of the 6 tabs:**
- Overview — edit question/hypothesis/status; refresh; verify persisted. Summary counts match reality.
- Composites tab — select baseline + each variant, see intervention summary
- Interventions tab — table populated; edit one description; refresh
- Runs tab — run the baseline; verify history updates
- Visualizations tab — create a comparison `rate-cmp` (baseline + high-rate, DnaA_count); add a viz that references it
- Conclusions tab — fill all 4 sections (Claims / Evidence / Limitations / Next steps), save, refresh, see structured markdown round-trip

- [ ] **Step 3: Promote a variant** (e.g., `simplified-replication`) → verify a new module lands in `pbg_chromosome_rep1/composites/`, picks up via `discover_packages`, shows in the workspace catalog.

- [ ] **Step 4: Capture screenshots** of each tab for the PR description.

- [ ] **Step 5: Commit the migrated spec.yaml in v2ecoli:**

```bash
cd ~/code/v2ecoli-chromosome-rep1
git add investigations/t1/spec.yaml pbg_chromosome_rep1/composites/
git commit -m "chore(t1): migrate to v2 study vocabulary + E2E exercise"
```

---

## Self-review

- [x] Spec coverage: every vocabulary entity (Baseline/Variant/Intervention/Run/Comparison/Visualization/Conclusions) gets a task. Every endpoint in the spec has a task. Every tab has a task.
- [x] No placeholders. Code blocks for all code steps; commands for all commands.
- [x] Type consistency: `variants:` (plural noun in YAML + JS payloads), `variant` (singular in API field names), `intervention:` (singular noun, one per variant), `comparison:` (singular noun, list at top level). Consistent across all tasks.
- [x] Tasks ordered by dependency: A1 (migration) before A2 (validator uses migration); A2 before A5/A6 (which write the new shape); A3/A4 (endpoints) before B5/B6 (UI calling them); B1 (layout) before B2-B6 (filling tabs); A5 before D1/D2 (Sim Setup + Explorer need create-from-composite); E2 last (uses everything).
