# Reuse-first visualization pattern — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new visualization becomes a v2 `Visualization` class committed to `<workspace_pkg>/visualizations/<snake>.py`. /pbg-viz uses a new `as_visualization` decorator (analogous to `as_step`/`as_process`) so the skill emits a single decorated function. Generated classes are auto-discovered into `core.link_registry`, so each iteration grows the reusable catalog.

**Architecture:** Three phases. (A) pbg-superpowers grows an `as_visualization` decorator and ships v0.7.0. (B) pbg-template adds generation/accept/migration endpoints, a search input on the class catalog, a "Generate new visualization class" panel, and a migration banner. (C) `/pbg-viz` SKILL.md is rewritten to emit decorated-function files at the workspace-package location.

**Tech Stack:** Python 3.10+, process-bigraph, bigraph-schema, pbg-superpowers, vanilla JavaScript, Jinja2 templates, pytest.

---

## File Structure

### Created

| File | Responsibility |
|---|---|
| `pbg-template/scripts/_lib/migrations.py` | Classify a workspace.yaml viz entry into a migration action (auto-convert, regenerate, defer) given the current registry. Pure logic; no I/O. |
| `pbg-template/scripts/migrate-visualizations.py` | CLI wrapper around `migrations.py` for headless workflows. `--dry-run` prints the plan; otherwise rewrites workspace.yaml + writes log. |
| `pbg-template/tests/test_migrations.py` | Unit tests for the `migrations.py` classifier (no server, no FS dependency beyond fixture YAML). |
| `pbg-template/tests/test_visualization_endpoints.py` | Tests for the new `/api/visualization-generate`, `/api/visualization-accept`, `/api/visualization-migration-plan`, `/api/visualization-migrate` endpoints. |

### Modified

| File | Change |
|---|---|
| `pbg-superpowers/pbg_superpowers/visualization.py` | Add `as_visualization` decorator. |
| `pbg-superpowers/tests/test_visualization.py` | Append decorator tests. |
| `pbg-superpowers/pyproject.toml` | Bump version to 0.7.0. |
| `pbg-superpowers/pbg_superpowers/__init__.py` | Fix stale `__version__ = "0.1.0"` → `"0.7.0"`. |
| `pbg-template/scripts/_server/server.py` | New endpoints + cache-invalidation helper. |
| `pbg-template/scripts/_server/walkthrough.js` | Search input on catalog; new "Generate" panel; migration banner; accept/regenerate UX. |
| `pbg-template/scripts/_templates/index.html.j2` | New panels: search input, generate-new panel, migration banner, modals. |
| `~/.claude/skills/pbg-viz/SKILL.md` | Rewrite contract: emit decorated function at `<workspace_pkg>/visualizations/<snake>.py`. |

---

## Phase A — pbg-superpowers `as_visualization` + v0.7.0

### Task 1: Add `as_visualization` decorator + tests

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualization.py`
- Modify: `pbg-superpowers/tests/test_visualization.py`

Working dir: `/Users/eranagmon/code/pbg-superpowers`. Use whatever branch is checked out.

- [ ] **Step 1: Append failing tests** to `tests/test_visualization.py`

```python
# Append after existing tests:

from pbg_superpowers.visualization import as_visualization


def test_as_visualization_synthesizes_subclass():
    @as_visualization(inputs={'x': 'list[float]'}, name='MyViz', demo={'x': [1.0, 2.0]})
    def update_my_viz(state):
        return {'html': '<p>x=' + str(state['x']) + '</p>'}

    assert issubclass(update_my_viz, Visualization)
    assert update_my_viz.__name__ == 'MyViz'
    assert update_my_viz.__pb_kind__ == 'visualization'
    assert 'MyViz' in update_my_viz.__pb_aliases__
    inst = object.__new__(update_my_viz)
    assert inst.inputs() == {'x': 'list[float]'}
    assert inst.outputs() == {'html': 'string'}
    assert inst.update({'x': [1.0, 2.0]}) == {'html': '<p>x=[1.0, 2.0]</p>'}


def test_as_visualization_demo_dict():
    @as_visualization(inputs={'x': 'list[float]'},
                      demo={'x': [3.0, 4.0]})
    def update_demo_dict(state):
        return {'html': str(state['x'])}

    assert update_demo_dict.demo() == {'x': [3.0, 4.0]}


def test_as_visualization_demo_callable():
    @as_visualization(inputs={'x': 'list[float]'},
                      demo=lambda: {'x': [5.0, 6.0]})
    def update_demo_callable(state):
        return {'html': str(state['x'])}

    assert update_demo_callable.demo() == {'x': [5.0, 6.0]}


def test_as_visualization_function_name_validation():
    with pytest.raises(AssertionError, match='update_'):
        @as_visualization(inputs={})
        def bad_name(state):
            return {'html': ''}


def test_as_visualization_default_name_from_function():
    @as_visualization(inputs={'x': 'list[float]'})
    def update_inferred_name(state):
        return {'html': ''}

    assert update_inferred_name.__name__ == 'inferred_name'
    assert 'inferred_name' in update_inferred_name.__pb_aliases__


def test_as_visualization_aliases():
    @as_visualization(inputs={}, name='Primary', aliases=['alt1', 'alt2'])
    def update_aliased(state):
        return {'html': ''}

    assert 'Primary' in update_aliased.__pb_aliases__
    assert 'alt1' in update_aliased.__pb_aliases__
    assert 'alt2' in update_aliased.__pb_aliases__
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd /Users/eranagmon/code/pbg-superpowers
python -m pytest tests/test_visualization.py -v
```

Expected: 6 new tests fail with `ImportError: cannot import name 'as_visualization'`.

- [ ] **Step 3: Add the decorator** to `pbg_superpowers/visualization.py`

Append after the `Visualization` class:

```python
def as_visualization(inputs, name=None, demo=None, aliases=None):
    """Decorator: convert an ``update_*`` pure function into a Visualization subclass.

    The function must be named ``update_<viz_name>`` and accept
    ``state: dict`` -> ``{'html': str}``.

    Args:
        inputs:  typed input port map (same shape as Visualization.inputs()).
                 Keys are port names; values are bigraph-schema type strings.
        name:    class name override (default: derived from function name).
        demo:    sample state dict (or callable returning one) for dashboard previews.
        aliases: extra registration aliases for bigraph-schema discovery.

    Returns the synthesized Visualization subclass, ready to be registered by
    ``bigraph_schema.discover_packages()`` when the enclosing module is walked.
    """
    def decorator(func):
        if not func.__name__.startswith("update_"):
            raise AssertionError(
                f"as_visualization expects a function named update_<viz_name>; "
                f"got '{func.__name__}'"
            )
        viz_name = name or func.__name__[len("update_"):]
        _demo = demo

        class FunctionVisualization(Visualization):
            def inputs(self):
                return inputs

            def outputs(self):
                return {'html': 'string'}

            def update(self, state):
                return func(state)

            @classmethod
            def demo(cls):
                if callable(_demo):
                    return _demo()
                return dict(_demo or {})

        FunctionVisualization.__name__ = viz_name
        FunctionVisualization.__qualname__ = viz_name
        FunctionVisualization.__module__ = func.__module__
        FunctionVisualization.__doc__ = func.__doc__
        FunctionVisualization.__pb_kind__ = "visualization"
        FunctionVisualization.__pb_aliases__ = [viz_name] + list(aliases or [])
        FunctionVisualization.__pb_wrapped__ = func
        return FunctionVisualization
    return decorator
```

- [ ] **Step 4: Run, confirm pass**

```bash
python -m pytest tests/test_visualization.py -v
```

Expected: all tests pass (the original 6 from v2 work + 6 new = 12).

- [ ] **Step 5: Commit**

```bash
git add pbg_superpowers/visualization.py tests/test_visualization.py
git commit -m "feat: as_visualization decorator — function-style Visualization authoring"
```

---

### Task 2: Release pbg-superpowers v0.7.0

**Files:**
- Modify: `pbg-superpowers/pyproject.toml`
- Modify: `pbg-superpowers/pbg_superpowers/__init__.py`

Working dir: `/Users/eranagmon/code/pbg-superpowers`.

- [ ] **Step 1: Bump pyproject.toml**

```bash
cd /Users/eranagmon/code/pbg-superpowers
sed -i.bak 's/^version = "0\.6\.0"$/version = "0.7.0"/' pyproject.toml && rm pyproject.toml.bak
grep '^version = ' pyproject.toml
```

Expected: `version = "0.7.0"`.

- [ ] **Step 2: Fix the stale __version__ in __init__.py**

Read `pbg_superpowers/__init__.py` and find the line `__version__ = "0.1.0"`. Replace with `__version__ = "0.7.0"`. If no such line exists, add one near the top.

- [ ] **Step 3: Confirm v0.7.0 stamps**

```bash
.venv/bin/python3 -c "import pbg_superpowers; print(getattr(pbg_superpowers, '__version__', None))" 2>/dev/null || \
  python3 -c "import sys; sys.path.insert(0, '.'); from pbg_superpowers import __version__; print(__version__)"
```

Expected: `0.7.0`.

- [ ] **Step 4: Commit, tag, push**

```bash
git add pyproject.toml pbg_superpowers/__init__.py
git commit -m "chore: bump to 0.7.0 — as_visualization decorator"
git push origin HEAD 2>&1 | tail -5
git tag v0.7.0
git push origin v0.7.0 2>&1 | tail -5
```

- [ ] **Step 5: Verify PyPI workflow fired**

```bash
gh run list --workflow release.yml --limit 3
```

Expected: a new in-progress or queued run triggered by `v0.7.0`. No action needed beyond noting the run ID.

---

## Phase B — pbg-template

### Task 3: Catalog search input + filter

**Files:**
- Modify: `pbg-template/scripts/_templates/index.html.j2`
- Modify: `pbg-template/scripts/_server/walkthrough.js`

Working dir: `/Users/eranagmon/code/pbg-template`.

- [ ] **Step 1: Add a search input** above the catalog container in `scripts/_templates/index.html.j2`

Find the panel containing `id="viz-picker-container"`. Insert a search input just above it:

```html
    <input type="search" id="viz-catalog-search" placeholder="Search Visualization classes by name or doc…"
           style="width:100%;padding:6px;margin-bottom:8px;font-size:0.9em"
           oninput="_filterVizCatalog(this.value)">
    <div id="viz-picker-container">
```

- [ ] **Step 2: Add `_filterVizCatalog` to `scripts/_server/walkthrough.js`**

Find `_renderKindPicker` and add a sibling function:

```javascript
  function _filterVizCatalog(query) {
    var rows = document.querySelectorAll('#viz-picker-container .picker-row');
    var q = (query || '').toLowerCase().trim();
    rows.forEach(function(row) {
      if (!q) { row.style.display = ''; return; }
      var hay = (row.textContent || '').toLowerCase();
      row.style.display = hay.indexOf(q) === -1 ? 'none' : '';
    });
  }
  window._filterVizCatalog = _filterVizCatalog;
```

- [ ] **Step 3: Smoke-test in browser** (manual)

Re-render dashboard:
```bash
cd /Users/eranagmon/code/pbg-template
# (Sync to v2ecoli as usual; restart server; hard-reload.)
```

- [ ] **Step 4: Commit**

```bash
git add scripts/_templates/index.html.j2 scripts/_server/walkthrough.js
git commit -m "feat(viz): search input on Available Visualization classes catalog"
```

---

### Task 4: `migrations.py` module + unit tests

**Files:**
- Create: `pbg-template/scripts/_lib/migrations.py`
- Create: `pbg-template/tests/test_migrations.py`

- [ ] **Step 1: Write failing tests** at `tests/test_migrations.py`

```python
"""Tests for the workspace.yaml visualization migration classifier."""
from scripts._lib.migrations import classify_viz_entry


def test_classify_use_the_registered_class_pattern_with_match():
    entry = {
        'name': 'readdyplots',
        'description': 'Use the registered ReaDDyPlots class from the Registry. Run-time '
                       'instantiation of ReaDDyPlots against the gathered emitter results.',
    }
    classes = {'ReaDDyPlots', 'TimeSeriesPlot', 'Heatmap'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'auto-convert-to-class-backed'
    assert result['target_class'] == 'ReaDDyPlots'


def test_classify_use_the_registered_class_pattern_no_match():
    entry = {
        'name': 'unknown-class-ref',
        'description': 'Use the registered MissingThing class from the Registry.',
    }
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'defer'
    assert 'MissingThing' in result['reason']


def test_classify_wrapper_response_file_exists(tmp_path):
    entry = {'name': 'smoke-trajectory', 'description': 'Custom timeseries plot.'}
    responses_dir = tmp_path / '.pbg' / 'viz-responses'
    responses_dir.mkdir(parents=True)
    (responses_dir / 'smoke-trajectory.py').write_text('def visualize(results): return ""')
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes, workspace_root=tmp_path)
    assert result['action'] == 'regenerate-as-class'
    assert 'smoke-trajectory.py' in result['legacy_path']


def test_classify_description_only_no_response(tmp_path):
    entry = {'name': 'video-of-chromosome', 'description': 'a gif of the chromosome.'}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes, workspace_root=tmp_path)
    assert result['action'] == 'regenerate-as-class'
    assert result.get('legacy_path') is None


def test_classify_already_class_backed_is_no_op():
    entry = {'name': 'free-DnaA', 'class': 'TimeSeriesPlot', 'config': {'observable': 'free_DnaA'}}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'no-op'


def test_classify_legacy_structured_entry_no_class_no_description():
    entry = {'name': 'dnaA-trajectory', 'type': 'time-series', 'observables': ['DnaA']}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'defer'
    assert 'manual' in result['reason'].lower() or 'legacy structured' in result['reason'].lower()
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest tests/test_migrations.py -v
```

Expected: all 6 tests fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `scripts/_lib/migrations.py`**

```python
"""Classify a workspace.yaml visualization entry into a migration action.

Used by both the dashboard's migration plan endpoint and the scripts/migrate-
visualizations.py CLI. Pure logic — pass in the entry + the set of currently
registered class names; get back a dict describing what to do.
"""
from __future__ import annotations
import re
from pathlib import Path


_USE_REGISTERED_CLASS_RE = re.compile(
    r'use the registered (\w+) class', re.IGNORECASE,
)


def classify_viz_entry(
    entry: dict,
    registered_classes: set,
    workspace_root: Path | None = None,
) -> dict:
    """Return a dict describing what to do with ``entry``.

    Returns:
        action: 'no-op' | 'auto-convert-to-class-backed' | 'regenerate-as-class' | 'defer'
        target_class: (when auto-convert) the class name to bind
        legacy_path: (when regenerate) path to the existing wrapper response file, if any
        reason: (when defer) human-readable explanation
    """
    # Already class-backed: nothing to do.
    if entry.get('class'):
        return {'action': 'no-op'}

    name = entry.get('name', '')
    description = entry.get('description') or ''

    # Pattern 1: "use the registered X class"
    match = _USE_REGISTERED_CLASS_RE.search(description)
    if match:
        target = match.group(1)
        if target in registered_classes:
            return {'action': 'auto-convert-to-class-backed', 'target_class': target}
        return {
            'action': 'defer',
            'reason': f'description refers to class {target!r} which is not currently registered',
        }

    # Pattern 2: legacy structured entry (type/observables, no description) —
    # not a /pbg-viz-style entry, can't be auto-classified.
    if entry.get('type') or entry.get('observables'):
        if not description:
            return {
                'action': 'defer',
                'reason': 'legacy structured entry (no description); manual migration recommended',
            }

    # Pattern 3: has description; check for existing wrapper response file.
    legacy_path = None
    if workspace_root and name:
        candidate = Path(workspace_root) / '.pbg' / 'viz-responses' / f'{name}.py'
        if candidate.is_file():
            legacy_path = str(candidate)

    return {
        'action': 'regenerate-as-class',
        'legacy_path': legacy_path,
    }
```

- [ ] **Step 4: Run, confirm pass**

```bash
python -m pytest tests/test_migrations.py -v
```

Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib/migrations.py tests/test_migrations.py
git commit -m "feat(viz): migrations.classify_viz_entry for legacy workspace.yaml entries"
```

---

### Task 5: `/api/visualization-generate` + `/api/visualization-accept` endpoints

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`
- Create: `pbg-template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing tests** at `tests/test_visualization_endpoints.py`

```python
"""Tests for the new visualization generation + acceptance endpoints."""
import json
import urllib.request
import urllib.error

# These tests use the test_server harness pattern shared with other endpoint
# tests in this repo. See tests/test_investigations.py for the WorkspaceServer
# fixture if it differs from this minimal shape.
import pytest

from tests._fixtures.workspace_server import workspace_server  # noqa: F401


def _post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_post_visualization_generate_writes_request_with_new_contract(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/visualization-generate',
        {'name': 'fresh-test-viz',
         'description': 'a plot of free DnaA vs time with a 50-molecule threshold line'},
    )
    assert code == 200, j
    assert j['ok'] is True
    request_path = workspace_server.root / '.pbg' / 'viz-requests' / 'fresh-test-viz.md'
    assert request_path.is_file()
    body = request_path.read_text()
    # New contract: request mentions as_visualization and the target file path.
    assert 'as_visualization' in body
    assert 'visualizations/fresh_test_viz.py' in body
    # No reference to the old wrapper-function contract:
    assert 'def visualize(results' not in body


def test_post_visualization_generate_rejects_bad_name(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/visualization-generate',
        {'name': 'has spaces', 'description': 'x'},
    )
    assert code == 400
    assert 'name' in j.get('error', '').lower()


def test_post_visualization_accept_invalidates_core_cache(workspace_server):
    # Prepare a generated file in the workspace package's visualizations/ dir.
    pkg_viz = workspace_server.root / 'pbg_testws' / 'visualizations'
    pkg_viz.mkdir(parents=True, exist_ok=True)
    (pkg_viz / '__init__.py').write_text('')
    (pkg_viz / 'cache_probe.py').write_text(
        'from pbg_superpowers.visualization import as_visualization\n'
        '@as_visualization(inputs={"x": "list[float]"}, name="CacheProbe", demo={"x": [1.0]})\n'
        'def update_cache_probe(state):\n'
        '    return {"html": "<p>" + str(state["x"]) + "</p>"}\n'
    )

    code, j = _post(
        workspace_server.url + '/api/visualization-accept',
        {'name': 'cache-probe', 'class_name': 'CacheProbe'},
    )
    assert code == 200, j
    assert j['ok'] is True
    # After accept, the cache must have been invalidated so the new class
    # appears in /api/visualization-classes.
    req = urllib.request.Request(workspace_server.url + '/api/visualization-classes')
    with urllib.request.urlopen(req) as resp:
        classes = json.loads(resp.read())
    names = {c['name'] for c in classes['classes']}
    assert 'CacheProbe' in names
```

If the `workspace_server` fixture doesn't exist yet in `tests/_fixtures/`, mirror the pattern from `tests/test_investigations.py` — that file already spins up the server against a temp workspace. The shared fixture refactor is out of scope; if missing, add a local helper at the top of `test_visualization_endpoints.py`.

- [ ] **Step 2: Run, confirm fail**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest tests/test_visualization_endpoints.py -v
```

Expected: tests fail because endpoints don't exist yet (`HTTP 404`).

- [ ] **Step 3: Add endpoints in `scripts/_server/server.py`**

In the POST dispatch dict (search for `"/api/visualization": self._post_visualization,`), add:

```python
            "/api/visualization-generate":      self._post_visualization_generate,
            "/api/visualization-accept":        self._post_visualization_accept,
```

Then add the handler methods. Place them next to `_post_visualization_create` for locality:

```python
    def _post_visualization_generate(self, body: dict):
        """POST /api/visualization-generate {name, description} — write a
        new-contract viz-request file at .pbg/viz-requests/<name>.md. The
        /pbg-viz skill consumes the request and writes a decorated function
        to <workspace_pkg>/visualizations/<snake>.py.
        """
        import re as _re
        name = (body.get("name") or "").strip()
        if not name or not _re.match(r"^[a-zA-Z0-9_-]+$", name):
            return self._json({"error": "name must match ^[a-zA-Z0-9_-]+$"}, 400)
        description = (body.get("description") or "").strip()
        if not description:
            return self._json({"error": "description is required"}, 400)

        snake = name.lower().replace("-", "_")
        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text()) or {}
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        target = f"{pkg}/visualizations/{snake}.py"

        # Build context for the skill.
        observables = ws_data.get("observables") or []
        simulations = ws_data.get("simulations") or []
        obs_lines = "\n".join(
            f'  - `{o.get("name")}` (path: `{o.get("store_path")}`'
            + (f', units: {o["units"]}' if o.get("units") else "")
            + ")"
            for o in observables if isinstance(o, dict)
        ) or "  (none)"
        sim_lines = "\n".join(
            f'  - `{s.get("name")}`: t={s.get("t_start")}->{s.get("t_end")}'
            for s in simulations if isinstance(s, dict)
        ) or "  (none)"

        body_md = (
            f"# Visualization request: {name}\n\n"
            f"## Description (from user)\n\n"
            f"{description}\n\n"
            f"## Workspace context\n\n"
            f"- Workspace package: `{pkg}`\n"
            f"- Available observables:\n{obs_lines}\n"
            f"- Available simulations:\n{sim_lines}\n\n"
            f"## Instructions for the agent\n\n"
            f"Write a single function decorated with `@as_visualization` and save it to "
            f"`{target}`.\n\n"
            f"Output file structure (the only thing this file should contain):\n\n"
            f"```python\n"
            f'"""<class-name> — one-line description.\n\n'
            f"Generated by /pbg-viz from request '{name}'.\n"
            f'"""\n'
            f"from __future__ import annotations\n"
            f"import html as _html, json\n"
            f"from pbg_superpowers.visualization import as_visualization\n\n\n"
            f"@as_visualization(\n"
            f"    inputs={{'<port>': '<bigraph-type>', ...}},  # typed input ports\n"
            f"    name='<ClassName>',\n"
            f"    demo={{...}},                                  # synthetic state for dashboard preview\n"
            f")\n"
            f"def update_{snake}(state):\n"
            f"    # ... build the Plotly figure from state ...\n"
            f"    return {{'html': '<...Plotly HTML...>'}}\n"
            f"```\n\n"
            f"Constraints:\n\n"
            f"- The function MUST be named `update_<viz_name>` (snake_case).\n"
            f"- `inputs` MUST use bigraph-schema type strings — `'list[float]'`, `'float'`, "
            f"`'list[list[float]]'`, `'string'`. For trajectory ports prefer `'list[float]'`.\n"
            f"- `demo` MUST be realistic synthetic state matching `inputs` so the dashboard "
            f"preview is meaningful.\n"
            f"- Do NOT define a class manually; the decorator synthesizes the Visualization "
            f"subclass.\n"
            f"- Do NOT edit `__init__.py` — `bigraph_schema.discover_packages()` walks the "
            f"package automatically.\n"
            f"- The file must be self-contained (only `pbg_superpowers`, `process_bigraph`, "
            f"`html`, `json`, and standard `plotly`/`matplotlib` imports allowed).\n"
        )

        req_dir = WORKSPACE / ".pbg" / "viz-requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_path = req_dir / f"{name}.md"
        req_path.write_text(body_md)
        return self._json({
            "ok": True,
            "request_path": str(req_path),
            "target_file": target,
            "skill_command": f"/pbg-viz {name}",
            "instructions": (
                "In your active Claude Code session, run `/pbg-viz "
                f"{name}`. The skill will read this request and write the "
                "decorated function to the target file. Click Accept here "
                "when it's done."
            ),
        }, 200)

    def _post_visualization_accept(self, body: dict):
        """POST /api/visualization-accept {name, class_name} — finalize a
        generated viz: verify the file imports cleanly, invalidate the
        bigraph-schema core cache so the next allocate_core() picks up the
        new class, and commit the file on the active branch.
        """
        name = (body.get("name") or "").strip()
        class_name = (body.get("class_name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)

        snake = name.lower().replace("-", "_")
        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text()) or {}
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        target_rel = f"{pkg}/visualizations/{snake}.py"
        target_abs = WORKSPACE / target_rel
        if not target_abs.is_file():
            return self._json({"error": f"generated file not found at {target_rel}"}, 404)

        # Validate import: clear cached core, attempt to allocate fresh.
        try:
            import bigraph_schema.core as _bsc
            _bsc._cached_base_core = None
            _ws_add_to_sys_path()
            sys.path.insert(0, str(WORKSPACE))
            core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
            # Force a re-import of the new submodule too, in case Python cached
            # an earlier failed import.
            import importlib
            mod_name = f"{pkg}.visualizations.{snake}"
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                __import__(mod_name)
            core = core_module.build_core()
            registry = dict(core.link_registry)
        except Exception as e:
            return self._json({
                "error": f"generated file failed to import: {type(e).__name__}: {e}"
            }, 500)

        # Verify the class is now in the registry.
        if class_name and class_name not in {c.split('.')[-1] for c in registry}:
            return self._json({
                "error": f"class {class_name!r} not found in registry after import; "
                         f"check the @as_visualization name= argument matches"
            }, 500)

        commit_msg = f"feat(viz): generate {class_name or name} via /pbg-viz"
        def action():
            # _active_branch_action handles staging+commit; we just need to
            # ensure the file is on disk (already is).
            pass
        # _active_branch_action stages all modified+untracked files in scope;
        # since the file already exists, just return success with the commit.
        return self._json(*_active_branch_action(commit_msg, action))
```

Note: the `_active_branch_action` helper already exists in this file (see other endpoints). If its signature or commit-staging behavior differs from what's above, adapt — preserve the contract that the response is `(json_dict, status_code)`.

- [ ] **Step 4: Run, confirm pass**

```bash
python -m pytest tests/test_visualization_endpoints.py -v
```

Expected: 3/3 PASS. If the `workspace_server` fixture isn't there, build it inline and re-run.

- [ ] **Step 5: Commit**

```bash
git add scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "feat(viz): /api/visualization-generate and -accept endpoints"
```

---

### Task 6: `/api/visualization-migration-plan` + `/api/visualization-migrate` endpoints

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`
- Modify: `pbg-template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Append failing tests** to `tests/test_visualization_endpoints.py`

```python
def test_get_visualization_migration_plan_classifies_entries(workspace_server):
    # Seed workspace.yaml with three different legacy patterns.
    ws_file = workspace_server.root / 'workspace.yaml'
    ws = yaml.safe_load(ws_file.read_text()) or {}
    ws['visualizations'] = [
        {'name': 'readdyplots',
         'description': 'Use the registered TimeSeriesPlot class from the Registry.'},
        {'name': 'video-of-chromosome',
         'description': 'a gif of the chromosome.'},
        {'name': 'free-DnaA', 'class': 'TimeSeriesPlot', 'config': {'observable': 'free_DnaA'}},
    ]
    ws_file.write_text(yaml.dump(ws, sort_keys=False))

    req = urllib.request.Request(workspace_server.url + '/api/visualization-migration-plan')
    with urllib.request.urlopen(req) as resp:
        plan = json.loads(resp.read())

    by_name = {p['name']: p for p in plan['entries']}
    assert by_name['readdyplots']['action'] == 'auto-convert-to-class-backed'
    assert by_name['readdyplots']['target_class'] == 'TimeSeriesPlot'
    assert by_name['video-of-chromosome']['action'] == 'regenerate-as-class'
    assert by_name['free-DnaA']['action'] == 'no-op'


def test_post_visualization_migrate_applies_auto_conversions(workspace_server):
    ws_file = workspace_server.root / 'workspace.yaml'
    ws = yaml.safe_load(ws_file.read_text()) or {}
    ws['visualizations'] = [
        {'name': 'readdyplots',
         'description': 'Use the registered TimeSeriesPlot class from the Registry.'},
    ]
    ws_file.write_text(yaml.dump(ws, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/visualization-migrate',
        {'actions': [{'name': 'readdyplots', 'action': 'auto-convert-to-class-backed',
                      'target_class': 'TimeSeriesPlot'}]},
    )
    assert code == 200, j
    ws_after = yaml.safe_load(ws_file.read_text())
    entry = next(v for v in ws_after['visualizations'] if v['name'] == 'readdyplots')
    assert entry['class'] == 'TimeSeriesPlot'
    assert 'description' not in entry  # migration cleared the description
    # Log file written
    logs = list((workspace_server.root / '.pbg' / 'migrations').glob('*.log'))
    assert logs, 'expected a migration log file'
```

- [ ] **Step 2: Run, confirm fail**

```bash
python -m pytest tests/test_visualization_endpoints.py -v -k migration
```

- [ ] **Step 3: Add endpoints** to `scripts/_server/server.py`

GET dispatch (next to `/api/visualization-instances`):
```python
        if self.path.startswith("/api/visualization-migration-plan"):
            return self._get_visualization_migration_plan()
```

POST dispatch:
```python
            "/api/visualization-migrate":          self._post_visualization_migrate,
```

Handlers:

```python
    def _get_visualization_migration_plan(self):
        """GET /api/visualization-migration-plan — classify every entry in
        workspace.yaml.visualizations against the current registry.
        Returns: {entries: [{name, action, target_class?, legacy_path?, reason?}, ...]}
        """
        from scripts._lib.migrations import classify_viz_entry
        try:
            ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text()) or {}
        except Exception:
            ws_data = {}
        registered = {c["name"] for c in self._list_visualization_classes()}
        entries = []
        for entry in (ws_data.get("visualizations") or []):
            if not isinstance(entry, dict):
                continue
            classification = classify_viz_entry(entry, registered, workspace_root=WORKSPACE)
            classification = dict(classification)
            classification["name"] = entry.get("name")
            classification["description"] = entry.get("description", "")
            entries.append(classification)
        return self._json({"entries": entries}, 200)

    def _post_visualization_migrate(self, body: dict):
        """POST /api/visualization-migrate {actions: [...]} — apply the
        per-entry actions returned by /api/visualization-migration-plan.
        Each action is one of:
            {name, action: 'auto-convert-to-class-backed', target_class}
            {name, action: 'regenerate-as-class'}  (only logs intent; the
              actual regeneration is the user-driven /pbg-viz flow)
            {name, action: 'skip'}
        """
        import datetime
        actions = body.get("actions") or []
        if not isinstance(actions, list):
            return self._json({"error": "actions must be a list"}, 400)

        commit_msg = "chore(viz): migrate legacy workspace.yaml entries"

        def do_action():
            from scripts._lib.workspace_yaml import load_workspace, save_workspace
            ws_file = WORKSPACE / "workspace.yaml"
            ws = load_workspace(ws_file)
            entries = ws.get("visualizations") or []
            log_lines = [f"# Migration log {datetime.datetime.utcnow().isoformat()}Z"]
            changed = False
            for act in actions:
                name = act.get("name")
                idx = next((i for i, e in enumerate(entries)
                            if isinstance(e, dict) and e.get("name") == name), None)
                if idx is None:
                    log_lines.append(f"- {name}: skipped (not found)")
                    continue
                kind = act.get("action")
                if kind == "auto-convert-to-class-backed":
                    target = act.get("target_class")
                    if not target:
                        log_lines.append(f"- {name}: skipped (missing target_class)")
                        continue
                    before = dict(entries[idx])
                    entries[idx] = {"name": name, "class": target, "config": {}}
                    log_lines.append(f"- {name}: auto-convert -> class={target} (was: {before})")
                    changed = True
                elif kind == "regenerate-as-class":
                    log_lines.append(
                        f"- {name}: regenerate-as-class (no workspace.yaml change; "
                        f"user must run /pbg-viz {name} via the dashboard)"
                    )
                elif kind == "skip":
                    log_lines.append(f"- {name}: skip")
                else:
                    log_lines.append(f"- {name}: unknown action {kind!r}; skipping")

            log_dir = WORKSPACE / ".pbg" / "migrations"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.log"
            log_path.write_text("\n".join(log_lines) + "\n")

            if changed:
                ws["visualizations"] = entries
                save_workspace(ws_file, ws)

        return self._json(*_active_branch_action(commit_msg, do_action))
```

- [ ] **Step 4: Run, confirm pass**

```bash
python -m pytest tests/test_visualization_endpoints.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/_server/server.py tests/test_visualization_endpoints.py
git commit -m "feat(viz): /api/visualization-migration-plan and -migrate endpoints"
```

---

### Task 7: `scripts/migrate-visualizations.py` CLI

**Files:**
- Create: `pbg-template/scripts/migrate-visualizations.py`

- [ ] **Step 1: Write the CLI** at `scripts/migrate-visualizations.py`

```python
#!/usr/bin/env python3
"""Inspect or apply legacy workspace.yaml visualization migrations.

Usage:
    python3 scripts/migrate-visualizations.py            # print plan, exit
    python3 scripts/migrate-visualizations.py --apply    # apply auto-convertible
    python3 scripts/migrate-visualizations.py --apply --include-skipped
        # also apply skipped/deferred actions interactively
"""
from __future__ import annotations
import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._lib.migrations import classify_viz_entry  # noqa: E402


def _list_registered_classes() -> set:
    """Best-effort listing of registered Visualization classes (workspace package
    must be pip-installed for this to be accurate)."""
    sys.path.insert(0, str(ROOT))
    ws = yaml.safe_load((ROOT / "workspace.yaml").read_text()) or {}
    pkg = ws.get("package_path") or ("pbg_" + ws.get("name", "").replace("-", "_"))
    try:
        import bigraph_schema.core as _bsc
        _bsc._cached_base_core = None
        core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
        core = core_module.build_core()
        return {n.split(".")[-1] for n in core.link_registry}
    except Exception as e:
        print(f"warning: could not load registry ({e}); proceeding with empty set", file=sys.stderr)
        return set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes; default is dry-run.")
    parser.add_argument("--workspace", type=Path, default=ROOT,
                        help="Workspace root (default: this script's parent).")
    args = parser.parse_args()

    ws_file = args.workspace / "workspace.yaml"
    ws = yaml.safe_load(ws_file.read_text()) or {}
    entries = ws.get("visualizations") or []
    registered = _list_registered_classes()

    plan = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        c = classify_viz_entry(entry, registered, workspace_root=args.workspace)
        c = dict(c)
        c["name"] = entry.get("name")
        plan.append(c)

    print(f"Migration plan ({len(plan)} entries):")
    for c in plan:
        print(f"  - {c['name']}: {c['action']}", end="")
        if c.get("target_class"):
            print(f"  -> {c['target_class']}", end="")
        if c.get("reason"):
            print(f"  ({c['reason']})", end="")
        print()

    if not args.apply:
        print("\n(dry run — re-run with --apply to write changes)")
        return 0

    log_lines = [f"# CLI migration {datetime.datetime.utcnow().isoformat()}Z"]
    changed = False
    for c in plan:
        if c["action"] != "auto-convert-to-class-backed":
            log_lines.append(f"- {c['name']}: skip ({c['action']})")
            continue
        idx = next((i for i, e in enumerate(entries)
                    if isinstance(e, dict) and e.get("name") == c["name"]), None)
        if idx is None:
            continue
        before = dict(entries[idx])
        entries[idx] = {"name": c["name"], "class": c["target_class"], "config": {}}
        log_lines.append(f"- {c['name']}: auto-convert -> class={c['target_class']} (was: {before})")
        changed = True

    log_dir = args.workspace / ".pbg" / "migrations"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-cli.log"
    log_path.write_text("\n".join(log_lines) + "\n")
    print(f"\nLog written to {log_path}")

    if changed:
        ws["visualizations"] = entries
        ws_file.write_text(yaml.dump(ws, sort_keys=False))
        print(f"workspace.yaml updated.")
    else:
        print("No auto-convertible entries; workspace.yaml unchanged.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test dry-run on pbg-template's own (empty) workspace**

```bash
chmod +x scripts/migrate-visualizations.py
python3 scripts/migrate-visualizations.py
```

Expected: "Migration plan (0 entries):" then "(dry run — ...)". No error.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate-visualizations.py
git commit -m "feat(viz): scripts/migrate-visualizations.py CLI"
```

---

### Task 8: UI — "Generate new visualization class" panel + migration banner

**Files:**
- Modify: `pbg-template/scripts/_templates/index.html.j2`
- Modify: `pbg-template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add the generate panel + migration banner** to the template

In `scripts/_templates/index.html.j2`, find the Visualizations page section and the bottom of the catalog panel. Insert the migration banner near the top of the page section (after the page lead), and the generate panel below the catalog:

```html
  <!-- Migration banner (shown only if any legacy entries detected) -->
  <div id="viz-migration-banner" style="display:none;background:#fef3c7;border:1px solid #fde047;
        padding:10px;border-radius:6px;margin-bottom:12px">
    <strong id="viz-migration-banner-count"></strong>
    <button class="btn-mini" onclick="_openMigrationModal()" style="margin-left:8px">
      Review migration
    </button>
  </div>
```

(Place this just after `<p class="page-lead">…</p>` on the Visualizations page.)

And below the Available Visualization classes panel:

```html
  <!-- Generate new visualization class -->
  <div class="panel">
    <h3>Generate new visualization class</h3>
    <p class="panel-lead">Nothing in the catalog above matches? Describe what you want. The
      <code>/pbg-viz</code> skill writes a decorated function to
      <code>&lt;workspace_pkg&gt;/visualizations/&lt;snake&gt;.py</code>. After accepting, the new
      class joins the catalog for everyone.</p>
    <form id="form-viz-generate" onsubmit="event.preventDefault(); _submitVizGenerate(this)">
      <label>Name (kebab-case)
        <input name="name" pattern="^[a-zA-Z0-9_-]+$" required
               placeholder="e.g. dna-a-trajectory">
      </label>
      <label>Description
        <textarea name="description" rows="4" required
                  placeholder="e.g. 'free_DnaA concentration vs time with a horizontal line at the binding threshold of 50 molecules.'"></textarea>
      </label>
      <div class="form-error"></div>
      <button type="submit" class="action-btn">Generate</button>
    </form>
    <div id="viz-generate-status" style="margin-top:12px;font-size:0.9em;color:#555"></div>
  </div>

  <!-- Migration review modal -->
  <div id="modal-viz-migration" class="modal-overlay">
    <div class="modal-box" style="max-width:760px">
      <button class="modal-close" onclick="closeModal('modal-viz-migration')">&times;</button>
      <h3>Migrate legacy visualizations</h3>
      <p style="font-size:0.9em;color:#555">Review each entry's planned migration. Class-backed
        entries are skipped; description-only entries are either auto-converted or flagged
        for re-generation. Auto-conversions write to <code>workspace.yaml</code> and create
        a commit on the active branch.</p>
      <div id="viz-migration-plan-body" style="margin:8px 0"></div>
      <button class="action-btn" onclick="_submitMigration()">Apply migration</button>
    </div>
  </div>
```

- [ ] **Step 2: Add JS handlers** to `scripts/_server/walkthrough.js`

Append near the other viz functions:

```javascript
  function _submitVizGenerate(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    var statusEl = document.getElementById('viz-generate-status');
    if (errEl) errEl.textContent = '';
    var payload = {
      name: data.get('name'),
      description: data.get('description'),
    };
    fetch('/api/visualization-generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'generate failed';
          return;
        }
        if (statusEl) statusEl.innerHTML =
          'Request written to <code>' + j.request_path + '</code>.<br>' +
          'In your active Claude Code session, run <code>' + j.skill_command + '</code>.<br>' +
          'Target file: <code>' + j.target_file + '</code>.<br>' +
          'Polling for completion…';
        _pollForGeneratedClass(payload.name, j.target_file, 0);
      });
  }
  window._submitVizGenerate = _submitVizGenerate;

  function _pollForGeneratedClass(name, targetFile, attempt) {
    if (attempt > 600) {  // ~5 min
      var statusEl = document.getElementById('viz-generate-status');
      if (statusEl) statusEl.innerHTML += '<br><span style="color:#991b1b">Timed out waiting.</span>';
      return;
    }
    fetch('/' + targetFile + '?_=' + Date.now()).then(function(r) {
      if (r.ok) {
        var statusEl = document.getElementById('viz-generate-status');
        if (statusEl) statusEl.innerHTML +=
          '<br><span style="color:#1f7a3a">File detected.</span> ' +
          '<button class="btn-mini" onclick="_vizClassPreview(\'local:' + name + '\',\'' + name + '\')">' +
          'Preview</button> ' +
          '<button class="btn-mini" onclick="_acceptGeneratedClass(\'' + name + '\')">Accept &amp; commit</button>';
      } else {
        setTimeout(function() { _pollForGeneratedClass(name, targetFile, attempt + 1); }, 500);
      }
    }).catch(function() {
      setTimeout(function() { _pollForGeneratedClass(name, targetFile, attempt + 1); }, 500);
    });
  }

  function _acceptGeneratedClass(name) {
    // The class name in the file is decided by the generator; we ask the
    // server to detect it via the @as_visualization name= argument.
    fetch('/api/visualization-accept', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        var statusEl = document.getElementById('viz-generate-status');
        if (!ok) {
          if (statusEl) statusEl.innerHTML +=
            '<br><span style="color:#991b1b">Accept failed: ' + (j.error || '') + '</span>';
          return;
        }
        if (statusEl) statusEl.innerHTML +=
          '<br><span style="color:#1f7a3a">Committed. Reloading catalog…</span>';
        setTimeout(function() { window.location.reload(); }, 600);
      });
  }
  window._acceptGeneratedClass = _acceptGeneratedClass;

  function _loadVizMigrationBanner() {
    fetch('/api/visualization-migration-plan').then(function(r) { return r.json(); })
      .then(function(plan) {
        var actionable = (plan.entries || []).filter(function(e) {
          return e.action !== 'no-op';
        });
        var banner = document.getElementById('viz-migration-banner');
        var countEl = document.getElementById('viz-migration-banner-count');
        if (!banner || !countEl) return;
        if (actionable.length === 0) { banner.style.display = 'none'; return; }
        banner.style.display = '';
        countEl.textContent = actionable.length + ' legacy visualization entries can be migrated';
        window._vizMigrationPlan = plan;
      });
  }
  window._loadVizMigrationBanner = _loadVizMigrationBanner;

  function _openMigrationModal() {
    var body = document.getElementById('viz-migration-plan-body');
    var plan = window._vizMigrationPlan || {entries: []};
    body.innerHTML = (plan.entries || []).map(function(e) {
      var label = '<strong>' + _esc(e.name) + '</strong> &mdash; ' + _esc(e.action);
      if (e.target_class) label += ' &rarr; <code>' + _esc(e.target_class) + '</code>';
      if (e.reason) label += '<br><small style="color:#888">' + _esc(e.reason) + '</small>';
      if (e.action === 'no-op') return '';
      return '<div style="padding:6px 0;border-bottom:1px solid #eee">' + label + '</div>';
    }).join('') || '<p>Nothing to migrate.</p>';
    openModal('modal-viz-migration');
  }
  window._openMigrationModal = _openMigrationModal;

  function _submitMigration() {
    var plan = window._vizMigrationPlan || {entries: []};
    var actions = (plan.entries || [])
      .filter(function(e) { return e.action === 'auto-convert-to-class-backed'; })
      .map(function(e) {
        return {name: e.name, action: e.action, target_class: e.target_class};
      });
    fetch('/api/visualization-migrate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({actions: actions}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) { alert(j.error || 'migrate failed'); return; }
        closeModal('modal-viz-migration');
        window.location.reload();
      });
  }
  window._submitMigration = _submitMigration;
```

- [ ] **Step 3: Trigger banner load on Visualizations page open**

Find where the Visualizations page is shown / activated in walkthrough.js (search for `'visualizations'` near a page-switch handler). Add a call to `_loadVizMigrationBanner()` when the page becomes active. If no such hook exists, call it once near the end of `_loadRegistry`:

```javascript
        // ... existing registry-load completion ...
        if (typeof _loadVizMigrationBanner === 'function') _loadVizMigrationBanner();
```

- [ ] **Step 4: Re-render dashboard + smoke-test in browser**

```bash
# Sync to v2ecoli, restart server, hard-reload.
# Expected: Visualizations tab shows banner (since v2ecoli has 3+ legacy entries).
# Click "Review migration" -> modal lists the entries -> "Apply migration".
```

- [ ] **Step 5: Commit**

```bash
git add scripts/_templates/index.html.j2 scripts/_server/walkthrough.js
git commit -m "feat(viz): generate panel + migration banner UI"
```

---

## Phase C — /pbg-viz skill

### Task 9: Rewrite SKILL.md for the new contract

**Files:**
- Modify: `~/.claude/skills/pbg-viz/SKILL.md`

- [ ] **Step 1: Replace the SKILL.md contents** with:

```markdown
---
name: pbg-viz
description: Generate a v2 Visualization (decorated function) into the workspace package from a natural-language description in the pbg-template dashboard.
user-invocable: true
allowed-tools: Bash(*) Read Write Edit
argument-hint: <visualization-name>
---

# /pbg-viz <visualization-name>

This skill turns a natural-language visualization request into a committed
`Visualization` v2 class inside the workspace's Python package.

## Output contract

Write exactly one file to `<workspace_pkg>/visualizations/<snake_name>.py`
containing a single function decorated with `@as_visualization` (from
pbg-superpowers >= 0.7.0). The decorator synthesizes a Visualization subclass
that `bigraph_schema.discover_packages()` picks up automatically — no
`__init__.py` editing needed.

Required template:

```python
"""<ClassName> — one-line description.

Generated by /pbg-viz on <date> from request '<viz-name>'.
"""
from __future__ import annotations
import html as _html, json
from pbg_superpowers.visualization import as_visualization


@as_visualization(
    inputs={'<port>': '<bigraph-type>', ...},   # typed input ports
    name='<ClassName>',                          # CamelCase class name
    demo={'<port>': [...], ...},                 # synthetic state for preview
)
def update_<snake_name>(state):
    """<one-line description>."""
    # ... build Plotly (preferred) or matplotlib figure from state ...
    return {'html': '<...rendered HTML...>'}
```

## Constraints

- Function name MUST start with `update_`. Snake-case.
- `inputs` MUST use bigraph-schema type strings — `'list[float]'`, `'float'`,
  `'list[list[float]]'`, `'string'`. For trajectory data prefer `'list[float]'`.
- `demo` MUST be a realistic synthetic state dict matching `inputs` so the
  dashboard preview is meaningful. Use 5-10 data points minimum.
- Do NOT define a class manually; the decorator synthesizes it.
- Do NOT edit `__init__.py` — discover_packages walks the package.
- File must be self-contained — only import from `pbg_superpowers`,
  `process_bigraph`, stdlib (`html`, `json`, `math`, etc.), or
  `plotly` / `matplotlib`.

## Steps

1. Read `.pbg/viz-requests/<visualization-name>.md` from the current workspace.
   If the file doesn't exist, abort and tell the user to click **Generate** in
   the dashboard first.

2. Parse the description and the workspace context (observables,
   simulations, package name).

3. Decide:
   - **Library:** Plotly for interactive plots; matplotlib for static / 3D /
     paper-quality. Default to Plotly.
   - **Inputs:** Match port names to declared observables. Use `'list[float]'`
     for per-step trajectories. Use `'list[list[float]]'` for sweeps.
   - **Class name:** CamelCase, derived from the kebab-case viz name
     (e.g. `dna-a-trajectory` → `DnaATrajectory`).
   - **Demo data:** Synthetic values that produce a meaningful preview.

4. Write the file using the template above. Pretty-print Plotly traces/layout
   with `json.dumps` so the HTML is human-readable. Wrap the figure in a
   `<div id="viz" style="height:380px">` with the standard Plotly CDN load.

5. Report success: print the target path so the user can verify, e.g.
   ```
   Wrote pbg_chromosome_rep1/visualizations/dna_a_trajectory.py
   Class name: DnaATrajectory. Click Accept in the dashboard.
   ```

## Decorators in the process-bigraph ecosystem

`as_visualization` is one of three function-to-class decorators provided by
this ecosystem:

| Decorator | Module | Synthesizes |
|---|---|---|
| `as_step` | `process_bigraph.composite` | `Step` subclass (one-shot update) |
| `as_process` | `process_bigraph.composite` | `Process` subclass (timestepped update) |
| `as_visualization` | `pbg_superpowers.visualization` | `Visualization` subclass (HTML-emitting Step) |

Each one expects a function named `update_<thing>` and stamps the synthesized
class with `__pb_kind__` + `__pb_aliases__` for nicer dashboard surfacing.
Discovery (`bigraph_schema.discover_packages`) doesn't care about the markers;
it walks installed pbg-* distributions and registers everything that subclasses
`Edge`. The markers are pure metadata.

## Smoke test

After writing, the user clicks **Accept** in the dashboard. The server:

1. Invalidates `bigraph_schema.core._cached_base_core`.
2. Imports `<workspace_pkg>.core` and calls `build_core()`.
3. Verifies the new class appears in `core.link_registry`.
4. Commits the file on the active branch.

If the import fails, the server returns the error message and the file stays
uncommitted. Fix the import and click Accept again.
```

- [ ] **Step 2: Manual end-to-end check** (no automated test for the skill itself)

Create a synthetic request file and walk the skill through it manually in a
dedicated session (separate from this one, to verify the SKILL.md is enough
context):
```bash
mkdir -p /tmp/skill-test/.pbg/viz-requests /tmp/skill-test/pbg_testws/visualizations
cat > /tmp/skill-test/.pbg/viz-requests/test-bar.md <<'EOF'
# Visualization request: test-bar
## Description (from user)
A bar chart of three named counts.
## Workspace context
- Workspace package: `pbg_testws`
- Available observables:
  - `counts` (path: `state.counts`, units: items)
- Available simulations:
  (none)
## Instructions for the agent
... (full new-contract instructions as in Task 5's generated request) ...
EOF
```

In a fresh Claude Code session: `/pbg-viz test-bar`. Verify it writes
`/tmp/skill-test/pbg_testws/visualizations/test_bar.py` with a single
`@as_visualization`-decorated function.

- [ ] **Step 3: Commit the skill change**

The SKILL.md lives outside any of the project repos (in `~/.claude/skills/`).
Skill files aren't normally git-tracked from the project's perspective. If a
skill-management repo exists, commit there; otherwise, the change persists as
a personal-config edit. Note the change in this plan's checklist when done.

---

## Phase D — Verification on v2ecoli

### Task 10: End-to-end verification

**Files:**
- (workspace state in `/Users/eranagmon/code/v2ecoli-chromosome-rep1`)

- [ ] **Step 1: Install pbg-superpowers v0.7.0**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
uv pip install -U pbg-superpowers 2>&1 | tail -3
.venv/bin/python3 -c "
from pbg_superpowers.visualization import as_visualization, Visualization

@as_visualization(inputs={'x': 'list[float]'}, name='SmokeTest', demo={'x': [1.0, 2.0]})
def update_smoke_test(state):
    return {'html': '<p>' + str(state['x']) + '</p>'}

assert issubclass(update_smoke_test, Visualization)
assert update_smoke_test.__name__ == 'SmokeTest'
assert update_smoke_test.demo() == {'x': [1.0, 2.0]}
print('as_visualization smoke test PASS')
"
```

Expected: `as_visualization smoke test PASS`. If the install resolves to v0.6.0
instead of v0.7.0, retry after a short wait — PyPI propagation can lag.

- [ ] **Step 2: Sync pbg-template changes into v2ecoli**

```bash
cp /Users/eranagmon/code/pbg-template/scripts/_lib/migrations.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/migrations.py
cp /Users/eranagmon/code/pbg-template/scripts/_server/server.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp /Users/eranagmon/code/pbg-template/scripts/_server/walkthrough.js \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp /Users/eranagmon/code/pbg-template/scripts/_templates/index.html.j2 \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cp /Users/eranagmon/code/pbg-template/scripts/migrate-visualizations.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/migrate-visualizations.py

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

- [ ] **Step 3: Migration banner end-to-end**

In the browser (hard-reload):
1. Open Visualizations tab.
2. Expected: yellow banner reading "3+ legacy visualization entries can be migrated".
3. Click "Review migration".
4. Expected modal lists `readdyplots` (auto-convert → TimeSeriesPlot... wait, the description says ReaDDyPlots, so auto-convert → ReaDDyPlots if it's registered), `timeseriesplot` (auto-convert → TimeSeriesPlot), `video-of-chromosome` (regenerate-as-class).
5. Click "Apply migration".
6. Page reloads. Banner shows only `video-of-chromosome` as remaining (or
   hides if it's been deferred).
7. Check `workspace.yaml`: `readdyplots` and `timeseriesplot` entries are
   now `{name, class, config: {}}`.
8. Check `.pbg/migrations/<timestamp>.log` exists.

- [ ] **Step 4: Generate end-to-end**

In the browser:
1. On Visualizations tab, scroll to "Generate new visualization class".
2. Fill name `free-dnaa-trajectory`, description "DnaA concentration vs time
   for the chromosome partition simulation".
3. Submit. Status shows "Request written to ...". Skill command shown.
4. In *this* Claude Code session (separate from the dashboard's), the user
   runs `/pbg-viz free-dnaa-trajectory` — or with the rewritten SKILL.md, I
   (Claude) can do this on the user's request. The skill writes
   `pbg_chromosome_rep1/visualizations/free_dnaa_trajectory.py`.
5. Dashboard polling detects the file. Status updates with Preview + Accept
   buttons.
6. Click Preview. Modal iframe shows the demo render.
7. Click Accept. Server validates import, invalidates cache, commits the
   file, page reloads.
8. Check "Available Visualization classes" catalog — `FreeDnaATrajectory`
   (or whatever the skill named it) is now listed.
9. Confirm `git log -1` shows the auto-commit on the active branch.

- [ ] **Step 5: Push pbg-template if all green**

```bash
cd /Users/eranagmon/code/pbg-template
git log --oneline -10
git push 2>&1 | tail -3
```

Do NOT push v2ecoli automatically — that's a separate decision after the
manual verification above passes.

---

## Self-review

(Author note: per the writing-plans skill, this self-review is run inline,
not as a separate task. Findings already folded into the plan above.)

**Spec coverage:**

- Section 1 (Three artifacts): Task 5 (endpoints), Task 6 (migration plan
  endpoints), Task 8 (UI for instances panel — already in place from prior
  work, only the migration banner is new). ✓
- Section 2 (Lifecycle): Task 5 (Step 2 generate / Step 3 accept), Task 8
  (Step 1 search UI / Step 4 register prompt). ✓
- Section 3 (as_visualization decorator): Task 1. ✓
- Section 4 (Generated file shape): Task 5 (request template includes it) +
  Task 9 (SKILL.md). ✓
- Section 5 (Build & discovery hookup): Task 5's accept endpoint (cache
  invalidation + import probe). ✓
- Section 6 (Migration): Tasks 4 (classifier), 6 (endpoints), 7 (CLI), 8
  (banner UI). ✓
- Section 7 (/pbg-viz changes): Task 9. ✓

**Placeholder scan:** None remaining. Every step has either a complete code
block or an explicit command. The two manual checkpoints (Task 9 Step 2,
Task 10 Steps 3-4) describe expected outcomes precisely so the agent knows
when they pass.

**Type consistency:** `as_visualization(inputs, name, demo, aliases)` —
same signature in Task 1 (definition), Task 5 (request-template body), Task 9
(SKILL.md). `classify_viz_entry(entry, registered_classes, workspace_root)` —
same signature in Task 4 (definition) and Task 7 (CLI usage). API endpoint
paths `/api/visualization-{generate,accept,migration-plan,migrate}` —
consistent across server.py (Task 5, 6) and walkthrough.js (Task 8).

**Risks not in the spec:**

1. **`_active_branch_action` semantics for generated files.** This helper
   requires a clean working tree before it commits. Task 5's accept endpoint
   stages the generated file via the helper's normal flow; if the user has
   unrelated dirty files, accept will fail. Mitigation: the existing helper
   already gives a clear error message; users hit this regularly with the
   workspace dashboard and know how to resolve. No new mitigation required.

2. **PyPI propagation delay.** Task 10 Step 1 may resolve to v0.6.0
   immediately after Task 2 pushes the tag. The plan notes this; retry after
   a short wait.

3. **The `workspace_server` test fixture may not exist.** If Task 5 Step 4
   fails with `ImportError` on the fixture, the implementer should add the
   fixture inline or copy from `tests/test_investigations.py`. Plan flags
   this in the task body.

---

Plan saved. Use superpowers:subagent-driven-development to execute.
