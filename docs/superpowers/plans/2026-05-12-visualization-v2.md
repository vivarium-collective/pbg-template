# Visualization v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `render_final` Visualization contract with `update(state)` only, persist the emitter schema upstream in `SQLiteEmitter`, and dispatch Investigation visualizations via small composites so process-bigraph's type system validates the wiring. Adding a visualization to an investigation that already has runs re-renders without re-running.

**Architecture:** Three repos touched in dependency order — process-bigraph (PR, not direct push) → pbg-superpowers (Visualization v2 + 5 default rewrites + PyPI release) → pbg-template (orchestrator refactor + new render-viz endpoint + frontend tweak). Spec at `docs/superpowers/specs/2026-05-12-visualization-v2-design.md`.

**Tech Stack:** Python 3.11+, sqlite3, process-bigraph (Composite + Step + bigraph-schema types), Plotly via CDN, vanilla JS.

**File structure:**

| File | Action | Responsibility |
|---|---|---|
| `process-bigraph/process_bigraph/emitter.py` | modify | `_init_history_db` + `save_simulation_metadata` + `load_emit_schema` |
| `process-bigraph/tests/test_emitter_sqlite.py` (or similar) | modify | 3 new tests for emit_schema persistence |
| `pbg-superpowers/pbg_superpowers/visualization.py` | modify | Drop `render_final`/`supports_streaming`; sole `update(state)` |
| `pbg-superpowers/pbg_superpowers/visualizations/{time_series,param_vs_observable,distribution,phase_space,heatmap}.py` | rewrite | Each implements typed `inputs()` + `update(state)` |
| `pbg-superpowers/tests/test_default_visualizations.py` | rewrite | One test per default class against new contract |
| `pbg-template/scripts/_lib/investigations.py` | modify | New: `gather_emitter_outputs`, `build_viz_composite`, rewritten `render_visualizations` |
| `pbg-template/scripts/_server/server.py` | modify | New endpoint `POST /api/investigation-render-viz` |
| `pbg-template/scripts/_server/walkthrough.js` | modify | `_submitAddViz` chains a render-viz call after spec write |
| `pbg-template/tests/test_investigations.py` | modify | New tests for gather/build/render |

---

### Task 1: process-bigraph — `emit_schema` column + persistence

**Files:**
- Modify: `process_bigraph/emitter.py`
- Modify or create: `process_bigraph/tests/test_emitter_sqlite.py`

**Branch:** `feat/sqlite-emitter-schema-persistence`

- [ ] **Step 1: Create feature branch + write failing tests**

```bash
cd /Users/eranagmon/code/process-bigraph
git checkout -b feat/sqlite-emitter-schema-persistence
```

Find the existing emitter tests (likely `tests/test_emitter_sqlite.py` or `tests/test_sqlite.py`). If none exist for SQLiteEmitter, create `tests/test_emitter_sqlite_schema.py`:

```python
"""Tests for SQLiteEmitter emit_schema persistence."""
import json
from pathlib import Path

import pytest

from process_bigraph import allocate_core
from process_bigraph.emitter import SQLiteEmitter, load_emit_schema


def _make_emitter(tmp_path, simulation_id='sim-1', emit=None):
    core = allocate_core()
    config = {
        'emit': emit or {'level': 'float'},
        'file_path': str(tmp_path),
        'db_file': 'history.db',
        'simulation_id': simulation_id,
    }
    return SQLiteEmitter(config=config, core=core)


def test_sqlite_emitter_persists_schema(tmp_path):
    emitter = _make_emitter(tmp_path, emit={'level': 'float', 'time': 'float'})
    db = tmp_path / 'history.db'
    schema = load_emit_schema(str(db), 'sim-1')
    assert schema == {'level': 'float', 'time': 'float'}


def test_load_emit_schema_returns_empty_for_missing_run(tmp_path):
    _make_emitter(tmp_path, simulation_id='sim-1')
    db = tmp_path / 'history.db'
    assert load_emit_schema(str(db), 'no-such-sim') == {}


def test_load_emit_schema_returns_empty_when_db_missing(tmp_path):
    db = tmp_path / 'never-created.db'
    assert load_emit_schema(str(db), 'sim-1') == {}
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
cd /Users/eranagmon/code/process-bigraph
python -m pytest tests/test_emitter_sqlite_schema.py -v
```

Expected: ImportError on `load_emit_schema` or column-missing SQL error.

- [ ] **Step 3: Add `emit_schema` column to `simulations` table**

Open `process_bigraph/emitter.py`. Find `_init_history_db` (around line 302). After the existing migration block:

```python
    # Migrate older dbs that predate completed_at / elapsed_seconds.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(simulations)")}
    if 'completed_at' not in existing:
        conn.execute('ALTER TABLE simulations ADD COLUMN completed_at TEXT')
    if 'elapsed_seconds' not in existing:
        conn.execute('ALTER TABLE simulations ADD COLUMN elapsed_seconds REAL')
```

Add:

```python
    if 'emit_schema' not in existing:
        conn.execute('ALTER TABLE simulations ADD COLUMN emit_schema TEXT')
```

And include `emit_schema` in the initial `CREATE TABLE`:

```python
    conn.execute('''
        CREATE TABLE IF NOT EXISTS simulations (
            simulation_id TEXT PRIMARY KEY,
            name TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            elapsed_seconds REAL,
            composite_config TEXT,
            metadata TEXT,
            emit_schema TEXT
        )
    ''')
```

- [ ] **Step 4: Persist schema in `SQLiteEmitter.__init__`**

Find `SQLiteEmitter.__init__` (around line 535). After the existing `_init_history_db(self._conn)` call:

```python
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        _init_history_db(self._conn)

        # NEW: persist emit_schema for this simulation_id (idempotent upsert)
        emit_schema = config.get('emit') or {}
        if emit_schema:
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            self._conn.execute(
                'INSERT INTO simulations '
                '(simulation_id, started_at, emit_schema) '
                'VALUES (?, ?, ?) '
                'ON CONFLICT(simulation_id) DO UPDATE SET '
                '  emit_schema = excluded.emit_schema',
                (self.simulation_id, now_iso, json.dumps(emit_schema, default=_json_default)),
            )

        name = config.get('name')
```

Verify `datetime` and `json` are already imported at module top (they are, per the existing `save_simulation_metadata` implementation).

- [ ] **Step 5: Add `load_emit_schema` helper**

Below `save_simulation_metadata` (around line 367 in current source), add:

```python
def load_emit_schema(db_path, simulation_id) -> dict:
    '''Return the recorded emit schema for one simulation, or {} if missing.

    The schema is whatever was passed as the ``emit`` config to SQLiteEmitter:
    a mapping of port name → bigraph-schema type string. Returns an empty
    dict when the db file doesn't exist, or when no row matches the
    simulation_id, or when the emit_schema column is NULL.
    '''
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        _init_history_db(conn)  # ensures column exists for legacy DBs
        row = conn.execute(
            'SELECT emit_schema FROM simulations WHERE simulation_id = ?',
            (simulation_id,),
        ).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return {}
    finally:
        conn.close()
```

Export it: add `load_emit_schema` to the module's `__all__` if one exists; otherwise it's auto-importable.

- [ ] **Step 6: Run tests, confirm pass**

```bash
python -m pytest tests/test_emitter_sqlite_schema.py -v
```

Expected: 3 PASS.

Also run the rest of process-bigraph's tests to confirm no regression:

```bash
python -m pytest tests/ 2>&1 | tail -10
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add process_bigraph/emitter.py tests/test_emitter_sqlite_schema.py
git commit -m "$(cat <<'EOF'
feat(SQLiteEmitter): persist emit schema to simulations.emit_schema

Adds an emit_schema TEXT column to the simulations table and writes
SQLiteEmitter.config['emit'] there at init time (idempotent upsert).
New helper load_emit_schema(db_path, simulation_id) -> dict returns
the parsed schema (or {} for missing runs / missing column / null
cell). Downstream consumers (the Investigations dashboard, post-hoc
visualization dispatch) can now introspect what observables a run
emits and their types without inferring from data rows.

Backwards-compatible: existing DBs auto-migrate via the ALTER TABLE
block in _init_history_db.
EOF
)"
```

- [ ] **Step 8: Push branch + open PR**

```bash
git push origin feat/sqlite-emitter-schema-persistence 2>&1 | tail -3
gh pr create --title "feat(SQLiteEmitter): persist emit schema to simulations table" \
  --body "$(cat <<'EOF'
## Summary

Adds an `emit_schema TEXT` column to the SQLite emitter's `simulations` table
and persists the emitter's `emit` config there at init time. New helper
`load_emit_schema(db_path, simulation_id) -> dict` returns the parsed schema
without instantiating an Emitter.

## Motivation

Downstream tooling (process-bigraph workspaces using the Investigations
dashboard) need to introspect what observables a recorded run emits and
their types — to type-check post-hoc visualizations against the data, render
the right plots, and surface errors when a visualization expects an
observable the run didn't emit. Today they have to infer schema from the
first history row, which is fragile (string-typed observables look the same
as JSON-stringified scalars; map-typed observables are hard to distinguish
from nested state). Persisting the schema at init time gives downstream
consumers a single source of truth.

## What changed

- `_init_history_db`: `simulations` table grows an `emit_schema TEXT`
  column. ALTER TABLE migration for existing DBs follows the existing
  `completed_at` / `elapsed_seconds` pattern.
- `SQLiteEmitter.__init__`: after schema bootstrap, writes
  `config.get('emit')` as JSON into the row for its `simulation_id`,
  via `INSERT ... ON CONFLICT DO UPDATE`.
- New module-level helper `load_emit_schema(db_path, simulation_id) -> dict`.

## Test plan

- [x] `test_sqlite_emitter_persists_schema` — round-trips a 2-key schema.
- [x] `test_load_emit_schema_returns_empty_for_missing_run` — unknown
      simulation_id returns `{}`.
- [x] `test_load_emit_schema_returns_empty_when_db_missing` — missing
      file returns `{}`.
- [x] Existing emitter tests pass.

No API changes to existing entry points — purely additive.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -5
```

Wait for the user to review + merge the PR. **Don't merge it yourself.** Report the PR URL.

---

### Task 2: pbg-superpowers — Visualization v2 base + tests

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualization.py`
- Modify: `pbg-superpowers/tests/test_visualization.py`

Working dir: `/Users/eranagmon/code/pbg-superpowers`. Branch: whatever is active (likely `feat/composite-generator-convention`).

- [ ] **Step 1: Rewrite test file**

Replace the existing `tests/test_visualization.py` contents with:

```python
"""Tests for pbg_superpowers.visualization.Visualization (v2: update(state) only)."""
import pytest

from process_bigraph import Step
from pbg_superpowers.visualization import Visualization


class _Echo(Visualization):
    """Test subclass that echoes the input as html."""

    def inputs(self):
        return {'msg': 'string'}

    def update(self, state):
        return {'html': '<p>' + state.get('msg', '') + '</p>'}


def test_visualization_is_step_subclass():
    assert issubclass(Visualization, Step)


def test_visualization_base_update_raises_not_implemented():
    inst = object.__new__(Visualization)
    with pytest.raises(NotImplementedError, match='update'):
        inst.update({})


def test_visualization_outputs_default_html():
    inst = object.__new__(Visualization)
    assert inst.outputs() == {'html': 'string'}


def test_visualization_inputs_default_empty():
    inst = object.__new__(Visualization)
    assert inst.inputs() == {}


def test_subclass_update_returns_html_dict():
    inst = object.__new__(_Echo)
    out = inst.update({'msg': 'hello'})
    assert out == {'html': '<p>hello</p>'}


def test_visualization_marker_classmethod():
    assert _Echo.is_visualization() is True
```

- [ ] **Step 2: Confirm fail**

```bash
cd /Users/eranagmon/code/pbg-superpowers
python -m pytest tests/test_visualization.py -v
```

Expected: tests fail (base `update` doesn't raise; some old tests don't match the new shape).

- [ ] **Step 3: Rewrite `pbg_superpowers/visualization.py`**

```python
"""Visualization Step base class — single contract: update(state) → {'html': str}.

Visualization is a process_bigraph.Step. Subclasses declare typed input ports
via ``inputs()`` and produce HTML via ``update(state)``. The bigraph runtime
type-checks the wiring when the Visualization is placed inside a Composite.

Two use modes both call the same ``update`` method:

1. **Streaming** — wired into a user's simulation Composite. ``update(state)``
   is called once per step with a per-step state dict; the Visualization
   accumulates internally and produces a fresh HTML each step.

2. **Post-hoc dispatch** — used by the Investigations dashboard. The
   orchestrator builds a small Composite per visualization with an input
   store pre-populated from the SQLiteEmitter's recorded trajectory, the
   Visualization Step wired to that store, and an output store of type
   ``'string'``. ``composite.run(1)`` fires ``update(state)`` once; the HTML
   is written to ``investigations/<name>/viz/<viz>.html``.

Discovery: Visualization extends Step extends Edge, so subclasses are
auto-discovered via ``bigraph_schema.package.discover`` and registered in
``core.link_registry``.
"""
from __future__ import annotations
from typing import Any

from process_bigraph import Step


class Visualization(Step):
    """Base class for renderable Visualization Steps.

    Subclasses MUST implement ``update(state) -> {'html': str}`` and SHOULD
    override ``inputs()`` to declare typed input ports using the bigraph-
    schema type system (e.g., ``{'level': 'list[float]'}``).
    """

    config_schema = {
        'title': {'_type': 'string', '_default': ''},
    }

    def inputs(self) -> dict[str, Any]:
        """Typed input ports — keys are port names; values are bigraph-schema
        type strings. Subclasses override.
        """
        return {}

    def outputs(self) -> dict[str, Any]:
        """All visualizations expose a single ``html`` string port."""
        return {'html': 'string'}

    def update(self, state: dict) -> dict:
        """Consume the input state and return ``{'html': '<rendered>'}``."""
        raise NotImplementedError(
            f'{type(self).__name__} must implement update(state) -> '
            f"{{'html': str}}."
        )

    @classmethod
    def is_visualization(cls) -> bool:
        """Marker for dashboard filtering: distinguishes viz Steps from Emitters."""
        return True
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
python -m pytest tests/test_visualization.py -v
```

Expected: 6/6 pass.

- [ ] **Step 5: Commit**

```bash
git add pbg_superpowers/visualization.py tests/test_visualization.py
git commit -m "feat: Visualization v2 — single update(state) contract; drop render_final + supports_streaming"
```

---

### Task 3: Rewrite `TimeSeriesPlot` for v2

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/time_series.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Replace `tests/test_default_visualizations.py` contents**

```python
"""Tests for the 5 default Visualization classes (v2: update(state))."""
from pbg_superpowers.visualizations import TimeSeriesPlot


def _trajectory_state():
    """One run's trajectory of ``level`` and ``time``."""
    return {
        'level': [1.0, 2.0, 4.0, 8.0],
        'time': [0.0, 1.0, 2.0, 3.0],
    }


def _multi_run_state():
    """Two runs' trajectories — orchestrator passes list-of-lists for sweeps."""
    return {
        'level': [[1.0, 2.0, 4.0], [3.0, 6.0, 12.0]],
        'time': [[0.0, 1.0, 2.0], [0.0, 1.0, 2.0]],
        '_run_labels': ['rate=1.0', 'rate=3.0'],  # set by orchestrator
    }


def test_time_series_plot_single_run():
    inst = object.__new__(TimeSeriesPlot)
    inst.config = {'title': 'Test'}
    html = inst.update(_trajectory_state())
    assert 'html' in html
    assert 'Plotly.newPlot' in html['html']
    assert 'Test' in html['html']


def test_time_series_plot_multi_run():
    inst = object.__new__(TimeSeriesPlot)
    inst.config = {'title': ''}
    html = inst.update(_multi_run_state())
    assert 'Plotly.newPlot' in html['html']
    # Two lines for two runs
    assert 'rate=1.0' in html['html']
    assert 'rate=3.0' in html['html']
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest tests/test_default_visualizations.py -v
```

Expected: assertion failures (existing TimeSeriesPlot uses render_final, not update).

- [ ] **Step 3: Replace `pbg_superpowers/visualizations/time_series.py`**

```python
"""TimeSeriesPlot — observable(s) vs time, one line per run."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


_PALETTE = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b',
            '#8b5cf6', '#06b6d4', '#84cc16', '#ec4899']


class TimeSeriesPlot(Visualization):
    """Plot one or more observables vs time.

    Inputs (declared types):
      observable: list[float]   — trajectory values, or list-of-lists for multi-run
      time:       list[float]   — same shape as observable

    Config:
      title: str — chart title
      (orchestrator may inject ``_run_labels: list[str]`` for multi-run plots
       and ``_overlays: list[dict]`` for reference ranges / experimental data)
    """

    def inputs(self):
        return {'observable': 'list[float]', 'time': 'list[float]'}

    def update(self, state):
        obs = state.get('observable')
        ts = state.get('time')
        if obs is None or ts is None:
            return {'html': '<p style="color:#991b1b">missing observable or time input</p>'}

        # Normalize: single run = flat list; multi-run = list of lists
        if obs and isinstance(obs[0], list):
            runs = list(zip(ts, obs))
        else:
            runs = [(ts, obs)]
        labels = state.get('_run_labels') or [''] * len(runs)
        overlays = state.get('_overlays') or []

        traces = []
        for i, (xs, ys) in enumerate(runs):
            traces.append({
                'x': xs, 'y': ys, 'type': 'scatter', 'mode': 'lines',
                'name': labels[i] if i < len(labels) else f'run {i}',
                'line': {'color': _PALETTE[i % len(_PALETTE)], 'width': 2},
            })

        shapes = []
        annotations = []
        for ov in overlays:
            kind = ov.get('kind')
            if kind == 'reference-range':
                y_min, y_max = ov.get('y_min'), ov.get('y_max')
                if y_min is not None and y_max is not None:
                    shapes.append({
                        'type': 'rect', 'xref': 'paper', 'yref': 'y',
                        'x0': 0, 'x1': 1, 'y0': y_min, 'y1': y_max,
                        'fillcolor': '#fef3c7', 'opacity': 0.3,
                        'line': {'width': 0},
                    })
                    annotations.append({
                        'xref': 'paper', 'yref': 'y',
                        'x': 0.02, 'y': y_max,
                        'text': _html.escape(ov.get('label', 'reference range')),
                        'showarrow': False,
                        'font': {'size': 11, 'color': '#92400e'},
                    })
            elif kind == 'experimental-points':
                pts = ov.get('points') or []
                if pts:
                    traces.append({
                        'x': [p['x'] for p in pts],
                        'y': [p['y'] for p in pts],
                        'type': 'scatter', 'mode': 'markers',
                        'name': ov.get('label', 'experimental'),
                        'marker': {'color': '#000', 'size': 8, 'symbol': 'circle-open'},
                    })

        title = (getattr(self, 'config', None) or {}).get('title', '')
        layout = {
            'title': {'text': _html.escape(title), 'font': {'size': 14}},
            'xaxis': {'title': {'text': 'time'}},
            'margin': {'l': 55, 'r': 15, 't': 40, 'b': 40},
            'legend': {'orientation': 'h', 'y': -0.2},
            'shapes': shapes,
            'annotations': annotations,
        }
        return {'html': (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ', ' + json.dumps(layout)
            + ', {responsive:true, displayModeBar:false});</script>'
        )}
```

- [ ] **Step 4: Confirm pass**

```bash
python -m pytest tests/test_default_visualizations.py -v
```

Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add pbg_superpowers/visualizations/time_series.py tests/test_default_visualizations.py
git commit -m "feat: TimeSeriesPlot v2 — typed inputs, single update(state) contract"
```

---

### Task 4: Rewrite `ParamVsObservable` for v2

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/param_vs_observable.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py` (append)

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import ParamVsObservable


def test_param_vs_observable():
    inst = object.__new__(ParamVsObservable)
    inst.config = {'title': 'Sweep'}
    state = {
        'sweep_param_values': [0.1, 0.5, 1.0],
        'reduced_observable':  [3.0, 7.5, 15.0],
    }
    out = inst.update(state)
    assert 'html' in out
    assert 'Plotly.newPlot' in out['html']
    assert '15' in out['html']
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Replace `pbg_superpowers/visualizations/param_vs_observable.py`**

```python
"""ParamVsObservable — sweep parameter value vs reduced observable.

The orchestrator does the reduction (final/mean/max/...) before populating
the input store; this Step just plots ``y vs x`` as a line+marker chart.
"""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


class ParamVsObservable(Visualization):
    """Plot reduced observable values across a sweep.

    Inputs (declared types):
      sweep_param_values: list[float] — x-axis (one value per run in the sweep)
      reduced_observable: list[float] — y-axis (reduced trajectory per run)

    Config:
      title: str
    """

    def inputs(self):
        return {
            'sweep_param_values': 'list[float]',
            'reduced_observable': 'list[float]',
        }

    def update(self, state):
        xs = state.get('sweep_param_values') or []
        ys = state.get('reduced_observable') or []
        title = (getattr(self, 'config', None) or {}).get('title', '')
        if xs and ys:
            pairs = sorted(zip(xs, ys))
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
        traces = [{
            'x': xs, 'y': ys, 'type': 'scatter', 'mode': 'lines+markers',
            'line': {'color': '#6366f1', 'width': 2},
            'marker': {'color': '#6366f1', 'size': 8},
        }]
        layout = {
            'title': {'text': _html.escape(title), 'font': {'size': 14}},
            'margin': {'l': 55, 'r': 15, 't': 40, 'b': 40},
            'showlegend': False,
        }
        return {'html': (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ', ' + json.dumps(layout)
            + ', {responsive:true, displayModeBar:false});</script>'
        )}
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_default_visualizations.py -v
```
Expected: 3/3 pass.

```bash
git add pbg_superpowers/visualizations/param_vs_observable.py tests/test_default_visualizations.py
git commit -m "feat: ParamVsObservable v2 — typed inputs, update(state)"
```

---

### Task 5: Rewrite `Distribution` for v2

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/distribution.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py` (append)

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import Distribution


def test_distribution_histogram():
    inst = object.__new__(Distribution)
    inst.config = {'title': 'Hist'}
    state = {'samples': [10.0, 10.3, 10.6, 10.9, 11.2]}
    out = inst.update(state)
    assert 'Plotly.newPlot' in out['html']
    assert 'histogram' in out['html'].lower()
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Replace `pbg_superpowers/visualizations/distribution.py`**

```python
"""Distribution — histogram of a sample list.

Orchestrator collects the samples (e.g., final-step values across N seed
runs) into a flat list; this Step renders a histogram.
"""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


class Distribution(Visualization):
    """Histogram of an observable's distribution.

    Inputs (declared types):
      samples: list[float] — the values to bin

    Config:
      title: str
    """

    def inputs(self):
        return {'samples': 'list[float]'}

    def update(self, state):
        samples = state.get('samples') or []
        title = (getattr(self, 'config', None) or {}).get('title', '')
        traces = [{
            'x': samples, 'type': 'histogram',
            'marker': {'color': '#6366f1'},
            'opacity': 0.85,
        }]
        layout = {
            'title': {'text': _html.escape(title), 'font': {'size': 14}},
            'yaxis': {'title': {'text': 'count'}},
            'margin': {'l': 55, 'r': 15, 't': 40, 'b': 40},
            'showlegend': False,
            'bargap': 0.05,
        }
        return {'html': (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ', ' + json.dumps(layout)
            + ', {responsive:true, displayModeBar:false});</script>'
        )}
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_default_visualizations.py -v
```
Expected: 4/4 pass.

```bash
git add pbg_superpowers/visualizations/distribution.py tests/test_default_visualizations.py
git commit -m "feat: Distribution v2 — typed inputs, update(state)"
```

---

### Task 6: Rewrite `PhaseSpace` for v2

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/phase_space.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py` (append)

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import PhaseSpace


def test_phase_space():
    inst = object.__new__(PhaseSpace)
    inst.config = {'title': 'XY'}
    state = {'x': [0.0, 1.0, 2.0, 3.0], 'y': [0.0, 1.0, 4.0, 9.0]}
    out = inst.update(state)
    assert 'Plotly.newPlot' in out['html']
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Replace `pbg_superpowers/visualizations/phase_space.py`**

```python
"""PhaseSpace — two observables plotted against each other."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


class PhaseSpace(Visualization):
    """XY trajectory of two observables.

    Inputs (declared types):
      x: list[float]
      y: list[float]

    Config:
      title: str
    """

    def inputs(self):
        return {'x': 'list[float]', 'y': 'list[float]'}

    def update(self, state):
        xs = state.get('x') or []
        ys = state.get('y') or []
        title = (getattr(self, 'config', None) or {}).get('title', '')
        traces = [{
            'x': xs, 'y': ys, 'type': 'scatter', 'mode': 'lines+markers',
            'line': {'color': '#6366f1', 'width': 2},
            'marker': {'size': 5},
        }]
        layout = {
            'title': {'text': _html.escape(title), 'font': {'size': 14}},
            'margin': {'l': 55, 'r': 15, 't': 40, 'b': 40},
            'showlegend': False,
        }
        return {'html': (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ', ' + json.dumps(layout)
            + ', {responsive:true, displayModeBar:false});</script>'
        )}
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_default_visualizations.py -v
```
Expected: 5/5 pass.

```bash
git add pbg_superpowers/visualizations/phase_space.py tests/test_default_visualizations.py
git commit -m "feat: PhaseSpace v2 — typed inputs, update(state)"
```

---

### Task 7: Rewrite `Heatmap` for v2 + bump + PyPI release

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/heatmap.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py` (append)
- Modify: `pbg-superpowers/pyproject.toml` (version bump)

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import Heatmap


def test_heatmap():
    inst = object.__new__(Heatmap)
    inst.config = {'title': 'Grid'}
    state = {
        'x_params': [1.0, 2.0, 3.0],
        'y_params': [10.0, 20.0],
        'z_values': [[10.0, 20.0, 30.0], [20.0, 40.0, 60.0]],
    }
    out = inst.update(state)
    assert 'Plotly.newPlot' in out['html']
    assert 'heatmap' in out['html'].lower()
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Replace `pbg_superpowers/visualizations/heatmap.py`**

```python
"""Heatmap — 2D parameter sweep, color = reduced observable."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


class Heatmap(Visualization):
    """Color matrix over a 2D parameter sweep.

    Inputs (declared types):
      x_params: list[float]
      y_params: list[float]
      z_values: list[list[float]]  — z[y_idx][x_idx]

    Config:
      title: str
    """

    def inputs(self):
        return {
            'x_params': 'list[float]',
            'y_params': 'list[float]',
            'z_values': 'list[list[float]]',
        }

    def update(self, state):
        xs = state.get('x_params') or []
        ys = state.get('y_params') or []
        zs = state.get('z_values') or []
        title = (getattr(self, 'config', None) or {}).get('title', '')
        traces = [{
            'z': zs, 'x': xs, 'y': ys, 'type': 'heatmap',
            'colorscale': 'Viridis',
        }]
        layout = {
            'title': {'text': _html.escape(title), 'font': {'size': 14}},
            'margin': {'l': 55, 'r': 60, 't': 40, 'b': 40},
        }
        return {'html': (
            '<div id="viz" style="height:420px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ', ' + json.dumps(layout)
            + ', {responsive:true, displayModeBar:false});</script>'
        )}
```

- [ ] **Step 4: Confirm pass**

```bash
python -m pytest tests/test_default_visualizations.py -v
```
Expected: 6/6 pass.

- [ ] **Step 5: Bump version + commit + push + tag**

```bash
cd /Users/eranagmon/code/pbg-superpowers
# Bump version (read current first)
CURRENT=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "current: $CURRENT"
# Bump minor (e.g. 0.5.1 → 0.6.0 to signal the breaking Visualization v2 change)
NEW="0.6.0"
sed -i.bak "s/^version = \"$CURRENT\"$/version = \"$NEW\"/" pyproject.toml && rm pyproject.toml.bak
git add pbg_superpowers/visualizations/heatmap.py tests/test_default_visualizations.py pyproject.toml
git commit -m "feat: Heatmap v2 + bump to $NEW — Visualization v2 (breaking: drop render_final)"
git push origin HEAD 2>&1 | tail -3
git tag "v$NEW"
git push origin "v$NEW" 2>&1 | tail -3
```

The `Publish to PyPI` workflow fires on the tag push.

---

### Task 8: investigations.py — `gather_emitter_outputs` + new `build_viz_composite`

**Files:**
- Modify: `pbg-template/scripts/_lib/investigations.py`
- Modify: `pbg-template/tests/test_investigations.py`

Working dir: `/Users/eranagmon/code/pbg-template`. Branch: `main`.

- [ ] **Step 1: Append failing tests** to `tests/test_investigations.py`

```python
import json
import sqlite3
from scripts._lib.investigations import gather_emitter_outputs, build_viz_composite


def _setup_db_with_schema(tmp_path):
    db = tmp_path / 'runs.db'
    conn = sqlite3.connect(str(db))
    # runs_meta (Investigations) — mirror the production schema
    conn.execute('CREATE TABLE runs_meta ('
                 ' run_id TEXT PRIMARY KEY, spec_id TEXT, sim_name TEXT,'
                 ' label TEXT, params_json TEXT, started_at REAL,'
                 ' completed_at REAL, n_steps INTEGER, status TEXT)')
    # history + simulations from process-bigraph
    conn.execute('CREATE TABLE history (simulation_id TEXT, step INTEGER, '
                 'global_time REAL, state TEXT)')
    conn.execute('CREATE TABLE simulations (simulation_id TEXT PRIMARY KEY, '
                 'name TEXT, started_at TEXT, emit_schema TEXT)')

    # one sim, one run, three rows
    conn.execute('INSERT INTO runs_meta VALUES (?,?,?,?,?,?,?,?,?)',
                 ('r1', 'spec', 'baseline', 'baseline',
                  json.dumps({'rate': 1.0}), 0.0, 1.0, 3, 'completed'))
    conn.execute('INSERT INTO simulations(simulation_id, started_at, emit_schema) '
                 'VALUES (?, ?, ?)',
                 ('r1', '2026-05-12', json.dumps({'level': 'float', 'time': 'float'})))
    for i in range(3):
        conn.execute('INSERT INTO history VALUES (?,?,?,?)',
                     ('r1', i, float(i),
                      json.dumps({'level': float(i + 1), 'time': float(i)})))
    conn.commit(); conn.close()
    return db


def test_gather_emitter_outputs_returns_schema(tmp_path):
    db = _setup_db_with_schema(tmp_path)
    out = gather_emitter_outputs(db)
    assert 'schemas' in out
    assert out['schemas']['r1'] == {'level': 'float', 'time': 'float'}


def test_gather_emitter_outputs_by_sim(tmp_path):
    db = _setup_db_with_schema(tmp_path)
    out = gather_emitter_outputs(db)
    assert 'baseline' in out['by_sim']
    runs = out['by_sim']['baseline']
    assert len(runs) == 1
    run = runs[0]
    assert run['run_id'] == 'r1'
    assert run['params'] == {'rate': 1.0}
    assert run['observables']['level'] == [1.0, 2.0, 3.0]
    assert run['observables']['time'] == [0.0, 1.0, 2.0]


def test_build_viz_composite_shape():
    viz_spec = {
        'name': 'levels', 'address': 'local:TimeSeriesPlot',
        'config': {'title': 'Demo'},
    }
    # Pretend gathered: one sim, one run with two observables
    gathered = {
        'schemas': {'r1': {'level': 'float', 'time': 'float'}},
        'by_sim': {'baseline': [{
            'run_id': 'r1', 'params': {}, 'sim_name': 'baseline',
            'observables': {'level': [1.0, 2.0, 4.0], 'time': [0.0, 1.0, 2.0]},
        }]},
    }
    # Stub registry — viz_class is just any object with inputs()/outputs()
    class _Stub:
        def inputs(self): return {'observable': 'list[float]', 'time': 'list[float]'}
        def outputs(self): return {'html': 'string'}
    registry = {'TimeSeriesPlot': _Stub}
    doc = build_viz_composite(viz_spec, gathered, registry)
    # Structural assertions: input store has the trajectory wired by name
    assert 'visualization' in doc
    assert doc['visualization']['_type'] == 'step'
    assert doc['visualization']['address'] == 'local:TimeSeriesPlot'
    assert 'outputs' in doc['visualization']
    assert doc['visualization']['outputs']['html'] == ['output_store']
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Add new helpers to `scripts/_lib/investigations.py`**

Find the existing `gather_results` function. Add new helpers below it (DO NOT delete `gather_results` yet — the legacy code paths still call it; Task 9 cleans those up).

```python
# ----------------------------------------------------------------------------
# Visualization v2 — emitter-driven, composite-dispatched
# ----------------------------------------------------------------------------

def gather_emitter_outputs(db_path: Path) -> dict:
    """Flatten runs.db into a per-observable trajectory shape + emitter schemas.

    Returns:
        {
          "schemas": {<run_id>: {<observable>: <type_str>}, ...},
          "by_sim": {<sim_name>: [{run_id, params, sim_name, observables}, ...]},
        }
    where observables is {<obs_name>: [v0, v1, ...]} (one entry per step).

    Pre-condition: ``runs.db`` must include both the Investigation's
    ``runs_meta`` table and process-bigraph's ``history`` + ``simulations``
    tables (the latter populated by ``SQLiteEmitter`` >= the schema-persistence
    release).
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return {"schemas": {}, "by_sim": {}}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Pull run metadata
        meta_rows = conn.execute(
            "SELECT run_id, sim_name, params_json FROM runs_meta"
        ).fetchall()
        run_meta = {}
        for r in meta_rows:
            try:
                params = json.loads(r["params_json"] or "{}")
            except json.JSONDecodeError:
                params = {}
            run_meta[r["run_id"]] = {
                "sim_name": r["sim_name"] or "default",
                "params": params,
            }

        # Pull emit schemas (graceful when column / table missing)
        schemas = {}
        try:
            sim_rows = conn.execute(
                "SELECT simulation_id, emit_schema FROM simulations"
            ).fetchall()
            for r in sim_rows:
                if r["emit_schema"]:
                    try:
                        schemas[r["simulation_id"]] = json.loads(r["emit_schema"])
                    except json.JSONDecodeError:
                        pass
        except sqlite3.OperationalError:
            pass

        # Pull per-step state and unpack each row's JSON into per-observable lists
        by_sim = {}
        # Guard against missing history table (all runs failed before first emit)
        has_history = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
        ).fetchone() is not None
        for run_id, meta in run_meta.items():
            observables = {}
            if has_history:
                rows = conn.execute(
                    "SELECT step, global_time, state FROM history "
                    "WHERE simulation_id=? ORDER BY step ASC",
                    (run_id,),
                ).fetchall()
                for row in rows:
                    try:
                        state = json.loads(row["state"]) if row["state"] else {}
                    except json.JSONDecodeError:
                        continue
                    for k, v in state.items():
                        observables.setdefault(k, []).append(v)
                    # Always synthesize a 'time' observable from global_time
                    observables.setdefault("time", []).append(row["global_time"])
            sim_name = meta["sim_name"]
            by_sim.setdefault(sim_name, []).append({
                "run_id": run_id,
                "sim_name": sim_name,
                "params": meta["params"],
                "observables": observables,
            })
        return {"schemas": schemas, "by_sim": by_sim}
    finally:
        conn.close()


def build_viz_composite(viz_spec: dict, gathered: dict, core_registry: dict) -> dict:
    """Build the small composite that dispatches one visualization.

    Resolves ``viz_spec['address']`` against ``core_registry`` to get the
    Visualization class. Reads its ``inputs()`` declaration to know which
    typed ports to wire. For each declared input, looks up a matching
    observable in ``gathered`` (by name; ``config.inputs_map`` can override),
    coerces shape (scalar ↔ list[scalar]) per the declared type, and
    pre-populates an ``inputs_store`` cell.

    Returns the composite state document (a dict ready to pass as
    ``Composite({"state": doc}, core=core)``).

    Resolution rules:
      - Default: input port ``<name>`` ← observable ``<name>``.
      - ``viz_spec['config']['inputs_map'] = {<port>: <observable>}`` overrides.
      - ``viz_spec['config']['sources']`` (optional list of sim_names) filters
        which sims contribute runs. Default = all sims.
      - Multi-run: for ``list[float]`` ports, the orchestrator passes either
        a flat list (single run) or a list-of-lists (multiple runs) and sets
        ``_run_labels`` on the inputs_store.
    """
    address = viz_spec["address"]
    class_key = address.split(":", 1)[1] if ":" in address else address
    viz_class = core_registry.get(class_key)
    if viz_class is None:
        raise KeyError(f"Visualization class not registered: {address}")

    config = dict(viz_spec.get("config") or {})
    inputs_map = config.get("inputs_map") or {}
    sources = config.get("sources")
    declared_inputs = viz_class().inputs() if callable(getattr(viz_class, '__call__', None)) else viz_class.inputs(viz_class)
    # Robust call: try class.inputs(instance) via __new__ to avoid invoking Step init
    try:
        instance = viz_class.__new__(viz_class)
        declared_inputs = instance.inputs()
    except Exception:
        declared_inputs = {}

    # Gather candidate runs filtered by `sources`
    candidate_runs = []
    by_sim = gathered.get("by_sim") or {}
    for sim_name, runs in by_sim.items():
        if sources and sim_name not in sources:
            continue
        candidate_runs.extend(runs)

    # Build the inputs_store: one cell per declared input port
    inputs_store = {}
    run_labels = []
    for port, port_type in declared_inputs.items():
        observable_name = inputs_map.get(port, port)
        per_run_values = []
        for run in candidate_runs:
            vals = run.get("observables", {}).get(observable_name)
            if vals is None:
                continue
            per_run_values.append(vals)
            # Build a stable run label from params
            params = run.get("params") or {}
            label = ", ".join(f"{k}={v}" for k, v in sorted(params.items())) \
                    or run["run_id"][-8:]
            if label not in run_labels:
                run_labels.append(label)
        # Shape per declared type
        if port_type == "list[float]":
            if len(per_run_values) == 1:
                inputs_store[port] = per_run_values[0]
            else:
                inputs_store[port] = per_run_values
        elif port_type == "float":
            inputs_store[port] = per_run_values[0][-1] if per_run_values else None
        elif port_type == "list[list[float]]":
            inputs_store[port] = per_run_values
        else:
            # Best effort: pass-through the first run's values
            inputs_store[port] = per_run_values[0] if per_run_values else None

    inputs_store["_run_labels"] = run_labels

    return {
        "inputs_store": inputs_store,
        "output_store": "",
        "visualization": {
            "_type": "step",
            "address": address,
            "config": {k: v for k, v in config.items() if k not in ("inputs_map", "sources")},
            "inputs": {port: ["inputs_store", port] for port in declared_inputs},
            "outputs": {"html": ["output_store"]},
        },
    }
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest tests/test_investigations.py -v
```
Expected: all pre-existing tests still pass, plus 3 new green tests.

```bash
git add scripts/_lib/investigations.py tests/test_investigations.py
git commit -m "feat: gather_emitter_outputs + build_viz_composite helpers for v2 dispatch"
```

---

### Task 9: Rewrite `render_visualizations` to dispatch via composites

**Files:**
- Modify: `pbg-template/scripts/_lib/investigations.py`
- Modify: `pbg-template/tests/test_investigations.py`

- [ ] **Step 1: Append failing integration-style test**

```python
def test_render_visualizations_v2_writes_html(tmp_path, monkeypatch):
    """End-to-end: build_viz_composite + Composite.run(1) writes html to viz/."""
    from scripts._lib.investigations import render_visualizations
    # Set up a minimal investigation directory with a populated runs.db
    inv_dir = tmp_path / "investigations" / "demo"
    inv_dir.mkdir(parents=True)
    _setup_db_with_schema(inv_dir)  # writes investigations/demo/runs.db

    # Use a stub Visualization class
    class _Stub:
        @classmethod
        def is_visualization(cls): return True
        def inputs(self): return {'observable': 'list[float]', 'time': 'list[float]'}
        def outputs(self): return {'html': 'string'}
        def update(self, state):
            return {'html': '<p>obs=' + str(state.get('observable')) + '</p>'}

    registry = {'TimeSeriesPlot': _Stub}
    spec = {
        'composite': 'pkg.composites.demo',
        'simulations': [{'name': 'baseline', 'kind': 'single',
                          'overrides': {}, 'steps': 3}],
        'observables': ['level'],
        'visualizations': [{
            'name': 'levels',
            'address': 'local:TimeSeriesPlot',
            'config': {'title': 'T'},
        }],
    }

    # Stub the Composite resolution: render_visualizations should accept a
    # "build_and_run" hook so we can avoid pulling in the full bigraph
    # runtime in a unit test. Production passes the real hook from server.py.
    captured = []
    def fake_build_and_run(doc, registry_arg):
        # Pretend Composite executed: read inputs_store, call viz.update(state)
        viz_class = registry_arg[doc['visualization']['address'].split(':', 1)[1]]
        inst = viz_class.__new__(viz_class)
        state = dict(doc['inputs_store'])
        out = inst.update(state)
        return out.get('html', '')

    paths = render_visualizations(spec, inv_dir, 'demo',
                                   core_registry=registry,
                                   build_and_run=fake_build_and_run)
    assert paths
    html_path = inv_dir / 'viz' / 'levels.html'
    assert html_path.is_file()
    text = html_path.read_text()
    assert '<p>obs=' in text
```

The test stubs out the actual Composite-runtime invocation via an
injectable `build_and_run` hook so the unit test doesn't pull in process-
bigraph's full runtime. Production wires in the real hook (Task 10).

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Rewrite `render_visualizations` in `scripts/_lib/investigations.py`**

Find the existing `render_visualizations` function (added in the earlier
Investigations rollout). Replace it with:

```python
def render_visualizations(spec: dict, inv_dir: Path, name: str, *,
                          core_registry: dict,
                          build_and_run=None) -> list[Path]:
    """Render every viz in ``spec.visualizations`` against the investigation's runs.db.

    For each viz:
      1. Build the viz composite via ``build_viz_composite``.
      2. Run it for 1 step via ``build_and_run(doc, core_registry) -> str``.
         (Production wires in a real Composite-runtime invocation; tests
         pass a stub.)
      3. Write the resulting HTML to ``<inv_dir>/viz/<viz_name>.html``.
      4. On any error, write an error stub HTML (other vizzes still render).

    Returns the list of written paths.
    """
    inv_dir = Path(inv_dir)
    viz_dir = inv_dir / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)

    if build_and_run is None:
        raise ValueError(
            "render_visualizations requires a build_and_run hook "
            "(production path: see server._post_investigation_run_viz_hook)."
        )

    gathered = gather_emitter_outputs(inv_dir / "runs.db")
    paths = []
    for viz_spec in spec.get("visualizations") or []:
        target = viz_dir / f"{viz_spec['name']}.html"
        try:
            doc = build_viz_composite(viz_spec, gathered, core_registry)
            html = build_and_run(doc, core_registry)
        except Exception as e:
            html = (
                f'<p style="color:#991b1b">Failed to render '
                f'<code>{viz_spec.get("name", "?")}</code>: '
                f'<code>{type(e).__name__}: {e}</code></p>'
            )
        target.write_text(html)
        paths.append(target)
    return paths
```

- [ ] **Step 4: Update `run_investigation`** to pass the new `build_and_run` hook.

Find the existing call site of `render_visualizations` inside `run_investigation`. It currently expects no hook. Update the orchestrator so it accepts an optional `build_and_run` kwarg and passes it down:

```python
def run_investigation(ws_root: Path, name: str, *,
                      run_one_composite,
                      core_registry: dict,
                      build_and_run=None) -> dict:
    ...
    # After all sims completed:
    inv_dir = Path(ws_root) / 'investigations' / name
    viz_paths = render_visualizations(
        spec, inv_dir, name,
        core_registry=core_registry,
        build_and_run=build_and_run,
    )
    ...
```

The actual production hook is wired in by the server (Task 10).

- [ ] **Step 5: Confirm tests pass + commit**

```bash
python -m pytest tests/test_investigations.py -v
```

Expected: all pre-existing tests still pass, plus the new render_visualizations_v2 test passes.

```bash
git add scripts/_lib/investigations.py tests/test_investigations.py
git commit -m "feat: render_visualizations dispatches via composite, type-checked"
```

---

### Task 10: Server — wire production `build_and_run` hook + new render-viz endpoint

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`

- [ ] **Step 1: Add the production `build_and_run` builder + helper**

Near the top of the `_post_investigation_run` method (just before the `run_investigation` call), define a closure that builds + runs each viz composite:

```python
        def build_and_run(viz_doc, registry_arg):
            """Production hook: build a Composite from viz_doc, run it 1 step,
            return the output_store's html string. Wired into render_visualizations.
            """
            # Use the already-constructed core (the one we built above for sims)
            from process_bigraph import Composite
            composite = Composite({'state': viz_doc}, core=core)
            composite.run(1)
            # Read the html out of the output_store
            state = composite.state
            html = state.get('output_store')
            if isinstance(html, dict):
                # In case the runtime returns a dict shape
                html = html.get('value') or html.get('_value') or ''
            return html if isinstance(html, str) else ''
```

Pass it into `run_investigation` at the existing call site:

```python
            summary = run_investigation(
                WORKSPACE, name,
                run_one_composite=run_one_composite,
                core_registry=registry,
                build_and_run=build_and_run,   # NEW
            )
```

Also: remove the old `render_visualizations` call site below `run_investigation` if any exists (it should all be inside the orchestrator now).

- [ ] **Step 2: Add `POST /api/investigation-render-viz` endpoint**

Add the new method on the Handler class (next to `_post_investigation_run`):

```python
    def _post_investigation_render_viz(self, body: dict):
        """POST /api/investigation-render-viz {name} — re-render visualizations
        against the investigation's existing emitter data. No simulation re-run.
        """
        _ws_add_to_sys_path()
        from scripts._lib.investigations import (
            load_spec, render_visualizations, InvestigationSpecError,
        )

        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)
        inv_dir = WORKSPACE / "investigations" / name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": f"investigation '{name}' not found"}, 404)
        try:
            spec = load_spec(spec_path)
        except InvestigationSpecError as e:
            return self._json({"error": f"spec error: {e}"}, 400)

        # Build the visualization registry the same way _post_investigation_run does
        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        sys.path.insert(0, str(WORKSPACE))
        try:
            core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
            core = core_module.build_core()
            registry = dict(core.link_registry)
        except Exception as e:
            return self._json({"error": f"failed to build core: {e}"}, 500)
        try:
            from pbg_superpowers.visualizations import (
                TimeSeriesPlot, ParamVsObservable, Distribution, PhaseSpace, Heatmap,
            )
            registry["TimeSeriesPlot"] = TimeSeriesPlot
            registry["ParamVsObservable"] = ParamVsObservable
            registry["Distribution"] = Distribution
            registry["PhaseSpace"] = PhaseSpace
            registry["Heatmap"] = Heatmap
        except ImportError:
            pass

        from process_bigraph import Composite

        def build_and_run(viz_doc, registry_arg):
            composite = Composite({'state': viz_doc}, core=core)
            composite.run(1)
            state = composite.state
            html = state.get('output_store')
            if isinstance(html, dict):
                html = html.get('value') or html.get('_value') or ''
            return html if isinstance(html, str) else ''

        viz_paths = render_visualizations(
            spec, inv_dir, name,
            core_registry=registry, build_and_run=build_and_run,
        )
        return self._json({
            "ok": True, "investigation": name,
            "n_visualizations": len(viz_paths),
            "viz_paths": [str(p) for p in viz_paths],
        }, 200)
```

Wire dispatch in `do_POST`'s endpoint dict:

```python
            "/api/investigation-render-viz": self._post_investigation_render_viz,
```

- [ ] **Step 3: Run the full test suite, confirm pass**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass. The e2e investigation-run test will exercise the new code path indirectly.

- [ ] **Step 4: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: server wires Composite-runtime build_and_run hook + /api/investigation-render-viz endpoint"
```

---

### Task 11: Frontend — `_submitAddViz` chains a render-viz call

**Files:**
- Modify: `pbg-template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Update `_submitAddViz`**

Find the existing `_submitAddViz` function. Find the line that runs after a successful add (the success branch's `_openInvestigation(payload.investigation)` call). Insert a render call before that refresh:

```javascript
  function _submitAddViz(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var configRaw = (data.get('config') || '').trim();
    var config = {};
    if (configRaw) {
      try { config = JSON.parse(configRaw); }
      catch (e) {
        if (errEl) errEl.textContent = 'Invalid JSON in config: ' + String(e);
        return;
      }
    }
    var payload = {
      investigation: data.get('investigation'),
      name: data.get('name'),
      address: data.get('address'),
      config: config,
    };
    fetch('/api/investigation-add-viz', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'add failed';
          return;
        }
        closeModal('modal-investigation-add-viz');
        // NEW: trigger a render pass so the freshly-added viz appears immediately
        return fetch('/api/investigation-render-viz', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: payload.investigation}),
        }).then(function() {
          _openInvestigation(payload.investigation);
        });
      });
  }
```

- [ ] **Step 2: Sync + render + smoke**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_server/walkthrough.js /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp scripts/_lib/investigations.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/investigations.py
cp scripts/_server/server.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: _submitAddViz chains /api/investigation-render-viz so new vizzes appear immediately"
```

---

### Task 12: Restart v2ecoli + manual verify + push everything

**Files:**
- (workspace state)

- [ ] **Step 1: Install latest pbg-superpowers from PyPI**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
uv pip install -U pbg-superpowers 2>&1 | tail -3
.venv/bin/python3 -c "from pbg_superpowers.visualization import Visualization; v = object.__new__(Visualization); assert not hasattr(v, 'render_final'); print('v2 contract confirmed')"
```

Expected: `v2 contract confirmed`.

- [ ] **Step 2: Restart server**

```bash
EXISTING=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])" 2>/dev/null || echo '')
[ -n "$EXISTING" ] && lsof -nP -iTCP:$EXISTING -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -I {} kill {} 2>/dev/null
rm -f .pbg/server/server-info; sleep 1
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
cat .pbg/server/server-info
```

- [ ] **Step 3: Manual verification checklist**

1. Hard-reload the dashboard tab.
2. Investigations → click an existing investigation (preferably one with runs.db) → switch to the Visualizations tab.
3. Click "+ Add visualization" → pick `TimeSeriesPlot`, name `levels`, config `{}` (empty) → submit.
4. Expected: modal closes, detail panel reloads, the Visualizations tab now shows an iframe with a Plotly figure rendered from the existing runs.db — **no Run click needed**.
5. Create a brand-new investigation → click Run → confirm visualizations are populated automatically.

- [ ] **Step 4: Commit + push v2ecoli**

```bash
git add -A
git commit -m "fix: refresh to pbg-template + pbg-superpowers v0.6.0 — Visualization v2 dispatch"
git push 2>&1 | tail -3
```

- [ ] **Step 5: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git log --oneline -15
git push 2>&1 | tail -3
```

---

## Self-review notes

- **Phase A is a PR**, not a direct push. Task 1 ends with `gh pr create`; subsequent tasks (8, 9, 10) call `load_emit_schema` which lives in process-bigraph — they will rely on the user having merged the PR + reinstalled. Until merge, `load_emit_schema` may fail to import; the orchestrator falls back to "infer schema from data" path (the test fixture writes the simulations table directly so unit tests pass without needing the upstream merge).
- **Spec coverage:** Phase A → Task 1; Phase B base → Task 2; Phase B defaults → Tasks 3-7; Phase C gather/build → Task 8; Phase C render → Task 9; Phase C endpoint → Task 10; Phase D → Task 11; verify → Task 12. All covered.
- **Type consistency:** `gather_emitter_outputs` returns `{schemas, by_sim}`, both used by `build_viz_composite`. `render_visualizations` accepts a `build_and_run` hook (tests pass stubs; server passes real Composite invocation). `Visualization.update` returns `{html: str}` everywhere.
- **No placeholders.** Each step has the full code or command.
- **YAGNI deferred:** wrapper-side Visualization `inputs()` cleanup (Phase E in the spec) intentionally not implemented here. Each wrapper's `update(state)` already works as a streaming Step; their types can be cleaned up separately.
