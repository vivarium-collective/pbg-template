# Composite Explorer → Composite-document editor

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:** the read-only Composite Explorer page (workspace-level) and the "Use" button in Simulation Setup → Available Composites.

## Problem

Today the workspace-level Composite Explorer is mostly a viewer (state tree, optional loom-explore iframe). Composite tuning happens by hand-editing YAML or via the investigation perturb modal. Three concrete gaps surfaced:

1. **No UI for tuning a composite's process configs** — users edit YAML by hand or use the perturb-recipe modal (dotted-path JSON). The "Parameters" sub-page exists today but isn't structured around the process boundaries the user thinks in.
2. **No UI for adding an emitter back** — we just stripped inline emitters from default composites; users need an on-ramp to add them when a composite needs to run standalone. The `/pbg-emit` skill does this from CLI; the dashboard should too.
3. **No UI for adding a visualization** — selecting a `Visualization` class and wiring it to emitter outputs is currently a hand-YAML job.
4. **Simulation Setup carries an Observables section that overlaps with the new model** — observables belong with the composite (where the emitter lives) or with the investigation (`spec.yaml.observables`), not with simulation-launch config.

## Goals

- **Composite Explorer becomes a composite-document editor.** Three tabs alongside the loom-explore wiring view: Configure / Observables / Visualization. Edits accumulate in an in-memory composite doc; the wiring iframe re-renders live as the user edits.
- **Save creates an investigation-scoped sidecar.** Save dialog asks for an investigation name + sidecar composite name; writes the edited doc to `investigations/<inv>/composites/<sidecar>.yaml`. The source workspace composite is never modified.
- **Default composites stay bare.** The strip we just shipped (no inline emitter) holds for default workspace composites. Inline emitter + viz appear only after the user explicitly adds them through this editor.
- **Rename "Use" → "Explore"** in Simulation Setup's Available Composites panel — verb matches the intent (opens the Composite Explorer, doesn't commit anything to the workspace).
- **Remove the Observables section from Simulation Setup.** It's redundant with the new Observables tab (composite-scoped) and the Investigation Observables tab (workflow-scoped).

## Non-goals

- **Editing the source workspace composite in place.** Save always writes a sidecar; the workspace composite stays as-is. Future work can add a "publish back to workspace" button if needed.
- **Editing pbg-* upstream wrapper composites.** Those are submodule files; editing them needs PRs to the upstream repos. Out of scope here.
- **A composite *builder* from scratch.** This editor configures + instruments an *existing* composite. Building a composite from zero stays a YAML/skill task for now.
- **Cross-investigation overlays.** Edit one composite at a time; save creates one sidecar in one investigation.

## Architecture

### Top-level Composite Explorer layout

```
┌────────────────────────────────────────────────────────────────┐
│ Composite Explorer: chromosome-partition                       │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │                                                            │ │
│ │  loom-explore iframe (current in-memory doc)               │ │
│ │                                                            │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                │
│ [ Configure | Observables | Visualization ]   [ Save sidecar ] │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ Active tab panel (Configure shown by default)              │ │
│ │                                                            │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

Tab strip + Save button sit between the wiring view (top) and the active
panel content (bottom). Switching tabs doesn't reload loom-explore.

### In-memory document model

`window._composeDoc` (JS module var) holds the current edited composite as a
plain JS object: the parsed YAML from the source composite, mutated by
panel edits. On every edit:

1. The relevant panel mutates `_composeDoc` (e.g., Observables tab adds an
   `emitter:` step to `state`).
2. `_postCompositeToLoom(_composeDoc)` pushes the new doc into the iframe
   via the existing postMessage protocol — wiring re-renders.
3. Save serializes `_composeDoc` to YAML and writes via the new
   `POST /api/investigation-composite-save-sidecar` endpoint.

The source composite document is the initial value of `_composeDoc` on
"Explore" click. Reloading the page or picking a different composite
resets the in-memory state.

### Configure tab (renamed from "Parameters")

Rows-per-process layout, each row expandable. Walks `_composeDoc.state` and
emits one row per node with `_type: process`:

```
▼ partitioner                                       (local:ChromosomePartition)
    partition_method   [mukBEF-anchored ▼]   default: "mukBEF-anchored"
    cell_volume        [1.5e-15           ]   default: 1.5e-15 fL  (units: fL)
▶ growth                                            (local:ExponentialGrowth)
▶ replisome                                         (local:DnaAReplisome)
```

Each row's expanded view enumerates `node.config` keys. For each key, the
form input type depends on the value type:

- `string` → text input (or `<select>` if the schema enumerates options)
- `number` (int/float) → number input with step
- `boolean` → checkbox
- nested dict → textarea with JSON

**Units** display: if `_composeDoc.parameters?.<key>?.units` is set in the
composite's `parameters:` block (composite-document convention), the unit
string renders next to the input. If not, no unit shown.

**Default value** display: render `_composeDoc.parameters?.<key>?.default`
or the literal current config value. The input prepopulates with the
current value; changing it mutates `_composeDoc.state.<process>.config.<key>`.

Doesn't touch `_composeDoc.parameters`; only the process's `config` map.

### Observables tab

Single panel with two parts:

1. **Pick paths.** Same state-tree walker used by the Investigation
   Observables tab — flat list of `{path, type, default}` for every leaf
   store. Each path has a checkbox.
2. **Apply.** When the user changes the selection, the Observables tab
   immediately rewrites `_composeDoc.state.emitter` using the same logic
   as `inject_emitter_step` in `investigations.py`:

```yaml
emitter:
  _type: step
  address: 'local:SQLiteEmitter'
  config:
    emit: {<port>: <type>, ...}
  inputs:
    <port>: [path, to, leaf]
```

If no observables are picked, the `emitter` key is removed entirely (bare
state). Picking any path adds it back.

The wiring iframe re-renders live — the emitter appears/disappears as the
user ticks paths.

A small toggle above the tree: "Use RAMEmitter instead of SQLiteEmitter"
swaps the address (defaults to SQLite).

### Visualization tab

Two-column layout:

```
┌──────────────────────┬──────────────────────────────────────────┐
│ Visualization class  │ Wiring summary                           │
│ [ TimeSeriesPlot ▼]  │ ✓ observable ← emitter.observable        │
│                      │ ✓ time       ← emitter.time              │
│                      │ ✗ threshold  ← (no emitter port matches) │
│ Config (JSON):       │                                          │
│ {"title":"DnaA"}     │                                          │
└──────────────────────┴──────────────────────────────────────────┘
```

User flow:

1. Pick a Visualization class from `/api/visualization-classes`.
2. Auto-wiring: each declared input port (per `cls.inputs()`) auto-wires
   to the matching emitter output port if a name matches. Mismatches
   render as a `✗` line with a hint.
3. If at least one input wires, the panel writes a `viz:` step into
   `_composeDoc.state`:

```yaml
viz:
  _type: step
  address: 'local:TimeSeriesPlot'
  config: {title: 'DnaA'}     # from the JSON textarea
  inputs:
    observable: [emitter, observable]
    time:       [emitter, time]
```

(Mismatched ports are simply omitted from the wiring — the Visualization
runs with whatever was wired.)

4. Removing the viz: a "Remove visualization" button deletes
   `_composeDoc.state.viz`.

The loom-explore iframe re-renders — the viz step appears as a new node
downstream of the emitter.

### Save dialog

Triggered by the "Save sidecar" button at top-right of the tab strip.
Modal:

```
Save edited composite as sidecar
┌────────────────────────────────────────────────┐
│ Investigation: [ t1                       ▼]   │  ← existing investigations
│ Sidecar name:  [ chromosome-partition-tuned]   │  ← required, regex ^[a-zA-Z0-9_-]+$
│                                                │
│ Source: pbg_chromosome_rep1.composites.        │  ← read-only
│         chromosome-partition                   │
│                                                │
│ [Cancel]                            [Save]     │
└────────────────────────────────────────────────┘
```

If "t1" doesn't have a `composites/<sidecar>.yaml` slot already, the new
file is written there; otherwise the modal refuses with "already exists,
pick another name".

POST `/api/investigation-composite-save-sidecar`:
- Body: `{investigation, name, document}` where `document` is the
  serialized in-memory YAML.
- Server: validates the document is well-formed (`yaml.safe_load` round-trips),
  writes `investigations/<inv>/composites/<name>.yaml`, also appends an
  entry to `spec.yaml.composites[]` with `source` set to the original
  composite ref (so the Investigation Composites tab shows it as a
  separately-tracked sidecar). Uses `_commit_or_run` so a dirty tree
  refuses cleanly.
- Returns `{ok, branch, commit, path}`.

### Simulation Setup changes

Two surface-level changes only:

1. **Rename "Use" → "Explore"** on each row of the Available Composites
   panel. Click navigates to Composite Explorer (today) with the picked
   composite preloaded. Semantics: explore (and optionally tune + save as
   a sidecar), don't blindly "use".

2. **Remove the Observables section** from Simulation Setup. Observables
   live at:
   - The composite document level (added via Composite Explorer's
     Observables tab → inline emitter).
   - The investigation level (`spec.yaml.observables`, via the
     Investigation Observables tab).

   Both paths render in loom-explore (composite-level inline) or are
   applied at run time (investigation-level via the orchestrator).

### Backend endpoints

| Method + path | Purpose |
|---|---|
| `POST /api/investigation-composite-save-sidecar` | Body `{investigation, name, document}`. Validate doc, write `investigations/<inv>/composites/<name>.yaml`, append entry to `spec.yaml.composites[]`. Returns commit info. |

No other new endpoints — the existing `/api/composite-state`,
`/api/visualization-classes`, and `/api/investigations` cover the rest.

### Wrapper-package composites (the bond-network-with-viz question)

Upstream wrapper composites (`pbg-caspule`, `pbg-readdy`, etc.) still
carry inline emitter + viz steps. They're cloned via submodule and stay
upstream-managed. The dashboard renders whatever they declare. Stripping
them upstream is out of scope; users who want a clean view can use this
new editor to create a sidecar from the upstream composite (which would
inherit the upstream's structure — the editor doesn't auto-strip).

A small future enhancement: a "Strip emitter+viz" button in the Configure
tab that removes those steps from `_composeDoc` before saving. Documented
under Out of scope; not in this spec.

## Data flow

**Explore a workspace composite:**

1. User clicks Explore on `chromosome-partition` row.
2. Dashboard navigates to Composite Explorer with `?composite=<ref>` URL param.
3. JS fetches `/api/composite-state?ref=...` → parses → assigns to
   `window._composeDoc`.
4. PostMessage to loom-explore iframe → wiring renders.
5. Configure tab populated by walking `_composeDoc.state` for processes.
6. Observables tab loaded with empty selection.
7. Visualization tab loaded with empty class picker.

**Edit + save:**

1. User expands `partitioner` in Configure tab → changes `partition_method`
   to `mukBEF-free`. JS mutates `_composeDoc.state.partitioner.config.partition_method`.
2. User opens Observables tab → ticks `stores.chromosome.count`. JS
   rewrites `_composeDoc.state.emitter`.
3. User opens Visualization tab → picks `TimeSeriesPlot`. JS wires its
   inputs to the emitter's output ports.
4. Each step posts the updated doc to the loom-explore iframe; wiring
   reflects live.
5. User clicks Save sidecar → fills modal (investigation=t1,
   name=chromosome-partition-mukBEF-free) → POST.
6. Server writes `investigations/t1/composites/chromosome-partition-mukBEF-free.yaml`
   + updates `spec.yaml`. Commits via the active workstream.
7. UI: success toast; nav to the Investigation Composites tab (or stay
   on Composite Explorer with the sidecar name in the URL).

## Error handling

- **No investigations exist when Save is clicked.** Save dialog shows a
  "Create new investigation first" hint with a link to the Investigation
  create modal.
- **Edited path doesn't exist in the source composite.** Configure tab
  can only edit existing process configs (no add/remove processes), so
  this can't happen for Configure. Observables tab only shows real
  paths from the state-tree walker. Visualization tab's auto-wire skips
  missing ports.
- **Document validation fails on Save.** Server returns 400 with the
  yaml/schema error; modal surfaces it inline. The in-memory doc stays
  loaded so the user can fix.
- **Workspace tree dirty.** `_commit_or_run` refuses cleanly; modal
  surfaces the dirty-file list (consistent with the rest of the dashboard).

## Testing

**Configure helpers (pbg-template):**
- `test_walk_process_configs` — `_composeDoc.state` walker yields one
  entry per process with its config keys + units + defaults.
- `test_apply_process_config_update` — mutating a process's config key
  updates only that key.

**Observables wiring (pbg-template):**
- `test_inject_emitter_into_compose_doc` — picking paths writes the
  `emitter:` step with correct `inputs` + `config.emit` schema.
- `test_empty_observables_strips_emitter` — clearing the selection
  removes `emitter:` from `state` (bare composite).

**Viz auto-wiring:**
- `test_viz_auto_wire_matches_named_ports` — Viz inputs that match
  emitter output port names wire automatically.
- `test_viz_partial_match_omits_unmatched_ports` — Viz inputs without
  a matching emitter port are silently omitted from `viz.inputs`.

**Save endpoint:**
- `test_save_sidecar_writes_yaml_and_updates_spec` — round-trip
  fixture: post a doc, assert file exists, spec.yaml has the new
  composite entry, doc parses back to the same shape.
- `test_save_sidecar_refuses_duplicate_name` — second save with the
  same `(investigation, name)` returns 409.

## Backwards compatibility

- The existing Composite Explorer's wiring view and state tree continue
  to work; the new tabs are additive.
- Simulation Setup's "Use" button is replaced (not removed) by "Explore"
  pointing to the same destination. No URL or endpoint changes.
- Simulation Setup's Observables section is removed; its data (if any
  was stored) is not migrated. Users re-pick observables via the new
  Composite Explorer Observables tab. Worth noting: no users have
  observables stored there yet on v2ecoli.
- All existing investigation composites stay valid. Sidecar saves just
  add new entries.

## Implementation rollout

**Phase A — backend:**
- `/api/investigation-composite-save-sidecar` endpoint.
- Helper module `template/scripts/_lib/compose_doc_edit.py` with pure-
  logic functions: `apply_config_update`, `inject_emitter`,
  `strip_emitter`, `inject_viz_step`, `strip_viz_step`, plus the
  state-tree walker that emits process+config rows (Configure data).

**Phase B — frontend tabs:**
- Layout: wiring iframe + tab strip + active panel below.
- Configure tab: rows-per-process, expandable, config inputs.
- Observables tab: state-tree + checkboxes + RAMEmitter toggle.
- Visualization tab: class picker + auto-wire + config JSON.
- Live re-render: every edit posts updated doc to loom-explore.

**Phase C — Save dialog + integration:**
- Save modal (investigation picker + sidecar name input).
- POST + success/failure UX.
- Auto-nav to Investigation Composites tab on success.

**Phase D — Simulation Setup cleanup:**
- "Use" → "Explore".
- Remove Observables section.

**Phase E — v2ecoli verification:**
- Open `chromosome-partition` in Composite Explorer → tweak a param,
  add observables, add TimeSeriesPlot → save as
  `chromosome-partition-tuned` into t1 → confirm `investigations/t1/composites/chromosome-partition-tuned.yaml`
  + `t1/spec.yaml` has the new entry + loom-explore renders the
  instrumented composite end-to-end.

## Out of scope (follow-ups)

- **Publish-back-to-workspace.** A "Promote sidecar to workspace" button
  that copies a tuned sidecar back to `<pkg>/composites/`.
- **Strip emitter+viz button.** A Configure-tab action that removes
  inline emitter + viz from an upstream-cloned composite for a cleaner
  baseline.
- **Add/remove processes.** Building composites from scratch via
  click-to-add. Currently this editor only tunes existing processes.
- **Visualization config form.** Today the Visualization tab takes
  config as raw JSON; a future iteration could render structured form
  inputs based on the class's `config_schema`.
- **Reordering process nodes.** Loom-explore already lets users drag
  nodes for layout; that's not persisted yet (separate follow-up
  documented in the loom-explore spec).
