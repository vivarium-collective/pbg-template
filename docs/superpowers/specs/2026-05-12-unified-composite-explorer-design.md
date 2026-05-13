# Unified Composite Study + Composite Explorer

**Date:** 2026-05-12
**Status:** ⚠️ Superseded by [`2026-05-12-study-model-design.md`](./2026-05-12-study-model-design.md) on 2026-05-12. The Composite Study + Composite Explorer split (this spec) still stands; the Study data model has since been enriched with Baseline / Variant / Intervention / Comparison / Conclusions vocabulary and the 6-tab strip. Read the superseding spec for the current shape.
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:**
- The split between the workspace-level Composite Explorer (current editor) and the per-investigation detail viewer (`investigation-detail-tab` strip).
- The Composite Explorer editor refactor (`2026-05-12-composite-explorer-editor-design.md`) — its Configure tab survives the move into the Composite Study's Composites tab; the Observables and Visualization tabs are removed (those concerns live at study level only).

## Naming

Two distinct tools come out of this work:

- **Composite Explorer** — a lightweight, read-only viewer. Pick a composite from the workspace catalog, see its wiring in loom, optionally launch a Composite Study from it. No editing, no runs history, no observables/visualizations. Browser-only.
- **Composite Study** — the per-study working surface. An initial composite + perturbations (derived composites, optionally promotable to the workspace catalog) + a history of runs + observables + visualizations. Where research happens.

Both terms are user-facing labels.

The **Investigations** top-level menu entry remains; it now indexes Composite Studies. Each row is a Composite Study; clicking it enters the Composite Study workbench.

## Problem

Today the dashboard has two adjacent concepts with overlapping data:

- **Composite Explorer (workspace tab today, soon renamed):** pick a workspace composite, view its wiring, edit a single document via the just-shipped Configure/Observables/Visualization tabs, Save as a sidecar to some investigation.
- **Investigation detail viewer** (drill-in from the Investigations tab): per-study container with its own Composites/Runs/Observables/Visualizations tabs.

Three concrete problems:

1. **Two places to add observables / visualizations.** The editor refactor introduced composite-document-inline observables + viz (wired to an inline emitter step). The investigation viewer has its own observables list (`spec.yaml.observables`) and visualizations list (`spec.yaml.visualizations`). Users have to know which one to use; the data model carries both.
2. **Two places to view a composite's wiring.** The same loom-explore iframe is mounted in two views with subtly different surrounding affordances.
3. **No clear "research unit".** A study is conceptually: an initial composite + its perturbations + the runs you did + the observables you tracked + the visualizations you rendered. Today these are scattered across two UIs and the data model leaks the split.

## Goals

- **Composite Study = one per-study workbench.** Each study opens in the Composite Study view; its tabs are the study's facets (Composites tree, Runs history, Observables, Visualizations).
- **Investigations becomes a flat index of Composite Studies.** Click a row → enter the Composite Study for it. New studies are launched from Simulation Setup (pick a composite → start a study).
- **Observables + Visualizations live at study level only.** `spec.yaml.observables` and `spec.yaml.visualizations` are the source of truth. The orchestrator injects an emitter at run time per the study's observables list. The just-shipped inline-emitter/inline-viz editor (and its endpoints) is rolled back.
- **Keep a lightweight Composite Explorer** as a read-only catalog viewer. No editing, no tabs — just pick a workspace composite, see its wiring, optionally "Start a Composite Study with this composite" to launch one.
- **Derived composites are user-promotable to the workspace catalog.** A button on each derived composite in a Composite Study: "Promote to workspace catalog" copies it to `<workspace_pkg>/composites/<name>.composite.yaml` so future studies can pick it from Simulation Setup. Promotion is opt-in (the user judges whether the perturbation is worth promoting — typically after seeing run results that suggest the variant is meaningfully better).

## Non-goals

- **Cross-study composite references via study-id.** Studies remain independent; promotion goes through the workspace catalog (the single shared namespace).
- **Auto-promotion of derived composites.** Promotion is always an explicit user action — we don't infer "this one is good, save it" from run metrics in this design.
- **A new data shape for `spec.yaml`.** The existing multi-composite spec already supports everything we need (`composites: [...]`, `runs: [...]`, `observables: [...]`, `visualizations: [...]`).
- **Rolling back the multi-composite Investigation work.** That stays as-is; the UI changes route through the same `spec.yaml.composites` model.

## Architecture

### Composite Study (the per-study workbench)

```
┌────────────────────────────────────────────────────────────────┐
│ ← Investigations    Composite Study: dnaA-replication-…        │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ loom-explore iframe (currently-selected composite)         │ │
│ └────────────────────────────────────────────────────────────┘ │
│ [Composites] [Runs] [Observables] [Visualization]               │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ active tab panel                                            │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

URL: `#study/<study-name>` (or the existing `#investigations` + JS-managed sub-view; either is fine — implementation detail).

Header: breadcrumb (`← Investigations`) + study name. The "Save sidecar" button from the just-shipped editor is gone — every edit is automatically scoped to the open Composite Study.

**Wiring view** (top): loom-explore iframe shows the currently-selected composite from the Composites tab. Updates whenever the user picks a different composite or perturbs.

**Four tabs:**

1. **Composites** — sidebar list of composites in the study (initial + derived). Click a row → loom shows that composite + a Configure section appears below the wiring showing the composite's per-process configs (with default + units, editable). Per-composite actions: Perturb (creates a new derived), Rebuild (re-applies the recipe), Remove (refuses if the composite has dependents in Runs or Visualizations), **Promote to workspace catalog** (NEW — Phase C).

2. **Runs** — history of every run in this study, partitioned by composite name. Existing Investigation Runs view, no behavior change.

3. **Observables** — pick the state paths the study should record. `spec.yaml.observables` is the source of truth. Already present in the existing Investigation Observables tab — moves into the unified tab strip unchanged. The orchestrator injects an emitter into each composite-run at runtime per these paths (already-shipped `inject_emitter_step` helper).

4. **Visualization** — pick a class-backed Visualization instance + config to apply across this study's runs. Already present in the existing Investigation Add-Viz modal — moves into the unified tab strip. `spec.yaml.visualizations` is the source of truth.

The Configure surface — per-composite process-config editing from the editor refactor — folds into the Composites tab. When a composite is selected, the right pane shows wiring + collapsible per-process config rows below. No separate Configure tab.

### Investigations tab (Composite Study index)

```
┌────────────────────────────────────────────────┐
│ Investigations            [+ New from Sim Setup]│
│                                                │
│ ┌──────────────────────────────────────────┐  │
│ │ dnaA-replication-comparison  [open →]    │  │
│ │ 3 composites · 12 runs · 2 visualizations │  │
│ │ updated 2 hours ago                       │  │
│ └──────────────────────────────────────────┘  │
│ ┌──────────────────────────────────────────┐  │
│ │ chromosome-partition-baseline  [open →]  │  │
│ │ 1 composite · 0 runs · 0 visualizations  │  │
│ │ updated yesterday                         │  │
│ └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

A list of Composite Studies with summary stats; clicking a row navigates to the Composite Study workbench. The drill-in tab strip we have today (Spec/Runs/Visualizations/Composites/Observables) goes away — those are surfaced inside the Composite Study's tabs.

The "+ New" CTA is a hint that points to Simulation Setup (no new study-creation modal here — studies are created by picking a composite there).

### Simulation Setup (entry point for new Composite Studies)

Available Composites already has the "Explore" button (renamed from "Use" in the previous round). Clicking it:

1. Creates a NEW Composite Study with the picked composite as the initial composite. Study name auto-generated from the composite name + timestamp; user can rename later in the explorer header.
2. Navigates to the Composite Study workbench with the new study loaded.

No more "save sidecar to an arbitrary investigation" modal. You launch a fresh study from Sim Setup, then iterate in the workbench.

### Composite Explorer (workspace-level, read-only)

The lightweight viewer:

```
┌────────────────────────────────────────────────┐
│ Composite Explorer                             │
│                                                │
│ Catalog: [chromosome-partition ▼]              │
│                                                │
│ ┌────────────────────────────────────────┐    │
│ │ loom-explore iframe (read-only viewer) │    │
│ └────────────────────────────────────────┘    │
│                                                │
│ [Start a Composite Study with this composite]  │
└────────────────────────────────────────────────┘
```

URL: `#composite-explore` (keep the existing route).

- Picks a composite from the workspace catalog dropdown.
- Loom-explore renders it (no editing, no inline-emitter UI, no Save).
- "Start a Composite Study with this composite" button → creates a new study, navigates to the workbench.

This page is purely for browsing the catalog without committing to a study. Useful for "what's in this workspace's library?" inspection.

### Derived-composite promotion

In the Composites tab of a Composite Study, each derived composite row has a new **Promote to workspace catalog** action:

```
Composites in this study:
  • chromosome-partition           (initial, from pbg_chromosome_rep1.composites.chromosome-partition)
  • chromosome-partition-mukBEF-free  (extends: chromosome-partition)  [Promote] [Perturb] [Rebuild] [Remove]
  • chromosome-partition-high-rate    (extends: chromosome-partition)  [Promote] [Perturb] [Rebuild] [Remove]
```

**Promote** opens a modal:

- Target workspace package (auto-filled from `workspace.yaml.package_path`).
- Workspace-catalog name (defaults to the study's sidecar name).
- A short description (becomes the composite's top-level `description:`).

On submit, the server copies the study's sidecar YAML to `<workspace_pkg>/composites/<name>.composite.yaml` and commits. The promoted composite is then discoverable from Simulation Setup → Available Composites. The study's sidecar is unchanged — promotion is a one-way copy.

A `promoted: true` flag on the spec.yaml composites entry indicates the composite has a workspace-catalog twin (informational; doesn't change runtime behavior).

### Endpoint surface

**New endpoints:**

| Method + path | Purpose |
|---|---|
| `POST /api/investigation-create-from-composite` | Body: `{source_ref, study_name?}`. Creates a new investigation directory; copies the source composite into `composites/<baseline>.yaml`; writes spec.yaml with one-entry composites list. Returns `{study_name}`. Reachable from Simulation Setup Explore and Composite Explorer "Start a Composite Study". |
| `POST /api/composite-promote-to-catalog` | Body: `{investigation, sidecar_name, target_pkg?, catalog_name, description}`. Copies `investigations/<inv>/composites/<sidecar>.yaml` to `<pkg>/composites/<catalog_name>.composite.yaml`, sets the `description` field, commits. Marks the study's composite entry as `promoted: true`. |

**Removed endpoints (deprecated; removed entirely):**

The inline-emitter / inline-viz editor endpoints from the just-shipped Composite Explorer editor:

- `POST /api/compose-doc-inject-emitter`
- `POST /api/compose-doc-inject-viz`
- `POST /api/compose-doc-strip-viz`
- `POST /api/composite-state-tree-doc`
- `POST /api/composite-process-configs`
- `GET  /api/visualization-class-inputs`
- `POST /api/investigation-composite-save-sidecar`

The data-flow tests covering them are also removed. Their pure-logic counterparts in `compose_doc_edit.py` stay — they remain consumers of the `/pbg-emit` skill.

**Reused unchanged:**

- `/api/investigations` (list)
- `/api/investigation` (detail — payload shape stays the same; the UI is what changes)
- `/api/investigation-composites`, `-composite-add`, `-composite-perturb`, `-composite-rebuild`, `DELETE /api/investigation-composite`
- `/api/investigation-state-tree`
- `/api/investigation-set-observables`
- `/api/investigation-add-viz`, `-render-viz`
- `/api/investigation-run`
- `/api/composite-state` (for the read-only Composite Explorer)

### `compose_doc_edit` module

The pure-logic helpers (`inject_emitter`, `inject_viz_step`, `walk_process_configs`, etc.) stay in the codebase — they're still used by:

- `/pbg-emit` skill (CLI re-injection of an inline emitter for standalone runs).
- The orchestrator's `inject_emitter_step` (similar logic, separate copy in `investigations.py` — we may consolidate in a follow-up).

The dashboard no longer wires `inject_emitter` / `inject_viz_step` through HTTP. The unit tests for those helpers stay.

### Investigation Composites tab evolution

The Composites tab built earlier (sidebar list + state-tree detail + Add/Perturb/Rebuild/Remove) is the foundation of the Composite Study's Composites tab. Two additions:

1. **Configure section** — when a composite is selected, the right pane shows a per-process config editor below the state tree (or replacing the state tree, since loom-explore already shows structure). Reuses `walk_process_configs` from the editor refactor (in-memory only; no separate endpoint needed if we just pass the state-tree response through the existing investigation-state-tree endpoint with a richer payload).
2. **Promote button** — per derived-composite row; opens the promotion modal.

The Observables tab (path checkboxes, writes `spec.yaml.observables`) and Visualization tab (Add-viz modal + list) move from the current Investigation viewer into the Composite Study's tab strip. No behavior changes — just sliding the existing UI under the new top-level layout.

## Data flow

**Create a new Composite Study from Simulation Setup:**

1. User clicks Explore on `chromosome-partition` in Available Composites.
2. JS → `POST /api/investigation-create-from-composite` with `{source_ref: 'pbg_chromosome_rep1.composites.chromosome-partition'}`.
3. Server creates `investigations/<auto-name>/` with `spec.yaml` (one-entry composites list pointing at a fresh sidecar copy) + the sidecar at `composites/<baseline>.yaml`.
4. Response includes the auto-generated study name; JS navigates to the Composite Study workbench → mounts.

**Open an existing Composite Study from Investigations:**

1. User clicks "Open" on a row in the Investigations list.
2. JS navigates to the Composite Study workbench for that study.
3. Workbench mounts: fetches the study's `spec.yaml` (existing `/api/investigation` endpoint), populates the Composites sidebar, opens the first composite in loom.

**Promote a derived composite to the workspace catalog:**

1. User clicks Promote on a derived composite in the Composites tab.
2. Modal opens with target package + catalog name + description fields.
3. JS → `POST /api/composite-promote-to-catalog`.
4. Server copies the sidecar to `<workspace_pkg>/composites/<name>.composite.yaml`, adds the description, commits.
5. The Available Composites panel in Simulation Setup now shows the promoted composite on next refresh.

**Add an observable to a Composite Study:**

1. User opens the Observables tab in the workbench.
2. State-tree walker reports all leaf store paths across the study's composites.
3. User ticks a path; JS → `POST /api/investigation-set-observables`.
4. Server rewrites `spec.yaml.observables`. On the next run, the orchestrator's `inject_emitter_step` builds the emitter step per these paths and wires it into each composite document at runtime.

**Visualizations:**

1. User opens the Visualization tab, clicks "+ Add visualization".
2. Existing Add-viz modal (visualization class picker + config). On submit, appends to `spec.yaml.visualizations`.
3. On render-viz call, the orchestrator runs each viz against the emitter data.

## Error handling

- **Create-from-composite source not found:** 404 with the unresolved source ref.
- **Study name collision** (Simulation Setup launch creates an auto-name that already exists): retry with `<name>-2`, `<name>-3`, … in the server.
- **Promote-to-catalog name collision:** server returns 409 with "name already exists in catalog"; modal shows the message inline.
- **Promote on a composite that hasn't been built yet** (derived but never rebuilt after a parent change): server rebuilds first, then promotes.

## Testing

**Endpoints:**

- `test_post_create_from_composite_creates_study` — fixture workspace composite; POST; assert investigation dir exists + spec.yaml has the composite entry + sidecar file written.
- `test_post_create_from_composite_auto_name_collision_retry` — pre-existing study with the auto-generated name; new POST returns a `-2`-suffixed name.
- `test_post_promote_to_catalog_copies_sidecar` — fixture study with a sidecar; POST; assert `<pkg>/composites/<name>.composite.yaml` exists + description field set + spec.yaml entry has `promoted: true`.
- `test_post_promote_to_catalog_refuses_duplicate_name` — sidecar with a catalog-name that already exists; 409.

**Frontend:**

UI verification happens in Phase E (v2ecoli E2E). No automated frontend tests added.

## Backwards compatibility

- **Data model unchanged.** All existing `investigations/<name>/spec.yaml` files load as-is. The Composite Study workbench reads them through the existing endpoints.
- **The current Investigation Composites tab UI** is the substrate of the workbench's Composites tab — adding the Promote action and the Configure section is additive.
- **The just-shipped editor refactor's inline-emitter/viz endpoints are removed.** No live data uses them (we just shipped them; no one has used the Save flow yet). Tests for those endpoints are deleted.
- **The `#composite-explore` route** keeps working — it's the new lightweight Composite Explorer viewer (loom + catalog dropdown + "Start a Composite Study" CTA).
- **The `#investigations/<name>` route (or equivalent JS sub-view)** keeps working — it now opens the Composite Study workbench instead of the old detail viewer's tab strip.

## Implementation rollout

**Phase A — Endpoint surface:**

- `POST /api/investigation-create-from-composite` (new).
- `POST /api/composite-promote-to-catalog` (new).
- Remove the 7 inline-emitter / inline-viz / state-tree-doc / process-configs / save-sidecar / visualization-class-inputs endpoints + their tests.

**Phase B — Composite Study layout:**

- New top-level layout: header + breadcrumb + wiring view + tab strip + tab panel.
- Composites tab: existing sidebar + state-tree detail + Configure section below.
- Move Observables + Visualization tabs from the current Investigation detail viewer into the Composite Study's tab strip.
- Remove the Configure/Observables/Visualization tabs from the workspace-level page (which is now the lightweight Composite Explorer).

**Phase C — Promote action:**

- "Promote to workspace catalog" button on each derived-composite row.
- Promotion modal.
- Spec.yaml entry gets `promoted: true` (informational).

**Phase D — Simulation Setup entry + Composite Explorer (lightweight viewer):**

- Simulation Setup Explore button: replaces "navigate to Composite Explorer" with "create a Composite Study from this composite + navigate to its workbench".
- Composite Explorer (workspace-level page): rebuild as read-only — catalog dropdown + loom-explore + "Start a Composite Study" button. Delete the now-orphaned tab strip + panels.

**Phase E — Investigations index + v2ecoli E2E:**

- Investigations tab: flat study list with summary stats.
- v2ecoli verification: open existing `t1` in the workbench; create a new study from Sim Setup; perturb + promote a derived composite; confirm spec.yaml + catalog updates.

## Out of scope (follow-ups)

- **Auto-suggestion of which derived composites to promote** based on run metrics — defer until we have a metrics surface to read.
- **Study templates** — "use this study as a starting point for a new one". Possible via a "Clone study" action; not in this design.
- **Cross-study comparison view** — e.g., overlay runs from multiple studies in one chart. Visualization-level future work.
- **Renaming a Composite Study** in place. The study name is the directory name; renaming requires a directory rename + spec.yaml + git move. Defer.
- **Consolidating the two copies of `inject_emitter`-style logic** (compose_doc_edit.py + investigations.py). Cleanup follow-up.
- **Renaming the Investigations menu entry** to "Composite Studies" or "Studies". Possible but a bigger label-change ripple; for now Investigations stays as the menu label, Composite Studies is what it indexes.
