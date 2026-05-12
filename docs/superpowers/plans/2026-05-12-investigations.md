# Investigations (v0.5.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase system in pbg-template with Investigations — declarative, runnable research recipes that bundle one composite + one or more simulations (single / sweep / seeds) + observables + post-hoc visualizations + overlays. Each Investigation lives at `investigations/<name>/` with its own SQLite results DB and rendered HTML visualizations.

**Architecture:** Each Investigation is a directory. `spec.yaml` declares composite + simulations + observables + visualizations. A new `/api/investigation-run` endpoint orchestrates: expand simulation blocks, run the composite (injecting `SQLiteEmitter`), gather results, then call each Visualization's `render_final(results, config)` and write HTML to `investigations/<name>/viz/`. Five new default `Visualization(Step)` subclasses (TimeSeriesPlot, ParamVsObservable, Distribution, PhaseSpace, Heatmap) ship in `pbg-superpowers/pbg_superpowers/visualizations/`. The Visualization base class gains a `render_final` method; `update()` (per-step streaming) becomes opt-in via `supports_streaming = True`. The old Phase system is removed entirely — no migration script.

**Tech Stack:** Python 3.11+, sqlite3 (via existing `composite_runs.py` helpers), PyYAML, Plotly (CDN, already loaded by dashboard), vanilla JS (matches existing `walkthrough.js`). Tests via pytest.

**Spec reference:** `docs/superpowers/specs/2026-05-11-investigations-design.md`

**File structure:**

| File | Action | Responsibility |
|---|---|---|
| `pbg-superpowers/pbg_superpowers/visualization.py` | modify | Add `render_final` + `supports_streaming` to base class |
| `pbg-superpowers/pbg_superpowers/visualizations/__init__.py` | create | Re-export default Visualization classes |
| `pbg-superpowers/pbg_superpowers/visualizations/time_series.py` | create | `TimeSeriesPlot` |
| `pbg-superpowers/pbg_superpowers/visualizations/param_vs_observable.py` | create | `ParamVsObservable` |
| `pbg-superpowers/pbg_superpowers/visualizations/distribution.py` | create | `Distribution` |
| `pbg-superpowers/pbg_superpowers/visualizations/phase_space.py` | create | `PhaseSpace` |
| `pbg-superpowers/pbg_superpowers/visualizations/heatmap.py` | create | `Heatmap` |
| `pbg-superpowers/tests/test_default_visualizations.py` | create | Unit tests for 5 defaults |
| `pbg-template/scripts/_lib/investigations.py` | create | spec load + simulation expansion + run orchestration |
| `pbg-template/scripts/_server/server.py` | modify | Add 4 new endpoints, remove 3 phase endpoints |
| `pbg-template/scripts/_templates/index.html.j2` | modify | Replace Build Model section + menu link |
| `pbg-template/scripts/_server/walkthrough.js` | modify | Investigations list + detail + actions; remove phase JS |
| `pbg-template/scripts/_templates/_assets/style.css` | modify | Remove `.phase-*`, add `.investigation-*` + `.viz-frame` |
| `pbg-template/tests/test_investigations.py` | create | Unit tests |
| `pbg-template/tests/test_investigation_run_e2e.py` | create | End-to-end integration |
| `pbg-template/workspace.yaml.j2` | modify | Drop `phases: []`; no investigations field needed (file-based) |
| `pbg-template/scripts/_lib/phase_files.py` | delete | |
| `pbg-template/scripts/_lib/phase_md.py` | delete | |
| `pbg-template/scripts/_lib/phase_gate.py` | delete | |
| `pbg-template/phases/` | delete | template directory + plan.md placeholder |
| `pbg-template/.pbg/schemas/phase.schema.json` | delete | |
| `pbg-superpowers/skills/pbg-investigate/SKILL.md` | create | new launcher skill |
| `pbg-superpowers/skills/pbg-phase/` | delete | old phase skill |
| `pbg-superpowers/plugin.yaml` | modify | swap pbg-phase → pbg-investigate in skills list |

---

### Task 1: Visualization base class — `render_final` + `supports_streaming`

**Files:**
- Modify: `pbg-superpowers/pbg_superpowers/visualization.py`
- Modify: `pbg-superpowers/tests/test_visualization.py` (existing — add new tests)

- [ ] **Step 1: Write the failing tests** — append to `pbg-superpowers/tests/test_visualization.py`

```python
def test_visualization_render_final_raises_by_default():
    """Base class render_final must raise NotImplementedError so subclasses must override."""
    import pytest
    with pytest.raises(NotImplementedError, match="render_final"):
        Visualization.render_final(None, {}, config={})


def test_visualization_supports_streaming_default_false():
    """Default class attribute is False — subclasses opt in to streaming."""
    assert Visualization.supports_streaming is False


def test_visualization_update_default_returns_empty_html():
    """Base update is a no-op for final-mode visualizations."""
    inst = object.__new__(Visualization)
    out = inst.update({}, 1.0)
    assert out == {'html': ''}
```

- [ ] **Step 2: Run tests to verify fail**

Run: `cd /Users/eranagmon/code/pbg-superpowers && python -m pytest tests/test_visualization.py -v`
Expected: 3 new tests FAIL (no `render_final`, no `supports_streaming`, `update` raises NotImplementedError).

- [ ] **Step 3: Modify `pbg_superpowers/visualization.py`**

Replace the existing `Visualization` class with:

```python
"""Visualization Step base class — final-mode (default) + opt-in streaming.

A Visualization is a process_bigraph.Step. Subclasses always implement
``render_final(results, config)`` (called once at end of an Investigation,
given the full results dict). Subclasses MAY also implement ``update()``
for per-step streaming mode by setting ``supports_streaming = True``.

Discovery: Visualization extends Step extends Edge, so subclasses are
auto-discovered via bigraph_schema.package.discover and registered in
``core.link_registry`` alongside Emitters / Processes / Types.
"""
from __future__ import annotations
from typing import Any

from process_bigraph import Step


class Visualization(Step):
    """Base class for renderable Visualization Steps.

    Subclasses MUST implement ``render_final(results, *, config)``.
    Subclasses MAY implement ``update(state, interval)`` and set
    ``supports_streaming = True`` for per-step rendering inside Composites.
    """

    supports_streaming: bool = False

    config_schema = {
        'title': {'_type': 'string', '_default': ''},
    }

    def inputs(self) -> dict[str, Any]:
        """Default empty. Streaming subclasses override to declare consumed
        observables via wires (per the existing Composite Step contract)."""
        return {}

    def outputs(self) -> dict[str, Any]:
        """Default: single ``html`` string output. Used by both modes."""
        return {'html': 'string'}

    def render_final(self, results: dict, *, config: dict) -> str:
        """Render the visualization once given the full results dict.

        ``results`` shape:
            {<sim_name>: {"runs": [{"run_id", "params", "trajectory"}, ...]}, ...}

        ``config`` is whatever the Investigation spec passed under ``config:``,
        plus a special ``_overlays`` key that the orchestrator injects with
        resolved overlay payloads (experimental-points, reference-range,
        cross-investigation-series).

        Returns a self-contained HTML fragment (Plotly figure typically).
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement render_final(results, *, config). "
            f"See pbg_superpowers.visualization.Visualization for the contract."
        )

    def update(self, state: dict, interval: float = 1.0) -> dict:
        """Optional per-step rendering for streaming mode.

        Default returns ``{'html': ''}`` (no-op) so that Visualization
        subclasses that only do final-mode rendering still satisfy the
        Step contract when accidentally wired into a Composite.
        """
        return {'html': ''}

    @classmethod
    def is_visualization(cls) -> bool:
        """Marker for dashboard filtering."""
        return True
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_visualization.py -v`
Expected: all tests PASS (3 new + the existing ones).

- [ ] **Step 5: Commit**

```bash
cd /Users/eranagmon/code/pbg-superpowers
git add pbg_superpowers/visualization.py tests/test_visualization.py
git commit -m "feat: Visualization base — render_final required, update opt-in via supports_streaming"
```

---

### Task 2: Default Visualization — `TimeSeriesPlot`

**Files:**
- Create: `pbg-superpowers/pbg_superpowers/visualizations/__init__.py`
- Create: `pbg-superpowers/pbg_superpowers/visualizations/time_series.py`
- Create: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Write the failing test**

Create `pbg-superpowers/tests/test_default_visualizations.py`:

```python
"""Unit tests for the default Visualization classes shipped with pbg-superpowers."""
from pbg_superpowers.visualizations import TimeSeriesPlot


def _fixture_results():
    """Minimal results dict: 1 sim, 2 runs, observable 'level' over 4 steps."""
    return {
        "baseline": {
            "runs": [
                {
                    "run_id": "r1",
                    "params": {"rate": 1.0},
                    "trajectory": [
                        {"step": i, "time": float(i), "state": {"level": 1.0 * (i + 1)}}
                        for i in range(4)
                    ],
                },
                {
                    "run_id": "r2",
                    "params": {"rate": 2.0},
                    "trajectory": [
                        {"step": i, "time": float(i), "state": {"level": 2.0 * (i + 1)}}
                        for i in range(4)
                    ],
                },
            ]
        }
    }


def test_time_series_plot_render_returns_html():
    inst = TimeSeriesPlot.__new__(TimeSeriesPlot)
    inst.config = {}
    html = inst.render_final(
        _fixture_results(),
        config={"observable": "level", "sources": ["baseline"], "title": "Test"},
    )
    assert isinstance(html, str)
    assert "Plotly.newPlot" in html
    assert "Test" in html  # title appears in HTML


def test_time_series_plot_two_lines_for_two_runs():
    inst = TimeSeriesPlot.__new__(TimeSeriesPlot)
    inst.config = {}
    html = inst.render_final(
        _fixture_results(),
        config={"observable": "level", "sources": ["baseline"], "title": ""},
    )
    # Each run becomes one Plotly trace. Look for the run_ids in the HTML.
    assert "r1" in html or "rate=1.0" in html
    assert "r2" in html or "rate=2.0" in html


def test_time_series_plot_reference_range_overlay():
    inst = TimeSeriesPlot.__new__(TimeSeriesPlot)
    inst.config = {}
    html = inst.render_final(
        _fixture_results(),
        config={
            "observable": "level", "sources": ["baseline"], "title": "",
            "_overlays": [
                {"kind": "reference-range", "y_min": 1.5, "y_max": 5.0,
                 "label": "phys-range"},
            ],
        },
    )
    # Reference range becomes a shaded band — look for the band's marker.
    assert "phys-range" in html


def test_time_series_plot_missing_observable_in_state():
    """Some trajectory points may lack the observable (sparse emission).
    The plot should silently skip those points without crashing."""
    results = {
        "baseline": {
            "runs": [{
                "run_id": "r1", "params": {},
                "trajectory": [
                    {"step": 0, "time": 0.0, "state": {"level": 1.0}},
                    {"step": 1, "time": 1.0, "state": {}},  # missing
                    {"step": 2, "time": 2.0, "state": {"level": 3.0}},
                ],
            }],
        }
    }
    inst = TimeSeriesPlot.__new__(TimeSeriesPlot)
    inst.config = {}
    html = inst.render_final(
        results,
        config={"observable": "level", "sources": ["baseline"], "title": ""},
    )
    assert "Plotly.newPlot" in html
```

- [ ] **Step 2: Run tests to verify fail**

Run: `cd /Users/eranagmon/code/pbg-superpowers && python -m pytest tests/test_default_visualizations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pbg_superpowers.visualizations'`.

- [ ] **Step 3: Create `pbg_superpowers/visualizations/__init__.py`**

```python
"""Default Visualization classes shipped with pbg-superpowers.

All five inherit ``pbg_superpowers.visualization.Visualization`` and implement
``render_final(results, *, config) -> str``. They are auto-discovered via
``bigraph_schema.package.discover`` so workspaces don't need to register them
manually.

Usage (from a composite or investigation spec):
    visualizations:
      - name: trajectory
        address: "local:TimeSeriesPlot"
        config: {observable: free_DnaA, sources: [baseline]}
"""
from pbg_superpowers.visualizations.time_series import TimeSeriesPlot

__all__ = ["TimeSeriesPlot"]
```

- [ ] **Step 4: Create `pbg_superpowers/visualizations/time_series.py`**

```python
"""TimeSeriesPlot — observable(s) vs time, one line per run."""
from __future__ import annotations
import html as _html
import json
from typing import Any

from pbg_superpowers.visualization import Visualization


_PALETTE = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b',
            '#8b5cf6', '#06b6d4', '#84cc16', '#ec4899']


class TimeSeriesPlot(Visualization):
    """Plot one observable across N runs, one trace per run.

    Config keys:
      observable: str — name of the observable to plot (read from trajectory state)
      sources:    list[str] — which simulations to include (sim names from spec)
      title:      str — optional chart title

    Special config (set by orchestrator, not by user):
      _overlays:  list[dict] — overlay payloads to render alongside primary traces
    """

    def render_final(self, results: dict, *, config: dict) -> str:
        observable = config.get("observable", "")
        sources = config.get("sources") or list(results.keys())
        title = config.get("title", "")
        overlays = config.get("_overlays") or []

        traces: list[dict] = []
        color_idx = 0
        for sim_name in sources:
            sim = results.get(sim_name) or {}
            for run in sim.get("runs", []):
                xs, ys = [], []
                for pt in run.get("trajectory", []):
                    state = pt.get("state") or {}
                    if observable not in state:
                        continue
                    xs.append(pt.get("time"))
                    ys.append(state[observable])
                if not xs:
                    continue
                label = run.get("run_id", "")
                params = run.get("params") or {}
                if params:
                    label = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
                traces.append({
                    "x": xs, "y": ys, "type": "scatter", "mode": "lines",
                    "name": label, "line": {"color": _PALETTE[color_idx % len(_PALETTE)],
                                            "width": 2},
                })
                color_idx += 1

        shapes: list[dict] = []
        annotations: list[dict] = []
        for ov in overlays:
            kind = ov.get("kind")
            if kind == "reference-range":
                y_min, y_max = ov.get("y_min"), ov.get("y_max")
                if y_min is not None and y_max is not None:
                    shapes.append({
                        "type": "rect", "xref": "paper", "yref": "y",
                        "x0": 0, "x1": 1, "y0": y_min, "y1": y_max,
                        "fillcolor": "#fef3c7", "opacity": 0.3, "line": {"width": 0},
                    })
                    annotations.append({
                        "xref": "paper", "yref": "y", "x": 0.02, "y": y_max,
                        "text": _html.escape(ov.get("label", "reference range")),
                        "showarrow": False, "font": {"size": 11, "color": "#92400e"},
                    })
            elif kind == "experimental-points":
                pts = ov.get("points") or []
                if pts:
                    traces.append({
                        "x": [p["x"] for p in pts],
                        "y": [p["y"] for p in pts],
                        "type": "scatter", "mode": "markers",
                        "name": ov.get("label", "experimental"),
                        "marker": {"color": "#000", "size": 8, "symbol": "circle-open"},
                    })
            elif kind == "cross-investigation-series":
                xs = ov.get("x") or []
                ys = ov.get("y") or []
                if xs and ys:
                    traces.append({
                        "x": xs, "y": ys, "type": "scatter", "mode": "lines",
                        "name": ov.get("label", "cross-investigation"),
                        "line": {"color": "#94a3b8", "width": 1.5, "dash": "dash"},
                    })
            elif kind == "warning":
                annotations.append({
                    "xref": "paper", "yref": "paper", "x": 0.5, "y": 1.04,
                    "text": "⚠ overlay: " + _html.escape(ov.get("message", "")),
                    "showarrow": False, "font": {"size": 10, "color": "#991b1b"},
                })

        layout = {
            "title": {"text": _html.escape(title), "font": {"size": 14}},
            "xaxis": {"title": {"text": "time"}},
            "yaxis": {"title": {"text": _html.escape(observable)}},
            "margin": {"l": 55, "r": 15, "t": 40, "b": 40},
            "legend": {"orientation": "h", "y": -0.2},
            "shapes": shapes,
            "annotations": annotations,
        }
        return (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_default_visualizations.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/eranagmon/code/pbg-superpowers
git add pbg_superpowers/visualizations/ tests/test_default_visualizations.py
git commit -m "feat: TimeSeriesPlot default Visualization + render_final tests"
```

---

### Task 3: Default Visualization — `ParamVsObservable`

**Files:**
- Create: `pbg-superpowers/pbg_superpowers/visualizations/param_vs_observable.py`
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/__init__.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Append failing test** to `pbg-superpowers/tests/test_default_visualizations.py`

```python
from pbg_superpowers.visualizations import ParamVsObservable


def _sweep_fixture_results():
    """Sweep over rate=[0.1, 0.5, 1.0]; observable 'level' rises monotonically.
    Final values: 1.5, 7.5, 15.0."""
    runs = []
    for rate in [0.1, 0.5, 1.0]:
        traj = [{"step": i, "time": float(i),
                  "state": {"level": rate * (i + 1) * 3}}
                for i in range(5)]
        runs.append({"run_id": f"r-{rate}", "params": {"rate": rate},
                     "trajectory": traj})
    return {"rate-sweep": {"runs": runs}}


def test_param_vs_observable_final_reduce():
    inst = ParamVsObservable.__new__(ParamVsObservable)
    inst.config = {}
    html = inst.render_final(
        _sweep_fixture_results(),
        config={"sweep": "rate-sweep", "sweep_param": "rate",
                "observable": "level", "reduce": "final", "title": ""},
    )
    assert "Plotly.newPlot" in html
    # The y values for the three rates should appear (1.5, 7.5, 15.0)
    assert "1.5" in html
    assert "15" in html


def test_param_vs_observable_mean_reduce():
    inst = ParamVsObservable.__new__(ParamVsObservable)
    inst.config = {}
    html = inst.render_final(
        _sweep_fixture_results(),
        config={"sweep": "rate-sweep", "sweep_param": "rate",
                "observable": "level", "reduce": "mean", "title": ""},
    )
    assert "Plotly.newPlot" in html
```

- [ ] **Step 2: Run tests to verify fail**

Run: `python -m pytest tests/test_default_visualizations.py::test_param_vs_observable_final_reduce -v`
Expected: FAIL with `ImportError: cannot import name 'ParamVsObservable'`.

- [ ] **Step 3: Create `pbg_superpowers/visualizations/param_vs_observable.py`**

```python
"""ParamVsObservable — sweep parameter vs reduced observable value."""
from __future__ import annotations
import html as _html
import json
import statistics
from typing import Any

from pbg_superpowers.visualization import Visualization


def _reduce(values: list[float], how: str) -> float:
    if not values:
        return float("nan")
    if how == "final":
        return values[-1]
    if how == "mean":
        return statistics.fmean(values)
    if how == "max":
        return max(values)
    if how == "min":
        return min(values)
    if how == "integral":
        # Trapezoidal sum assuming unit step spacing
        return sum((values[i] + values[i + 1]) / 2 for i in range(len(values) - 1))
    return values[-1]  # default to final


class ParamVsObservable(Visualization):
    """Plot sweep parameter values vs a reduced observable across runs.

    Config keys:
      sweep:        str  — name of the simulation block (must be kind=sweep or seeds)
      sweep_param:  str  — parameter name to plot on x-axis
      observable:   str  — observable name to extract from each trajectory
      reduce:       str  — final | mean | max | min | integral
      title:        str  — optional
    """

    def render_final(self, results: dict, *, config: dict) -> str:
        sweep_name = config.get("sweep", "")
        param = config.get("sweep_param", "")
        observable = config.get("observable", "")
        how = config.get("reduce", "final")
        title = config.get("title", "")

        sim = results.get(sweep_name) or {}
        runs = sim.get("runs", [])

        xs, ys = [], []
        for run in runs:
            params = run.get("params") or {}
            if param not in params:
                continue
            traj = run.get("trajectory") or []
            values = [
                pt["state"].get(observable)
                for pt in traj if observable in (pt.get("state") or {})
            ]
            values = [v for v in values if v is not None]
            if not values:
                continue
            xs.append(params[param])
            ys.append(_reduce(values, how))

        # Sort by x for a clean line
        if xs:
            pairs = sorted(zip(xs, ys))
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]

        traces = [{
            "x": xs, "y": ys, "type": "scatter", "mode": "lines+markers",
            "name": observable,
            "line": {"color": "#6366f1", "width": 2},
            "marker": {"color": "#6366f1", "size": 8},
        }]
        layout = {
            "title": {"text": _html.escape(title), "font": {"size": 14}},
            "xaxis": {"title": {"text": _html.escape(param)}},
            "yaxis": {"title": {"text": _html.escape(observable) + " (" + how + ")"}},
            "margin": {"l": 55, "r": 15, "t": 40, "b": 40},
            "showlegend": False,
        }
        return (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )
```

- [ ] **Step 4: Update `pbg_superpowers/visualizations/__init__.py`**

```python
"""Default Visualization classes shipped with pbg-superpowers."""
from pbg_superpowers.visualizations.time_series import TimeSeriesPlot
from pbg_superpowers.visualizations.param_vs_observable import ParamVsObservable

__all__ = ["TimeSeriesPlot", "ParamVsObservable"]
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_default_visualizations.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add pbg_superpowers/visualizations/ tests/test_default_visualizations.py
git commit -m "feat: ParamVsObservable default Visualization"
```

---

### Task 4: Default Visualization — `Distribution`

**Files:**
- Create: `pbg-superpowers/pbg_superpowers/visualizations/distribution.py`
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/__init__.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import Distribution


def _seeds_fixture_results():
    """5 seed runs of the same sim; observable 'level' has noise around 10."""
    runs = []
    for k in range(5):
        traj = [{"step": i, "time": float(i),
                  "state": {"level": 10.0 + k * 0.3}}  # different terminal value per seed
                for i in range(3)]
        runs.append({"run_id": f"r-seed-{k}", "params": {"seed": k},
                     "trajectory": traj})
    return {"replicates": {"runs": runs}}


def test_distribution_histogram_at_final():
    inst = Distribution.__new__(Distribution)
    inst.config = {}
    html = inst.render_final(
        _seeds_fixture_results(),
        config={"observable": "level", "sources": ["replicates"],
                 "at_step": "final", "kind": "histogram", "title": ""},
    )
    assert "Plotly.newPlot" in html
    assert "histogram" in html.lower()
```

- [ ] **Step 2: Run test, confirm fails**

Run: `python -m pytest tests/test_default_visualizations.py::test_distribution_histogram_at_final -v`
Expected: FAIL `ImportError: cannot import name 'Distribution'`.

- [ ] **Step 3: Create `distribution.py`**

```python
"""Distribution — histogram or KDE of an observable across runs."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


class Distribution(Visualization):
    """Plot the distribution of an observable across runs at a fixed step.

    Config keys:
      observable: str
      sources:    list[str]
      at_step:    "final" | int (step index)
      kind:       "histogram" | "kde"  (kde currently renders as histogram with smoothing)
      title:      str
    """

    def render_final(self, results: dict, *, config: dict) -> str:
        observable = config.get("observable", "")
        sources = config.get("sources") or list(results.keys())
        at_step = config.get("at_step", "final")
        kind = config.get("kind", "histogram")
        title = config.get("title", "")

        values: list[float] = []
        for sim_name in sources:
            sim = results.get(sim_name) or {}
            for run in sim.get("runs", []):
                traj = run.get("trajectory") or []
                if not traj:
                    continue
                if at_step == "final":
                    pt = traj[-1]
                else:
                    try:
                        pt = traj[int(at_step)]
                    except (IndexError, ValueError):
                        continue
                state = pt.get("state") or {}
                if observable in state:
                    values.append(state[observable])

        traces = [{
            "x": values, "type": "histogram",
            "marker": {"color": "#6366f1"},
            "opacity": 0.85,
            "name": observable,
        }]
        layout = {
            "title": {"text": _html.escape(title), "font": {"size": 14}},
            "xaxis": {"title": {"text": _html.escape(observable)}},
            "yaxis": {"title": {"text": "count"}},
            "margin": {"l": 55, "r": 15, "t": 40, "b": 40},
            "showlegend": False,
            "bargap": 0.05,
        }
        return (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )
```

- [ ] **Step 4: Update `__init__.py`**

```python
"""Default Visualization classes shipped with pbg-superpowers."""
from pbg_superpowers.visualizations.time_series import TimeSeriesPlot
from pbg_superpowers.visualizations.param_vs_observable import ParamVsObservable
from pbg_superpowers.visualizations.distribution import Distribution

__all__ = ["TimeSeriesPlot", "ParamVsObservable", "Distribution"]
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `python -m pytest tests/test_default_visualizations.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add pbg_superpowers/visualizations/ tests/test_default_visualizations.py
git commit -m "feat: Distribution default Visualization (histogram of observable across runs)"
```

---

### Task 5: Default Visualization — `PhaseSpace`

**Files:**
- Create: `pbg-superpowers/pbg_superpowers/visualizations/phase_space.py`
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/__init__.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import PhaseSpace


def _phase_space_fixture():
    """One run with two observables (x, y) traced over 5 steps."""
    traj = [{"step": i, "time": float(i),
              "state": {"x": float(i), "y": i * i}} for i in range(5)]
    return {"single": {"runs": [{"run_id": "r1", "params": {}, "trajectory": traj}]}}


def test_phase_space_xy_trajectory():
    inst = PhaseSpace.__new__(PhaseSpace)
    inst.config = {}
    html = inst.render_final(
        _phase_space_fixture(),
        config={"x_observable": "x", "y_observable": "y",
                 "sources": ["single"], "title": ""},
    )
    assert "Plotly.newPlot" in html
```

- [ ] **Step 2: Run test, confirm fails**

Run: `python -m pytest tests/test_default_visualizations.py::test_phase_space_xy_trajectory -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Create `phase_space.py`**

```python
"""PhaseSpace — two observables plotted against each other."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization


_PALETTE = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b',
            '#8b5cf6', '#06b6d4', '#84cc16', '#ec4899']


class PhaseSpace(Visualization):
    """Plot two observables against each other (XY trajectory).

    Config keys:
      x_observable: str
      y_observable: str
      sources:      list[str]
      title:        str
    """

    def render_final(self, results: dict, *, config: dict) -> str:
        x_obs = config.get("x_observable", "")
        y_obs = config.get("y_observable", "")
        sources = config.get("sources") or list(results.keys())
        title = config.get("title", "")

        traces = []
        color_idx = 0
        for sim_name in sources:
            sim = results.get(sim_name) or {}
            for run in sim.get("runs", []):
                xs, ys = [], []
                for pt in run.get("trajectory") or []:
                    state = pt.get("state") or {}
                    if x_obs in state and y_obs in state:
                        xs.append(state[x_obs])
                        ys.append(state[y_obs])
                if not xs:
                    continue
                params = run.get("params") or {}
                label = ", ".join(f"{k}={v}" for k, v in sorted(params.items())) \
                        or run.get("run_id", "")
                traces.append({
                    "x": xs, "y": ys, "type": "scatter", "mode": "lines+markers",
                    "name": label,
                    "line": {"color": _PALETTE[color_idx % len(_PALETTE)], "width": 2},
                    "marker": {"size": 5},
                })
                color_idx += 1

        layout = {
            "title": {"text": _html.escape(title), "font": {"size": 14}},
            "xaxis": {"title": {"text": _html.escape(x_obs)}},
            "yaxis": {"title": {"text": _html.escape(y_obs)}},
            "margin": {"l": 55, "r": 15, "t": 40, "b": 40},
            "legend": {"orientation": "h", "y": -0.2},
        }
        return (
            '<div id="viz" style="height:380px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )
```

- [ ] **Step 4: Update `__init__.py`**

```python
"""Default Visualization classes shipped with pbg-superpowers."""
from pbg_superpowers.visualizations.time_series import TimeSeriesPlot
from pbg_superpowers.visualizations.param_vs_observable import ParamVsObservable
from pbg_superpowers.visualizations.distribution import Distribution
from pbg_superpowers.visualizations.phase_space import PhaseSpace

__all__ = ["TimeSeriesPlot", "ParamVsObservable", "Distribution", "PhaseSpace"]
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `python -m pytest tests/test_default_visualizations.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add pbg_superpowers/visualizations/ tests/test_default_visualizations.py
git commit -m "feat: PhaseSpace default Visualization (X vs Y observable trajectory)"
```

---

### Task 6: Default Visualization — `Heatmap`

**Files:**
- Create: `pbg-superpowers/pbg_superpowers/visualizations/heatmap.py`
- Modify: `pbg-superpowers/pbg_superpowers/visualizations/__init__.py`
- Modify: `pbg-superpowers/tests/test_default_visualizations.py`

- [ ] **Step 1: Append test**

```python
from pbg_superpowers.visualizations import Heatmap


def _heatmap_fixture():
    """2D sweep: 3×3 grid over (a, b). Observable 'z' = a * b."""
    runs = []
    for a in [1, 2, 3]:
        for b in [10, 20, 30]:
            traj = [{"step": i, "time": float(i),
                      "state": {"z": float(a * b)}} for i in range(2)]
            runs.append({"run_id": f"r-{a}-{b}", "params": {"a": a, "b": b},
                         "trajectory": traj})
    return {"grid": {"runs": runs}}


def test_heatmap_renders_2d():
    inst = Heatmap.__new__(Heatmap)
    inst.config = {}
    html = inst.render_final(
        _heatmap_fixture(),
        config={"sweep": "grid", "x_param": "a", "y_param": "b",
                 "observable": "z", "reduce": "final", "title": ""},
    )
    assert "Plotly.newPlot" in html
    assert "heatmap" in html.lower()
```

- [ ] **Step 2: Run test, confirm fails**

Run: `python -m pytest tests/test_default_visualizations.py::test_heatmap_renders_2d -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Create `heatmap.py`**

```python
"""Heatmap — 2D parameter sweep, color = reduced observable."""
from __future__ import annotations
import html as _html
import json

from pbg_superpowers.visualization import Visualization
from pbg_superpowers.visualizations.param_vs_observable import _reduce


class Heatmap(Visualization):
    """Plot a 2D parameter sweep as a color matrix.

    Config keys:
      sweep:      str  — name of the simulation block (must be a 2D sweep)
      x_param:    str
      y_param:    str
      observable: str
      reduce:     final | mean | max | min | integral
      title:      str
    """

    def render_final(self, results: dict, *, config: dict) -> str:
        sweep_name = config.get("sweep", "")
        x_param = config.get("x_param", "")
        y_param = config.get("y_param", "")
        observable = config.get("observable", "")
        how = config.get("reduce", "final")
        title = config.get("title", "")

        sim = results.get(sweep_name) or {}
        runs = sim.get("runs", [])

        # Collect (x, y) → reduced(observable)
        cell: dict[tuple, float] = {}
        x_vals: set = set()
        y_vals: set = set()
        for run in runs:
            params = run.get("params") or {}
            if x_param not in params or y_param not in params:
                continue
            traj = run.get("trajectory") or []
            values = [pt["state"][observable]
                      for pt in traj
                      if observable in (pt.get("state") or {})]
            if not values:
                continue
            x, y = params[x_param], params[y_param]
            x_vals.add(x); y_vals.add(y)
            cell[(x, y)] = _reduce(values, how)

        x_sorted = sorted(x_vals)
        y_sorted = sorted(y_vals)
        z = [[cell.get((x, y)) for x in x_sorted] for y in y_sorted]

        traces = [{
            "z": z, "x": x_sorted, "y": y_sorted, "type": "heatmap",
            "colorscale": "Viridis",
            "colorbar": {"title": observable + " (" + how + ")"},
        }]
        layout = {
            "title": {"text": _html.escape(title), "font": {"size": 14}},
            "xaxis": {"title": {"text": _html.escape(x_param)}},
            "yaxis": {"title": {"text": _html.escape(y_param)}},
            "margin": {"l": 55, "r": 60, "t": 40, "b": 40},
        }
        return (
            '<div id="viz" style="height:420px"></div>'
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
            '<script>Plotly.newPlot("viz", '
            + json.dumps(traces) + ", " + json.dumps(layout)
            + ", {responsive:true, displayModeBar:false});</script>"
        )
```

- [ ] **Step 4: Update `__init__.py`**

```python
"""Default Visualization classes shipped with pbg-superpowers."""
from pbg_superpowers.visualizations.time_series import TimeSeriesPlot
from pbg_superpowers.visualizations.param_vs_observable import ParamVsObservable
from pbg_superpowers.visualizations.distribution import Distribution
from pbg_superpowers.visualizations.phase_space import PhaseSpace
from pbg_superpowers.visualizations.heatmap import Heatmap

__all__ = ["TimeSeriesPlot", "ParamVsObservable", "Distribution", "PhaseSpace", "Heatmap"]
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `python -m pytest tests/test_default_visualizations.py -v`
Expected: 9 PASS.

- [ ] **Step 6: Bump pbg-superpowers version + commit + push + tag for PyPI**

```bash
cd /Users/eranagmon/code/pbg-superpowers
# bump pyproject version
sed -i.bak 's/^version = "0.2.0"$/version = "0.3.0"/' pyproject.toml && rm pyproject.toml.bak

git add pbg_superpowers/visualizations/ tests/test_default_visualizations.py pyproject.toml
git commit -m "feat: Heatmap default Visualization (2D sweep color matrix) + bump to 0.3.0"
git push origin main 2>&1 | tail -3
git tag v0.3.0
git push origin v0.3.0 2>&1 | tail -3   # triggers PyPI release workflow
```

---

### Task 7: Investigation backend — `load_spec` + `expand_simulations`

**Files:**
- Create: `pbg-template/scripts/_lib/investigations.py`
- Create: `pbg-template/tests/test_investigations.py`

- [ ] **Step 1: Write failing test**

Create `pbg-template/tests/test_investigations.py`:

```python
"""Unit tests for scripts._lib.investigations."""
import sys
from pathlib import Path

import pytest

_SCRIPTS_PARENT = Path(__file__).parent.parent
if str(_SCRIPTS_PARENT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_PARENT))

from scripts._lib.investigations import (
    load_spec, expand_simulations, InvestigationSpecError,
)


def _write_spec(tmp_path, text):
    p = tmp_path / "spec.yaml"
    p.write_text(text)
    return p


def test_load_spec_valid(tmp_path):
    p = _write_spec(tmp_path, """
name: minimal
composite: pkg.composites.demo
simulations:
  - name: single
    kind: single
    overrides: {rate: 1.0}
    steps: 5
observables: [level]
""")
    spec = load_spec(p)
    assert spec["name"] == "minimal"
    assert spec["composite"] == "pkg.composites.demo"
    assert len(spec["simulations"]) == 1


def test_load_spec_missing_name(tmp_path):
    p = _write_spec(tmp_path, """
composite: pkg.x
simulations: []
observables: []
""")
    with pytest.raises(InvestigationSpecError, match="name"):
        load_spec(p)


def test_load_spec_missing_composite(tmp_path):
    p = _write_spec(tmp_path, """
name: x
simulations: []
observables: []
""")
    with pytest.raises(InvestigationSpecError, match="composite"):
        load_spec(p)


def test_load_spec_bad_simulation_kind(tmp_path):
    p = _write_spec(tmp_path, """
name: x
composite: pkg.x
simulations:
  - {name: s, kind: bogus, steps: 1}
observables: [a]
""")
    with pytest.raises(InvestigationSpecError, match="kind"):
        load_spec(p)


def test_load_spec_seeds_zero(tmp_path):
    p = _write_spec(tmp_path, """
name: x
composite: pkg.x
simulations:
  - {name: s, kind: seeds, n_seeds: 0, steps: 1, base_overrides: {}}
observables: [a]
""")
    with pytest.raises(InvestigationSpecError, match="n_seeds"):
        load_spec(p)


def test_expand_simulations_single():
    spec = {"simulations": [
        {"name": "s1", "kind": "single",
         "overrides": {"rate": 1.0}, "steps": 5},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 1
    assert runs[0]["sim_name"] == "s1"
    assert runs[0]["overrides"] == {"rate": 1.0}
    assert runs[0]["steps"] == 5
    assert "run_label" in runs[0]


def test_expand_simulations_sweep_1d():
    spec = {"simulations": [
        {"name": "sw", "kind": "sweep",
         "sweep_over": {"rate": [0.1, 0.5, 1.0]},
         "base_overrides": {"unbinding": 0.01},
         "steps": 10},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 3
    assert all(r["sim_name"] == "sw" for r in runs)
    rates = sorted(r["overrides"]["rate"] for r in runs)
    assert rates == [0.1, 0.5, 1.0]
    assert all(r["overrides"]["unbinding"] == 0.01 for r in runs)


def test_expand_simulations_sweep_2d():
    spec = {"simulations": [
        {"name": "grid", "kind": "sweep",
         "sweep_over": {"a": [1, 2], "b": [10, 20, 30]},
         "base_overrides": {}, "steps": 1},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 6  # 2 × 3


def test_expand_simulations_seeds():
    spec = {"simulations": [
        {"name": "rep", "kind": "seeds",
         "n_seeds": 5, "base_overrides": {"rate": 0.1}, "steps": 4},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 5
    seeds = sorted(r["overrides"]["seed"] for r in runs)
    assert seeds == [0, 1, 2, 3, 4]
    assert all(r["overrides"]["rate"] == 0.1 for r in runs)


def test_expand_simulations_mixed():
    spec = {"simulations": [
        {"name": "a", "kind": "single", "overrides": {}, "steps": 1},
        {"name": "b", "kind": "sweep", "sweep_over": {"x": [1, 2]},
         "base_overrides": {}, "steps": 1},
        {"name": "c", "kind": "seeds", "n_seeds": 3,
         "base_overrides": {}, "steps": 1},
    ]}
    runs = expand_simulations(spec)
    assert len(runs) == 1 + 2 + 3
    names = {r["sim_name"] for r in runs}
    assert names == {"a", "b", "c"}
```

- [ ] **Step 2: Run tests, confirm fail**

Run: `cd /Users/eranagmon/code/pbg-template && python -m pytest tests/test_investigations.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `scripts/_lib/investigations.py`**

```python
"""Investigation spec loading, validation, and simulation expansion.

An Investigation is a directory at ``investigations/<name>/`` containing a
``spec.yaml`` plus generated artifacts (``runs.db``, ``viz/<name>.html``,
``data/*.csv``, ``notes.md``). This module owns:

  - load_spec(path): parse + validate a single spec.yaml
  - expand_simulations(spec): flatten the three simulation kinds into runs

The orchestration (run a composite for each expanded run, persist via
SQLiteEmitter, render visualizations) lives in further functions added in
subsequent tasks.
"""
from __future__ import annotations
import itertools
from pathlib import Path
from typing import Any

import yaml


class InvestigationSpecError(ValueError):
    """Raised when an investigation spec.yaml fails validation."""


_VALID_KINDS = {"single", "sweep", "seeds"}
_REQUIRED_TOP_LEVEL = ("name", "composite")
_VALID_STATUSES = {"planned", "running", "complete", "failed", "invalid"}


def load_spec(path: Path) -> dict:
    """Parse + validate ``investigations/<name>/spec.yaml``.

    Raises:
        InvestigationSpecError: on any structural problem.
    """
    text = Path(path).read_text()
    try:
        spec = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise InvestigationSpecError(f"malformed YAML: {e}") from e

    if not isinstance(spec, dict):
        raise InvestigationSpecError("spec must be a YAML mapping at top level")

    for field in _REQUIRED_TOP_LEVEL:
        if field not in spec or not spec[field]:
            raise InvestigationSpecError(f"missing required field: {field}")

    sims = spec.get("simulations") or []
    if not isinstance(sims, list):
        raise InvestigationSpecError("simulations must be a list")

    for i, sim in enumerate(sims):
        if not isinstance(sim, dict):
            raise InvestigationSpecError(f"simulations[{i}] must be a mapping")
        if not sim.get("name"):
            raise InvestigationSpecError(f"simulations[{i}].name is required")
        kind = sim.get("kind")
        if kind not in _VALID_KINDS:
            raise InvestigationSpecError(
                f"simulations[{i}].kind must be one of {sorted(_VALID_KINDS)}; got {kind!r}"
            )
        if kind == "sweep":
            sweep_over = sim.get("sweep_over") or {}
            if not isinstance(sweep_over, dict) or not sweep_over:
                raise InvestigationSpecError(
                    f"simulations[{i}].sweep_over must be a non-empty mapping"
                )
            for k, vals in sweep_over.items():
                if not isinstance(vals, list) or not vals:
                    raise InvestigationSpecError(
                        f"simulations[{i}].sweep_over.{k} must be a non-empty list"
                    )
        elif kind == "seeds":
            n = sim.get("n_seeds", 0)
            if not isinstance(n, int) or n < 1:
                raise InvestigationSpecError(
                    f"simulations[{i}].n_seeds must be a positive integer; got {n!r}"
                )
        steps = sim.get("steps", 0)
        if not isinstance(steps, int) or steps < 1:
            raise InvestigationSpecError(
                f"simulations[{i}].steps must be a positive integer"
            )

    observables = spec.get("observables") or []
    if not isinstance(observables, list):
        raise InvestigationSpecError("observables must be a list")

    visualizations = spec.get("visualizations") or []
    if not isinstance(visualizations, list):
        raise InvestigationSpecError("visualizations must be a list")
    for i, viz in enumerate(visualizations):
        if not isinstance(viz, dict):
            raise InvestigationSpecError(f"visualizations[{i}] must be a mapping")
        if not viz.get("name"):
            raise InvestigationSpecError(f"visualizations[{i}].name is required")
        if not viz.get("address"):
            raise InvestigationSpecError(f"visualizations[{i}].address is required")

    return spec


def expand_simulations(spec: dict) -> list[dict]:
    """Flatten ``spec.simulations`` into a list of concrete runs.

    Each returned entry has keys:
      sim_name: str  — name of the originating simulation block
      run_label: str — unique label within the simulation (e.g. 'rate=0.1', 'seed=2')
      overrides: dict — composite parameter overrides for this run
      steps: int     — number of composite ticks
    """
    out: list[dict] = []
    for sim in spec.get("simulations") or []:
        kind = sim["kind"]
        steps = int(sim["steps"])
        if kind == "single":
            out.append({
                "sim_name": sim["name"],
                "run_label": "single",
                "overrides": dict(sim.get("overrides") or {}),
                "steps": steps,
            })
        elif kind == "sweep":
            sweep_over = sim["sweep_over"]
            base = sim.get("base_overrides") or {}
            keys = list(sweep_over.keys())
            value_lists = [sweep_over[k] for k in keys]
            for combo in itertools.product(*value_lists):
                ovr = dict(base)
                for k, v in zip(keys, combo):
                    ovr[k] = v
                label = ", ".join(f"{k}={ovr[k]}" for k in keys)
                out.append({
                    "sim_name": sim["name"],
                    "run_label": label,
                    "overrides": ovr,
                    "steps": steps,
                })
        elif kind == "seeds":
            n = int(sim["n_seeds"])
            base = sim.get("base_overrides") or {}
            for k in range(n):
                ovr = dict(base)
                ovr["seed"] = k
                out.append({
                    "sim_name": sim["name"],
                    "run_label": f"seed={k}",
                    "overrides": ovr,
                    "steps": steps,
                })
    return out
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `python -m pytest tests/test_investigations.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_lib/investigations.py tests/test_investigations.py
git commit -m "feat: investigations.py — load_spec + expand_simulations (single/sweep/seeds)"
```

---

### Task 8: Investigation backend — `gather_results` + `load_overlays`

**Files:**
- Modify: `pbg-template/scripts/_lib/investigations.py` (append)
- Modify: `pbg-template/tests/test_investigations.py` (append)

- [ ] **Step 1: Append failing tests**

```python
import json
import sqlite3

from scripts._lib.investigations import gather_results, load_overlays


def _setup_runs_db(tmp_path):
    """Create a minimal runs.db matching the SQLiteEmitter + runs_meta shape."""
    db = tmp_path / "runs.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE runs_meta (
            run_id TEXT PRIMARY KEY, spec_id TEXT, sim_name TEXT,
            label TEXT, params_json TEXT, started_at REAL,
            completed_at REAL, n_steps INTEGER, status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulation_id TEXT, step INTEGER, global_time REAL, state TEXT
        )
    """)
    # one sim "single" with one run, three step rows
    conn.execute(
        "INSERT INTO runs_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("r1", "spec", "single", "single", json.dumps({"rate": 1.0}),
         0.0, 1.0, 3, "completed"),
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO history (simulation_id, step, global_time, state) VALUES (?, ?, ?, ?)",
            ("r1", i, float(i), json.dumps({"level": float(i + 1)})),
        )
    conn.commit()
    conn.close()
    return db


def test_gather_results_one_sim_one_run(tmp_path):
    db = _setup_runs_db(tmp_path)
    spec = {"simulations": [{"name": "single", "kind": "single",
                              "overrides": {"rate": 1.0}, "steps": 3}]}
    results = gather_results(spec, db)
    assert "single" in results
    assert len(results["single"]["runs"]) == 1
    run = results["single"]["runs"][0]
    assert run["run_id"] == "r1"
    assert run["params"] == {"rate": 1.0}
    assert len(run["trajectory"]) == 3
    assert run["trajectory"][2]["state"] == {"level": 3.0}


def test_load_overlays_reference_range(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "reference-range", "y_min": 1.0, "y_max": 5.0,
                          "label": "x"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "reference-range"
    assert payload[0]["y_min"] == 1.0


def test_load_overlays_experimental_points_missing_csv(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "experimental-points",
                          "data": "data/missing.csv",
                          "x_column": "t", "y_column": "v",
                          "label": "experiments"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "warning"
    assert "missing" in payload[0]["message"]


def test_load_overlays_experimental_points_ok(tmp_path):
    inv_dir = tmp_path / "investigations" / "demo"
    inv_dir.mkdir(parents=True)
    data_dir = inv_dir / "data"
    data_dir.mkdir()
    (data_dir / "exp.csv").write_text("t,v\n0,1.0\n1,2.5\n2,3.7\n")
    spec = {}
    viz = {"overlays": [{"kind": "experimental-points",
                          "data": "data/exp.csv",
                          "x_column": "t", "y_column": "v",
                          "label": "exp"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "experimental-points"
    assert payload[0]["points"] == [
        {"x": "0", "y": "1.0"}, {"x": "1", "y": "2.5"}, {"x": "2", "y": "3.7"},
    ]


def test_load_overlays_cross_investigation_missing(tmp_path):
    spec = {}
    viz = {"overlays": [{"kind": "cross-investigation-series",
                          "investigation": "ghost", "observable": "x",
                          "label": "ghost"}]}
    payload = load_overlays(spec, viz, tmp_path, "demo")
    assert len(payload) == 1
    assert payload[0]["kind"] == "warning"
```

- [ ] **Step 2: Run tests, confirm fail**

Run: `python -m pytest tests/test_investigations.py -v`
Expected: 5 new tests FAIL (`ImportError: cannot import name 'gather_results'`).

- [ ] **Step 3: Append to `scripts/_lib/investigations.py`**

```python
# ----------------------------------------------------------------------------
# Results aggregation + overlay resolution
# ----------------------------------------------------------------------------

import csv
import json
import sqlite3


def gather_results(spec: dict, db_path: Path) -> dict:
    """Read the investigation's runs.db and group trajectories by sim_name.

    Returns: {<sim_name>: {"runs": [{"run_id", "params", "trajectory"}, ...]}}

    Trajectory shape: [{"step", "time", "state"}, ...] where ``state`` is a
    parsed JSON dict (whatever SQLiteEmitter wrote).
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, dict] = {}
        # All metadata rows for this investigation
        meta_rows = conn.execute(
            "SELECT run_id, sim_name, params_json FROM runs_meta"
        ).fetchall()
        run_meta: dict[str, dict] = {}
        for row in meta_rows:
            try:
                params = json.loads(row["params_json"] or "{}")
            except json.JSONDecodeError:
                params = {}
            run_meta[row["run_id"]] = {
                "sim_name": row["sim_name"] or "default",
                "params": params,
            }
        # Trajectories per run
        for run_id, meta in run_meta.items():
            traj_rows = conn.execute(
                "SELECT step, global_time AS time, state FROM history "
                "WHERE simulation_id=? ORDER BY step ASC",
                (run_id,),
            ).fetchall()
            traj = []
            for tr in traj_rows:
                try:
                    state = json.loads(tr["state"]) if tr["state"] else {}
                except json.JSONDecodeError:
                    state = {}
                traj.append({"step": tr["step"], "time": tr["time"], "state": state})
            sim_name = meta["sim_name"]
            out.setdefault(sim_name, {"runs": []})
            out[sim_name]["runs"].append({
                "run_id": run_id, "params": meta["params"], "trajectory": traj,
            })
    finally:
        conn.close()
    return out


def load_overlays(spec: dict, viz_config: dict, ws_root: Path,
                  investigation_name: str) -> list[dict]:
    """Resolve each overlay entry into a uniform payload.

    Args:
        spec: the parent investigation spec (for context if needed)
        viz_config: the visualization dict, expected to have an 'overlays' list
        ws_root: workspace root path (overlay files are resolved relative to
                 investigations/<investigation_name>/)
        investigation_name: directory name of the current investigation

    Returns: list of overlay payload dicts. Failed lookups become
        {"kind": "warning", "message": "..."} so visualizations can either
        skip them or annotate the figure.
    """
    overlays = viz_config.get("overlays") or []
    payload: list[dict] = []
    inv_dir = Path(ws_root) / "investigations" / investigation_name

    for ov in overlays:
        kind = ov.get("kind")
        if kind == "reference-range":
            payload.append({
                "kind": "reference-range",
                "y_min": ov.get("y_min"),
                "y_max": ov.get("y_max"),
                "label": ov.get("label", "reference range"),
            })
        elif kind == "experimental-points":
            data_rel = ov.get("data") or ""
            data_path = inv_dir / data_rel
            if not data_path.is_file():
                payload.append({
                    "kind": "warning",
                    "message": f"experimental-points file missing: {data_rel}",
                })
                continue
            x_col = ov.get("x_column", "x")
            y_col = ov.get("y_column", "y")
            try:
                with data_path.open() as fh:
                    reader = csv.DictReader(fh)
                    points = [{"x": r.get(x_col), "y": r.get(y_col)} for r in reader]
            except Exception as e:
                payload.append({
                    "kind": "warning",
                    "message": f"experimental-points read failed: {e}",
                })
                continue
            payload.append({
                "kind": "experimental-points",
                "label": ov.get("label", "experimental"),
                "points": points,
            })
        elif kind == "cross-investigation-series":
            other_name = ov.get("investigation", "")
            other_db = Path(ws_root) / "investigations" / other_name / "runs.db"
            if not other_db.is_file():
                payload.append({
                    "kind": "warning",
                    "message": f"cross-investigation reference not found: {other_name}",
                })
                continue
            other_obs = ov.get("observable", "")
            xs, ys = [], []
            conn = sqlite3.connect(str(other_db))
            try:
                rows = conn.execute(
                    "SELECT global_time, state FROM history ORDER BY step ASC"
                ).fetchall()
                for tm, st in rows:
                    try:
                        s = json.loads(st) if st else {}
                    except json.JSONDecodeError:
                        continue
                    if other_obs in s:
                        xs.append(tm)
                        ys.append(s[other_obs])
            finally:
                conn.close()
            if not xs:
                payload.append({
                    "kind": "warning",
                    "message": f"cross-investigation observable not present: {other_obs} in {other_name}",
                })
                continue
            payload.append({
                "kind": "cross-investigation-series",
                "label": ov.get("label", f"{other_name}.{other_obs}"),
                "style": ov.get("style", "dashed-line"),
                "x": xs, "y": ys,
            })
        else:
            payload.append({
                "kind": "warning",
                "message": f"unknown overlay kind: {kind!r}",
            })
    return payload
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `python -m pytest tests/test_investigations.py -v`
Expected: 15 PASS (10 from Task 7 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib/investigations.py tests/test_investigations.py
git commit -m "feat: investigations.py — gather_results + load_overlays (CSV, ref-range, cross-investigation)"
```

---

### Task 9: Investigation backend — `run_investigation` orchestrator

**Files:**
- Modify: `pbg-template/scripts/_lib/investigations.py` (append)
- Modify: `pbg-template/tests/test_investigations.py` (append)

- [ ] **Step 1: Append failing test** (unit test for `run_investigation` is best done via the E2E test in Task 14; here we add a small test for the spec status updater and the lock file helper)

```python
from scripts._lib.investigations import (
    update_spec_status, acquire_run_lock, release_run_lock,
)


def test_update_spec_status_writes_status_and_last_run(tmp_path):
    inv_dir = tmp_path / "investigations" / "demo"
    inv_dir.mkdir(parents=True)
    (inv_dir / "spec.yaml").write_text("""
name: demo
composite: pkg.x
simulations: []
observables: []
status: planned
""")
    update_spec_status(tmp_path, "demo", status="complete", last_run="2026-05-12T10:00:00")
    new_text = (inv_dir / "spec.yaml").read_text()
    assert "status: complete" in new_text
    assert "2026-05-12T10:00:00" in new_text


def test_acquire_and_release_run_lock(tmp_path):
    inv_dir = tmp_path / "investigations" / "x"
    inv_dir.mkdir(parents=True)
    assert acquire_run_lock(tmp_path, "x") is True
    # Second acquire on same investigation must fail
    assert acquire_run_lock(tmp_path, "x") is False
    release_run_lock(tmp_path, "x")
    # After release, acquire succeeds again
    assert acquire_run_lock(tmp_path, "x") is True
    release_run_lock(tmp_path, "x")
```

- [ ] **Step 2: Run tests, confirm fail**

Run: `python -m pytest tests/test_investigations.py -v`
Expected: 2 new tests FAIL with ImportError.

- [ ] **Step 3: Append helpers + orchestrator to `scripts/_lib/investigations.py`**

```python
# ----------------------------------------------------------------------------
# Spec status updater + run lock + orchestrator
# ----------------------------------------------------------------------------

import datetime
import errno


def update_spec_status(ws_root: Path, name: str, *, status: str,
                       last_run: str | None = None) -> None:
    """Update the status + last_run fields in investigations/<name>/spec.yaml.

    Preserves the rest of the spec verbatim by parsing → mutating → re-dumping.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; must be one of {sorted(_VALID_STATUSES)}")
    spec_path = Path(ws_root) / "investigations" / name / "spec.yaml"
    spec = yaml.safe_load(spec_path.read_text()) or {}
    spec["status"] = status
    if last_run is not None:
        spec["last_run"] = last_run
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))


def _lock_path(ws_root: Path, name: str) -> Path:
    return Path(ws_root) / "investigations" / name / ".run.lock"


def acquire_run_lock(ws_root: Path, name: str) -> bool:
    """Try to acquire an exclusive run lock for one investigation.

    Returns True if acquired, False if another run is already in progress.
    """
    lock = _lock_path(ws_root, name)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = lock.open("x")
        fd.write(str(datetime.datetime.utcnow()))
        fd.close()
        return True
    except FileExistsError:
        return False


def release_run_lock(ws_root: Path, name: str) -> None:
    """Release the run lock. No-op if the lock doesn't exist."""
    lock = _lock_path(ws_root, name)
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


def run_investigation(ws_root: Path, name: str, *,
                      run_one_composite: callable,
                      core_registry: dict) -> dict:
    """Top-level orchestrator. Returns a summary dict.

    Args:
        ws_root: workspace root path
        name: investigation directory name
        run_one_composite: callable(spec_id, overrides, steps, sim_name,
            run_id, db_file) -> {"status": "completed"|"failed", "error"?: str}
            (injected so the orchestrator can be unit-tested with a mock;
            in production the server passes a function that resolves the
            composite + subprocess-runs it the same way _post_composite_test_run does)
        core_registry: process_bigraph core.link_registry — used to look up
            Visualization classes by address (e.g. "local:TimeSeriesPlot")

    Side effects: writes runs.db + viz/<name>.html, updates spec.yaml.

    Returns:
        {name, n_runs, n_visualizations, status, viz_paths, errors}
    """
    from scripts._lib import composite_runs as cr

    ws_root = Path(ws_root)
    inv_dir = ws_root / "investigations" / name
    spec_path = inv_dir / "spec.yaml"
    spec = load_spec(spec_path)  # raises InvestigationSpecError on bad shape

    if not acquire_run_lock(ws_root, name):
        return {"name": name, "error": "investigation is already running",
                "status": "running"}

    try:
        update_spec_status(ws_root, name, status="running")
        db_file = str(inv_dir / "runs.db")
        # Clear prior runs (re-runs replace results)
        prior = inv_dir / "runs.db"
        if prior.exists():
            prior.unlink()
        conn = cr.connect(db_file)
        # Add sim_name column to runs_meta if our local copy doesn't have it.
        try:
            conn.execute("ALTER TABLE runs_meta ADD COLUMN sim_name TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        # Expand + run each simulation
        expanded = expand_simulations(spec)
        errors: list[dict] = []
        any_failed = False
        for run in expanded:
            run_id = cr.generate_run_id(spec["composite"], run["overrides"])
            cr.save_metadata(conn, spec_id=spec["composite"], run_id=run_id,
                              params=run["overrides"],
                              label=run["run_label"],
                              started_at=__import__("time").time())
            # Stamp sim_name on the row
            conn.execute("UPDATE runs_meta SET sim_name=? WHERE run_id=?",
                          (run["sim_name"], run_id))
            conn.commit()
            res = run_one_composite(
                spec_id=spec["composite"],
                overrides=run["overrides"],
                steps=run["steps"],
                sim_name=run["sim_name"],
                run_id=run_id,
                db_file=db_file,
            )
            if res.get("status") == "completed":
                cr.complete_metadata(conn, run_id=run_id, n_steps=run["steps"],
                                      status="completed")
            else:
                any_failed = True
                cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="failed")
                errors.append({"run_id": run_id, "error": res.get("error", "")})
        conn.close()

        # Visualization pass
        results = gather_results(spec, Path(db_file))
        viz_paths = render_visualizations(spec, results, ws_root, name,
                                           core_registry=core_registry)

        final_status = "complete" if not any_failed else "failed"
        update_spec_status(ws_root, name, status=final_status,
                           last_run=datetime.datetime.utcnow().isoformat())

        return {
            "name": name,
            "n_runs": len(expanded),
            "n_visualizations": len(viz_paths),
            "status": final_status,
            "viz_paths": [str(p) for p in viz_paths],
            "errors": errors,
        }
    except Exception as e:
        update_spec_status(ws_root, name, status="failed")
        raise
    finally:
        release_run_lock(ws_root, name)


def render_visualizations(spec: dict, results: dict, ws_root: Path,
                          name: str, *, core_registry: dict) -> list[Path]:
    """For each viz in the spec, look up its Visualization class and call render_final.

    Writes HTML to investigations/<name>/viz/<viz-name>.html. Returns paths written.
    """
    inv_dir = Path(ws_root) / "investigations" / name
    viz_dir = inv_dir / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for viz in spec.get("visualizations") or []:
        addr = viz["address"]
        # Strip the optional "local:" prefix to match registry keys
        class_key = addr.split(":", 1)[1] if ":" in addr else addr
        viz_class = core_registry.get(class_key)
        if viz_class is None:
            # Skip — write a stub HTML so the UI shows an error
            stub = viz_dir / f"{viz['name']}.html"
            stub.write_text(
                f"<p style='color:#991b1b'>Visualization class not registered: "
                f"<code>{addr}</code>. Install the package that ships it.</p>"
            )
            paths.append(stub)
            continue
        config = dict(viz.get("config") or {})
        config["_overlays"] = load_overlays(spec, viz, ws_root, name)
        try:
            instance = viz_class.__new__(viz_class)
            html = instance.render_final(results, config=config)
        except Exception as e:
            html = (
                f"<p style='color:#991b1b'>render_final failed for "
                f"<code>{viz['name']}</code>: <code>{e}</code></p>"
            )
        target = viz_dir / f"{viz['name']}.html"
        target.write_text(html)
        paths.append(target)
    return paths
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `python -m pytest tests/test_investigations.py -v`
Expected: 17 PASS (15 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib/investigations.py tests/test_investigations.py
git commit -m "feat: investigations.run_investigation orchestrator + render_visualizations + run lock"
```

---

### Task 10: Server endpoint — `GET /api/investigations`

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`

- [ ] **Step 1: Add the handler** — insert next to existing investigation-related endpoints (or near `_get_composites` for cohesion):

```python
    def _get_investigations(self):
        """GET /api/investigations — return summaries of all investigations."""
        _ws_add_to_sys_path()
        from scripts._lib.investigations import load_spec, InvestigationSpecError

        inv_root = WORKSPACE / "investigations"
        if not inv_root.is_dir():
            return self._json({"investigations": []}, 200)
        out = []
        for d in sorted(inv_root.iterdir()):
            if not d.is_dir():
                continue
            spec_path = d / "spec.yaml"
            if not spec_path.is_file():
                continue
            try:
                spec = load_spec(spec_path)
                out.append({
                    "name": spec["name"],
                    "composite": spec["composite"],
                    "description": spec.get("description", ""),
                    "tags": spec.get("tags") or [],
                    "status": spec.get("status", "planned"),
                    "last_run": spec.get("last_run"),
                    "n_simulations": len(spec.get("simulations") or []),
                })
            except InvestigationSpecError as e:
                out.append({
                    "name": d.name, "status": "invalid", "error": str(e),
                })
        return self._json({"investigations": out}, 200)
```

- [ ] **Step 2: Wire dispatch in `do_GET`** — add before more-specific paths (no collisions because `/api/investigation/` (singular) is more specific):

```python
        if self.path.startswith("/api/investigations"):
            return self._get_investigations()
```

- [ ] **Step 3: Smoke test by hand** — start the server in a fixture workspace, hit the endpoint:

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
cp /Users/eranagmon/code/pbg-template/scripts/_server/server.py scripts/_server/server.py
mkdir -p investigations
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])" 2>/dev/null || echo 0)
[ "$PORT" != "0" ] && curl -s "http://localhost:$PORT/api/investigations"
```

Expected: `{"investigations": []}` (workspace has no investigations yet).

- [ ] **Step 4: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/server.py
git commit -m "feat: GET /api/investigations — list all investigations + summaries"
```

---

### Task 11: Server endpoint — `GET /api/investigation/<name>`

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`

- [ ] **Step 1: Add the handler**

```python
    def _get_investigation_detail(self):
        """GET /api/investigation/<name> — full spec + viz file paths + runs summary."""
        _ws_add_to_sys_path()
        from scripts._lib.investigations import load_spec, InvestigationSpecError
        from scripts._lib import composite_runs as cr

        path_only = self.path.split("?", 1)[0]
        rest = path_only[len("/api/investigation/"):]
        if "/" in rest or not rest:
            return self._json({"error": "bad route"}, 400)
        name = rest

        inv_dir = WORKSPACE / "investigations" / name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)
        try:
            spec = load_spec(spec_path)
        except InvestigationSpecError as e:
            return self._json({"error": str(e), "name": name, "status": "invalid"}, 200)

        viz_dir = inv_dir / "viz"
        viz_files = []
        if viz_dir.is_dir():
            for v in sorted(viz_dir.glob("*.html")):
                viz_files.append({"name": v.stem, "path": str(v.relative_to(WORKSPACE))})

        runs_summary = []
        db = inv_dir / "runs.db"
        if db.is_file():
            conn = cr.connect(db)
            try:
                rows = conn.execute(
                    "SELECT run_id, sim_name, label, params_json, status, n_steps "
                    "FROM runs_meta ORDER BY started_at DESC"
                ).fetchall()
                for r in rows:
                    import json as _j
                    try:
                        params = _j.loads(r["params_json"] or "{}")
                    except _j.JSONDecodeError:
                        params = {}
                    runs_summary.append({
                        "run_id": r["run_id"], "sim_name": r["sim_name"] or "",
                        "label": r["label"] or "", "params": params,
                        "status": r["status"], "n_steps": r["n_steps"] or 0,
                    })
            finally:
                conn.close()

        return self._json({
            "name": name,
            "spec": spec,
            "viz_files": viz_files,
            "runs_summary": runs_summary,
        }, 200)
```

- [ ] **Step 2: Wire dispatch** in `do_GET` BEFORE the `/api/investigations` (plural) entry, so the more-specific singular route matches first:

```python
        if self.path.startswith("/api/investigation/"):
            return self._get_investigation_detail()
        if self.path.startswith("/api/investigations"):
            return self._get_investigations()
```

- [ ] **Step 3: Smoke test**

```bash
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
curl -s "http://localhost:$PORT/api/investigation/nonexistent"
```

Expected: `{"error": "investigation not found"}` with HTTP 404.

- [ ] **Step 4: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/server.py
git commit -m "feat: GET /api/investigation/<name> — spec + viz files + runs summary"
```

---

### Task 12: Server endpoint — `POST /api/investigation-create`

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`

- [ ] **Step 1: Add handler**

```python
    def _post_investigation_create(self, body: dict):
        """POST /api/investigation-create {name, composite} — scaffold a new investigation."""
        name = (body.get("name") or "").strip()
        composite = (body.get("composite") or "").strip()
        if not name or not composite:
            return self._json({"error": "name and composite are required"}, 400)
        # Validate name shape (slug-like)
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", name):
            return self._json({"error": "name must match [a-zA-Z0-9_-]+"}, 400)

        inv_dir = WORKSPACE / "investigations" / name
        if inv_dir.exists():
            return self._json({"error": f"investigation '{name}' already exists"}, 409)

        def action():
            inv_dir.mkdir(parents=True, exist_ok=False)
            (inv_dir / "data").mkdir()
            (inv_dir / "data" / ".keep").write_text("")
            # Minimal spec.yaml stub
            stub = (
                f"name: {name}\n"
                f"description: \"\"\n"
                f"composite: {composite}\n"
                f"\n"
                f"simulations:\n"
                f"  - name: baseline\n"
                f"    kind: single\n"
                f"    overrides: {{}}\n"
                f"    steps: 10\n"
                f"\n"
                f"observables: []\n"
                f"\n"
                f"visualizations: []\n"
                f"\n"
                f"status: planned\n"
            )
            (inv_dir / "spec.yaml").write_text(stub)

        commit_msg = f"feat(investigations): scaffold {name}"
        resp, code = _active_branch_action(commit_msg, action)
        if code == 200:
            resp.update({"ok": True, "name": name})
        return self._json(resp, code)
```

- [ ] **Step 2: Wire dispatch** in `do_POST` endpoint dict:

```python
            "/api/investigation-create": self._post_investigation_create,
```

- [ ] **Step 3: Smoke test**

```bash
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
curl -s -X POST "http://localhost:$PORT/api/investigation-create" \
     -H 'Content-Type: application/json' \
     -d '{"name":"smoke","composite":"pbg_chromosome_rep1.composites.dnaa-binding"}'
ls investigations/smoke/
rm -rf investigations/smoke/   # cleanup smoke test
```

Expected: response includes `ok: true`; directory + `spec.yaml` + `data/.keep` created.

- [ ] **Step 4: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: POST /api/investigation-create — scaffold investigation directory"
```

---

### Task 13: Server endpoint — `POST /api/investigation-delete`

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`

- [ ] **Step 1: Add handler**

```python
    def _post_investigation_delete(self, body: dict):
        """POST /api/investigation-delete {name} — remove investigation directory."""
        import shutil
        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)
        inv_dir = WORKSPACE / "investigations" / name
        if not inv_dir.is_dir():
            return self._json({"error": f"investigation '{name}' not found"}, 404)

        def action():
            shutil.rmtree(inv_dir)

        commit_msg = f"feat(investigations): delete {name}"
        resp, code = _active_branch_action(commit_msg, action)
        if code == 200:
            resp.update({"ok": True, "name": name})
        return self._json(resp, code)
```

- [ ] **Step 2: Wire dispatch** in `do_POST`:

```python
            "/api/investigation-delete": self._post_investigation_delete,
```

- [ ] **Step 3: Smoke test (round-trip with create)**

```bash
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
curl -s -X POST "http://localhost:$PORT/api/investigation-create" \
     -H 'Content-Type: application/json' \
     -d '{"name":"smoke-del","composite":"pbg_chromosome_rep1.composites.dnaa-binding"}'
curl -s -X POST "http://localhost:$PORT/api/investigation-delete" \
     -H 'Content-Type: application/json' \
     -d '{"name":"smoke-del"}'
ls investigations/smoke-del/ 2>&1
```

Expected: directory created then deleted; final `ls` returns "No such file".

- [ ] **Step 4: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: POST /api/investigation-delete — remove investigation directory"
```

---

### Task 14: Server endpoint — `POST /api/investigation-run` + integration test

**Files:**
- Modify: `pbg-template/scripts/_server/server.py`
- Create: `pbg-template/tests/test_investigation_run_e2e.py`

- [ ] **Step 1: Write the failing integration test**

Create `pbg-template/tests/test_investigation_run_e2e.py`:

```python
"""End-to-end test of the /api/investigation-run lifecycle.

Reuses the ws_increase_demo fixture from test_composite_explorer_api.py
plus a fixture investigation in tests/_fixtures/ws_increase_demo/investigations/baseline/.
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
import socket
import subprocess
import shutil
import os

import pytest

_REPO_ROOT = Path(__file__).parent.parent
FIXTURE_WORKSPACE = _REPO_ROOT / "tests" / "_fixtures" / "ws_increase_demo"


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture
def server(tmp_path):
    if not FIXTURE_WORKSPACE.is_dir():
        pytest.skip(f"Fixture workspace not present at {FIXTURE_WORKSPACE}")
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_WORKSPACE, ws)
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, str(_REPO_ROOT / "scripts" / "_server" / "server.py"),
         "--workspace", str(ws), "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    info_path = ws / ".pbg" / "server" / "server-info"
    for _ in range(40):
        if info_path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=2)
        pytest.fail(f"server did not start:\n{out.decode()}\n{err.decode()}")
    yield {"url": f"http://127.0.0.1:{port}", "ws": ws}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()


def _post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode())


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def test_list_includes_fixture_investigation(server):
    status, body = _get(f"{server['url']}/api/investigations")
    assert status == 200
    names = [inv["name"] for inv in body["investigations"]]
    assert "baseline" in names


def test_run_baseline_investigation(server):
    status, body = _post(f"{server['url']}/api/investigation-run", {"name": "baseline"})
    assert status == 200, body
    assert body["status"] == "complete"
    assert body["n_runs"] == 4  # 1 single + 3 sweep
    assert body["n_visualizations"] == 1
    db = server["ws"] / "investigations" / "baseline" / "runs.db"
    assert db.is_file()
    viz = server["ws"] / "investigations" / "baseline" / "viz" / "levels.html"
    assert viz.is_file()
    assert viz.stat().st_size > 1000
    assert "Plotly.newPlot" in viz.read_text()


def test_detail_after_run(server):
    _post(f"{server['url']}/api/investigation-run", {"name": "baseline"})
    status, body = _get(f"{server['url']}/api/investigation/baseline")
    assert status == 200
    assert body["spec"]["status"] == "complete"
    assert len(body["runs_summary"]) == 4
    assert any(v["name"] == "levels" for v in body["viz_files"])
```

- [ ] **Step 2: Create the fixture investigation**

```bash
mkdir -p tests/_fixtures/ws_increase_demo/investigations/baseline/data
```

Write `tests/_fixtures/ws_increase_demo/investigations/baseline/spec.yaml`:

```yaml
name: baseline
description: "Sanity-check fixture investigation."
composite: pbg_ws_increase_demo.composites.increase-demo
simulations:
  - name: single
    kind: single
    overrides: {rate: 2.0}
    steps: 5
  - name: rate-sweep
    kind: sweep
    sweep_over: {rate: [1.0, 2.0, 4.0]}
    base_overrides: {}
    steps: 5
observables: [level]
visualizations:
  - name: levels
    address: "local:TimeSeriesPlot"
    config:
      observable: level
      sources: [single, rate-sweep]
      title: "Level trajectories"
status: planned
```

Add `tests/_fixtures/ws_increase_demo/investigations/baseline/data/.keep`.

- [ ] **Step 3: Run the test, confirm fails**

Run: `python -m pytest tests/test_investigation_run_e2e.py -v`
Expected: list test passes, the run test fails because the endpoint isn't there yet.

- [ ] **Step 4: Add `/api/investigation-run` handler** in `scripts/_server/server.py`

```python
    def _post_investigation_run(self, body: dict):
        """POST /api/investigation-run {name} — run all simulations + render visualizations."""
        _ws_add_to_sys_path()
        from scripts._lib.investigations import (
            run_investigation, InvestigationSpecError,
        )
        from scripts._lib.composite_lookup import substitute_parameters, find_composite_path
        from scripts._lib import composite_runs as cr

        name = (body.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, 400)

        # Verify the workspace package + core to register Visualization classes.
        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))

        def run_one_composite(*, spec_id, overrides, steps, sim_name, run_id, db_file):
            """Run one composite via subprocess. Matches _post_composite_test_run shape."""
            path = find_composite_path(WORKSPACE, pkg, spec_id)
            if path is None:
                return {"status": "failed", "error": f"composite not found: {spec_id}"}
            text = path.read_text()
            spec = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
            state = substitute_parameters(spec.get("state") or {},
                                          spec.get("parameters") or {},
                                          overrides)
            state = cr.inject_sqlite_emitter(state, run_id=run_id, db_file=db_file)

            py = sys.executable
            script = textwrap.dedent(f"""
                import json, sys, traceback
                try:
                    from {pkg}.core import build_core
                    from process_bigraph import Composite
                    from process_bigraph.emitter import SQLiteEmitter
                    core = build_core()
                    core.register_link('SQLiteEmitter', SQLiteEmitter)
                    composite = Composite({{'state': {json.dumps(state)}}}, core=core)
                    composite.run({steps})
                    print('@@@OK@@@')
                except Exception as e:
                    print('@@@ERROR@@@')
                    print(traceback.format_exc())
            """)
            try:
                result = subprocess.run([py, "-c", script], cwd=WORKSPACE,
                                         capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired as exc:
                try:
                    if exc.process: exc.process.kill(); exc.process.communicate(timeout=2)
                except Exception: pass
                return {"status": "failed", "error": "timeout"}
            if "@@@ERROR@@@" in result.stdout:
                return {"status": "failed",
                         "error": result.stdout.split("@@@ERROR@@@", 1)[1].strip()[-500:]}
            if "@@@OK@@@" not in result.stdout:
                return {"status": "failed",
                         "error": "runner returned unexpected output"}
            return {"status": "completed"}

        # Build the visualization registry. We need the workspace's core for
        # the Visualization class lookup; import the workspace package and
        # build a fresh core here (in-process, no subprocess needed).
        sys.path.insert(0, str(WORKSPACE))
        try:
            core_module = __import__(f"{pkg}.core", fromlist=["build_core"])
            core = core_module.build_core()
            registry = dict(core.link_registry)
        except Exception as e:
            return self._json({"error": f"failed to build core: {e}"}, 500)

        # Also register the default Visualization classes from pbg_superpowers
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
            pass  # not installed — that viz will be skipped with a stub HTML

        try:
            summary = run_investigation(
                WORKSPACE, name,
                run_one_composite=run_one_composite,
                core_registry=registry,
            )
        except InvestigationSpecError as e:
            return self._json({"error": f"spec error: {e}"}, 400)
        except FileNotFoundError as e:
            return self._json({"error": str(e)}, 404)
        return self._json(summary, 200)
```

- [ ] **Step 5: Wire dispatch** in `do_POST`:

```python
            "/api/investigation-run": self._post_investigation_run,
```

- [ ] **Step 6: Run tests, confirm pass**

Run: `python -m pytest tests/test_investigation_run_e2e.py -v`
Expected: 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/server.py tests/test_investigation_run_e2e.py tests/_fixtures/ws_increase_demo/investigations
git commit -m "feat: POST /api/investigation-run — orchestrate simulations + render visualizations"
```

---

### Task 15: Remove the Phase backend

**Files:**
- Delete: `pbg-template/scripts/_lib/phase_files.py`
- Delete: `pbg-template/scripts/_lib/phase_md.py`
- Delete: `pbg-template/scripts/_lib/phase_gate.py`
- Delete: `pbg-template/.pbg/schemas/phase.schema.json`
- Delete: `pbg-template/phases/`
- Modify: `pbg-template/scripts/_server/server.py` (drop 3 endpoints + dispatches)
- Modify: `pbg-template/scripts/_lib/report.py` (drop `_read_phases`, `_current_phase`, `_phase_details`, callers)
- Modify: `pbg-template/scripts/lint-workspace.py` (drop phase reference check at line 225)
- Modify: `pbg-template/workspace.yaml.j2` (drop `phases: []` line)

- [ ] **Step 1: Delete backend phase files**

```bash
cd /Users/eranagmon/code/pbg-template
git rm scripts/_lib/phase_files.py scripts/_lib/phase_md.py scripts/_lib/phase_gate.py
git rm .pbg/schemas/phase.schema.json
git rm -r phases/
```

- [ ] **Step 2: Drop phase endpoints from `scripts/_server/server.py`**

Find and DELETE:
- Method `_post_phase_plan` (around line 944) — entire method
- Method `_post_phase_start` (around line 994) — entire method
- Method `_post_phase_gate` (around line 1048) — entire method
- Dispatch entries `"/api/phase-plan"`, `"/api/phase-start"`, `"/api/phase-gate"` in `do_POST`

- [ ] **Step 3: Drop phase code in `scripts/_lib/report.py`**

Find and DELETE (with the line ranges from the earlier survey):
- `_read_phases` (lines 127-159)
- `_current_phase` (lines 162-172)
- `_phase_details` (lines 175-194)
- Wherever the main `render_workspace_report` builds the template context with `phases=` / `current_phase=` / `phase_details=`, delete those keys.

The dashboard template no longer references these keys after Task 16 (HTML changes), so leaving them undefined in the context is fine for now.

- [ ] **Step 4: Drop phase reference check in `scripts/lint-workspace.py`**

Open `scripts/lint-workspace.py`, find the "Visualization phase references" check around line 225. Delete that check (visualizations no longer reference phases under the new model).

- [ ] **Step 5: Drop `phases: []` from `workspace.yaml.j2`**

Open `pbg-template/workspace.yaml.j2`. Delete the line `phases: []`. Do NOT add a replacement — Investigations are file-based discovery, so the workspace.yaml doesn't need an entry.

- [ ] **Step 6: Verify nothing imports the deleted modules**

```bash
grep -rn "phase_files\|phase_md\|phase_gate\|_read_phases\|_current_phase\|_phase_details" scripts/ tests/ 2>/dev/null
```

Expected: no hits. If any remain, fix them.

- [ ] **Step 7: Run existing tests, confirm no regression**

```bash
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all existing tests still pass (composite_runs, composite_explorer_api, pyproject_edit, investigations, investigation_run_e2e). Tests `test_phase_*` should not exist or all phase-related test files should be deleted in this step too:

```bash
git rm tests/test_phase_*.py 2>/dev/null  # if these files exist
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: remove Phase backend — endpoints, lib modules, schema, template phases/ dir"
```

---

### Task 16: HTML — replace Build Model page with Investigations page

**Files:**
- Modify: `pbg-template/scripts/_templates/index.html.j2`

- [ ] **Step 1: Find the existing menu link + page**

In `pbg-template/scripts/_templates/index.html.j2`:
- Menu link: search for `data-page="build-model"`. Replace with a link to Investigations.
- Page section: `<section id="page-build-model">`. Replace the entire section with the Investigations page below.

- [ ] **Step 2: Update the menu link**

Find:
```html
<a class="menu-link" data-page="build-model" ...>Build Model</a>
```

Replace with:
```html
<a class="menu-link" data-page="investigations" onclick="_switchPage('investigations'); return false;">Investigations</a>
```

- [ ] **Step 3: Replace the page section**

Find `<section id="page-build-model" ...>` and its closing `</section>`. Replace the entire block with:

```html
<!-- ===== PAGE: INVESTIGATIONS ===== -->
<section id="page-investigations" class="page" data-page="investigations">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
    <h2 class="page-title" style="margin:0">Investigations</h2>
    <button class="action-btn" onclick="_createInvestigation()">+ New investigation</button>
  </div>
  <p class="page-lead">Declarative research recipes — pick a composite, declare simulations (single / sweep / seeds), name observables, choose visualizations. Run, save, compare.</p>

  <!-- Browse toolbar matches v0.5.6 catalog/composite browse -->
  <div class="card-browse-toolbar" id="investigations-toolbar">
    <input type="search" class="card-browse-search" id="investigations-search" placeholder="Filter investigations…">
    <div class="card-browse-chips" id="investigations-tag-chips"></div>
    <span class="card-browse-view-toggle">
      <button class="view-btn active" data-view="grid" onclick="_setInvestigationsView('grid')">▦</button>
      <button class="view-btn" data-view="list" onclick="_setInvestigationsView('list')">≡</button>
    </span>
  </div>

  <div id="investigations-grid">
    <p class="empty-state">Loading investigations…</p>
  </div>

  <!-- Detail panel renders inline after a row is clicked -->
  <div id="investigation-detail" style="display:none; margin-top:16px"></div>
</section>

<!-- Modal: create investigation -->
<div id="modal-investigation-create" class="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal('modal-investigation-create')">&times;</button>
    <h3>Create investigation</h3>
    <form id="form-investigation-create" onsubmit="event.preventDefault(); _submitInvestigationCreate(this)">
      <label>Name <input name="name" placeholder="dnaa-binding-baseline" required pattern="[a-zA-Z0-9_-]+"></label>
      <label>Composite <select name="composite" id="modal-investigation-composite-select" required>
        <option value="">— pick a composite —</option>
      </select></label>
      <div class="form-error"></div>
      <button type="submit">Create</button>
    </form>
  </div>
</div>
```

- [ ] **Step 4: Render dashboard + visual smoke check**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_templates/index.html.j2 /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Open dashboard URL → confirm the menu shows "Investigations" instead of "Build Model", and the page renders with the toolbar + empty-state message. Buttons won't work yet (Task 18 wires JS).

- [ ] **Step 5: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_templates/index.html.j2
git commit -m "feat: Investigations page replaces Build Model in dashboard sidebar"
```

---

### Task 17: CSS — Investigation styles, remove Phase styles

**Files:**
- Modify: `pbg-template/scripts/_templates/_assets/style.css`

- [ ] **Step 1: Remove phase-era rules**

Open `pbg-template/scripts/_templates/_assets/style.css`. Delete ONLY these `.phase-*` rules (they were identified in the earlier survey at lines 81–106):

```css
.phase-tracker a.pill { ... }
.phase-tracker a.pill:hover { ... }
.phase-tracker a.pill.current { ... }
.current-phase-banner { ... }
.phase-detail { ... }
.phase-detail h3 { ... }
.phase-detail-section { ... }
.phase-detail-actions { ... }
```

**Keep `.status-pill` and its variants (`.complete`, `.in_progress`, `.gate_pending`, `.planned`)** — these are shared with the Composite Explorer's History tab and with the new Investigation card. Don't touch them.

Re-check by grepping for any remaining `phase-` selectors:

```bash
grep "\\.phase-" scripts/_templates/_assets/style.css
```

Expected: no output.

- [ ] **Step 2: Append Investigation rules** to `style.css`:

```css
/* ── Investigations page (v0.5.0) ───────────────────────────────────── */
#investigations-grid{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:12px; margin-top:8px;
}
.investigation-card{
  background:#fff; border:1px solid #e5e7eb; border-radius:8px;
  padding:14px 16px; cursor:pointer; transition:box-shadow 0.1s, border-color 0.1s;
}
.investigation-card:hover{
  border-color:#3b82f6; box-shadow:0 2px 8px rgba(0,0,0,0.06);
}
.investigation-card .name{ font-weight:600; font-size:1.04em; margin-bottom:4px }
.investigation-card .composite{ font-size:0.82em; color:#6b7280; font-family:monospace }
.investigation-card .meta{ display:flex; gap:8px; font-size:0.78em; color:#94a3b8; margin-top:6px }
.investigation-card .status-pill{ font-size:0.75em; padding:2px 8px; border-radius:9999px }

#investigations-grid.list-view{ display:flex; flex-direction:column; gap:6px }
#investigations-grid.list-view .investigation-card{ display:grid; grid-template-columns:1fr 2fr auto auto; gap:14px; align-items:center; padding:8px 12px }
#investigations-grid.list-view .investigation-card .composite{ font-size:0.84em }
#investigations-grid.list-view .investigation-card .meta{ margin-top:0 }

.investigation-detail{
  background:#f8fafc; border:1px solid #e5e7eb; border-radius:8px;
  padding:16px;
}
.investigation-detail-header{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  margin-bottom:12px;
}
.investigation-detail-tabs{
  display:flex; gap:2px; border-bottom:2px solid #e5e7eb; margin:0 0 12px;
}
.investigation-detail-tab{
  background:transparent; border:none; padding:6px 14px;
  font-size:0.88em; color:#64748b; cursor:pointer;
  border-bottom:2px solid transparent; margin-bottom:-2px;
}
.investigation-detail-tab.active{
  color:#1e293b; font-weight:600; border-bottom-color:#3b82f6;
}
.investigation-detail-panel{ display:none }
.investigation-detail-panel.active{ display:block }
.viz-frame{
  width:100%; height:420px; border:1px solid #e5e7eb; border-radius:6px;
  margin-bottom:10px; background:#fff;
}
.spec-yaml-pre{
  background:#f8fafc; border:1px solid #e5e7eb; border-radius:6px;
  padding:10px 14px; font-family:"SF Mono",Menlo,monospace; font-size:0.82em;
  overflow:auto; max-height:480px;
}
```

- [ ] **Step 3: Render + visual smoke check**

```bash
cp scripts/_templates/_assets/style.css /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/_assets/style.css
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Reload the dashboard → Investigations page should be visually clean (empty grid + toolbar styled).

- [ ] **Step 4: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_templates/_assets/style.css
git commit -m "feat: CSS — drop .phase-* rules, add .investigation-card + .viz-frame"
```

---

### Task 18: JS — Investigations list + render + browse-toolbar wiring

**Files:**
- Modify: `pbg-template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add the investigations block** to `walkthrough.js`. Insert it near the bottom, BEFORE the closing `})();` of the IIFE.

```javascript
  // ─── Investigations tab (v0.5.0) ──────────────────────────────────────
  window._investigations = [];
  window._investigationsFilter = { search: '', tags: new Set() };
  window._investigationsView = 'grid';

  function _loadInvestigations() {
    fetch('/api/investigations')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        window._investigations = data.investigations || [];
        _buildInvestigationTagChips();
        _renderInvestigations();
      })
      .catch(function(err) {
        var grid = document.getElementById('investigations-grid');
        if (grid) grid.innerHTML = '<p style="color:#c00">Failed to load: ' + _esc(String(err)) + '</p>';
      });
  }
  window._loadInvestigations = _loadInvestigations;

  function _buildInvestigationTagChips() {
    var container = document.getElementById('investigations-tag-chips');
    if (!container) return;
    var tags = new Set();
    window._investigations.forEach(function(inv) {
      (inv.tags || []).forEach(function(t) { tags.add(t); });
    });
    var chips = Array.from(tags).sort().map(function(t) {
      var active = window._investigationsFilter.tags.has(t) ? ' active' : '';
      return '<button class="card-browse-chip' + active + '"' +
             ' onclick="_toggleInvestigationChip(\'' + _esc(t) + '\', this)">' +
             _esc(t) + '</button>';
    }).join('');
    container.innerHTML = chips;
  }

  function _toggleInvestigationChip(tag, btn) {
    var s = window._investigationsFilter.tags;
    if (s.has(tag)) { s.delete(tag); btn.classList.remove('active'); }
    else { s.add(tag); btn.classList.add('active'); }
    _renderInvestigations();
  }
  window._toggleInvestigationChip = _toggleInvestigationChip;

  function _renderInvestigations() {
    var grid = document.getElementById('investigations-grid');
    if (!grid) return;
    var f = window._investigationsFilter;
    var q = f.search.toLowerCase();
    var filtered = window._investigations.filter(function(inv) {
      if (q) {
        var hay = (inv.name + ' ' + (inv.description || '') + ' ' +
                    (inv.tags || []).join(' ')).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      if (f.tags.size > 0) {
        var match = (inv.tags || []).some(function(t) { return f.tags.has(t); });
        if (!match) return false;
      }
      return true;
    });
    if (!filtered.length) {
      grid.innerHTML = '<p class="empty-state">No investigations match the filter. ' +
                       'Click <em>New investigation</em> to create one.</p>';
      grid.classList.remove('list-view');
      return;
    }
    grid.classList.toggle('list-view', window._investigationsView === 'list');
    grid.innerHTML = filtered.map(_renderInvestigationCard).join('');
  }

  function _renderInvestigationCard(inv) {
    var status = inv.status || 'planned';
    var statusClass = ({planned:'planned', running:'in_progress', complete:'complete',
                        failed:'gate_pending', invalid:'gate_pending'})[status] || 'planned';
    var lastRun = inv.last_run ? new Date(inv.last_run + 'Z').toLocaleString() : '—';
    return '<div class="investigation-card" onclick="_openInvestigation(\'' + _esc(inv.name) + '\')">' +
      '<div class="name">' + _esc(inv.name) + '</div>' +
      '<div class="composite"><code>' + _esc(inv.composite || '?') + '</code></div>' +
      '<div class="meta">' +
        '<span class="status-pill ' + statusClass + '">' + _esc(status) + '</span>' +
        '<span>' + (inv.n_simulations || 0) + ' sim' + ((inv.n_simulations || 0) === 1 ? '' : 's') + '</span>' +
        '<span>last run: ' + _esc(lastRun) + '</span>' +
      '</div>' +
    '</div>';
  }

  function _setInvestigationsView(view) {
    window._investigationsView = view;
    document.querySelectorAll('#investigations-toolbar .view-btn').forEach(function(b) {
      b.classList.toggle('active', b.dataset.view === view);
    });
    _renderInvestigations();
  }
  window._setInvestigationsView = _setInvestigationsView;

  // Wire search input on first menu-switch to the tab
  document.addEventListener('input', function(e) {
    if (e.target && e.target.id === 'investigations-search') {
      window._investigationsFilter.search = e.target.value;
      _renderInvestigations();
    }
  });
```

- [ ] **Step 2: Hook into `_switchPage`**

Find `_switchPage(pageId)` (around line 240). Add inside it, alongside the other tab-load triggers:

```javascript
    if (pageId === 'investigations') {
      if (!window._investigationsLoaded) {
        window._investigationsLoaded = true;
        _loadInvestigations();
      }
    }
```

- [ ] **Step 3: Add `_createInvestigation` + `_submitInvestigationCreate`**

Append to the investigations block:

```javascript
  function _createInvestigation() {
    var sel = document.getElementById('modal-investigation-composite-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">— pick a composite —</option>';
    fetch('/api/composites').then(function(r) { return r.json(); }).then(function(data) {
      (data.composites || []).forEach(function(c) {
        var opt = document.createElement('option');
        opt.value = c.id; opt.textContent = c.name + '   (' + c.id + ')';
        sel.appendChild(opt);
      });
      openModal('modal-investigation-create');
    });
  }
  window._createInvestigation = _createInvestigation;

  function _submitInvestigationCreate(form) {
    var data = new FormData(form);
    var payload = { name: data.get('name'), composite: data.get('composite') };
    fetch('/api/investigation-create', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          var err = form.querySelector('.form-error');
          if (err) err.textContent = j.error || 'create failed';
          return;
        }
        closeModal('modal-investigation-create');
        window._investigationsLoaded = false;
        _switchPage('investigations'); // triggers reload
      });
  }
  window._submitInvestigationCreate = _submitInvestigationCreate;
```

- [ ] **Step 4: Sync + render + smoke**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_server/walkthrough.js /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Open dashboard → Investigations tab → expect empty-state message + toolbar wired. Click + New investigation → modal opens with composite dropdown populated. Submit → row should appear after refresh.

- [ ] **Step 5: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: Investigations list + create modal + browse toolbar"
```

---

### Task 19: JS — Investigation detail panel + Run button

**Files:**
- Modify: `pbg-template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add `_openInvestigation` + detail panel rendering**

Append to the investigations block in `walkthrough.js`:

```javascript
  function _openInvestigation(name) {
    var detail = document.getElementById('investigation-detail');
    detail.style.display = '';
    detail.innerHTML = '<p class="empty-state">Loading…</p>';
    fetch('/api/investigation/' + encodeURIComponent(name))
      .then(function(r) { return r.json(); })
      .then(function(data) { _renderInvestigationDetail(name, data); })
      .catch(function(err) {
        detail.innerHTML = '<p style="color:#c00">Failed: ' + _esc(String(err)) + '</p>';
      });
  }
  window._openInvestigation = _openInvestigation;

  function _renderInvestigationDetail(name, data) {
    var detail = document.getElementById('investigation-detail');
    if (data.error) {
      detail.innerHTML = '<p style="color:#c00">' + _esc(data.error) + '</p>';
      return;
    }
    var spec = data.spec || {};
    var vizFiles = data.viz_files || [];
    var runs = data.runs_summary || [];
    var lastRun = spec.last_run ? new Date(spec.last_run + 'Z').toLocaleString() : '—';
    var status = spec.status || 'planned';
    var statusClass = ({planned:'planned', running:'in_progress', complete:'complete',
                        failed:'gate_pending'})[status] || 'planned';

    detail.innerHTML =
      '<div class="investigation-detail-header">' +
        '<div><strong style="font-size:1.1em">' + _esc(name) + '</strong> ' +
        '<span class="status-pill ' + statusClass + '" style="margin-left:8px">' + _esc(status) + '</span><br>' +
        '<small class="muted">composite: <code>' + _esc(spec.composite || '?') + '</code> · last run: ' + _esc(lastRun) + '</small></div>' +
        '<div>' +
          '<button class="action-btn" onclick="_runInvestigation(\'' + _esc(name) + '\')">' +
          (status === 'planned' ? 'Run' : 'Re-run') + '</button>' +
          '<button class="btn-mini" onclick="_deleteInvestigation(\'' + _esc(name) + '\')">Delete</button>' +
        '</div>' +
      '</div>' +
      '<div class="investigation-detail-tabs">' +
        '<button class="investigation-detail-tab active" data-tab="spec" onclick="_invDetailTab(\'spec\')">Spec</button>' +
        '<button class="investigation-detail-tab" data-tab="runs" onclick="_invDetailTab(\'runs\')">Runs (' + runs.length + ')</button>' +
        '<button class="investigation-detail-tab" data-tab="viz" onclick="_invDetailTab(\'viz\')">Visualizations (' + vizFiles.length + ')</button>' +
      '</div>' +
      '<div class="investigation-detail-panel active" data-tab="spec">' +
        '<pre class="spec-yaml-pre">' + _esc(JSON.stringify(spec, null, 2)) + '</pre>' +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="runs">' +
        (runs.length ? _renderInvestigationRunsTable(runs) : '<p class="empty-state">No runs yet — click Run to generate them.</p>') +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="viz">' +
        (vizFiles.length ?
          vizFiles.map(function(v) {
            return '<h4 style="margin-bottom:4px">' + _esc(v.name) + '</h4>' +
                   '<iframe class="viz-frame" src="/' + _esc(v.path) + '?ts=' + Date.now() + '"></iframe>';
          }).join('') :
          '<p class="empty-state">No visualizations rendered yet.</p>') +
      '</div>';
  }

  function _invDetailTab(tab) {
    document.querySelectorAll('.investigation-detail-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.investigation-detail-panel').forEach(function(p) {
      p.classList.toggle('active', p.dataset.tab === tab);
    });
  }
  window._invDetailTab = _invDetailTab;

  function _renderInvestigationRunsTable(runs) {
    var rows = runs.map(function(r) {
      var pstr = Object.keys(r.params || {}).map(function(k) {
        return k + '=' + r.params[k];
      }).join(', ') || '—';
      var statusClass = ({completed: 'completed', failed: 'failed',
                          running: 'running'})[r.status] || 'planned';
      return '<tr><td>' + _esc(r.sim_name) + '</td>' +
             '<td><code>' + _esc(pstr) + '</code></td>' +
             '<td>' + (r.n_steps || 0) + '</td>' +
             '<td><span class="ce-history-status ' + statusClass + '">' + _esc(r.status) + '</span></td>' +
             '<td><code style="font-size:0.78em">' + _esc(r.run_id.slice(-12)) + '</code></td></tr>';
    }).join('');
    return '<table style="width:100%"><thead><tr>' +
      '<th>Simulation</th><th>Params</th><th>Steps</th><th>Status</th><th>Run id</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function _runInvestigation(name) {
    var detail = document.getElementById('investigation-detail');
    var btn = detail.querySelector('button.action-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    fetch('/api/investigation-run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) { alert('Run failed: ' + (j.error || 'unknown')); }
        // Refresh both the list (status update) and the detail panel
        window._investigationsLoaded = false;
        _loadInvestigations();
        _openInvestigation(name);
      })
      .catch(function(err) { alert('Network error: ' + err); });
  }
  window._runInvestigation = _runInvestigation;

  function _deleteInvestigation(name) {
    if (!confirm('Delete investigation "' + name + '"? This removes its runs.db, visualizations, and spec.yaml.')) return;
    fetch('/api/investigation-delete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (!j.ok) { alert('Delete failed: ' + (j.error || 'unknown')); return; }
      var detail = document.getElementById('investigation-detail');
      if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
      window._investigationsLoaded = false;
      _loadInvestigations();
    });
  }
  window._deleteInvestigation = _deleteInvestigation;
```

- [ ] **Step 2: Sync + manual test**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_server/walkthrough.js /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Open dashboard → Investigations tab → create a test investigation → click it → detail panel renders (Spec / Runs / Visualizations tabs) → click Run → wait for the spinner to clear → switch to Visualizations tab → iframe should load.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: investigation detail panel — Spec/Runs/Visualizations tabs + Run button + Delete"
```

---

### Task 20: Skill — `/pbg-investigate` + remove `/pbg-phase`

**Files:**
- Create: `pbg-superpowers/skills/pbg-investigate/SKILL.md`
- Delete: `pbg-superpowers/skills/pbg-phase/`
- Modify: `pbg-superpowers/plugin.yaml`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p /Users/eranagmon/code/pbg-superpowers/skills/pbg-investigate
```

Write `/Users/eranagmon/code/pbg-superpowers/skills/pbg-investigate/SKILL.md`:

````markdown
---
name: pbg-investigate
description: Launch or re-run an Investigation in the dashboard. Ensures the dashboard server is up, posts to /api/investigation-run, opens the Investigations tab in focus mode. Usage `/pbg-investigate <name>`.
---

# /pbg-investigate — Run an Investigation

Open the dashboard's Investigations tab focused on one investigation, executing it if needed.

## Inputs

- `<name>` (required) — directory name under `investigations/`, e.g. `dnaa-binding-baseline`.

## Steps

1. Walk up from the current directory to find `workspace.yaml`. Fail clearly if not found.
2. Verify `investigations/<name>/spec.yaml` exists. If not, exit with a clear error.
3. Check whether `.pbg/server/server-info` exists and the URL inside it responds to `/api/composites` with HTTP 200. If yes, reuse. Otherwise, run `bash scripts/serve.sh` in the background and poll for `server-info` up to 30 seconds.
4. POST `/api/investigation-run` with `{"name": <name>}` and wait for completion.
5. Open `<url>/#investigations` in the user's default browser.
6. Print the summary returned by the server (n_runs, n_visualizations, status).

## Implementation

```bash
#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "Usage: /pbg-investigate <name>" >&2
  exit 1
fi

DIR="$PWD"
while [ "$DIR" != "/" ] && [ ! -f "$DIR/workspace.yaml" ]; do
  DIR="$(dirname "$DIR")"
done
[ -f "$DIR/workspace.yaml" ] || { echo "ERROR: not inside a pbg workspace" >&2; exit 1; }
cd "$DIR"

[ -f "investigations/$NAME/spec.yaml" ] || {
  echo "ERROR: investigations/$NAME/spec.yaml not found" >&2; exit 1; }

INFO=".pbg/server/server-info"
URL=""
if [ -f "$INFO" ]; then
  URL="$(python3 -c "import json; print(json.load(open('$INFO'))['url'])" 2>/dev/null || echo '')"
  if [ -n "$URL" ] && ! curl -sf -o /dev/null --max-time 2 "$URL/api/composites"; then
    URL=""
  fi
fi
if [ -z "$URL" ]; then
  echo "starting dashboard server..."
  rm -f "$INFO"
  bash scripts/serve.sh > /tmp/pbg-investigate-server.log 2>&1 &
  for i in $(seq 1 60); do
    [ -f "$INFO" ] && break; sleep 0.5
  done
  [ -f "$INFO" ] || { cat /tmp/pbg-investigate-server.log; exit 1; }
  URL="$(python3 -c "import json; print(json.load(open('$INFO'))['url'])")"
fi

echo "Running investigation '$NAME'..."
SUMMARY=$(curl -sf -X POST "$URL/api/investigation-run" \
            -H 'Content-Type: application/json' \
            -d "{\"name\":\"$NAME\"}")
echo "Summary: $SUMMARY"

OPEN_URL="$URL/#investigations"
if command -v open >/dev/null; then open "$OPEN_URL"
elif command -v xdg-open >/dev/null; then xdg-open "$OPEN_URL"
elif command -v start >/dev/null; then start "$OPEN_URL"
else echo "Open this URL: $OPEN_URL"; fi
```
````

- [ ] **Step 2: Delete `/pbg-phase`**

```bash
cd /Users/eranagmon/code/pbg-superpowers
git rm -r skills/pbg-phase/
```

- [ ] **Step 3: Update `plugin.yaml`**

Open `/Users/eranagmon/code/pbg-superpowers/plugin.yaml`. Find the `skills:` list. Replace `pbg-phase` with `pbg-investigate`.

- [ ] **Step 4: Commit + push**

```bash
cd /Users/eranagmon/code/pbg-superpowers
git add skills/pbg-investigate/SKILL.md plugin.yaml
git commit -m "feat: /pbg-investigate replaces /pbg-phase — Investigation launcher skill"
git push origin main 2>&1 | tail -3
```

---

### Task 21: Sync to v2ecoli + manual cleanup + push pbg-template

**Files:**
- Modify: workspace state in `/Users/eranagmon/code/v2ecoli-chromosome-rep1`

- [ ] **Step 1: Final sync of pbg-template → v2ecoli**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_lib/investigations.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/investigations.py
cp scripts/_server/server.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp scripts/_server/walkthrough.js /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp scripts/_templates/index.html.j2 /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cp scripts/_templates/_assets/style.css /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/_assets/style.css
cp scripts/_lib/report.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/report.py
cp scripts/lint-workspace.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/lint-workspace.py
# Delete obsolete files in v2ecoli (mirror the pbg-template delete)
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
rm -f scripts/_lib/phase_files.py scripts/_lib/phase_md.py scripts/_lib/phase_gate.py
rm -f .pbg/schemas/phase.schema.json
```

- [ ] **Step 2: One-time cleanup of v2ecoli phases**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
# Drop phases: from workspace.yaml (preserves rest)
python3 -c "
import yaml
with open('workspace.yaml') as f: ws = yaml.safe_load(f)
ws.pop('phases', None)
with open('workspace.yaml', 'w') as f: yaml.safe_dump(ws, f, sort_keys=False)
"
# Move phases/ to a backup (don't lose existing notes content)
mv phases/ .pbg/_phases_legacy_backup/
```

- [ ] **Step 3: Install pbg-superpowers v0.3.0 from PyPI**

(Bumped to 0.3.0 in Task 6 with the new visualization defaults.)

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
uv pip install -U pbg-superpowers 2>&1 | tail -3
.venv/bin/python3 -c "from pbg_superpowers.visualizations import TimeSeriesPlot; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Restart v2ecoli dashboard**

```bash
EXISTING_PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])" 2>/dev/null || echo '')
if [ -n "$EXISTING_PORT" ]; then
  lsof -nP -iTCP:$EXISTING_PORT -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -I {} kill {} 2>/dev/null || true
fi
rm -f .pbg/server/server-info
sleep 1
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
cat .pbg/server/server-info
```

- [ ] **Step 5: Manual verification checklist**

In the dashboard:

- [ ] Sidebar shows "Investigations" (not "Build Model").
- [ ] Investigations tab loads empty grid with toolbar.
- [ ] Click "+ New investigation" → modal opens; composite dropdown has entries from `/api/composites`.
- [ ] Submit modal with a valid name + composite → row appears in the grid.
- [ ] Click the row → detail panel renders (Spec / Runs / Visualizations tabs).
- [ ] Edit `investigations/<name>/spec.yaml` in your editor to add a `single` simulation, an observable, and a `TimeSeriesPlot` visualization.
- [ ] Click Run → status changes to running → complete; n_runs and n_visualizations reflected.
- [ ] Switch to Visualizations tab → iframe loads the rendered Plotly HTML.
- [ ] Switch back to the grid → row's status pill is "complete", `last_run` is recent.

- [ ] **Step 6: Commit + push v2ecoli sync**

```bash
git add -A
git commit -m "fix: refresh to pbg-template v0.5.0 — Investigations replace Phases"
git push 2>&1 | tail -3
```

- [ ] **Step 7: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git log --oneline -22 | head -22
git push 2>&1 | tail -3
```

---

## Self-review notes

- **Spec coverage:**
  - Architecture / directory layout → Tasks 12 (create scaffold) + 21 (cleanup).
  - Visualization base + 5 defaults → Tasks 1-6.
  - investigations.py (load, expand, gather, overlays, orchestrator) → Tasks 7-9.
  - All 4 new endpoints + remove 3 old ones → Tasks 10-14, 15.
  - HTML + CSS + JS → Tasks 16-19.
  - Skill → Task 20.
  - Final sync + push → Task 21.
- **No placeholders:** every step has the actual code or command.
- **Type consistency:** `run_id` is consistent with `simulation_id` (same string by design — established in Composite Explorer Workbench plan). `sim_name` is consistent across `expand_simulations` output and the `runs_meta.sim_name` column.
- **Backwards-compat caveat:** the `runs_meta` table is shared between the Composite Explorer's workspace-level DB and each Investigation's per-investigation DB. The new `sim_name` column is added via `ALTER TABLE` in Task 9 step 3, only on the per-investigation DB. The workspace-level DB doesn't need it because Composite Explorer doesn't group runs by sim.
