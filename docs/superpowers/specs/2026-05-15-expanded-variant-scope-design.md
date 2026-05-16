# Expanded Variant scope — patch-style composite overlays

**Date:** 2026-05-15
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Sibling spec:** `2026-05-15-studies-with-tests-and-investigations-design.md` (ships independently — that work doesn't depend on this).
**Supersedes (in scope):**
- The `parameter_overrides:` field on Variants in v3 Study spec.
- The Phase-1 `process_overrides:` design sketch in `2026-05-12-multi-composite-investigations-design.md` (subsumed by the broader overlay model).

## Vocabulary

| Term | Definition |
|---|---|
| **Variant** | A derived composite produced by applying an *overlay* on top of a baseline composite. Lives as an entry under `study.yaml.variants[]`. |
| **Document overlay** | A partial process-bigraph document (mostly under the `state:` key) that the rebuilder deep-merges onto the baseline document. Carries any combination of edits: parameter values, initial-state values, process configs, pathway nested configs, new processes, swapped process addresses, removals. |
| **Deep merge** | Recursive dict-on-dict merge. Leaves (scalars, lists) are replaced wholesale. `null` at any path means *delete this node from the baseline*. |
| **Rebuild** | The orchestrator pass that walks `baseline → variant`, applies the overlay (and the parent's overlay if `extends:` chains), and produces a runnable `Composite` document. |

## Problem

The current v3 Study Variant model supports only one kind of edit: `parameter_overrides:` (a dict of dotted paths → scalar values). This is too narrow for real research workflows. To compare a baseline cell against a perturbed-mechanism variant, users today must:

- Author an entire new architecture (a separate composite generator) — as PR #28 did with `replication_initiation` for the DnaA cycle work.
- Or fork the Study entirely.

Both are heavier than the variant abstraction was meant to be. A Variant should be the right tool for *any* in-study composite derivation: changing parameters, changing initial state, swapping a process implementation, adding a process, removing a process, editing a process's pathway config.

The `2026-05-12-multi-composite-investigations-design.md` already sketched a Phase-1 expansion adding `process_overrides:` (swap / remove). That sketch is correct in direction but limited; this spec subsumes it with a uniform patch model.

## Goals

- **One overlay field handles every kind of edit.** `document_overlay:` is a partial process-bigraph document. Anything expressible in a composite document is expressible as an overlay.
- **Predictable merge semantics.** Recursive dict-merge for dicts; wholesale replacement for leaves (scalars, lists). `null` at a path = delete. Follows the JSON Merge Patch convention (RFC 7396).
- **Adding processes.** A new process appears in the overlay as a normal node (`_type: process`, `address`, `config`, `inputs`, `outputs`) at a path that doesn't exist in the baseline. The merge inserts it.
- **Replacing processes (swap).** The overlay sets the process's `address` (and optionally `config`/`inputs`/`outputs`) at the existing path. Merge keeps unspecified fields from the baseline.
- **Removing processes.** Overlay sets the path to `null`. Merge deletes the node.
- **Initial-state edits.** Overlay writes the value at the store path (e.g., `state.chromosome.DnaA_count: 200`). Merge replaces the default with the new value.
- **Pathway / nested-config edits.** Same mechanism — the overlay reaches down via the nested dict, no special syntax.
- **Hard cutover for `parameter_overrides`.** Schema bump v4→v5. Migration helper unflattens existing `parameter_overrides: {a.b.c: value}` into `document_overlay: {state: {a: {b: {c: value}}}}`. After migration the old field is removed from disk.
- **Process-bigraph rebuild remains the source of truth.** The merged document goes through `Composite(...)` construction; bigraph-schema validates port wiring + types. The variant overlay is just a recipe; validation enforcement is downstream.

## Non-goals

- **Cross-variant inheritance beyond `extends:` parent.** Variants extend one parent (which can be a variant or the baseline). DAG-style multi-parent extension is deferred.
- **Cross-store merge across composite documents.** Overlay merges within one composite, not across composites.
- **Adding new process schema-types.** The overlay can use any existing schema type; it cannot define a new bigraph-schema type.
- **Operation-tagged list edits.** Lists are replaced wholesale. No `{op: add, value: x}` mini-DSL inside lists.
- **Validating port wiring at variant-edit time.** Validation happens at rebuild (when `Composite(...)` is constructed). Overlay author writes any wiring; rebuild flags invalid references.
- **Dashboard tree editor for overlays.** v5 ships with a YAML-textarea editor + validation; tree-editor UI is a follow-up.

## Architecture

### `study.yaml` variant entry shape (v5)

```yaml
schema_version: 5
# ... existing v4 fields (objective, baseline, runs, visualizations, tests, references, implementation_tasks, conclusion)

variants:
  - name: simple-rate-tweak
    base_composite: baseline              # references a study.baseline[].name
    document_overlay:
      state:
        replication:
          config:
            rate: 2.0
            pathways:
              dnaA_box_binding:
                enabled: true

  - name: titration-mechanism
    base_composite: baseline
    document_overlay:
      state:
        mass_initiation: null              # remove the heuristic process
        dnaA_box_binding:                  # add a new process
          _type: process
          address: 'local:DnaABoxBinding'
          config: {n_boxes: 307}
          inputs:  {boxes: [chromosome, dnaA_boxes]}
          outputs: {boxes: [chromosome, dnaA_boxes]}
        chromosome:
          DnaA_count: 200                  # initial-state edit

  - name: combo                            # extends another variant
    base_composite: baseline
    extends: titration-mechanism           # apply this variant on top of titration-mechanism
    document_overlay:
      state:
        replication:
          address: 'local:DnaAReplisome'   # swap process address (config/wiring kept from parent)
```

Notes:

- `base_composite` references a `study.baseline[].name`. Required.
- `extends:` (optional) — names another variant to use as the parent. If absent, the parent is the baseline.
- `document_overlay:` is a partial composite document. It MUST be a mapping (or absent). Top-level keys should be `state:` (the common case); other top-level keys like `core:` are passed through for future use.

### Merge algorithm

`merge_overlay(baseline_doc: dict, overlay: dict) -> dict`:

```
merge(b, o):
  if o is None:
    return DELETED                          # signal removal at this path
  if not isinstance(o, dict) or not isinstance(b, dict):
    return o                                # replace wholesale (scalars, lists)
  out = dict(b)
  for k, v in o.items():
    sub = merge(b.get(k), v)
    if sub is DELETED:
      out.pop(k, None)
    else:
      out[k] = sub
  return out
```

Properties:
- **Dict + dict** → recurse.
- **Scalar in overlay** → replace whatever's in baseline (even if baseline is a dict).
- **List in overlay** → replace baseline's list wholesale (no append, no smart-merge).
- **`null` in overlay** → remove the key from the merged result.
- **Path doesn't exist in baseline** → overlay subtree inserted as-is.

This is JSON Merge Patch (RFC 7396) semantics. Predictable and well-specified.

### Validation pass

After merge, the rebuilt document is passed to `Composite(state=merged, core=core)`. process-bigraph + bigraph-schema validate:
- Every node with `_type: process` has a resolvable `address`.
- Every port in `inputs`/`outputs` references a valid store path.
- Type compatibility at port boundaries.

If validation fails, the rebuild raises `CompositeRebuildError` with the merged document path and the underlying error. The dashboard surfaces this inline in the Variant editor.

The variant overlay itself is NOT validated against a schema beyond shape (must be a mapping; `state:` if present must be a mapping). Wiring correctness lives downstream at rebuild.

### Migration: v4 → v5

`migrate_v4_to_v5(spec: dict) -> dict`:

For each entry in `spec.variants`:
1. If `parameter_overrides:` exists, unflatten it: for each `"a.b.c": value` pair, build a nested dict `{a: {b: {c: value}}}` under `document_overlay.state`.
2. If `process_overrides:` exists (from the unrealized Phase-1 design), translate:
   - String value `'local:NewAddress'` → `document_overlay.state.<name>.address = 'local:NewAddress'`.
   - Dict value `{address, config}` → merge into `document_overlay.state.<name>`.
   - `null` value (removal) → `document_overlay.state.<name>: null`.
3. Remove `parameter_overrides:` and `process_overrides:` from the variant entry.
4. Set `schema_version: 5` at the top level.

Idempotent: re-running on a v5 spec is a no-op. v4 specs without any `parameter_overrides` get an empty `document_overlay: {}` or no overlay at all.

Migration runs in-memory inside `load_spec` (chained after v3→v4). On the next save of a study, the migrated form is written to disk.

### Rebuild

The orchestrator's existing `rebuild_variant(workspace, study_slug, variant_name)` is extended:

```
def rebuild_variant(workspace, study_slug, variant_name):
    spec = load_spec(workspace / "studies" / study_slug / "study.yaml")
    variant = find_variant(spec, variant_name)

    # Resolve baseline document
    baseline_entry = find_baseline(spec, variant.base_composite)
    base_doc = build_composite_document(baseline_entry.composite, baseline_entry.params)

    # Apply parent-variant overlay if extends:
    if variant.get("extends"):
        parent = find_variant(spec, variant["extends"])
        parent_doc = rebuild_variant(workspace, study_slug, parent["name"])  # recursive
        merged = parent_doc
    else:
        merged = base_doc

    # Apply this variant's overlay
    if variant.get("document_overlay"):
        merged = merge_overlay(merged, variant["document_overlay"])

    return merged
```

Recursion is bounded by `extends:` depth; the validator rejects cycles (a variant cannot transitively extend itself).

### Dashboard UX changes

**Variant editor in Study detail (Variants tab):**

- Replace the existing "Parameter overrides" form (key-value entry per row) with a YAML textarea labelled "Document overlay" pre-filled with the variant's current overlay. Edits are submitted via `POST /api/study-variant-set-overlay`.
- Right-side panel: live preview of the merged document for the variant (read-only YAML render), refreshed on save.
- Validation errors from rebuild surface as an inline banner above the textarea.

**The Variants list still shows:**
- Variant name.
- Parent (`extends:` or baseline).
- A 1-line "what does it change?" summary derived from the overlay (e.g., "2 process swaps, 1 add, 3 state edits").

### Endpoint surface

| Method + path | Body | Purpose |
|---|---|---|
| `POST /api/study-variant-set-overlay` | `{study, variant, overlay}` | Replaces the variant's `document_overlay`. Triggers re-validation by attempting a rebuild; returns 400 with error if invalid. |
| `POST /api/study-variant-rebuild` | `{study, variant}` | Rebuild and return the merged document (preview). Does not run the variant. |
| Existing `POST /api/study-variant-add` | `{study, name, base_composite, document_overlay?, extends?}` | Add a variant. The `parameter_overrides` body key is accepted for backward-compat but converted to `document_overlay` immediately. |
| Existing `POST /api/study-variant-set-params` | DEPRECATED. Returns 410 Gone with a pointer to set-overlay. |

## Data flow

### Author a variant via the dashboard

1. User clicks **+ Add variant** in the Study Variants tab. Modal: name, parent (baseline or another variant), YAML textarea for overlay.
2. JS → `POST /api/study-variant-add {study, name, base_composite, document_overlay}`.
3. Server validates the overlay shape, attempts a rebuild, returns 400 on failure (with the rebuild error) or 201 on success.

### Edit a variant's overlay

1. User opens the Variants tab → clicks a variant → edits the overlay YAML in the textarea → clicks Save.
2. JS → `POST /api/study-variant-set-overlay`.
3. Server rebuilds; on success, persists the new overlay and returns the merged document for the preview panel.

### Run a variant

Unchanged from current v3 flow — `POST /api/study-run-variant` resolves the variant's merged document via `rebuild_variant`, injects the SQLiteEmitter, and runs.

### Migrate a v4 study on first open

1. Dashboard receives a request for a v4 study spec.
2. `load_spec` runs the v4→v5 migration in-memory.
3. The dashboard renders Variants with `document_overlay` fields.
4. On any save (e.g., editing the overlay), the v5 form is persisted; the old `parameter_overrides:` is gone from disk.

## Error handling

- **Overlay isn't a mapping.** Validation rejects with `OverlayShapeError("document_overlay must be a mapping, got <type>")`.
- **Overlay path conflicts with non-dict node in baseline** (e.g., overlay sets `state.chromosome.x.y = 1` but baseline has `state.chromosome.x = 5`). Merge replaces the scalar with the overlay dict (per the algorithm). Rebuild then fails downstream if the resulting shape is invalid; the failure surfaces with the offending path.
- **`extends` cycle.** Validator rejects with `VariantCycleError("variant 'a' extends 'b' extends 'a'")`.
- **`extends` references missing variant.** `OverlayResolveError("variant 'a' extends 'missing'; no such variant")`.
- **Rebuild fails bigraph-schema validation.** `CompositeRebuildError` with the merged document path and the underlying error. Dashboard surfaces in-line.
- **Migration encounters an unknown legacy field.** Preserved verbatim under `_legacy:` for safety; logged as a warning. Doesn't block migration.

## Testing

**Merge algorithm (pure unit tests, no I/O):**
- `test_merge_empty_overlay_returns_baseline`
- `test_merge_replaces_scalar`
- `test_merge_recurses_into_dict`
- `test_merge_replaces_list_wholesale`
- `test_merge_null_removes_node`
- `test_merge_inserts_new_subtree`
- `test_merge_scalar_overlay_replaces_dict_baseline`
- `test_merge_dict_overlay_replaces_scalar_baseline`

**Migration (v4 → v5):**
- `test_migrate_v4_to_v5_unflattens_parameter_overrides`
- `test_migrate_v4_to_v5_translates_process_overrides_swap_string`
- `test_migrate_v4_to_v5_translates_process_overrides_swap_dict`
- `test_migrate_v4_to_v5_translates_process_overrides_remove_null`
- `test_migrate_v4_to_v5_strips_legacy_fields`
- `test_migrate_v4_to_v5_idempotent`
- `test_migrate_v4_to_v5_preserves_unrelated_fields`

**Rebuild:**
- `test_rebuild_variant_no_overlay_equals_baseline`
- `test_rebuild_variant_applies_overlay_param`
- `test_rebuild_variant_applies_overlay_state_initial_value`
- `test_rebuild_variant_swaps_process_address`
- `test_rebuild_variant_adds_new_process`
- `test_rebuild_variant_removes_process_via_null`
- `test_rebuild_variant_chains_extends`
- `test_rebuild_variant_rejects_extends_cycle`
- `test_rebuild_variant_surfaces_bigraph_schema_validation_error`

**Endpoints:**
- `test_post_variant_set_overlay_persists`
- `test_post_variant_set_overlay_returns_400_on_invalid_rebuild`
- `test_post_variant_rebuild_returns_merged_document`
- `test_post_variant_add_accepts_legacy_parameter_overrides_body`
- `test_post_variant_set_params_returns_410_gone`

**End-to-end:**
- `test_e2e_create_variant_with_process_swap_runs_correctly` — author a variant that swaps mass_initiation → DnaA-titration, run it, verify the trajectory differs from baseline.

## Backwards compatibility

- **v4 → v5 migration is automatic** in `load_spec`. Disk file rewrites on next save (consistent with v3→v4 pattern).
- **Existing `POST /api/study-variant-add` body with `parameter_overrides:` keeps working** — the server unflattens to `document_overlay:` before storing.
- **`POST /api/study-variant-set-params` returns 410 Gone** with a deprecation pointer. Skills + UI are updated to use `set-overlay` instead.
- **The `parameter_overrides:` key may persist on-disk in unmigrated workspaces.** Idempotent migration handles this — re-opens just produce v5 in memory and on next save.

## Implementation rollout

**Phase 1 — Merge + migration (pbg-template / vivarium-dashboard core):**
- `vivarium_dashboard/lib/overlay_merge.py` with `merge_overlay` + the DELETED sentinel.
- `vivarium_dashboard/lib/spec_migration.py` adds `migrate_v4_to_v5`.
- Chain into `load_spec` after `migrate_v3_to_v4`.

**Phase 2 — Rebuild integration:**
- `vivarium_dashboard/lib/composite_recipes.py` (or wherever variant rebuilds live) gains `rebuild_variant(workspace, study, variant_name)` that walks the `extends:` chain and applies overlays.
- Cycle detection.
- Wire into the existing variant-run path.

**Phase 3 — Endpoints:**
- `POST /api/study-variant-set-overlay`.
- `POST /api/study-variant-rebuild`.
- Update `POST /api/study-variant-add` to accept either body shape.
- Deprecate `POST /api/study-variant-set-params` (410 Gone with pointer).

**Phase 4 — Dashboard UX:**
- Variant editor textarea (YAML).
- Merged-document preview panel.
- "Changes summary" badge derivation from overlay.

**Phase 5 — Verify on v2ecoli:**
- Create a Study that uses `extends:`-chained variants to compare the baseline mass-threshold model with the DnaA-ATP titration mechanism — proving the use case PR #28 had to work around with a separate architecture.

## Sequencing with the Tests + Investigations spec

This spec is **independent** of `2026-05-15-studies-with-tests-and-investigations-design.md`. They can land in either order. Concretely:

- Tests + Investigations operates on **run outputs**: the trajectory in `runs.db`, regardless of how the variant got there.
- Variant overlay operates on **the recipe before running**.

There is no shared file, schema, or endpoint between the two. Both bump schema versions (v3→v4 for Tests; v4→v5 for variants), and the migrations chain trivially because each only touches its own fields.

The current recommended order is:
1. Land Tests + Investigations (Plan in flight).
2. Then this spec's plan.
3. Then v2ecoli content (PDF extraction + 8 studies + investigation.yaml + first overlay-using variant).

## Out of scope (follow-ups)

- **Tree-editor UI for overlays.** v5 ships with a YAML textarea + validation. Tree editor is a future enhancement.
- **Operation-tagged list edits** (`{op: add/remove, value: x}` inside lists). Not needed yet.
- **Cross-composite overlays** (a variant overlaying parts of a sibling composite). Variants stay scoped to one baseline.
- **Schema-validated overlays.** No `overlay.schema.json`. Validation is downstream at rebuild via process-bigraph.
- **Multi-parent variant inheritance** (DAG over variants). Single-parent only.
- **Diffing two variants visually** (loom-explore could highlight overlay changes). Future enhancement.
