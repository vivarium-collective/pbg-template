# Visualization v2 — emitter-driven, composite-dispatched, type-checked

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:** parts of `2026-05-11-investigations-design.md` (the `render_final` contract is dropped)

## Problem

The Visualization v1 contract (`render_final(results, *, config) -> str`) has three
real problems:

1. **Two APIs, neither clean.** Streaming visualizations (`BondNetworkPlots` etc.
   inside composites) use `update(state)`. Investigation visualizations use
   `render_final(results, config)`. Maintaining both is friction, and the
   results dict the orchestrator hand-builds is structurally different from
   what the streaming Step receives.
2. **Decoupled from emitted data.** Today the visualization either has to be
   wired into the composite at simulation time, or the Investigation
   orchestrator manually reads `runs.db` and reshapes data. Adding a viz
   to an investigation that has already run requires a re-run.
3. **No type guarantees.** Visualization inputs aren't type-checked against the
   data the emitter actually produces. Mismatches show up as silent failures
   or KeyError at render time.

## Goals

- **One contract.** Visualization is a `Step`. The sole method is
  `update(state) -> {'html': str}`. Same shape streaming and post-hoc.
- **Emitter persists schema.** `SQLiteEmitter` writes the `emit` config (the
  per-port type map) into the run's `simulations` row alongside the history,
  so anything that reads `runs.db` can introspect the available observables
  and their types without guessing.
- **Type-checked dispatch via a composite.** For each visualization, the
  orchestrator builds a tiny in-memory composite spec: an input store
  populated with the gathered trajectory(ies), typed per the emitter schema;
  the Visualization Step wired to that store; an output store of type
  `'string'` to capture the HTML. `Composite({...}, core=core)` validates
  the wiring against the registered types. `composite.run(1)` fires the
  viz's `update()`. The bigraph runtime catches type mismatches as real
  errors, not Python silent failures.
- **Post-hoc by default, no inline wiring.** Investigations stop wiring
  visualizations into the user's simulation composite. After simulations
  complete, the orchestrator runs the viz pass against the emitter's
  stored state. Adding a viz to an investigation that already has runs
  re-renders without re-running.

## Non-goals (this redesign)

- Streaming visualizations stay supported: existing wrapper-shipped Visualization
  classes (`BondNetworkPlots`, etc.) keep working when wired into a composite's
  state directly. Their `update(state)` signature is already correct.
- Per-wrapper Visualization input-type cleanup. Deferred to a follow-up pass.
- Re-thinking the Investigation spec format. The YAML shape is unchanged.
- Cross-investigation overlays: keep working as before, resolved by the
  orchestrator into the input-store data.

## Architecture

### Phase A — `SQLiteEmitter` schema persistence (upstream)

```sql
ALTER TABLE simulations ADD COLUMN emit_schema TEXT;
```

`SQLiteEmitter.__init__` writes `config.get('emit')` as JSON into the
`simulations.emit_schema` cell for its `simulation_id`. Existing
`save_simulation_metadata` is the natural seam — its `INSERT ... ON CONFLICT
DO UPDATE` already handles idempotent upserts. New helper:

```python
def load_emit_schema(db_path: str, simulation_id: str) -> dict:
    """Return the emit schema for a recorded run, or {} if none."""
```

### Phase B — Visualization v2 base + 5 defaults (pbg-superpowers)

```python
class Visualization(Step):
    """Sole contract: inputs() declares typed ports; update(state) returns HTML."""

    config_schema = {'title': {'_type': 'string', '_default': ''}}

    def inputs(self) -> dict[str, Any]:
        """Typed input ports declared per the bigraph-schema type system.

        For trajectory data: 'list[float]', 'list[integer]', 'list[string]'.
        For final-value scalars: 'float', 'integer', 'string'.
        For more complex shapes: register a new type if needed.
        """
        return {}

    def outputs(self) -> dict[str, Any]:
        return {'html': 'string'}

    def update(self, state: dict) -> dict:
        """Consume the trajectory state and return rendered HTML.

        ``state`` is keyed by input port name (per ``inputs()``); each value
        is whatever shape the wire delivers (typically a flat list for
        ``list[float]`` inputs, or a single value for scalar inputs).
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement update(state) -> {{'html': str}}."
        )
```

Defaults (each implements `update`):

- `TimeSeriesPlot` — `inputs = {observable: 'list[float]', time: 'list[float]'}`
- `ParamVsObservable` — `inputs = {sweep_param_values: 'list[float]', reduced_observable: 'list[float]'}`
- `Distribution` — `inputs = {samples: 'list[float]'}`
- `PhaseSpace` — `inputs = {x: 'list[float]', y: 'list[float]'}`
- `Heatmap` — `inputs = {x_params: 'list[float]', y_params: 'list[float]', z_values: 'list[list[float]]'}`

The investigation spec's `config:` block under each viz entry still provides
the title and per-class details (e.g., `reduce: final|mean|max`).

### Phase C — Composite-driven viz dispatch (pbg-template)

`scripts/_lib/investigations.py` gains:

```python
def gather_emitter_outputs(runs_db: Path) -> dict:
    """Returns:
        {
            "schemas":    {<run_id>: <emit_schema_dict>},
            "by_sim":     {<sim_name>: [{run_id, params, observables: {<obs>: [v0,v1,...]}}, ...]},
        }
    """

def build_viz_composite(viz_spec, gathered, core_registry) -> dict:
    """Build the small composite document for one viz.

    Structure:
        {
            'inputs_store': {<port_name>: <trajectory or scalar>},
            'output_store': '',
            'visualization': {
                '_type': 'step',
                'address': viz_spec['address'],
                'config': viz_spec.get('config') or {},
                'inputs':  {<port_name>: ['inputs_store', <port_name>]},
                'outputs': {'html': ['output_store']},
            },
        }
    """

def render_visualizations(spec, ws_root, name, core, core_registry) -> list[Path]:
    """For each viz in spec.visualizations:
      1. Resolve viz.inputs() against gathered emitter outputs (by-name matching).
      2. Build the viz composite.
      3. Composite(state, core=core).run(1) — type-checked dispatch.
      4. Read output_store html, write to investigations/<name>/viz/<viz>.html.
    """
```

`_post_investigation_run` flow becomes:

1. Validate spec.
2. Run all simulations into `runs.db` (same as today). **No inline viz wiring.**
3. Call `render_visualizations` (new path).
4. Update spec.yaml status.

New endpoint `POST /api/investigation-render-viz {name}`:

- Skips the simulation step entirely.
- Just runs the viz pass against existing emitter data.
- Returns the same summary shape as `investigation-run` minus `n_runs`.

### Phase D — Frontend

`_submitAddViz` already POSTs to `/api/investigation-add-viz` (which appends
the viz entry to spec.yaml). After the spec.yaml write succeeds, the frontend
follows up with a POST to `/api/investigation-render-viz` so the new
visualization appears in the detail panel immediately. No Run click required.

## Data flow

**Investigation run (full):**

1. POST `/api/investigation-run {name}` → expand simulations → for each run,
   the composite is built with SQLiteEmitter injected via
   `composite_runs.inject_sqlite_emitter`. SQLiteEmitter's init writes
   `emit_schema` to the simulations table (this is the new Phase A behavior).
2. After all runs complete, `gather_emitter_outputs(runs.db)` flattens
   trajectories by observable + reads back per-run schemas.
3. For each viz in `spec.visualizations`: build the viz composite, run it
   for 1 step inside the workspace's core, write HTML.
4. Update spec.yaml status + last_run.

**Add visualization (post-hoc):**

1. POST `/api/investigation-add-viz {investigation, name, address, config}` →
   appends the viz entry to spec.yaml.
2. Frontend chains POST `/api/investigation-render-viz {name}` → just the
   viz pass → new HTML appears in the detail panel iframe.

**Cross-investigation overlays:**

The `overlays` block on each viz entry is unchanged — the orchestrator
resolves overlay data (CSV, reference-range, other-investigation observables)
into the input store alongside the primary observable trajectories. The viz
class chooses what to do with overlay entries that arrive in its inputs
(typically by checking a `_overlays` config key set by the orchestrator).

## Input-resolution rules

When `gather_emitter_outputs` provides `observables` and `schemas`, the
orchestrator resolves each viz's declared `inputs()`:

- **Exact-name match.** Default: a viz's `inputs.level` port maps to the
  emitter observable `level`. Visualization config can override via
  `inputs_map: {level: free_DnaA}`.
- **Type coercion** is minimal:
  - Emitter says `level: float`, viz wants `list[float]` → orchestrator passes
    the per-step trajectory list `[v0, v1, ...]`.
  - Emitter says `level: list[float]` already (one row contains a list), viz
    wants `list[float]` → pass the last row's value as-is (no per-step
    aggregation).
  - Emitter says `level: float`, viz wants `float` → pass the final value.
  - Anything else → composite build fails with the bigraph type error.
- **Multi-run inputs.** A viz that wants per-run plotting (e.g., `TimeSeriesPlot`
  drawing one line per run in a sweep) declares an input port whose value is
  a *list of run trajectories*. The viz config's `sources: [<sim_name>, ...]`
  tells the orchestrator which simulations to include. Each input port's
  store value is the concatenation of run-traces from those sims.

## Error handling

- **Missing emit schema** (older runs.db without the new column): orchestrator
  falls back to inferring schema from the first history row.
- **Type mismatch at composite build**: the bigraph runtime raises; the
  orchestrator catches and writes an error stub HTML for that viz, surfaced
  in the detail panel.
- **Missing observable** (viz declares an input not present in emitter outputs):
  the orchestrator writes a warning stub for that viz; other visualizations
  still render.
- **render_visualizations exception**: per-viz isolation — failure of one
  viz doesn't abort the others.

## Testing

Phase A:
- `test_sqlite_emitter_persists_schema` — instantiate emitter with `emit:
  {level: 'float'}`, write a row, query `simulations.emit_schema`, assert
  parsed JSON matches.
- `test_load_emit_schema_returns_dict`.
- `test_load_emit_schema_missing_simulation_id_returns_empty`.

Phase B:
- For each of the 5 default Vis classes: build minimal state matching its
  declared inputs, call `update(state)`, assert HTML contains expected
  Plotly markers and the correct number of traces.
- `test_visualization_base_update_raises_not_implemented`.

Phase C:
- `test_gather_emitter_outputs_flattens_by_observable` — fixture runs.db with
  2 runs × 3 steps × 2 observables → returns 2 sims × runs × observables.
- `test_build_viz_composite_shape` — verify the JSON structure matches the
  schema shown above.
- `test_render_visualizations_e2e_via_composite` — fixture investigation,
  call render_visualizations, assert HTML files written, contain
  `Plotly.newPlot`.
- `test_render_visualizations_type_mismatch_writes_error_stub` — viz declares
  `inputs={level: 'integer'}` but emitter has `level: 'float'` → composite
  build fails → error stub HTML written, other vizzes unaffected.
- `test_post_investigation_render_viz_endpoint` — POST against fixture, no
  simulation run, just viz output materializes.

Phase D:
- Manual: add a viz via the modal after running an investigation → iframe
  appears without a Run click.

## Backwards compatibility

- The old `render_final` callers in `render_visualizations` are removed.
  No other code in the ecosystem implements `render_final` (it was only the
  5 default classes); deleting it is safe.
- Existing investigation runs.db files without `emit_schema` rows: orchestrator
  falls back to schema inference (Error handling rules above). No data loss.
- Wrapper-side streaming Visualizations (`BondNetworkPlots`, etc.) keep
  working — their `update(state)` signature is unchanged.

## Out of scope (follow-ups)

- Cleanup of wrapper Visualization `inputs()` types (currently many use bare
  `'float'` for trajectory ports). Each wrapper's repo will need a small
  follow-up.
- A `register_type` pass for richer overlay shapes (`list[{time: float,
  value: float}]` or `dataframe`).
- Streaming-mode dashboard integration for the per-step `update(state)` path
  (e.g., live HTML push via SSE while a long sim runs).
