# Investigation Panel + Study Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepen the Investigations + Studies UX: inline-expand study cards inside the Investigation panel to reveal full study content; add an inline "+ Add study" form (baseline-picker + objective); promote Conclusions and Visualizations to their own Study tabs; add inline-editable question/hypothesis/status to the Study Overview tab.

**Architecture:** All work in `/Users/eranagmon/code/vivarium-dashboard-tests-investigations/` on branch `feat/studies-with-tests-and-investigations`. Backend already exposes the needed endpoints (`/api/investigation/<slug>` for study detail, `/api/investigation-set-overview` for question/hypothesis/status, `/api/study-set-conclusion`, `/api/composites` for the baseline picker, `/api/study-baseline-add`, `/api/plan-create`, `/api/plan-study-add`). This plan is mostly frontend: 4 study-detail UI tasks + 2 investigations-panel UI tasks + 1 thin backend helper to consolidate study creation.

**Tech stack:** Python stdlib `http.server`, vanilla JS (ES5-style matching codebase), Jinja2 templates, CSS, YAML.

**Source:** Builds on `2026-05-15-studies-with-tests-and-investigations-design.md` and reuses fields already defined in `2026-05-12-study-model-design.md` (question / hypothesis / status / conclusion).

---

## Phase A — Study detail tabs

### Task A1: Inline-editable question + hypothesis + status in Overview tab

**Files:**
- Modify: `vivarium_dashboard/templates/study-detail.html` (Overview panel)
- Modify: `vivarium_dashboard/static/study-detail.js`
- Modify: `vivarium_dashboard/static/style.css`

**Backend already exists**: `POST /api/investigation-set-overview` (line 6080 of server.py) accepts `{investigation, fields: {question?, hypothesis?, status?}}` and writes those scalars to study.yaml.

- [ ] **Step 1:** In `templates/study-detail.html`, find the `panel-overview` section (around line 26). Above the existing Objective block, insert:

```html
<div class="overview-section">
  <h2 class="overview-label">Question</h2>
  <div id="question-text" class="overview-prose" data-editable="true"
       data-field="question"
       data-placeholder="(what research question is this study asking?)">{{ study.question or '' }}</div>
</div>

<div class="overview-section">
  <h2 class="overview-label">Hypothesis</h2>
  <div id="hypothesis-text" class="overview-prose" data-editable="true"
       data-field="hypothesis"
       data-placeholder="(predicted outcome)">{{ study.hypothesis or '' }}</div>
</div>

<div class="overview-section">
  <h2 class="overview-label">Status</h2>
  <select id="status-select" data-field="status" class="overview-status-select">
    <option value="draft"       {% if study.status == 'draft'       %}selected{% endif %}>draft</option>
    <option value="in-progress" {% if study.status == 'in-progress' %}selected{% endif %}>in-progress</option>
    <option value="completed"   {% if study.status == 'completed'   %}selected{% endif %}>completed</option>
    <option value="archived"    {% if study.status == 'archived'    %}selected{% endif %}>archived</option>
  </select>
</div>
```

- [ ] **Step 2:** In `static/study-detail.js`, find the existing blur-save handler for `#objective-text` and `#conclusion-text`. Extend it to also handle elements with `data-field="question"` / `"hypothesis"`. The save POST body becomes:

```javascript
fetch('/api/investigation-set-overview', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    investigation: studyName(),
    fields: { [field]: el.textContent }
  })
});
```

Add a change handler for `#status-select` that POSTs `{fields: {status: this.value}}` to the same endpoint.

If there's no existing blur-save handler for `data-editable="true"` elements, write one that:
1. Listens for `blur` on every `[data-editable="true"]` element.
2. Reads the element's `data-field` attribute (fall back: derive from the element's id — e.g., `objective-text` → `objective`).
3. Posts to the appropriate endpoint (`/api/investigation-set-overview` for question/hypothesis/status; `/api/study-set-objective` for objective; `/api/study-set-conclusion` for conclusion).

- [ ] **Step 3:** CSS — append to `style.css`:

```css
.overview-status-select {
  font-size: 1rem;
  padding: 0.3rem 0.5rem;
  border-radius: 4px;
  border: 1px solid #ccc;
  background: white;
}
```

- [ ] **Step 4:** Manual verification: open a study in the dashboard, edit question + hypothesis, change status, refresh the page → values persist.

- [ ] **Step 5:** Commit.
```bash
git add vivarium_dashboard/templates/study-detail.html vivarium_dashboard/static/study-detail.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): inline-editable question/hypothesis/status in study Overview tab"
```

---

### Task A2: Promote Conclusions to its own tab with 4 textareas

**Files:**
- Modify: `vivarium_dashboard/templates/study-detail.html` (add new tab + panel, remove inline Conclusion from Overview)
- Modify: `vivarium_dashboard/static/study-detail.js` (split/join markdown on H2 headers; save handler)

**Backend already exists**: `POST /api/study-set-conclusion {study, text}` (line 6050 area).

- [ ] **Step 1:** In `templates/study-detail.html`:

(a) Remove the inline Conclusion block from `panel-overview` (lines 49–53). Keep Objective.

(b) Add a new tab button after the existing Tests button (around line 23):

```html
<button class="study-tab" data-kind="conclusions" onclick="_setStudyTab('conclusions')">Conclusions</button>
```

(c) Add a new panel after `panel-tests`:

```html
<section class="study-tab-panel" data-kind="conclusions" id="panel-conclusions" hidden>
  <div class="conclusions-grid">
    <div class="conclusion-field">
      <h3>Claims</h3>
      <textarea id="conclusion-claims" rows="6" data-section="Claims"></textarea>
    </div>
    <div class="conclusion-field">
      <h3>Evidence</h3>
      <textarea id="conclusion-evidence" rows="6" data-section="Evidence"></textarea>
    </div>
    <div class="conclusion-field">
      <h3>Limitations</h3>
      <textarea id="conclusion-limitations" rows="6" data-section="Limitations"></textarea>
    </div>
    <div class="conclusion-field">
      <h3>Next steps</h3>
      <textarea id="conclusion-next-steps" rows="6" data-section="Next steps"></textarea>
    </div>
  </div>
  <p class="muted">Saved as one markdown blob in study.yaml.conclusion with H2 headers.</p>
</section>
```

- [ ] **Step 2:** In `static/study-detail.js`, add split/join helpers + load/save:

```javascript
function _splitConclusion(md) {
  // Split on H2 headers (## Claims, ## Evidence, ## Limitations, ## Next steps).
  // Anything before the first H2 lands in Claims. Recognize headers
  // case-sensitively per the spec.
  var sections = { Claims: '', Evidence: '', Limitations: '', 'Next steps': '' };
  if (!md) return sections;
  var parts = md.split(/(^|\n)##\s+/);
  var leadingFreeText = parts.shift();
  sections.Claims = (leadingFreeText || '').replace(/^\n+/, '').trim();
  for (var i = 0; i < parts.length; i += 2) {
    var nl = parts[i]; // empty or "\n"
    var rest = parts[i + 1];
    if (rest == null) continue;
    var newlineIdx = rest.indexOf('\n');
    var header = newlineIdx === -1 ? rest.trim() : rest.slice(0, newlineIdx).trim();
    var body = newlineIdx === -1 ? '' : rest.slice(newlineIdx + 1).trim();
    if (header in sections) sections[header] = body;
  }
  return sections;
}

function _joinConclusion(sections) {
  var parts = [];
  ['Claims', 'Evidence', 'Limitations', 'Next steps'].forEach(function (label) {
    var body = (sections[label] || '').trim();
    parts.push('## ' + label + '\n\n' + body);
  });
  return parts.join('\n\n').trim() + '\n';
}

function _loadConclusionsTab(study) {
  var s = _splitConclusion((study && study.conclusion) || '');
  document.getElementById('conclusion-claims').value      = s.Claims;
  document.getElementById('conclusion-evidence').value    = s.Evidence;
  document.getElementById('conclusion-limitations').value = s.Limitations;
  document.getElementById('conclusion-next-steps').value  = s['Next steps'];
}

function _saveConclusion() {
  var sections = {
    Claims:       document.getElementById('conclusion-claims').value,
    Evidence:     document.getElementById('conclusion-evidence').value,
    Limitations:  document.getElementById('conclusion-limitations').value,
    'Next steps': document.getElementById('conclusion-next-steps').value,
  };
  return fetch('/api/study-set-conclusion', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({study: studyName(), text: _joinConclusion(sections)}),
  });
}

// Wire blur-save on the 4 textareas.
['conclusion-claims', 'conclusion-evidence', 'conclusion-limitations', 'conclusion-next-steps'].forEach(function (id) {
  var el = document.getElementById(id);
  if (el) el.addEventListener('blur', _saveConclusion);
});
```

Hook `_loadConclusionsTab(study)` into `_setStudyTab('conclusions')` so the panel populates on open. The `study` object should already be available in the page closure (Task 13 used `window._studyName` — check what's there).

- [ ] **Step 3:** CSS — append:

```css
.conclusions-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.conclusion-field h3 { margin-top: 0; }
.conclusion-field textarea { width: 100%; box-sizing: border-box; font-family: inherit; padding: 0.5rem; }
```

- [ ] **Step 4:** Manual verification: open a study with a non-empty conclusion → 4 textareas populate (everything pre-H2 lands in Claims). Edit one, blur → reloads correctly.

- [ ] **Step 5:** Commit.
```bash
git add vivarium_dashboard/templates/study-detail.html vivarium_dashboard/static/study-detail.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): Conclusions tab with 4 labeled textareas (Claims/Evidence/Limitations/Next steps)"
```

---

### Task A3: Promote Visualizations to its own tab

**Files:**
- Modify: `vivarium_dashboard/templates/study-detail.html` (move viz-section out of Runs into a new tab)
- Modify: `vivarium_dashboard/static/study-detail.js` (load handler)
- Modify: `vivarium_dashboard/static/style.css` (minor)

- [ ] **Step 1:** In `templates/study-detail.html`:

(a) Find the `viz-section` inside `panel-runs` (around line 228). REMOVE that block from inside `panel-runs`.

(b) Add a new tab button (after Tests, before Conclusions if A2 landed):

```html
<button class="study-tab" data-kind="visualizations" onclick="_setStudyTab('visualizations')">Visualizations</button>
```

(c) Add a new panel:

```html
<section class="study-tab-panel" data-kind="visualizations" id="panel-visualizations" hidden>
  <div class="viz-section">
    <h3 class="section-title">Visualizations</h3>
    <div id="viz-list">
      {% for v in (study.visualizations or []) %}
      <div class="viz-config">
        <strong>{{ v.name }}</strong>
        <code class="muted">{{ v.address or '' }}</code>
        <button class="btn-render-viz" data-viz-name="{{ v.name }}">Render</button>
      </div>
      {% else %}
      <p class="empty-message">No visualizations yet.</p>
      {% endfor %}
    </div>
    <button class="btn-add-viz" onclick="_openAddVizModal()">+ Add visualization</button>
    <div id="viz-render-area"></div>
  </div>
</section>
```

- [ ] **Step 2:** In `static/study-detail.js`, ensure `_setStudyTab('visualizations')` toggles the panel visibility. The render button posts to `/api/investigation-render-viz` (existing endpoint). The add-viz modal is the existing `_openAddVizModal()` function if it exists; otherwise leave it as a TODO comment in the JS (this plan doesn't require building a new modal — reuse what's there).

Verify the existing add-viz / render-viz functions still work by inspection (look for `_openAddVizModal`, `_renderViz`, etc.).

- [ ] **Step 3:** Manual verification: open a study with visualizations → switch to Visualizations tab → see list. Click Render on one → check the existing render path triggers.

- [ ] **Step 4:** Commit.
```bash
git add vivarium_dashboard/templates/study-detail.html vivarium_dashboard/static/study-detail.js
git commit -m "feat(ui): promote Visualizations to its own Study tab (out of Runs)"
```

---

## Phase B — Investigation panel: study card expansion

### Task B1: Backend — compact study-summary endpoint (reuse-first)

**Files:**
- Optional: `vivarium_dashboard/server.py` — only add a new endpoint IF `GET /api/investigation/<slug>` doesn't return the needed shape.

- [ ] **Step 1:** Verify what `GET /api/investigation/<slug>` returns:

```bash
cd /Users/eranagmon/code/vivarium-dashboard-tests-investigations
grep -A 30 "_get_investigation_detail\|_get_investigation(self" vivarium_dashboard/server.py | head -50
```

If it returns the full study spec (objective, baseline, variants, interventions, runs, etc.), USE IT for the inline-card expansion. **Skip steps 2-3.**

- [ ] **Step 2:** ONLY IF the existing endpoint returns insufficient data — add a thin summary endpoint:

```python
    def _get_study_summary(self, slug: str):
        """GET /api/study/<slug>/summary — compact summary for inline-card use."""
        if not _SLUG_RE.match(slug):
            return self._json({"error": "invalid slug"}, 400)
        spec_path = WORKSPACE / "studies" / slug / "study.yaml"
        if not spec_path.exists():
            return self._json({"error": f"study not found: {slug}"}, 404)
        from .lib.investigations import load_spec
        spec = load_spec(spec_path)
        runs_db = WORKSPACE / "studies" / slug / "runs.db"
        runs_count = 0
        if runs_db.exists():
            import sqlite3
            try:
                conn = sqlite3.connect(runs_db); runs_count = conn.execute("SELECT COUNT(*) FROM runs_meta").fetchone()[0]; conn.close()
            except Exception:
                pass
        last = (spec.get("tests") or {}).get("last_results") or None
        return self._json({
            "slug": slug,
            "name": spec.get("name", slug),
            "objective": spec.get("objective", ""),
            "question": spec.get("question", ""),
            "hypothesis": spec.get("hypothesis", ""),
            "status": spec.get("status", "draft"),
            "baseline": [{"name": b.get("name"), "composite": b.get("composite")} for b in (spec.get("baseline") or [])],
            "variants": [{"name": v.get("name")} for v in (spec.get("variants") or [])],
            "interventions": [{"name": i.get("name"), "description": i.get("description", "")} for i in (spec.get("interventions") or [])],
            "runs_count": runs_count,
            "tests": last,  # {passed, failed, skipped, duration_s, timestamp} or null
        }, 200)
```

Register at GET dispatcher with pattern matching `/api/study/<slug>/summary`. Add a basic test in `tests/test_plan_endpoints.py` (reuse the `dashboard_client` fixture).

- [ ] **Step 3:** Commit if you added the endpoint.

---

### Task B2: Inline study-card expansion in Investigation panel

**Files:**
- Modify: `vivarium_dashboard/static/investigations.js`
- Modify: `vivarium_dashboard/static/style.css`

- [ ] **Step 1:** In `static/investigations.js`, change the study-card click handler. Currently it does `location.hash = '#studies/<slug>'`. Replace with toggle-expand:

```javascript
function toggleStudyCard(li, slug) {
  if (li.classList.contains('expanded')) {
    li.classList.remove('expanded');
    var content = li.querySelector('.study-card-content');
    if (content) content.remove();
    return;
  }
  li.classList.add('expanded');
  // Fetch the study summary (reuse the legacy /api/investigation/<slug> endpoint).
  fetch('/api/investigation/' + encodeURIComponent(slug)).then(function (r) {
    return r.json();
  }).then(function (study) {
    var content = document.createElement('div');
    content.className = 'study-card-content';
    content.innerHTML = renderStudyExpanded(study);
    li.appendChild(content);
  });
}

function renderStudyExpanded(study) {
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  var baselines = (study.baseline || []).map(function (b) { return '<li><code>' + esc(b.name) + '</code> — <code class="muted">' + esc(b.composite) + '</code></li>'; }).join('');
  var variants = (study.variants || []).map(function (v) { return '<li><code>' + esc(v.name) + '</code></li>'; }).join('');
  var interventions = (study.interventions || []).map(function (i) { return '<li><strong>' + esc(i.name) + '</strong>: ' + esc(i.description || '') + '</li>'; }).join('');
  var tests = (study.tests && study.tests.last_results) || null;
  var testsLine = tests
    ? (tests.passed + ' passed / ' + tests.failed + ' failed / ' + tests.skipped + ' skipped')
    : '(no test results yet)';
  return [
    '<div class="card-section"><h5>Objective</h5><p>' + esc(study.objective || '(none)') + '</p></div>',
    '<div class="card-section"><h5>Question</h5><p>' + esc(study.question || '(none)') + '</p></div>',
    '<div class="card-section"><h5>Hypothesis</h5><p>' + esc(study.hypothesis || '(none)') + '</p></div>',
    '<div class="card-section"><h5>Baseline (' + (study.baseline || []).length + ')</h5><ul>' + baselines + '</ul></div>',
    '<div class="card-section"><h5>Variants (' + (study.variants || []).length + ')</h5><ul>' + (variants || '<li class="muted">(none)</li>') + '</ul></div>',
    '<div class="card-section"><h5>Interventions (' + (study.interventions || []).length + ')</h5><ul>' + (interventions || '<li class="muted">(none)</li>') + '</ul></div>',
    '<div class="card-section"><h5>Tests</h5><p>' + esc(testsLine) + '</p></div>',
    '<div class="card-section"><a class="open-study-link" href="#studies/' + encodeURIComponent(study.name) + '">Open in own page →</a></div>',
  ].join('');
}
```

- [ ] **Step 2:** Replace the existing `study-link` click handler in `openInvestigation`. Where currently the click does `location.hash = '#studies/<slug>'`, change to:

```javascript
li.addEventListener('click', function (e) {
  // Allow the "Open in own page" link to navigate normally.
  if (e.target.matches('.open-study-link')) return;
  toggleStudyCard(li, s.study);
});
```

- [ ] **Step 3:** CSS — append:

```css
.study-card { cursor: pointer; }
.study-card.expanded { background: #fafafa; flex-wrap: wrap; }
.study-card-content { flex-basis: 100%; padding: 0.6rem 0 0 0; border-top: 1px solid #eee; margin-top: 0.4rem; }
.study-card-content .card-section { margin: 0.4rem 0; }
.study-card-content .card-section h5 { margin: 0.2rem 0; font-size: 0.85em; text-transform: uppercase; color: #555; }
.study-card-content .card-section p { margin: 0.2rem 0; }
.study-card-content .card-section ul { margin: 0.2rem 0 0.2rem 1rem; padding: 0; }
.study-card-content .open-study-link { color: #4a90e2; text-decoration: none; font-size: 0.9em; }
.study-card-content .open-study-link:hover { text-decoration: underline; }
```

- [ ] **Step 4:** Manual verification: open an Investigation, click a study card → card expands showing objective / baseline / variants / interventions / tests. Click again → collapses. Other cards stay visible. "Open in own page" link navigates to the existing Study detail page.

- [ ] **Step 5:** Commit.
```bash
git add vivarium_dashboard/static/investigations.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): inline-expand study cards inside Investigation panel"
```

---

### Task B3: Inline "+ Add study" form in Investigation panel

**Files:**
- Modify: `vivarium_dashboard/templates/index.html.j2` (add inline form markup)
- Modify: `vivarium_dashboard/static/investigations.js` (form logic)
- Modify: `vivarium_dashboard/static/style.css`

- [ ] **Step 1:** In `templates/index.html.j2`, find the `page-investigations` section (after Task 14b's work). After the `<ol id="investigation-study-cards">` and inside `#investigation-detail`, add:

```html
<section class="add-study-form-section">
  <details class="add-study-details">
    <summary class="btn-add-study">+ Add study to this investigation</summary>
    <form id="add-study-form" onsubmit="return _submitAddStudy(event)">
      <label>Slug (short, lowercase): <input name="slug" required pattern="[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?"></label>
      <fieldset>
        <legend>Baseline composite(s)</legend>
        <div id="add-study-baseline-list" class="add-study-baseline-list">
          <p class="muted">(loading workspace composites…)</p>
        </div>
      </fieldset>
      <label>Objective:<br>
        <textarea name="objective" rows="3" placeholder="What is this study testing?"></textarea>
      </label>
      <label>Gate:
        <select name="gate">
          <option value="tests-pass" selected>tests-pass (block next study until tests pass)</option>
          <option value="">none (next study unblocked immediately)</option>
        </select>
      </label>
      <div class="form-actions">
        <button type="submit" class="action-btn">Create study</button>
        <span id="add-study-feedback" class="muted"></span>
      </div>
    </form>
  </details>
</section>
```

- [ ] **Step 2:** In `static/investigations.js`, add the form logic:

```javascript
function _populateBaselineList() {
  var box = document.getElementById('add-study-baseline-list');
  if (!box) return;
  fetch('/api/composites').then(function (r) { return r.json(); }).then(function (catalog) {
    box.innerHTML = '';
    var comps = (catalog && catalog.composites) || [];
    if (!comps.length) {
      box.innerHTML = '<p class="muted">No composites in workspace catalog.</p>';
      return;
    }
    comps.forEach(function (c) {
      var label = document.createElement('label');
      label.className = 'baseline-checkbox';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = c.id;
      cb.dataset.name = c.name || c.id.split('.').pop();
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (c.name || c.id) + ' '));
      var fqn = document.createElement('code');
      fqn.className = 'muted';
      fqn.textContent = c.id;
      label.appendChild(fqn);
      box.appendChild(label);
      box.appendChild(document.createElement('br'));
    });
  });
}

window._submitAddStudy = function (event) {
  event.preventDefault();
  var form = event.target;
  var fd = new FormData(form);
  var slug = String(fd.get('slug') || '').trim();
  var objective = String(fd.get('objective') || '').trim();
  var gate = String(fd.get('gate') || '');
  var checked = Array.prototype.slice.call(form.querySelectorAll('input[type=checkbox]:checked'));
  if (!slug) { _setAddStudyFeedback('slug required', 'fail'); return false; }
  if (!checked.length) { _setAddStudyFeedback('pick at least one baseline composite', 'fail'); return false; }
  var invSlug = state.activeSlug;
  if (!invSlug) { _setAddStudyFeedback('no active investigation', 'fail'); return false; }

  _setAddStudyFeedback('creating study…', '');
  // Sequence: create the study, add baseline entries, append to investigation.
  fetch('/api/investigation-create', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: slug, objective: objective}),
  }).then(function (r) {
    if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || 'create failed'); });
    return Promise.all(checked.map(function (cb, idx) {
      return fetch('/api/study-baseline-add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({study: slug, name: cb.dataset.name + (idx ? '-' + idx : ''), composite: cb.value, params: {}}),
      });
    }));
  }).then(function () {
    return fetch('/api/plan-study-add', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slug: invSlug, study: slug, gate: gate || null}),
    });
  }).then(function (r) {
    if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || 'plan-study-add failed'); });
    _setAddStudyFeedback('created', 'ok');
    form.reset();
    document.querySelector('.add-study-details').open = false;
    openInvestigation(invSlug);  // refresh the detail view
  }).catch(function (e) {
    _setAddStudyFeedback('error: ' + e.message, 'fail');
  });
  return false;
};

function _setAddStudyFeedback(msg, kind) {
  var el = document.getElementById('add-study-feedback');
  if (!el) return;
  el.textContent = msg;
  el.className = 'muted' + (kind === 'ok' ? ' ok' : kind === 'fail' ? ' fail' : '');
}

// Wire the baseline-list population when the dialog opens.
document.addEventListener('DOMContentLoaded', function () {
  var detailsEl = document.querySelector('.add-study-details');
  if (detailsEl) {
    detailsEl.addEventListener('toggle', function () {
      if (detailsEl.open) _populateBaselineList();
    });
  }
});
```

- [ ] **Step 3:** CSS — append:

```css
.add-study-form-section { margin: 1rem 0; padding: 0.6rem; background: #fafafa; border-radius: 6px; }
.btn-add-study { cursor: pointer; padding: 0.4rem 0.6rem; background: #e7f3ff; border-radius: 4px; display: inline-block; }
.btn-add-study:hover { background: #d0e7ff; }
#add-study-form label { display: block; margin: 0.5rem 0; }
#add-study-form fieldset { margin: 0.5rem 0; padding: 0.5rem; }
#add-study-form fieldset legend { font-weight: bold; }
.baseline-checkbox { display: inline-block; padding: 0.2rem 0.4rem; }
.add-study-baseline-list { max-height: 200px; overflow-y: auto; }
.form-actions { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
#add-study-feedback.ok { color: #228B22; }
#add-study-feedback.fail { color: #B22222; }
```

- [ ] **Step 4:** Manual verification: open an Investigation → "+ Add study" → form expands → workspace composites populate as checkboxes → pick one + type slug + objective + submit → new study appears in the chain.

- [ ] **Step 5:** Commit.
```bash
git add vivarium_dashboard/templates/index.html.j2 vivarium_dashboard/static/investigations.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): inline + Add study form in Investigation panel (baseline picker + objective)"
```

---

## Self-review

**Spec coverage:**
- Inline-editable question/hypothesis/status — Task A1 ✓
- Conclusions tab with 4 textareas — Task A2 ✓
- Visualizations tab promoted out of Runs — Task A3 ✓
- Study card inline expansion — Task B2 ✓
- "+ Add study" inline form — Task B3 ✓

**Endpoint usage check:**
- `/api/investigation-set-overview` — exists (server.py:6080), accepts question/hypothesis/status.
- `/api/study-set-conclusion` — exists (server.py around 6050).
- `/api/study-set-objective` — exists (server.py:6120).
- `/api/investigation/<slug>` — exists, used for card expansion.
- `/api/composites` — exists, used for baseline picker.
- `/api/investigation-create` — exists, for study creation.
- `/api/study-baseline-add` — verified at server.py line ~table; if missing, add a thin handler in Task B3.
- `/api/plan-study-add` — created in Task 10 of the prior plan.

**Out of scope (follow-up):**
- Comparisons sub-panel (referenced by `2026-05-12-study-model-design.md` Visualization tab).
- "Begin Study" from Composite Explorer (path is in `_beginStudyFromComposite()` — separate work).
- Interventions tab redesign (current basic list is fine).
- Investigation-level visualizations / conclusions (not yet scoped).
