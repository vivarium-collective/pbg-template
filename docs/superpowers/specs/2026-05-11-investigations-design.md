# Investigations — Design (v0.5.0, replaces Phases)

**Date:** 2026-05-11
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)

## Problem

The Phase concept in pbg-template was an unstable mix of two unrelated ideas:
a workspace-development milestone (with code-gate verification) and a
research-execution recipe. Real research workflow looks like this:

> "Pick a composite. Decide which parameters to vary (a baseline, a sweep
> across binding rates, five seeds at the best point). Decide which observables
> to record. Decide which visualizations to render — including overlays of
> experimental data and reference ranges. Run it. Look at the results. Tweak
> the spec. Re-run. Compare to another investigation's results."

The Phase system models almost none of that. It tracks "phase 1 → phase 2"
with status pills and a gate concept, but there is no notion of a runnable
specification, parameter sweeps, observable selection, or visualization
declarations. Researchers end up running things ad-hoc in the Composite
Explorer and the artifacts disappear when the page reloads.

This spec replaces the Phase system entirely with **Investigations** — a
declarative, runnable, persistent research-recipe concept. Each Investigation
is a directory at `investigations/<name>/` containing:

- `spec.yaml` — composite ref + simulations + observables + visualizations + overlays + cross-investigation references
- `runs.db` — per-investigation SQLite with the trajectories of every run
- `viz/<viz-name>.html` — rendered visualization artifacts
- `data/` — investigation-local CSV files for experimental overlays
- `notes.md` — free-form research log

Investigations replace Phases as a **clean break**: no automated migration.
The two existing v2ecoli phase entries (`Baseline`, `Extension`) are
empty scaffolding and get deleted in a one-time manual cleanup.

## Goals

- **Declarative research recipes.** Each Investigation's spec.yaml describes one
  composite + one or more simulations + the observables + the visualizations.
- **Three simulation modes per Investigation.** Stand-alone runs, parameter
  sweeps, and N-seed replicate studies — all in one spec.
- **Auto-persisted results.** Every run writes to the investigation's
  `runs.db` via an injected `SQLiteEmitter`.
- **Final-mode visualizations (default).** Each Visualization is rendered
  once at end-of-run from the gathered trajectories. The existing per-step
  streaming Visualization class (used inside Composites) remains opt-in for
  subclasses that want it.
- **Overlays.** Experimental-data overlays (CSV), reference ranges (static
  bands), and cross-investigation series (load another Investigation's
  observable trajectory).
- **Cross-investigation references.** Investigation B can declare a
  reference to Investigation A and overlay A's observables on B's
  visualizations.
- **Interactive re-runs.** Click Run again, all visualizations refresh
  with new data. The same `spec.yaml` is the source of truth.
- **Discoverability.** Visualization classes are auto-discovered via
  `core.link_registry`. New defaults ship in pbg-superpowers; wrapper
  packages can contribute additional Visualizations.

## Non-goals (MVP)

- Inline spec editing in the dashboard. Users edit `spec.yaml` in their
  editor of choice; the dashboard polls for changes.
- Automated migration from Phases. Clean break.
- Cross-workspace Investigation references.
- Distributed / queued execution. All simulations run sequentially
  in-process under the dashboard server.
- Investigation versioning / archival of past runs. A re-run replaces
  the previous results.

## Terminology

- **Investigation** — a declarative research recipe (a directory + spec).
- **Simulation block** — one entry in `spec.simulations`. Has `kind` of
  `single` | `sweep` | `seeds`.
- **Run** — one concrete execution of the composite. A `single` block
  produces 1 run; a `sweep` produces N runs (cartesian product); a `seeds`
  block produces `n_seeds` runs.
- **Observable** — a name listed under `spec.observables` that the
  visualization layer reads from the trajectory state.
- **Visualization** — a registered `Visualization(Step)` subclass invoked
  via `render_final(results, config)`. Returns HTML.
- **Overlay** — a non-trajectory data layer (experimental points,
  reference range, cross-investigation series) added to a visualization.

## Architecture

An Investigation is a directory at `investigations/<name>/`:

```
investigations/<name>/
├── spec.yaml          # declarative spec (committed to git)
├── runs.db            # SQLite trajectories + run metadata
├── viz/
│   └── <viz-name>.html  # rendered visualizations
├── data/              # local CSVs for experimental overlays
└── notes.md           # optional research log
```

The dashboard's `Investigations` tab (replacing `Build Model`) lists all
investigations, supports the same search/chip/list browse toolbar shipped
in v0.5.6, and opens a detail panel per investigation.

A new `/api/investigation-run` endpoint orchestrates execution: parse the
spec, expand simulations into runs, inject a `SQLiteEmitter` into each
run's composite state, run sequentially, render visualizations via
`Visualization.render_final()`, write HTML to `viz/`. The `Visualization`
base class is amended:

```python
class Visualization(Step):
    supports_streaming = False  # subclass opts in

    # REQUIRED — called once at end with the Investigation's results
    def render_final(self, results: dict, *, config: dict) -> str:
        raise NotImplementedError

    # OPTIONAL — only implemented by streaming subclasses
    def update(self, state, interval=1.0):
        return {'html': ''}
```

Five default Visualization classes ship in
`pbg-superpowers/pbg_superpowers/visualizations/`:

- `TimeSeriesPlot` — observable(s) vs time, multi-line.
- `ParamVsObservable` — sweep parameter vs reduced observable.
- `Distribution` — histogram/KDE of an observable across seeds.
- `PhaseSpace` — two observables plotted against each other.
- `Heatmap` — 2D parameter sweep visualization.

Existing per-wrapper streaming Visualizations (`BondNetworkPlots`, etc.
from the v0.4.15 / Task #88 rollout) continue to function inside Composites
via their `update()` method but do not appear in the Investigation
visualization picker unless they also implement `render_final`.

The old Phase system is removed entirely:
- `.pbg/schemas/phase.schema.json`
- `phases/` directory in the template
- `scripts/_lib/phase_files.py`, `phase_md.py`, `phase_gate.py`
- `/api/phase-plan`, `/api/phase-start`, `/api/phase-gate` endpoints
- The build-model UI page + Phase Tracker
- `/pbg-phase` skill in pbg-superpowers

## Components

### Backend

**`scripts/_lib/investigations.py` (new).** Spec loading, run orchestration,
results aggregation, viz rendering.

- `load_spec(path) -> dict` — parse + validate `spec.yaml`. Raises
  `InvestigationSpecError(message)` on validation failure.
- `expand_simulations(spec) -> list[dict]` — flatten the three simulation
  kinds into a flat list of `{sim_name, run_label, overrides, steps}`.
  Sweeps expand via cartesian product. Seeds add `seed=k` to overrides.
- `run_investigation(ws_root, name) -> dict` — top-level orchestrator.
  Opens `investigations/<name>/runs.db`, runs each expanded simulation
  (injecting `SQLiteEmitter`, capturing `simulation_id`), gathers results,
  invokes each visualization's `render_final`, writes HTML, updates
  `spec.yaml.status` + `last_run`.
- `gather_results(spec, db_path) -> dict` — read trajectories from
  `runs.db`, return `{<sim_name>: {runs: [{run_id, params, trajectory}, ...]}}`.
- `render_visualizations(spec, results, ws_root, name) -> list[Path]` — for
  each viz: look up the class in `core.link_registry`, instantiate, call
  `render_final(results, config={**viz.config, '_overlays': overlay_payload})`,
  write HTML.
- `load_overlays(spec, viz_config, ws_root, name) -> list[dict]` —
  resolves `experimental-points` (CSV), `reference-range` (static), and
  cross-investigation series (reads another investigation's `runs.db`)
  into a uniform overlay payload.

**`scripts/_server/server.py` (modified).** New endpoints:

- `GET /api/investigations` → list of all `investigations/<name>/spec.yaml`
  summaries (name, composite, status, last_run, sim count).
- `GET /api/investigation/<name>` → full spec + viz file paths + runs_summary.
- `POST /api/investigation-run` `{name}` → kicks off `run_investigation`,
  returns summary.
- `POST /api/investigation-create` `{name, composite}` → scaffolds a new
  investigation directory + minimal spec.yaml. Wrapped in
  `_active_branch_action`.
- `POST /api/investigation-delete` `{name}` → removes directory. Wrapped
  in `_active_branch_action`.

Removed: `/api/phase-plan`, `/api/phase-start`, `/api/phase-gate`.

### Default Visualization classes — `pbg-superpowers/pbg_superpowers/visualizations/`

New subpackage. One module per class. All use Plotly under the hood and
auto-register via `bigraph_schema.package.discover`.

- `time_series.py` — `TimeSeriesPlot`. Config: `observable`, `sources`
  (sim names), `title`. One line per run.
- `param_vs_observable.py` — `ParamVsObservable`. Config: `sweep` (sim
  name), `sweep_param`, `observable`, `reduce` (`final|mean|max|min|integral`),
  `title`.
- `distribution.py` — `Distribution`. Config: `observable`, `sources`,
  `at_step` (default `final`), `kind` (`histogram|kde`).
- `phase_space.py` — `PhaseSpace`. Config: `x_observable`,
  `y_observable`, `sources`.
- `heatmap.py` — `Heatmap`. Config: `sweep` (2D), `x_param`, `y_param`,
  `observable`, `reduce`.

All five inherit the modified `Visualization` base with `render_final`.

### Frontend

**`scripts/_templates/index.html.j2` (modified).**

- Replace `<section id="page-build-model">` and its menu link with
  `<section id="page-investigations">`.
- New menu link "Investigations".
- Inside the page: list view of investigations using the v0.5.6 browse
  toolbar (search + tag chips + list/grid view). Click an investigation
  row to expand a detail panel showing spec preview + sim summary + Run
  button + embedded viz iframes.

**`scripts/_server/walkthrough.js` (modified).**

- New: `_loadInvestigations`, `_renderInvestigations`,
  `_openInvestigation(name)`, `_runInvestigation(name)`,
  `_createInvestigation()`.
- Removed: `_postPhaseAction`, `submitPhasePlan`, `phaseStart`,
  `phaseGate`, phase-detail rendering.

**`scripts/_templates/_assets/style.css` (modified).**

- Remove `.phase-tracker`, `.current-phase-banner`, `.phase-detail*`.
- Add `.investigation-card`, `.investigation-detail`, `.viz-frame`
  (iframe styling).

### Skill — `pbg-superpowers/skills/pbg-investigate/SKILL.md` (new)

Replaces `/pbg-phase`. `/pbg-investigate <name>` skill:

1. Reads `investigations/<name>/spec.yaml`.
2. If simulations haven't been run, calls `/api/investigation-run`.
3. Opens `investigations/<name>/viz/` in the browser.
4. Optionally drafts a `notes.md` summary of findings.

The old `/pbg-phase` skill is deleted from pbg-superpowers.

### Tests

- `tests/test_investigations.py` (new): unit-tests for `load_spec`,
  `expand_simulations` (single/sweep/seeds), `gather_results`,
  `load_overlays`.
- `tests/test_investigation_run_e2e.py` (new): full lifecycle integration
  test — fixture investigation with `single` + `sweep`, run via
  `/api/investigation-run`, assert SQLite has rows + viz HTML files exist
  + spec.yaml status updates.
- `pbg-superpowers/tests/test_default_visualizations.py` (new): one
  test per default class verifying `render_final` produces expected
  Plotly HTML shape from a minimal `results` fixture.

## Data flow

### Flow 1 — Create an investigation

User on Investigations tab clicks "New investigation" → modal asks for
name + composite (dropdown from `/api/composites`) → POST
`/api/investigation-create` → server scaffolds:

```
investigations/<name>/
  spec.yaml          # minimal placeholder
  data/.keep
```

Returns the new spec; frontend reloads the investigations list + opens
the detail panel. Wrapped in `_active_branch_action`.

### Flow 2 — Edit spec.yaml

The dashboard does NOT have an inline spec editor in MVP. User edits
`spec.yaml` in their editor. The detail panel auto-detects file mtime
via a poll on `/api/investigation/<name>` and refreshes the spec preview.

### Flow 3 — Run an investigation

User clicks Run on the detail panel → POST `/api/investigation-run` `{name}`
→ server:

1. `load_spec("investigations/<name>/spec.yaml")` → validate.
2. `expand_simulations(spec)` → flatten into runs.
3. For each expanded run:
   - `find_composite_path(...)` → load + parameter-substitute composite state.
   - `cr.inject_sqlite_emitter(state, run_id, db_file="investigations/<name>/runs.db")`.
   - `cr.save_metadata(...)`.
   - Subprocess: run the composite for `steps` ticks.
   - `cr.complete_metadata(...)`.
4. `gather_results(...)` → `{<sim_name>: {runs: [...]}}`.
5. For each visualization:
   - Look up `address` in `core.link_registry`.
   - `load_overlays(viz.config, ...)` → uniform overlay payload.
   - Instantiate, call `render_final(results, config={**viz.config, '_overlays': ...})`.
   - Write `investigations/<name>/viz/<viz-name>.html`.
6. Update `spec.yaml.status` + `last_run`.
7. Return summary; frontend refreshes the detail panel.

### Flow 4 — View an investigation

User clicks an investigation in the list → GET `/api/investigation/<name>`
→ detail panel renders inside the panel:

- Header: name, status pill, composite link, last_run timestamp.
- Inner tabs: **Spec** | **Runs** | **Visualizations** | **Notes**.
  - Spec: pretty-printed YAML + Edit button (file open).
  - Runs: table of expanded runs with View-state button that opens the
    existing Composite Explorer's State tab pinned to that run.
  - Visualizations: one `<iframe>` per viz HTML file, embedded inline.
  - Notes: live-rendered markdown of `notes.md` if present.

### Flow 5 — Cross-investigation reference

When a visualization's `overlays:` list declares:

```yaml
visualizations:
  - name: free-dnaA-trajectory
    address: "local:TimeSeriesPlot"
    config: {observable: free_DnaA, sources: [baseline]}
    overlays:
      - kind: cross-investigation-series
        investigation: chromosome-replication-init
        observable: oriC_state
        style: dashed-line
        label: "from chromosome-replication-init"
```

…`load_overlays`:

1. Opens `investigations/chromosome-replication-init/runs.db`.
2. Queries the `history` table for the named observable across all rows.
3. Returns the trajectory as an overlay payload entry with
   `kind: cross-investigation-series`, style, label.
4. The Visualization's `render_final` receives this in `config["_overlays"]`
   and renders it alongside the primary traces.

If the referenced investigation doesn't exist or hasn't run, the resolver
returns a warning entry; the viz renders without that overlay and the
warning appears in the run summary's "Overlay issues" sidebar.

### Flow 6 — Clean break (no migration)

pbg-template v0.5.0 removes all Phase machinery. New workspaces have no
`phases:` field — instead, the (optional) `investigations:` field is a
discovery hint; investigations are file-based.

v2ecoli gets a one-time manual cleanup commit: delete `phases:` from
workspace.yaml, delete `phases/` directory. No migration script.

## Schema (`spec.yaml`)

```yaml
name: <slug>                          # required, matches directory name
description: <string>                 # optional
composite: <composite-id>             # required, must resolve via composite discovery
tags: [<string>, ...]                 # optional; surfaces as chip filters on the Investigations browse toolbar
                                      # (same v0.5.6 mechanism used by Catalog + Composites)

simulations:                          # required, ≥1 entry
  - name: <string>                    # required, unique within investigation
    kind: single | sweep | seeds      # required
    # for kind=single
    overrides: {<param>: <value>}
    # for kind=sweep
    sweep_over: {<param>: [<value>, ...]}
    base_overrides: {<param>: <value>}
    # for kind=seeds
    n_seeds: <int >= 1>
    base_overrides: {<param>: <value>}
    # all kinds
    steps: <int >= 1>

observables: [<string>, ...]          # required, ≥1 entry

visualizations:                       # optional
  - name: <string>                    # required, unique within investigation
    address: "local:<ClassName>"      # required, must resolve via core.link_registry
    config: {<key>: <value>}          # required, passed to render_final
    overlays:                         # optional
      - kind: experimental-points | reference-range | cross-investigation-series
        # kind-specific fields
        data: <path>                    # for experimental-points
        x_column: <string>
        y_column: <string>
        style: <string>
        label: <string>
        y_min: <number>                 # for reference-range
        y_max: <number>
        investigation: <name>           # for cross-investigation-series
        observable: <string>
        use_in: <viz-name>

status: planned | running | complete | failed | invalid
                                      # auto-managed; not hand-edited
last_run: <iso-timestamp>             # auto-managed
```

## Error handling

**Spec validation errors.** `load_spec` raises `InvestigationSpecError` for
missing required fields, unknown simulation kinds, `seeds` with
`n_seeds <= 0`, `sweep` with empty `sweep_over`, malformed YAML.
`/api/investigation-run` catches and returns 400. Detail panel shows
the error inline above the Run button; `spec.yaml.status = "invalid"`.

**Missing composite.** `find_composite_path` returns `None` → run aborts
with `{error: "composite not found: <id>", suggestion: "did you forget to
pip-install the package?"}`. No runs persisted. Status → `"failed"`.

**Per-run simulation failure.** Each run in its own subprocess + try/except.
On failure, that run's `runs_meta` row is marked `status='failed'` with
a truncated traceback; execution proceeds to the next run. After all
runs, if any failed, the investigation `status` is `"failed"` (vs
`"complete"`). The viz pass still runs against whatever results exist —
visualizations can show partial data with a banner.

**Visualization class not registered.** `core.link_registry[viz.address]`
raises KeyError → that viz is skipped; its summary slot returns
`{name, error: "Visualization class not registered. Install the package
that ships it."}`. Other visualizations still render.

**Overlay data missing.** Each overlay is resolved independently:
- `experimental-points` with missing CSV → warning entry.
- `cross-investigation-series` referencing a missing investigation or
  one with no `runs.db` → warning entry.
- `reference-range` is inline; never fails.

The viz's `render_final` receives warnings via `config["_overlays"]`. The
detail panel surfaces them in a sidebar.

**`render_final` exception.** Captured per-viz. Traceback stored in the
viz error slot. Viz HTML is not written. Other visualizations unaffected.

**runs.db locked / corrupt.** Single-process server, single writer; lock
contention is rare. If SQLite raises, the run aborts with a 500. Manual
fix: `rm investigations/<name>/runs.db && rerun`.

**Concurrent runs.** Per-investigation `.lock` file prevents two
simultaneous runs of the same investigation. Second request → 409
`{error: "investigation is already running"}`.

**Disk write failures.** Each artifact write has its own try/except.
Failures logged + surfaced. Status reflects the outcome.

## Testing

### Unit tests (`tests/test_investigations.py`)

- `test_load_spec_valid` — minimal valid spec parses.
- `test_load_spec_missing_name` — raises with `name`.
- `test_load_spec_missing_composite` — raises with `composite`.
- `test_load_spec_bad_simulation_kind` — `kind: bogus` raises.
- `test_load_spec_seeds_zero` — `n_seeds: 0` raises.
- `test_expand_simulations_single` — 1 expanded run, literal overrides.
- `test_expand_simulations_sweep_1d` — 3 values → 3 runs, labels include `<sim>__<param>=<value>`.
- `test_expand_simulations_sweep_2d` — cartesian product count + labels.
- `test_expand_simulations_seeds` — `n_seeds: 5` → 5 runs with `seed=0..4`.
- `test_expand_simulations_mixed` — spec with all three kinds → flat list.

### Overlay resolver tests (same file)

- `test_load_overlays_experimental_points_ok` — CSV present → payload.
- `test_load_overlays_experimental_points_missing_file` — warning.
- `test_load_overlays_reference_range` — static y_min/y_max.
- `test_load_overlays_cross_investigation_ok` — fixture investigation
  with existing `runs.db` → trajectory.
- `test_load_overlays_cross_investigation_missing` — warning.

### Default Visualization tests (`pbg-superpowers/tests/test_default_visualizations.py`)

For each of the 5 defaults: construct minimal `results`, call
`render_final(results, config)`, assert returned HTML contains expected
Plotly markers (`Plotly.newPlot`, title, correct trace count) and reflects
overlays when present.

### Integration test (`tests/test_investigation_run_e2e.py`)

Extends fixture workspace `ws_increase_demo` with a fixture investigation.
Lifecycle:

1. `GET /api/investigations` → list contains the investigation, status=`planned`.
2. `POST /api/investigation-run {name: baseline}` → 200.
3. Assert `runs.db` has 4 rows (1 single + 3 sweep), all `status='completed'`.
4. Assert `viz/levels.html` exists, size > 1000 bytes, contains `Plotly.newPlot`.
5. Assert `spec.yaml.status == "complete"`, `last_run` set.
6. `GET /api/investigation/baseline` → spec + viz_files + runs_summary.
7. Re-run replaces previous results.

### Per-run failure test

Add a sim that crashes → run completes, status=`failed`, failed row has
`status='failed'`, viz still renders against successful runs.

### Manual verification checklist

- Investigations tab in sidebar (replacing Build Model).
- Browse toolbar present (search/chips/list).
- Create modal → submit → directory scaffolded → list refreshes.
- Edit `spec.yaml` → reload detail panel → spec preview updates.
- Run button → progress indicator → results populate.
- Embedded viz iframes load `viz/<name>.html`.
- Cross-investigation reference: second investigation overlays first's
  observable correctly.
- `/pbg-phase` skill gone; `/pbg-investigate` present.

### Backwards compatibility

- Workspaces with existing `phases:` list in workspace.yaml: dashboard
  ignores it. User does a one-time manual cleanup.
- `phases/` directories in workspaces: harmlessly left in place;
  dashboard does not render anything from them.

## Out of scope (follow-ups)

- Inline dashboard spec editor (CodeMirror or similar).
- Parallel / distributed run execution.
- Investigation versioning + archived past runs.
- Cross-workspace Investigation references.
- A "Suggest" action that calls Claude to draft a spec.yaml from
  natural language.
- Composite Explorer Workbench integration: launch a fresh Investigation
  from the workbench using its current parameter values.

## Open questions

None at design time — locked in during brainstorm:

- One composite per Investigation (multi-composite handled via
  cross-investigation references).
- Directory-per-investigation (`investigations/<name>/`).
- Three simulation kinds: `single` | `sweep` | `seeds`.
- Final-only Visualizations by default; per-step streaming is opt-in
  via `supports_streaming` class attribute.
- Five default Visualizations: TimeSeriesPlot, ParamVsObservable,
  Distribution, PhaseSpace, Heatmap.
- Overlay kinds: experimental-points, reference-range, cross-investigation-series.
- Visualizations addressed via `core.link_registry` (`local:ClassName`).
- Clean break from Phases; no migration script.
- Re-runs replace previous results in `runs.db` (no archival).
