# Multi-composite Investigations + Observables tab

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:** the single-`composite:` field in current Investigation spec.yaml

## Problem

An Investigation today binds to **one** composite — a Python module path
(`pbg_chromosome_rep1.composites.chromosome-partition`) that builds a single
`Composite` document at run time. Two real problems:

1. **No way to express perturbations or model variants in a Study.** A research
   workflow often compares a baseline against parameter perturbations
   ("DnaA rate doubled"), process swaps ("simplified replication mechanism"),
   or removals ("knock out replication"). Today each comparison is its own
   Investigation; visualizations can overlay across investigations but the
   spec can't express the comparison as a coherent unit.
2. **Composite structure is opaque to the dashboard.** Users can't browse the
   wiring of the composite their Study is using, can't see which store paths
   exist, and can't selectively enable emitters from the UI. The Composite
   Explorer tab exists at workspace level but isn't scoped to the Study, so
   what-you-see-is-not-what-runs.

## Goals

- **Multi-composite Studies.** An Investigation's spec lists one *or many*
  composites. Each composite is either *registered* (cloned from a workspace-
  package composite module) or *derived* (extends another composite in the
  study with parameter or process overrides).
- **Stored composite documents.** Each composite in an Investigation has a
  rendered document at `investigations/<name>/composites/<composite>.yaml` —
  version-controlled, diffable, frozen at the moment of "Save composite".
  Derivation recipes live alongside in `spec.yaml`; rebuilding the document
  is an explicit action.
- **Composites tab.** A new tab in the Investigation viewer lists every
  composite in the study, lets you click into each one to browse its state
  tree, and exposes "+ Add composite" + "Perturb" actions.
- **Observables tab.** A new tab in the Investigation viewer shows the union
  of state paths across the study's composites; checkboxes select which paths
  the emitter records. Selection is one global list, applied to every run.
  Paths missing in a given composite are skipped with a warning for that run,
  not an error.
- **Backwards-compatible migration.** Existing Investigations with the legacy
  single-`composite:` field migrate cleanly: their composite is rendered to
  `composites/<baseline>.yaml`, spec.yaml is rewritten as a one-entry
  `composites:` list.

## Non-goals (this design)

- **Full structural edits** to derived composites (add new processes, rewire
  inputs/outputs). Phase-1 derivation supports parameter overrides + process
  swap/removal only. Full structural-edit recipes are a follow-up.
- **Cross-Study composite sharing.** Each Investigation owns its own
  composite files. A future enhancement could promote a derived composite to
  the workspace's composite catalog, but that flow isn't in scope here.
- **Composite-document editing in-tab.** The Composites tab is read-only
  browsing + recipe-driven derivation; raw YAML editing happens in the
  workspace-level Composite Explorer.
- **Renaming Investigation → Study.** The user chose to keep the
  "Investigation" name. All file paths, endpoints, and labels stay.

## Architecture

### File layout per Investigation

```
investigations/<name>/
├─ spec.yaml                   # Study manifest — composites list, observables, runs, visualizations
├─ composites/                 # NEW — rendered composite documents
│  ├─ baseline.yaml            #   one file per composite entry in spec.yaml
│  └─ high-rate.yaml
├─ runs.db                     # emitter SQLite + runs_meta (unchanged)
├─ viz/                        # rendered visualization HTML (unchanged)
└─ notes.md
```

### spec.yaml shape (updated)

```yaml
name: dnaA-replication-comparison
composites:
  - name: baseline                                      # nickname within this study
    source: pbg_chromosome_rep1.composites.chromosome-partition
    # `document` is the rendered file path; auto-set when the source is rendered
    document: ./composites/baseline.yaml

  - name: high-rate                                     # derived composite — parameter perturbation
    extends: baseline                                   # references another composite in THIS study
    parameter_overrides:
      replication.rate: 2.0                             # dotted store/process path -> new scalar
    document: ./composites/high-rate.yaml

  - name: no-replication                                # derived composite — process removal
    extends: baseline
    process_overrides:
      replication: null                                 # null = remove that process
    document: ./composites/no-replication.yaml

observables:                                            # global, applied to every composite-run
  - {path: [chromosome, DnaA_count]}
  - {path: [chromosome, free_DnaA]}

runs:
  - composite: baseline
    params: {seed: 1}
    steps: 100
  - composite: high-rate
    params: {seed: 1}
    steps: 100
  - composite: no-replication
    params: {seed: 1}
    steps: 100

visualizations:
  - name: dnaA-traj
    class: TimeSeriesPlot
    config:
      observable: DnaA_count
      sources: [baseline, high-rate, no-replication]    # filter to these composite-runs
```

Backwards-compatible single-composite shape:

```yaml
name: legacy-single
composites:
  - name: baseline
    source: pbg_chromosome_rep1.composites.chromosome-partition
    document: ./composites/baseline.yaml
runs:
  - composite: baseline
    params: {}
    steps: 100
```

### Composite document shape (existing process-bigraph)

Each `composites/<name>.yaml` is a real process-bigraph composite document —
what `Composite({...}, core=core).run()` consumes directly:

```yaml
state:
  chromosome:
    DnaA_count: {_type: integer, _default: 100}
    free_DnaA:  {_type: float,   _default: 50.0}
  replication:
    _type: process
    address: 'local:DnaAReplisome'
    config: {rate: 1.0}
    inputs:  {dna: [chromosome]}
    outputs: {dna: [chromosome]}
  emitter:
    _type: step
    address: 'local:SQLiteEmitter'
    config:
      emit: {DnaA_count: integer, free_DnaA: float}
    inputs:
      DnaA_count: [chromosome, DnaA_count]
      free_DnaA:  [chromosome, free_DnaA]
```

### Derivation recipe (Phase 1: parameters + process swap)

Two override blocks on a derived composite, both optional, both applied in
order: parameters first, then process overrides.

**`parameter_overrides:`** — dict mapping dotted path → new scalar value.
The dotted path identifies either a store's value (`chromosome.DnaA_count`)
or a process's config key (`replication.rate`). The orchestrator walks the
parent document, finds the addressed node, and sets the value.

```yaml
parameter_overrides:
  chromosome.DnaA_count: 200                            # change store default
  replication.rate: 2.0                                 # change process config
```

**`process_overrides:`** — dict mapping process-name → replacement spec or `null`.
Replacement can be a string (new address only, config unchanged) or a dict
(new address + new config). `null` removes the process from the document.

```yaml
process_overrides:
  replication: 'local:SimplifiedReplication'            # swap address, keep config
  rnap_transcription:                                   # swap address + config
    address: 'local:NoiseFreeRNAP'
    config: {seed: null}
  oric_initiator: null                                  # remove
```

Wiring (inputs/outputs) of a swapped process inherits from the parent unless
explicitly overridden. If the new Process class declares incompatible
`inputs()`/`outputs()`, the rebuild surfaces a bigraph-schema validation
error in the UI.

### Run dispatch

`spec.yaml.runs[].composite` names which composite to use. Orchestrator:

1. Resolves `composite_name` → loads `composites/<name>.yaml`.
2. Builds `Composite({"state": <doc>}, core=workspace_core)`.
3. Applies any `params` from the run entry as extra overlays (no document
   mutation — these are per-run parameter sweeps, distinct from the
   composite's permanent perturbation).
4. Runs for `steps` timesteps; SQLiteEmitter writes to the shared `runs.db`
   with `sim_name = <composite_name>`.

### Observables tab UX

The tab loads every composite in the study, walks each state document, and
flattens the union of (path, type, default-value) leaves. Rendered as a
collapsible tree with per-row checkboxes:

```
[ ] Emit entire state (root)

chromosome/
  ☑ DnaA_count         integer    default 100    (in: baseline, high-rate, no-replication)
  ☐ free_DnaA          float      default 50.0   (in: baseline, high-rate)
  ☐ fork_positions     list[float] default [0.5,0.5] (in: baseline, high-rate)
replication/                                       (process — config below)
  ☐ config/rate        float      default 1.0    (in: baseline, no-replication)
```

The right-side annotation lists which composites contain that path. When the
user saves observables, `spec.yaml.observables:` is rewritten with the
selected `{path: [...]}` entries. The orchestrator rebuilds each composite's
emitter step at run time — paths not present in a composite are silently
skipped for that composite, with a per-run warning in the log.

### Composites tab UX

Sidebar list of composite names; click one to load its state tree (read-only
view, same renderer as Observables tab but without checkboxes). Actions:

- **+ Add composite** — modal: pick a workspace composite by name from the
  Registry's composites catalog. Server clones it to
  `composites/<chosen-name>.yaml` and adds the entry to `spec.yaml.composites`.
- **Perturb** (on each composite row) — modal: pick a name for the derived
  composite, then enter parameter or process overrides as JSON (Phase 1
  surface). Server creates the derivation recipe in spec.yaml, rebuilds the
  derived document.
- **Rebuild** (on derived composites) — re-render from recipe; surfaces in
  the UI when the parent document changes.
- **Remove** — delete the composite entry + its document file. Refuses if any
  run or visualization references it (returns a list of dependents).

### Backend endpoints

| Method + path | Purpose |
|---|---|
| `GET /api/investigation-composites?investigation=<n>` | List all composites in the study with metadata (name, source, extends, document path, last-build timestamp). |
| `POST /api/investigation-composite-add` | Body: `{investigation, name, source}`. Clones the registered composite into the study; appends to spec.yaml; renders document. |
| `POST /api/investigation-composite-perturb` | Body: `{investigation, name, extends, parameter_overrides?, process_overrides?}`. Validates parent exists; writes recipe to spec.yaml; renders derived document. |
| `POST /api/investigation-composite-rebuild` | Body: `{investigation, name}`. Re-renders a derived composite from its recipe in spec.yaml. |
| `DELETE /api/investigation-composite` | Body: `{investigation, name}`. Removes the entry + document. Refuses if dependents exist. |
| `GET /api/investigation-state-tree?investigation=<n>&composite=<c>` | Returns the recursive state tree of a single composite, for the Composites tab + Observables tab tree-rendering. |
| `POST /api/investigation-set-observables` | Body: `{investigation, paths: [[chromosome, DnaA_count], ...], emit_all: bool}`. Rewrites `spec.yaml.observables`. The emitter step in each composite document is rebuilt at next run, not at observable-save (keeps composite documents stable). |

### Migration of existing investigations

Run-once migration, triggered automatically on first dashboard open of an
investigation with the legacy single-`composite:` field. Migration steps:

1. Detect: `spec.yaml.composite` is a string and `spec.yaml.composites` is
   absent.
2. Render the Python-module composite to a state document (call the
   composite-builder function; serialize to YAML).
3. Write `investigations/<name>/composites/<baseline>.yaml`. The baseline
   name is the last dotted segment of the legacy composite reference
   (`pbg_x.composites.chromosome-partition` → `chromosome-partition`).
4. Rewrite spec.yaml:
   - Replace `composite: <path>` with `composites:` list containing one
     entry `{name: <baseline>, source: <path>, document: ./composites/<baseline>.yaml}`.
   - Update every `runs[]` entry: add `composite: <baseline>`.
5. Stage + commit as a single migration commit on the active branch.

Original Python module is not touched — it remains a registered workspace
composite that future Investigations can clone from.

## Data flow

**Create new Investigation:**

1. User picks "Pick a starting composite" → selects e.g.
   `pbg_chromosome_rep1.composites.chromosome-partition` from the Registry's
   composites catalog.
2. Dashboard POSTs `/api/investigation-create {name, source}`.
3. Server creates the directory, writes initial spec.yaml, renders
   `composites/<baseline>.yaml` from the source module.
4. Redirect to the Investigation viewer.

**Add perturbation:**

1. User opens the study's Composites tab → clicks **Perturb** on `baseline`.
2. Modal: name (e.g. `high-rate`), parameter overrides
   `{replication.rate: 2.0}`.
3. Dashboard POSTs `/api/investigation-composite-perturb`.
4. Server writes the recipe in spec.yaml; renders the derived document
   by deep-copying parent + applying overrides.
5. Composites tab refreshes; new composite appears in the list.

**Configure observables:**

1. User opens the Observables tab.
2. Server returns the union of state paths across all composites.
3. User ticks `chromosome.DnaA_count` + `chromosome.free_DnaA`.
4. Dashboard POSTs `/api/investigation-set-observables`.
5. Server rewrites `spec.yaml.observables`.

**Run all:**

1. User clicks **Run all** on the Investigation header.
2. Orchestrator iterates `runs[]`. For each entry:
   - Loads `composites/<runs[].composite>.yaml`.
   - Builds the composite (with SQLiteEmitter injected at the observables paths).
   - Runs for `steps` timesteps.
3. Visualizations re-render against `runs.db`. The `sources:` field on each
   viz filters which composite-runs contribute traces (e.g. show only
   `baseline` vs `high-rate` for one chart, all three for another).

## Error handling

- **Parameter override path not found:** rebuild fails with
  `"path 'replication.foo' not in composite 'baseline'"`. UI surfaces the
  error inline in the Perturb modal.
- **Process swap with incompatible inputs/outputs:** bigraph-schema raises a
  type-mismatch at `Composite()` construction. Surfaced in the
  Composites tab with the offending port name.
- **Observable path missing in a composite:** per-run warning in the runs
  log; that observable's column is null for that run; other observables
  still record. Visualization handles nulls gracefully.
- **Remove a composite with dependents:** endpoint returns 409 + the list of
  dependents (`runs[].composite == <name>` or `visualizations[].sources`
  contains `<name>`). User must clear dependencies first.

## Testing

**Migration (pbg-template):**
- `test_migrate_single_composite_investigation` — fixture with old-style
  `composite: pkg.composites.foo` spec.yaml; run migration; assert
  `composites/foo.yaml` rendered, spec.yaml rewritten as `composites:` list,
  `runs[].composite = foo` set.

**Composite operations:**
- `test_composite_add_clones_registered_source` — POST add; assert document
  file exists + spec.yaml entry present.
- `test_composite_perturb_parameter_only` — POST perturb with
  `parameter_overrides`; assert derived document has overridden value while
  parent is unchanged.
- `test_composite_perturb_process_swap` — POST perturb with
  `process_overrides`; assert derived document has new address.
- `test_composite_perturb_process_remove` — POST perturb with
  `process_overrides: {foo: null}`; assert derived document lacks that process.
- `test_composite_perturb_invalid_path_fails` — POST perturb with a
  non-existent parameter path; assert 400 + error message names the path.
- `test_composite_remove_with_dependents_refuses` — POST remove on a
  composite referenced by a run; assert 409 + dependents listed.

**State-tree + observables:**
- `test_state_tree_walks_nested_state` — fixture composite with stores +
  processes; assert returned tree has correct path + type for each leaf.
- `test_set_observables_writes_spec_yaml` — POST set-observables; assert
  spec.yaml.observables rewritten.

**End-to-end run:**
- `test_run_multi_composite_writes_separate_sim_names` — fixture study with
  3 composites + 1 run each; after run, assert runs.db has 3 rows with
  distinct `sim_name` values.
- `test_run_skips_missing_observable_in_composite` — observable path absent
  in one composite; assert that composite's run records nulls for that
  column, others record normally.

## Backwards compatibility

- **Existing single-composite Investigations** migrate via the run-once
  flow on first dashboard open. No manual intervention.
- **Visualization v2 dispatch** continues to read `runs.db` and render via
  the orchestrator's `gather_emitter_outputs` + `build_viz_composite`. The
  visualizations' `sources:` config field already filters by sim_name; for
  a single-composite migrated investigation, the baseline composite's name
  is the only sim_name.
- **`investigation-run`, `investigation-render-viz`, `investigation-add-viz`
  endpoints** stay; their internals adapt to the multi-composite spec.
- **The Composite Explorer (workspace level)** is unchanged. The
  Investigation-level Composites tab is a separate, study-scoped view.

## Implementation rollout

**Phase A — Schema + migration**
- Spec.yaml validator accepts the new `composites:` list shape.
- Migration script + auto-trigger on Investigation viewer open.

**Phase B — Backend endpoints**
- composite-add, composite-perturb, composite-rebuild, composite-remove.
- state-tree (single-composite).
- set-observables (rewrites spec.yaml.observables).

**Phase C — Orchestrator update**
- `run_investigation` resolves each `runs[].composite` to its document.
- Emitter step rebuilt per-composite per-run from `spec.yaml.observables`.

**Phase D — UI**
- Composites tab in Investigation viewer.
- Observables tab in Investigation viewer.
- "Pick a starting composite" step in the create-Investigation modal.

**Phase E — Verify on v2ecoli**
- Migrate the `test` + `2` Investigations.
- Create a new multi-composite Investigation (baseline + 1 perturbation).
- Confirm comparison visualization renders both traces.
