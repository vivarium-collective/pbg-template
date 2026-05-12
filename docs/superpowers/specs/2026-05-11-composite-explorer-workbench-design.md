# Composite Explorer Workbench — Design

**Date:** 2026-05-11
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)

## Problem

The Composite Explorer page in the pbg-template dashboard currently supports a single one-shot interaction loop: pick a composite spec, edit parameters, click Test run, see the emitter results. That's a starting point, not a workbench. Day-to-day research on a composite spec actually looks like:

1. Run a short simulation.
2. Inspect the resulting state (not just emitted scalars — the full state tree).
3. Capture a state from time T and use it as the new initial state for a follow-up run.
4. Tweak parameters.
5. Re-run.
6. Compare the new trajectory against earlier ones to see whether the parameter change moved the system the way you expected.

The current page can't do steps 2–6. Each Test run replaces the previous results; there's no history, no compare view, no way to drill into the full state tree at an arbitrary step, no way to promote a captured state into the next run's initial conditions.

This spec turns the existing Composite Explorer page into that workbench, in-place, behind a small in-page tab strip — without restructuring the dashboard's navigation.

## Goals

- **Persist runs.** Every Test run survives the server restart and shows up in a History tab.
- **Compare runs.** Multi-select runs from History, overlay their trajectories in one chart per observable, highlight parameter differences.
- **Explore state.** For any selected run, scrub a step slider and see the full state tree at that step.
- **Snapshot to initial.** Capture a state at step T and pre-fill the Parameters editor with matching leaf values.
- **Pop out.** Open the explorer in its own window, free of the dashboard chrome.
- **Skill access.** Launch the explorer from the terminal via `/pbg-explore <spec-id>`.

## Non-goals (MVP)

- Headless comparison/scripting via CLI (the skill is a UI launcher only).
- Cross-spec comparison (Compare tab is scoped to one spec_id at a time).
- DB cleanup tooling — users can `rm .pbg/composite-runs.db`.
- Run labeling UX beyond an auto-derived label (param diff vs default). Custom names are a follow-up.
- "Save state as new composite YAML" — Snapshot lives entirely in memory for the iterate-fast loop.

## Architecture

The Composite Explorer remains a single page in the dashboard (`#composite-explore`) but grows an **in-page tab strip** with four tabs:

- **Wiring** — current page contents, unchanged: name/description block, bigraph-viz diagram + Update button, Parameters editor, Resolved state JSON, Test run, Create simulation.
- **History** — table of past runs from `.pbg/composite-runs.db`, filtered by this spec_id. Per-row View button and Compare checkbox.
- **Compare** — visible only when ≥2 History rows are checked. One Plotly chart per observable, all selected runs overlaid (one color per run). Parameter × run table beneath the chart, cells highlighted where values differ from the row median.
- **State** — given a selected run + step slider (0 to N-1), shows a collapsible JSON tree of the full `composite.state` at that step. Two buttons: "Use as initial" (snapshot the leaf values into Wiring tab's Parameters editor) and "Open in new window" (per-run pop-out).

**Pop-out** lives in the page header, independent of tabs: a button that opens `?focus=composite-explore&id=<id>` in a new window. The skill `/pbg-explore` invokes this URL after ensuring the server is up.

Why one page with tabs (not separate pages): the four tabs share state — spec_id, parameter overrides, selected runs set. Cross-tab interactions (View → State, Use as initial → Wiring) are direct DOM swaps, not navigation. The dashboard's existing sidebar stays the navigation surface.

## Components

### Backend

**`scripts/_lib/composite_runs.py` (new module).** SQLite connection management + schema bootstrap + query helpers.

- `connect(ws_root) -> sqlite3.Connection` — opens `.pbg/composite-runs.db`, bootstraps schema on first connect.
- `save_metadata(conn, spec_id, run_id, params, label, started_at)` — INSERT a row into `runs_meta`.
- `complete_metadata(conn, run_id, n_steps, status)` — UPDATE the existing row with `completed_at`, `n_steps`, `status`.
- `query_runs(conn, spec_id) -> list[dict]` — newest-first list of runs for a spec.
- `query_run(conn, run_id) -> list[dict]` — trajectory `[{step, time, state}, ...]` from the SQLiteEmitter `history` table.
- `query_run_state(conn, run_id, step) -> dict | None` — single state dict at one step.
- `inject_sqlite_emitter(state: dict, run_id: str, db_file: str) -> dict` — returns a new state dict with a `SQLiteEmitter` step wired to the same input ports the spec's existing emitter consumes. Idempotent — if a SQLite emitter is already wired with this run_id, no-op.

**`scripts/_server/server.py` (modified):**

- `_post_composite_test_run`: before building the Composite, generate `simulation_id = <spec_id>__<timestamp>__<6char-hash>`, call `inject_sqlite_emitter()` on the resolved state, call `save_metadata()` once, run the sim, then `complete_metadata()`. Add `simulation_id` to the response dict.
- New endpoints:
  - GET `/api/composite-runs?spec_id=X` → `_get_composite_runs`
  - GET `/api/composite-run/<run_id>` → `_get_composite_run`
  - GET `/api/composite-run/<run_id>/state?step=N` → `_get_composite_run_state`

### Frontend (`scripts/_server/walkthrough.js`)

- `_ceSwitchTab(tab)` — toggles `.ce-tab-panel.active` class.
- `_ceLoadHistory()`, `_ceRenderHistoryRow(run)` — fetch + render History.
- `_ceToggleCompareSelection(run_id, checked)` — manages `window._ceCompareSet: Set<string>`; shows/hides Compare tab + badge.
- `_ceRenderCompare()` — `Promise.all` fetches of selected runs, builds Plotly overlay traces (one color per run from a fixed palette), diff table where cells differing from row median highlight.
- `_ceLoadState(run_id, step)`, `_ceRenderStateTree(obj, container)` — collapsible JSON tree. Port the tree renderer from `pbg-caspule/demo/demo_report.py`.
- `_ceSnapshotToInitial(stateObj)` — walks the tree, matches leaves to Parameters editor inputs by parameter name, populates values, switches to Wiring tab. Reports matched/skipped counts.
- `_ceOpenPopout()` — `window.open(<focus-url>, '_blank', 'width=1200,height=900')`, falls back to same-tab if blocked.

### HTML (`scripts/_templates/index.html.j2`)

- Tab strip + four `.ce-tab-panel` divs wrapping the existing explorer markup.
- "Pop out" button next to the "Composite explorer" title.
- The current contents of `<section id="page-composite-explore">` become the "Wiring" tab panel.

### CSS (`scripts/_templates/_assets/style.css`)

- `.ce-tab-strip`, `.ce-tab`, `.ce-tab.active`, `.ce-tab-panel`, `.ce-tab-panel.active`.
- `.ce-state-tree` (collapsible nodes, indentation, monospace, light syntax colors keyed to value type).
- `.ce-diff-cell.highlight` (background color for differing param values).
- `.ce-compare-legend` (color-coded run swatches).

### Skill (`pbg-superpowers/skills/pbg-explore/SKILL.md` — new)

Thin bash skill. Argument: `<spec-id>`.

1. Locate workspace root by walking up from `pwd` for `workspace.yaml`.
2. Check `.pbg/server/server-info` exists and `curl -s <url>/api/composites` returns 200.
3. If not, run `bash scripts/serve.sh` in the background; poll for `server-info` for up to 30 seconds.
4. Read URL from `server-info`.
5. `open '<url>?focus=composite-explore&id=<spec-id>'` (macOS) or platform equivalent.

Reports a clear error if step 3 times out.

## Data flow

### Flow 1 — Test run + persistence

User clicks Test run in Wiring tab → POST `/api/composite-test-run` with `{id, overrides, steps, label?}` → server resolves the spec, calls `inject_sqlite_emitter(state, simulation_id, db_file='.pbg/composite-runs.db')`, calls `save_metadata(...)`, runs N steps, then `complete_metadata(...)`. Returns `{simulation_id, results, steps}`. Frontend appends a new row to History (no full refetch) and surfaces a "Run saved as <simulation_id>" toast.

### Flow 2 — Browsing history

User switches to History tab → GET `/api/composite-runs?spec_id=X` → server returns the list, newest first → table renders with View button + compare checkbox per row.

### Flow 3 — Compare selection

User checks ≥2 rows → frontend keeps `window._ceCompareSet`, shows Compare tab + badge with count → on tab switch, parallel GET `/api/composite-run/<run_id>` calls → frontend builds Plotly traces (one color per run, one chart per observable found in any trajectory) and a parameter × run table where each cell highlights if its value differs from row median.

### Flow 4 — State exploration

User clicks View on a history row → frontend switches to State tab, sets selected_run_id, defaults step to 0 → GET `/api/composite-run/<run_id>` (cached if recently fetched for Compare) → render collapsible JSON tree at step 0 + step slider 0..N-1. Moving the slider re-renders from cached trajectory. If trajectory isn't cached, GET `/api/composite-run/<run_id>/state?step=N`.

### Flow 5 — Snapshot to initial

User clicks "Use as initial" → frontend walks the state tree → for each leaf, tries to match a Parameters editor input by parameter name (parameter declarations include the wire target in the spec) → matching inputs get `value` set → switch to Wiring tab. Unmatched/mismatched leaves logged to a "Mapped X of Y leaves" footer with expandable skipped list.

### Flow 6 — Pop-out

User clicks Pop out → `window.open(location.pathname + '?focus=composite-explore&id=' + spec_id, '_blank', 'width=1200,height=900')` → new window loads the dashboard URL but enters focus mode (existing `_initMenuNav` path), hiding everything except the explorer. All API endpoints work identically.

### Flow 7 — Skill `/pbg-explore <spec-id>`

Bash skill: check server-info + curl probe; if absent, run `bash scripts/serve.sh` in background, poll for server-info up to 30s; then `open '<url>?focus=composite-explore&id=<spec-id>'`. No backend changes.

## Data model

### SQLite schema (`.pbg/composite-runs.db`)

```sql
-- Bootstrapped by composite_runs.connect() on first connect.
CREATE TABLE IF NOT EXISTS runs_meta (
  run_id TEXT PRIMARY KEY,
  spec_id TEXT NOT NULL,
  label TEXT,
  params_json TEXT,            -- JSON-encoded overrides applied to this run
  started_at REAL NOT NULL,    -- unix epoch seconds
  completed_at REAL,           -- NULL while running
  n_steps INTEGER,             -- final count (may be 0 if failed early)
  status TEXT NOT NULL         -- 'running' | 'completed' | 'failed'
);
CREATE INDEX IF NOT EXISTS idx_runs_meta_spec ON runs_meta(spec_id);

-- 'history' table is created by process_bigraph.emitter.SQLiteEmitter
-- (one row per recorded step; partition column is simulation_id which
-- equals our run_id). Schema owned by process-bigraph.
```

### `simulation_id` (== `run_id`) format

`<spec_id>__<unix-epoch-int>__<6-hex-chars>`

Example: `pbg_caspule.composites.bond-network-demo__1715470512__a3f9c2`

Spec_id-prefix makes SQL filtering trivial; timestamp gives natural sort order; short hash disambiguates rapid-fire runs in the same second.

## Error handling

**Run failures.** Composite raises mid-run → SQLiteEmitter has already written partial history rows. `_post_composite_test_run` catches the exception, calls `complete_metadata(status='failed', n_steps=<truncated>)`, returns `{simulation_id, error, traceback, partial_results}`. Frontend renders the run in History with a red status pill + collapsible error panel. Failed runs are still selectable for Compare and State.

**DB lifecycle.** First request creates the DB and bootstraps schema. SQLite single-process locking is sufficient (one dashboard server process; concurrent test-runs serialize at the SQLite layer). No automatic cleanup — document the file path so users can `rm .pbg/composite-runs.db`.

**Missing run / spec.** `/api/composite-run/<run_id>` returns 404 if the metadata row is absent. Frontend shows "Run not found — it may have been deleted from the database." Skill checks server-info before opening the URL; if spec_id doesn't exist on the server, the URL load shows the existing "No composite id specified" empty state.

**Snapshot mapping mismatches.** "Use as initial" gives each leaf one of three outcomes:

- **Matched** — input value set, leaf marked green
- **Type mismatch** (state value is `list`, parameter is `float`) — skipped, marked yellow
- **No matching parameter** — skipped, marked gray

Post-snapshot UI shows a "Mapped X of Y leaves" footer with a "Show skipped" expandable list. User keeps full control to manually edit any unmapped input.

**Compare across mismatched specs.** History tab is filtered to one spec_id, so this is hard to reach. If reached via crafted URL, chart shows the union of observables, traces labeled with the run's spec_id. No hard error.

**Pop-out blocked.** If `window.open` returns `null`, fall back to `window.location.search = '?focus=composite-explore&id=' + spec_id` on the current tab.

**Large state trees.** JSON tree caps rendered depth at 5 levels; deeper subtrees show `…` with an Expand affordance. No virtualization.

**Skill timeout.** `/pbg-explore` polls for `server-info` for up to 30 seconds after launching `serve.sh`. If it doesn't appear, the skill prints the serve.sh output and exits non-zero so the user sees the actual server startup error.

## Testing

### Unit tests (`pbg-template/tests/test_composite_runs.py`, new)

- `test_schema_bootstrap` — connecting to a fresh DB creates both `history` and `runs_meta` tables.
- `test_insert_metadata` — `save_metadata(...)` writes a row that `query_runs(spec_id)` returns.
- `test_complete_metadata` — `complete_metadata(...)` updates the existing row's `completed_at`, `n_steps`, `status`.
- `test_inject_sqlite_emitter` — helper takes a state dict + run_id, returns a new state dict with `SQLiteEmitter` step wired to all stores declared by the spec's existing emitters; second call with the same run_id is a no-op.

### Integration test (`tests/test_composite_explorer_api.py`, new)

Spins up the server against a fixture workspace containing the `increase-demo` composite from `pbg-superpowers/tests/fixtures/`. Lifecycle:

1. POST `/api/composite-test-run` `{id, overrides, steps: 5}` → assert 200, response has `simulation_id`, `results`, `steps == 5`.
2. Verify `.pbg/composite-runs.db` exists and has a `runs_meta` row with `status == 'completed'`.
3. GET `/api/composite-runs?spec_id=<id>` → assert list contains the run.
4. GET `/api/composite-run/<run_id>` → assert trajectory length 5.
5. GET `/api/composite-run/<run_id>/state?step=2` → assert state dict.
6. Second run with different overrides → distinct `simulation_id`, both listed.
7. Force a failure (invalid override) → row has `status == 'failed'`.

### Manual verification checklist

- Test run from Wiring → row appears in History within 1s.
- Multi-select 2+ runs → Compare tab appears, charts overlay correctly.
- Compare param-diff table highlights cells differing from row median.
- Click View on a History row → State tab opens with selected run, slider at 0.
- Move slider → tree re-renders without network call.
- "Use as initial" with matching parameter → input updates, tab switches to Wiring; mismatch → yellow/gray in skipped footer.
- Pop-out button → new window opens in focus mode.
- `/pbg-explore <spec-id>` → server starts, browser opens.
- Pop-out blocked → falls back to same-tab navigation.
- Server restart preserves all History rows.

### Backwards compatibility

- `/api/composite-test-run` callers continue working — `simulation_id` is an *added* response field; existing fields are preserved.
- Workspaces without `.pbg/composite-runs.db`: first call to the explorer bootstraps the DB transparently.

### Frontend smoke (live verification, no automated runner)

- Explorer page loads on a clean workspace with empty History.
- Compare tab hidden until ≥2 rows selected.
- State tab's "no run selected" empty state is sensible.

## Out of scope (follow-ups)

- Custom run labels (user-typed names).
- Run pinning / starring.
- Cross-spec comparison.
- Headless `/pbg-explore --run` to kick off a sim without opening a browser.
- "Save state as new composite YAML" — generates a new spec file with the captured state substituted as defaults.
- DB cleanup CLI (`/pbg-explore --clear`).
- Visualization Step output rendering inside the Compare tab.

## Open questions

None at design time — defaults locked in during brainstorm:

- Test runs auto-persist (no opt-in).
- DB is per-workspace at `.pbg/composite-runs.db`.
- Compare = N runs overlaid (not a fixed pair).
- Snapshot = in-memory override of Parameters editor (not new YAML file).
- Pop-out reuses existing focus-mode CSS.
- Skill is a thin URL launcher (no headless mode).
