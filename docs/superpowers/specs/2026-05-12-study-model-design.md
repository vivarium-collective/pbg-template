# Study model — Baseline / Variants / Interventions / Comparisons / Conclusions

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:**
- `2026-05-12-unified-composite-explorer-design.md` (the unified Composite Study + Composite Explorer spec).
- The implementation plan `2026-05-12-unified-composite-explorer.md` (replaced by a fresh plan to be written from this spec).

The unified-CE spec's structural decisions — Composite Study as the per-study workbench, Composite Explorer as the read-only viewer, derived composites promotable to the workspace catalog, Investigations tab as a flat index — all stand. This spec adds the research-workflow vocabulary on top.

## Vocabulary

| Term | Definition |
|---|---|
| **Composite Study** | A research unit. Contains study metadata (question / hypothesis / status) + one baseline + zero or more variants + runs + observables + comparisons + visualizations + conclusions. |
| **Study metadata** | Three top-level scalars: `question` (the research question), `hypothesis` (predicted outcome), `status` (`draft` \| `in-progress` \| `completed` \| `archived`). All free-edit from the Overview tab. |
| **Baseline Composite** | The reference model the study starts from. One per study. Cloned from a workspace catalog composite at study-creation time. |
| **Composite Variant** | An executable composite document derived from the baseline (or from another variant). Each variant has its own sidecar YAML. Promotable to the workspace catalog. |
| **Intervention** | A recipe applied to a baseline or variant to produce a new variant. Holds `parameter_overrides` and/or `process_overrides`. Per-variant inline; not a separate reusable object. |
| **Run** | One execution of a variant (or the baseline) under a specific simulation setup. Recorded in the study's runs.db. |
| **Comparison** | A named selection of variants + observables, used to set up a cross-variant analysis. Minimal shape `{name, variants[], observables[]}`. Visualizations render against a comparison. |
| **Visualization** | A view over runs and/or comparisons. Existing `spec.yaml.visualizations` model — entries can now reference a comparison by name. |
| **Conclusions** | A free-text markdown writeup of the study's findings. One per study. |

"Group" is the conceptual term for a variant + its intervention — what an experimentalist would call a treatment condition. In storage and UI, the data is the **Variant** (with its Intervention inline). The Group label is a UX shorthand, not a separate entity.

## Problem

The previous unified-CE spec modelled a Study as a flat list of composites with a few side-fields (runs, observables, visualizations). That captures structure but doesn't carry the research workflow's vocabulary:

- Users think "baseline + experimental conditions", not "list of equally-weighted composites".
- "Why did we make this variant?" is answered by an **intervention** (a recipe). Currently that recipe is inline in the composite entry but unnamed and not surfaced as a first-class concept.
- "What do we conclude from this study?" has no place to live. There's no Conclusions tab; findings live in PR descriptions or notebooks.
- "Compare these three variants on these two observables" is currently fudged through visualization configs. A first-class Comparison object makes the intent legible.

## Goals

- **Promote vocabulary to the spec.** `spec.yaml.baseline` (string), `spec.yaml.variants[]`, `spec.yaml.comparisons[]`, `spec.yaml.conclusions` are first-class. Each variant's intervention lives in its entry.
- **6-tab Composite Study workbench.** Overview | Composites | Interventions | Runs | Visualizations | Conclusions.
- **Comparisons are explicit objects.** Visualizations can reference a Comparison by name. The Visualization tab also hosts a Comparisons sub-panel for create/edit/delete.
- **Conclusions are markdown** stored at `spec.yaml.conclusions`, edited via a simple textarea in the Conclusions tab (no rich editor needed).
- **Migration from current spec.yaml is automatic.** Existing `composites[]` gets translated: first entry becomes the baseline; rest become variants with their `parameter_overrides`/`process_overrides` becoming `intervention.*`.

## Non-goals

- **Workspace-level intervention library.** Interventions stay per-variant inline. A future enhancement can promote interventions to a catalog (separate from composite promotion).
- **Statistical tests in Comparisons.** Comparisons hold `{name, variants[], observables[]}` only. The viz system handles whatever statistical view is needed.
- **Multi-variant groups.** A "group" maps 1:1 to a variant. Parameter sweeps are runs-level (multiple runs of one variant) and don't create extra variants.
- **Conclusions linked to specific runs/comparisons.** Conclusions are a single per-study markdown blob. Cross-linking (e.g., "[see run #42]" auto-rendering) is a follow-up.
- **Rich-text editing.** Plain markdown textarea; rendered with the existing markdown helper used elsewhere in the dashboard.

## Architecture

### Data model: `spec.yaml` shape

```yaml
name: dnaA-replication-comparison
question: |                                     # NEW: free-text research question
  Does doubling the replication rate proportionally shift DnaA accumulation?
hypothesis: |                                   # NEW: predicted outcome
  Final DnaA count after 100 steps will double when the replication rate doubles.
status: in-progress                             # NEW: draft | in-progress | completed | archived

baseline: chromosome-partition                 # name of the variant that is the baseline

variants:                                       # was: composites[]
  - name: chromosome-partition
    source: pbg_chromosome_rep1.composites.chromosome-partition
    document: ./composites/chromosome-partition.yaml
    # No intervention — this is the baseline.

  - name: high-rate
    extends: chromosome-partition               # parent variant (or baseline)
    document: ./composites/high-rate.yaml
    intervention:                                # NEW: was inline at variant level
      description: "Double the replication rate"
      parameter_overrides:
        state.replication.config.rate: 2.0

  - name: no-replication
    extends: chromosome-partition
    document: ./composites/no-replication.yaml
    intervention:
      description: "Remove the replication process entirely"
      process_overrides:
        replication: null

  - name: simplified-replication
    extends: chromosome-partition
    document: ./composites/simplified-replication.yaml
    intervention:
      description: "Replace the DnaA replisome with a simplified model"
      process_overrides:
        replication: 'local:SimplifiedReplication'
    promoted: true                               # marked after Promote-to-catalog

runs:                                            # unchanged shape
  - composite: chromosome-partition              # = variant name (terminology stays "composite" in this field for API compatibility)
    params: {seed: 1}
    steps: 100
  - composite: high-rate
    params: {seed: 1}
    steps: 100

observables:                                     # unchanged
  - {path: [chromosome, DnaA_count]}

comparisons:                                     # NEW
  - name: replication-rate-comparison
    description: "Effect of doubling the replication rate"
    variants: [chromosome-partition, high-rate]
    observables: [DnaA_count]

visualizations:                                  # unchanged shape; viz can reference a comparison
  - name: dnaA-traj-comparison
    class: TimeSeriesPlot
    config:
      observable: DnaA_count
      comparison: replication-rate-comparison    # NEW optional field
      # OR equivalent: sources: [chromosome-partition, high-rate]  # existing path stays valid

conclusions: |                                   # NEW; markdown blob, 4 conventional sections
  ## Claims

  Doubling the replication rate doubles the final DnaA count after 100 steps.

  ## Evidence

  - rate-cmp visualization shows the 2× ratio cleanly.
  - All 3 replicates per condition converged within 5% of the mean.

  ## Limitations

  - Rate parameter above 1.5 may not be physiologically realistic.
  - We didn't test below 0.5.

  ## Next steps

  - Sweep the rate parameter at finer resolution.
  - Add the chromosome-state observable to confirm replisome timing.
```

Conclusions is stored as one markdown blob; the UI splits/joins on the four conventional `## Claims`, `## Evidence`, `## Limitations`, `## Next steps` headers. If a blob doesn't follow that structure (e.g., legacy free-form), the entire content lands in the Claims textarea on first load; saving re-emits the structured form.

**Renaming**: `spec.yaml.composites` becomes `spec.yaml.variants`. The `composite:` field inside each `runs[]` entry stays the same — it references a variant by name, and "composite" remains a clean term for that. Inside endpoints + UI, "variant" is the user-facing label.

**Backwards compatibility**: `load_spec` accepts both `composites:` (legacy) and `variants:` (new). A small migration helper rewrites the file on first open of an old-shape study. `parameter_overrides` and `process_overrides` at the top level of a variant entry are also accepted (legacy); the migration nests them under `intervention:`.

### Composite Study workbench (6 tabs)

```
┌────────────────────────────────────────────────────────────────┐
│ ← Investigations    Composite Study: dnaA-replication-…        │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ loom-explore iframe (currently-selected variant)           │ │
│ └────────────────────────────────────────────────────────────┘ │
│ [Overview][Composites][Interventions][Runs][Visualizations][Conclusions] │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ active tab panel                                            │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

#### Overview tab

Editable study-metadata header + read-only at-a-glance summary.

**Editable header** (top of the tab):

- **Question** (multi-line text) — the research question being asked.
- **Hypothesis** (multi-line text) — predicted outcome.
- **Status** (dropdown: draft / in-progress / completed / archived).

Each edit auto-saves on blur via `POST /api/investigation-set-overview`.

**Summary** (below the header, read-only):

- Baseline composite name + source ref
- Variant count + names (with their intervention descriptions)
- Run count (total) + per-variant run-count
- Comparison count + names
- Visualization count
- First 200 chars of Conclusions, "Read more →"

Useful as a landing view; user navigates to specific tabs from there.

#### Composites tab (today's Composites, lightly reshaped)

Sidebar list of variants (baseline always first, then derived). Click any → loom-explore renders + Configure section appears below the wiring with the variant's per-process configs. Same actions as today: Add (new variant from registry), Perturb (create derived variant via intervention), Rebuild, Remove, Promote.

When a variant is selected, the right pane also shows its Intervention summary (`description:` + readable representation of `parameter_overrides` and `process_overrides`) — but this is a read-only mirror; full editing happens in the Interventions tab.

#### Interventions tab (NEW)

Cross-cutting view: a table of all interventions in the study, one row per non-baseline variant. Columns: variant name, parent (`extends`), description, parameter overrides (count or compact list), process overrides (count or compact list).

Click an intervention row → opens an inline editor. Edits to `description` are immediate; edits to `parameter_overrides`/`process_overrides` reuse the existing Perturb modal logic (POSTs to `/api/investigation-composite-perturb` with the updated recipe; the variant document rebuilds from its parent).

This tab is the "tell me at a glance what experimental conditions are in play" view.

#### Runs tab (today's Runs, unchanged)

History of every run. Group by variant. Click a run → see params, status, last_run timestamp. Run buttons (single-run, run-all).

#### Visualizations tab (today's Visualizations + Comparisons sub-panel)

Two sections in this tab:

1. **Comparisons** (top, NEW):
   - List of comparisons in the study
   - Each row: name, variants included, observables included, [Edit] [Remove]
   - "+ Add comparison" button → modal: name, multi-select variants, multi-select observables
2. **Visualizations** (bottom, existing):
   - Same Add-visualization modal as today, with one addition: a "Comparison" dropdown that, when selected, auto-fills `sources` from the comparison's variants list and `observable` from its observables.

#### Conclusions tab (NEW)

Four labeled textareas — **Claims**, **Evidence**, **Limitations**, **Next steps** — backed by `spec.yaml.conclusions` (a single markdown blob with conventional `## Claims` / `## Evidence` / `## Limitations` / `## Next steps` H2 sections).

On load, the JS splits the blob on those H2 headers and fills each textarea. On Save, it re-joins them with the H2 headers and POSTs the combined blob to `/api/investigation-set-conclusions`. Legacy free-form blobs land entirely in the Claims textarea on first load; saving re-emits the structured form.

Below the textareas, the live-rendered markdown preview (debounced 300ms).

### Endpoint surface

**New endpoints (this spec):**

| Method + path | Purpose |
|---|---|
| `POST /api/investigation-set-conclusions` | Body: `{investigation, markdown}`. Writes `spec.yaml.conclusions`. |
| `POST /api/investigation-set-overview` | Body: `{investigation, fields: {question?, hypothesis?, status?}}`. Selective update of the three Overview metadata fields. `status` must be one of `draft` \| `in-progress` \| `completed` \| `archived`. |
| `POST /api/investigation-comparison-add` | Body: `{investigation, name, description?, variants[], observables[]}`. Appends to `spec.yaml.comparisons`. |
| `POST /api/investigation-comparison-update` | Body: `{investigation, name, fields_to_update}`. Replaces a comparison entry. |
| `DELETE /api/investigation-comparison` | Body: `{investigation, name}`. Refuses with 409 if any visualization references this comparison. |

**Endpoints unchanged from the unified-CE plan:**

- `POST /api/investigation-create-from-composite` (Phase A Task 2 of the unified plan stays)
- `POST /api/composite-promote-to-catalog` (Phase A Task 3 stays)
- All existing investigation/composite endpoints reused

**Endpoints to remove (rollback of the just-shipped editor):**

Same as in the unified plan — the 7 inline-edit endpoints stay deprecated/removed.

### Migration helper

A one-time `migrate_study_to_v2_vocabulary(spec_path)` helper:

1. Detect: `spec.composites` present and no `spec.variants`.
2. Rename `composites:` → `variants:`.
3. For each variant entry: if it has `parameter_overrides` or `process_overrides` at the top level, nest them under `intervention:` with `description: ""`.
4. Identify the baseline: the variant with `source:` (no `extends:`) is the baseline; set `spec.baseline: <that variant's name>`. If multiple have `source` and no `extends` (shouldn't happen in v2ecoli's t1), pick the first; warn in a migration log.
5. Initialize `spec.comparisons: []`, `spec.conclusions: ""`, `spec.question: ""`, `spec.hypothesis: ""`, and `spec.status: "draft"` if absent.
6. Write back.

Auto-trigger on the first `/api/investigation` open of an unmigrated spec.

### `spec.yaml` validator extension

`load_spec` accepts the new shape:

```python
if spec.get('variants') is not None:
    # New shape — validate variants list, each has name + (source OR extends)
    ...
elif spec.get('composites'):
    # Legacy shape — accept; migration runs on viewer open
    ...
```

Both shapes coexist during the migration window (typically one session per workspace).

## Data flow

**Preview a composite, then optionally start a study:**

1. User clicks **Explore** on a composite row in Simulation Setup.
2. Navigate to `/composite-explorer?composite=<name>`. No API call yet; nothing is created on disk.
3. Composite Explorer loads with that composite pre-selected: shows wiring in loom + a brief metadata pane (source module, processes, default state shape).
4. If the user wants to proceed, they click **Begin Study** in the Explorer.
5. JS → `POST /api/investigation-create-from-composite`. Server creates `investigations/<auto-name>/spec.yaml` with the v2 shape: `baseline: <composite-name>`, `variants: [{name, source, document}]`.
6. Navigate to the Composite Study workbench.

This preserves a "look without committing" path. Sim Setup → Explorer is free; only the **Begin Study** click creates persistent state.

**Add a variant (intervention):**

1. User opens the Composites tab → clicks Perturb on a variant.
2. Existing Perturb modal: name + JSON parameter_overrides + JSON process_overrides + description (NEW field).
3. JS → `POST /api/investigation-composite-perturb` (existing endpoint). Server creates the sidecar AND nests the recipe under `intervention:` in the new spec.yaml entry.

**Add a comparison:**

1. User opens the Visualizations tab → clicks "+ Add comparison".
2. Modal: name, multi-select variants, multi-select observables.
3. JS → `POST /api/investigation-comparison-add`.
4. Server appends to `spec.yaml.comparisons`.

**Render a comparison-aware visualization:**

1. User opens the Visualizations tab → clicks "+ Add visualization".
2. Modal includes a Comparison dropdown.
3. Selecting a comparison auto-fills `config.sources` (variants list) + `config.observable` (first observable). User can tweak.
4. Existing add-viz endpoint writes the entry.

**Edit Conclusions:**

1. User opens the Conclusions tab → edits the markdown.
2. Save → `POST /api/investigation-set-conclusions`.
3. Server writes `spec.yaml.conclusions`.

## Error handling

- **Comparison references unknown variant or observable:** 400 + the offending name. UI shows inline.
- **Delete a comparison with viz dependents:** 409 + list of viz names that reference it.
- **Conclusions over a reasonable size (e.g., > 256 KB):** 400. Markdown writeups shouldn't be that large; the limit protects against accidental paste-bombs.
- **Migrating a legacy spec fails mid-write:** atomic-rename pattern (write to `.spec.yaml.tmp`, rename) so the file either fully migrates or stays original.

## Testing

**Migration:**
- `test_migrate_study_to_v2_renames_composites_to_variants`
- `test_migrate_study_to_v2_nests_overrides_into_intervention`
- `test_migrate_study_to_v2_sets_baseline_from_first_source_variant`
- `test_migrate_study_to_v2_initializes_comparisons_and_conclusions_blank`
- `test_migrate_study_to_v2_idempotent`

**Spec validator:**
- `test_load_spec_accepts_variants_shape`
- `test_load_spec_still_accepts_legacy_composites_shape`
- `test_load_spec_validates_baseline_references_a_variant`

**Comparison endpoints:**
- `test_post_comparison_add_appends_to_spec`
- `test_post_comparison_update_replaces_entry`
- `test_delete_comparison_refuses_with_viz_dependents`
- `test_delete_comparison_succeeds_when_unreferenced`

**Conclusions:**
- `test_post_set_conclusions_writes_markdown`
- `test_post_set_conclusions_size_limit`

**Frontend:**
- UI verification in Phase E (v2ecoli E2E). No automated frontend tests.

## Backwards compatibility

- **Existing investigation spec.yaml files load via the legacy branch in `load_spec`.** Migration runs on first viewer open.
- **The `composites:` field on runs entries stays.** It's a reference to a variant by name; renaming would touch every endpoint that resolves it. Keep the field name; just rename the LIST that holds the variants.
- **Existing visualizations with `config.sources: [...]` continue to work.** The new `config.comparison: <name>` field is optional and additive.
- **No data loss** at any migration step. Legacy fields not explicitly translated are preserved verbatim.

## Implementation rollout

**Phase A — Data model + endpoints:**

- Migration helper.
- Validator extension.
- New endpoints (set-conclusions, comparison-add/update/delete).
- The unified-CE plan's create-from-composite + promote-to-catalog endpoints (still needed; carry over).
- Removal of the 7 inline-edit endpoints (still needed; carry over).

**Phase B — 6-tab Composite Study workbench:**

- Restructure (was Phase B in unified plan).
- Add Overview tab.
- Repurpose Composites tab to show variants + show intervention summary when a variant is selected.
- Add Interventions tab.
- Visualizations tab gains the Comparisons sub-panel.
- Add Conclusions tab.

**Phase C — Promote action:**

- Carry-over from unified plan.

**Phase D — Sim Setup + Composite Explorer:**

- Carry-over from unified plan.

**Phase E — Investigations index + v2ecoli E2E:**

- Investigations list with summary stats.
- v2ecoli verification: migration of `t1`, exercise each of the 6 tabs, create/edit a comparison + a conclusions blob, promote a variant.

## Out of scope (follow-ups)

- **Workspace-level intervention library.** Useful future feature; defer.
- **Statistical tests in Comparisons.** Comparison-as-object stays minimal.
- **Cross-linking conclusions to runs/comparisons** ([@run-42] auto-rendering style). Defer.
- **Multi-baseline studies.** One baseline per study is a deliberate simplification.
- **Diffing two variants visually** ("show me what changed between baseline and high-rate"). Could be a future enhancement to loom-explore.
- **Cloning a study as a template** ("use this study as the starting point for a new one"). Defer.
- **Auto-summary of conclusions** from runs.db metrics. Big future feature; out of scope.
