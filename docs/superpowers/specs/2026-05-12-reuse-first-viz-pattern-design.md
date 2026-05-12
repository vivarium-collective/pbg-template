# Reuse-first visualization pattern

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:** the v0.4.2 description-only `/pbg-viz` flow (wrapper functions) for new entries; legacy entries are migrated.

## Problem

After landing Visualization v2 (2026-05-12-visualization-v2-design.md) the workspace
has *three* parallel ways to add a visualization:

1. **Class-backed instances** (new, v2): `workspace.yaml` entries with `class: + config:`,
   composing with the Investigation v2 dispatch path.
2. **Wrapper functions** (v0.4.2): `/pbg-viz` skill generates
   `.pbg/viz-responses/<name>.py` with `def visualize(results: dict) -> str`. Does
   *not* compose with v2 dispatch — different state shape, no typed inputs, not
   discoverable as a class.
3. **Hand-written `Visualization` subclasses** in pbg-* wrapper packages.

The split is confusing for beginners, makes generated visualizations dead-end
artifacts (each one is a one-off, not reusable), and breaks the natural growth
loop where workspace use should *accumulate* reusable visualization classes.

## Goals

- **One artifact model.** Every visualization is a `Visualization` v2 subclass.
  No wrapper functions for new work.
- **Reuse-first UX.** When a user wants a visualization, the dashboard surfaces
  the existing catalog *before* offering to generate something new.
- **Generate-and-promote loop.** Generation produces a committable class file
  inside the workspace package. After commit, the class is discoverable in
  `core.link_registry` and shows up in *everyone's* catalog. Each iteration
  grows the reusable pool.
- **Low boilerplate.** Generated files use the `as_visualization` decorator
  (analogous to `process_bigraph.as_step` / `as_process`) so /pbg-viz emits one
  function, not a full class definition.
- **Clean migration.** Legacy description-only entries are auto-detected,
  classified, and migrated via a one-time dashboard action.

## Non-goals

- Re-thinking the Investigation v2 dispatch (already shipped).
- Rewriting hand-authored Visualization classes in pbg-* wrapper packages.
- Static type-checking of viz config schemas beyond what bigraph-schema does.
- A visual editor for hand-tuning Plotly layouts (separate follow-up).

## Architecture

### Three artifacts, clear roles

| Artifact | Lives at | Created by | Discovered via |
|---|---|---|---|
| **Visualization class** (Python) | `<workspace_pkg>/visualizations/<snake>.py` | `/pbg-viz`, hand-written, or shipped by pbg-* package | `bigraph_schema.discover_packages` via `allocate_core()` → `core.link_registry` |
| **Configured instance** | `workspace.yaml.visualizations[]`: `{name, class, config}` | User via Add-Viz modal | `GET /api/visualization-instances` |
| **Investigation viz** | `investigations/<x>/spec.yaml.visualizations[]`: `{name, address, config}` | User via Investigation Add-Viz modal | Investigation orchestrator |

### Lifecycle for adding a new visualization

```
User wants viz X
  ↓
[Step 1: SEARCH]
  Visualizations tab → "Available classes" panel (searchable)
  Match? ──yes──► register as class-backed instance (Step 4) — done
  ↓ no
[Step 2: GENERATE]
  "Generate new visualization class" → describe in natural language
  /pbg-viz writes <pkg>/visualizations/<snake>.py
  (one function decorated with @as_visualization)
  ↓
[Step 3: REVIEW & COMMIT]
  Dashboard shows: generated code + live demo render + declared inputs
  Edit / regenerate / accept → file committed to git
  Next build_core() picks it up → it's now in everyone's catalog
  ↓
[Step 4: REGISTER instance]
  Dashboard prompts: "Configure this class as a named instance?"
  User fills in config → workspace.yaml gets {name, class, config}
```

The key property: **Step 3 makes the class discoverable for future users**. After
a few iterations, Step 1's "Match?" hits more often, and Step 2 fires only for
genuinely novel needs.

### `as_visualization` decorator (pbg-superpowers)

Lives in `pbg_superpowers/visualization.py`, mirrors `process_bigraph.as_step`:

```python
def as_visualization(inputs, name=None, demo=None, aliases=None):
    """Decorator: convert an `update_*` pure function into a Visualization subclass.

    The function must be named `update_<viz_name>` and accept
    ``state: dict`` → ``{'html': str}``.

    Args:
        inputs: typed input port map (same shape as Visualization.inputs()).
                Keys are port names; values are bigraph-schema type strings.
        name:   class name override (default: derived from function name).
        demo:   sample state dict (or callable returning one) for dashboard previews.
        aliases: extra registration aliases for bigraph-schema discovery.

    Returns the synthesized Visualization subclass, ready to be registered by
    bigraph_schema.discover().
    """
    def decorator(func):
        if not func.__name__.startswith("update_"):
            raise AssertionError("Function name must be of the form update_*")
        viz_name = name or func.__name__[len("update_"):]
        _demo = demo

        class FunctionVisualization(Visualization):
            def inputs(self): return inputs
            def outputs(self): return {'html': 'string'}
            def update(self, state): return func(state)
            @classmethod
            def demo(cls):
                if callable(_demo):
                    return _demo()
                return dict(_demo or {})

        FunctionVisualization.__name__ = viz_name
        FunctionVisualization.__module__ = func.__module__
        FunctionVisualization.__pb_kind__ = "visualization"
        FunctionVisualization.__pb_aliases__ = [viz_name] + list(aliases or [])
        FunctionVisualization.__pb_wrapped__ = func
        return FunctionVisualization
    return decorator
```

### Generated file shape

`<workspace_pkg>/visualizations/dna_a_trajectory.py` (~25 lines, vs ~40 for an
explicit class):

```python
"""DnaATrajectory — DnaA concentration vs time with binding-threshold overlay.

Generated by /pbg-viz on 2026-05-12 from request 'dna-a-trajectory'.
"""
from __future__ import annotations
import html as _html, json
from pbg_superpowers.visualization import as_visualization


@as_visualization(
    inputs={'free_DnaA': 'list[float]', 'time': 'list[float]'},
    name='DnaATrajectory',
    demo={'free_DnaA': [40.0, 45.0, 50.0, 55.0, 60.0],
          'time':      [0.0, 1.0, 2.0, 3.0, 4.0]},
)
def update_dna_a_trajectory(state):
    """Render DnaA trajectory with binding-threshold reference line."""
    traces = [{'x': state['time'], 'y': state['free_DnaA'],
               'type': 'scatter', 'mode': 'lines',
               'line': {'color': '#6366f1', 'width': 2}}]
    layout = {
        'shapes': [{'type': 'line', 'xref': 'paper', 'x0': 0, 'x1': 1,
                    'y0': 50.0, 'y1': 50.0,
                    'line': {'dash': 'dash', 'color': '#f43f5e'}}],
        'margin': {'l': 55, 'r': 15, 't': 40, 'b': 40},
    }
    return {'html': (
        '<div id="viz" style="height:380px"></div>'
        '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
        '<script>Plotly.newPlot("viz",'
        + json.dumps(traces) + ',' + json.dumps(layout)
        + ', {responsive:true, displayModeBar:false});</script>'
    )}
```

No `__init__.py` editing required: `bigraph_schema.allocate_core()` calls
`discover_packages()` which walks every installed pbg-* distribution via
`importlib.metadata.packages_distributions()`, recurses through submodules using
`pkgutil.iter_modules`, finds every class that subclasses `Edge` (Step inherits
from Edge; Visualization inherits from Step), and registers each one in
`core.link_registry` under both its fully-qualified name
(`<pkg>.visualizations.dna_a_trajectory.DnaATrajectory`) and its short
`__name__` (`DnaATrajectory`).

The `__pb_kind__ = "visualization"` and `__pb_aliases__` markers the
`as_visualization` decorator stamps on the synthesized class are *metadata*,
consumed by our dashboard's catalog filter (so the UI can list only
visualizations, not all Steps), not by `discover_packages` itself.

### Build & discovery hookup

The standard pbg-template `<workspace_pkg>/core.py`:

```python
from process_bigraph import allocate_core

def build_core():
    return allocate_core()
```

Two preconditions for a new viz class to appear in `core.link_registry`:

1. **The workspace package is pip-installed in editable mode** (`pip install -e .`
   inside the workspace venv). Most pbg-template workspaces already are; the
   "Install" path in the dashboard's Imports panel does this for sibling
   packages. If a workspace isn't installed, the dashboard surfaces a warning
   on first generate.
2. **`bigraph_schema.core._cached_base_core` is invalidated.** `allocate_core()`
   caches the discovered base core after the first call. After /pbg-viz writes
   a new file, the server explicitly clears this cache
   (`bigraph_schema.core._cached_base_core = None`) so the next request rebuilds
   discovery and picks up the new class. No server restart required.

If a workspace's `build_core()` does explicit registration instead of relying on
`allocate_core()`, the generate flow detects this (by AST-inspecting `core.py`
or by failing to find the new class in `link_registry` after invalidation) and
prompts the user to either switch to `allocate_core()` or to paste in an
explicit registration line. The skill-generated file always works with the
common `allocate_core()`-based template.

### Dashboard UX (Visualizations tab, top-to-bottom)

1. **Workspace visualizations** — configured instances (already in place from
   the v2 work).
2. **Available Visualization classes** — searchable catalog with Preview + Use
   buttons. The search input is new; everything else exists. Filter by name,
   doc keyword, or input port name.
3. **Generate new visualization class** — new panel. "Describe what you need"
   form. Triggers /pbg-viz. After generation: preview iframe, accept /
   regenerate / edit buttons. Accept → commit + auto-prompt to register an
   instance.

The ordering signals the pattern: reuse first, generate last.

### `/pbg-viz` skill changes

The skill at `~/.claude/skills/pbg-viz/SKILL.md` is updated to:

- **New output target.** Files go to `<workspace_pkg>/visualizations/<snake>.py`
  (not `.pbg/viz-responses/<name>.py`).
- **New output contract.** One `update_<name>(state)` function decorated with
  `@as_visualization(inputs={...}, demo={...})`. No class definitions, no
  `__init__.py` edits, no separate `_demo()` helper — the decorator provides all
  of these.
- **Backward-compat detection.** Skill can detect a legacy request file (old
  format: "Takes one argument: `results: dict`...") and produce a v2 decorated
  function anyway. The skill prompt explains the new contract clearly enough
  that the agent doesn't get confused by stale request text.
- **Knowledge update.** SKILL.md gains a "Decorators" section explaining
  `as_step`, `as_process`, `as_visualization` and the discovery mechanism, so
  the skill can cross-reference these patterns when generating other pbg
  artifacts.

### Migration of legacy entries

A one-time CLI: `python3 scripts/migrate-visualizations.py`. Same migration is
surfaced via a dashboard banner ("3 legacy entries can be migrated → Run
migration") for beginners.

| Legacy entry shape | Detection | Migration |
|---|---|---|
| Description matches `"use the registered X class"` (e.g. `readdyplots`, `timeseriesplot`) | Regex on description | Auto-convert: rewrite entry as `{name, class: X, config: {}}`. Delete the viz-request file. Class must be in the registry. |
| Wrapper response file exists (e.g. `smoke-trajectory.py` in `.pbg/viz-responses/`) | File presence | Offer to re-generate as a v2 class via new /pbg-viz. Keep wrapper file (marked `.deprecated`) until user confirms the new class works. |
| Description-only, no response file (e.g. `video-of-chromosome`) | Default case | Re-trigger /pbg-viz via the new class-generating flow. |

Migration writes its actions to a log file (`.pbg/migrations/<timestamp>.log`)
so the user can audit and revert.

## Data flow

**New viz (reuse path):**

1. User opens Visualizations tab → sees catalog at top.
2. Picks a class (e.g. `TimeSeriesPlot`) → clicks Use.
3. Add-Viz modal opens with class pre-selected.
4. User fills config + name → submit.
5. `POST /api/visualization` writes `{name, class, config}` to `workspace.yaml`.

**New viz (generate path):**

1. No catalog match → user opens "Generate new visualization class" panel.
2. Fills description + suggested name → submit.
3. `POST /api/visualization-generate` writes a request file with the new
   contract and signals the active Claude Code session via the existing
   request-poll mechanism.
4. /pbg-viz reads the request, writes
   `<workspace_pkg>/visualizations/<snake>.py`.
5. Dashboard polls; on detection, shows preview iframe (calls the new
   `cls.demo()`) and the source code with accept/regenerate/edit actions.
6. Accept → server commits the file, invalidates
   `bigraph_schema.core._cached_base_core` so the next `allocate_core()` call
   rebuilds discovery, and prompts the user to register an instance.

**Migration:**

1. On dashboard load, server queries workspace.yaml + `.pbg/viz-requests/` +
   `.pbg/viz-responses/`.
2. Computes a migration plan (per-entry decision per the table above).
3. If `n > 0`, shows the banner with the count and a "Review migration"
   button.
4. User clicks → modal lists each entry with its planned action; user picks
   per-entry actions (auto, defer, skip).
5. Submit → server applies migrations, commits the change, logs to
   `.pbg/migrations/`.

## Error handling

- **Generated class fails to import.** Server catches the import error during
  the post-generate `allocate_core()` call (after cache invalidation), marks
  the class file with a `.broken` sibling note, and surfaces the error in the
  dashboard. User can edit or regenerate.
- **Workspace package not pip-installed.** Generation still writes the file,
  but discovery won't find it. Dashboard surfaces a banner with the exact
  command (`pip install -e .` in the workspace venv) to fix.
- **Migration target class missing from registry.** Auto-migration of a
  "use the registered X class" entry first verifies X is in the catalog. If
  not, defer that entry and surface a warning.
- **`as_visualization`-decorated function raises at update time.** Investigation
  v2's per-viz error isolation (already shipped) catches the exception and
  writes an error stub HTML for that viz; others still render.
- **Server can't reach an active Claude Code session.** Generation falls back
  to the existing "write request file; instruct user" path, but the dashboard
  message is friendlier ("If you're in Claude Code right now, the request is
  ready; if not, follow these steps...").

## Testing

**`as_visualization` decorator (pbg-superpowers):**
- `test_as_visualization_synthesizes_subclass` — decorate a function, assert
  `issubclass(result, Visualization)`, `result.__pb_kind__ == 'visualization'`,
  `result.__name__` matches override or function name.
- `test_as_visualization_demo_callable_or_dict` — both `demo={...}` literal and
  `demo=lambda: {...}` work.
- `test_as_visualization_function_name_validation` — raises if name doesn't
  start with `update_`.
- `test_decorated_class_round_trips_through_composite` — same shape as our
  TimeSeriesPlot tests but on a synthesized class.

**Discovery (pbg-superpowers + bigraph-schema):**
- `test_discover_finds_decorated_visualization` — temp module with one
  `@as_visualization` function, `discover([module])` returns a core whose
  `link_registry` contains the synthesized class under its alias.

**Migration (pbg-template):**
- `test_migrate_detects_use_the_registered_class_pattern` — workspace.yaml
  fixture with a `"use the registered ReaDDyPlots class..."` description; the
  detector returns `(action='auto-convert-to-class-backed', class='ReaDDyPlots')`.
- `test_migrate_skips_when_target_class_missing` — same fixture, but the
  registry doesn't contain `ReaDDyPlots`; detector returns
  `(action='defer', reason='class ReaDDyPlots not in registry')`.
- `test_migrate_writes_log_file` — after applying a migration, the log under
  `.pbg/migrations/<timestamp>.log` lists each entry's before/after state.

**Dashboard endpoints (pbg-template):**
- `test_post_visualization_generate_writes_request_with_new_contract` — POST
  with `{name, description}`; assert request markdown mentions the
  `as_visualization` contract.
- `test_get_visualization_migration_plan` — fixture workspace.yaml with the
  three legacy patterns; endpoint returns a plan with the three classifications.

**/pbg-viz skill (manual / fixture-based):**
- Place a request file with the new contract under
  `.pbg/viz-requests/<name>.md`; run the skill; assert
  `<workspace_pkg>/visualizations/<snake>.py` exists, imports cleanly, and the
  synthesized class round-trips through a Composite.

## Backwards compatibility

- **Existing class-backed instances (just shipped):** continue working, no
  change. Their dispatch path is unchanged.
- **Existing wrapper response files** (`.pbg/viz-responses/*.py`): not invoked
  by any new code path. Marked `.deprecated` during migration; can be deleted
  once the user accepts the v2 replacement.
- **Existing pbg-* wrapper packages** (`pbg-readdy`, `pbg-bioreactordesign`)
  ship hand-written Visualization classes; those keep working — `discover()`
  picks them up the same way.
- **Existing investigations** that reference a description-only viz by name:
  if the migration converts that entry to a class-backed instance, the
  investigation's spec.yaml stays unchanged and the next render uses the new
  class. If the user deferred the migration, the description-only entry
  stays; investigation render falls back to a per-viz error stub.

## Out of scope (follow-ups)

- A "promote a wrapper function to a Visualization class" command (we're not
  building this — wrappers get re-generated as classes via /pbg-viz on
  migration instead).
- Versioning of generated classes (semver of viz behavior).
- A class-level test harness — `cls.demo()` already covers preview;
  user-defined tests are the user's job.
- A registry-of-registries UI (cross-workspace visualization sharing). Each
  workspace's package can be a pip-installable pbg-* and shows up in others'
  catalogs that way; no extra mechanism needed.

## Implementation rollout

Three phases (each ends in a clean, ship-able state):

**Phase A — pbg-superpowers v0.7.0:** add `as_visualization` decorator + tests.
Cut release.

**Phase B — pbg-template:** add `/api/visualization-generate` endpoint, new
"Generate new visualization class" UI panel, search input on the catalog,
migration plan endpoint + banner. Sync to v2ecoli, verify.

**Phase C — `/pbg-viz` skill:** rewrite SKILL.md with the new contract, sample
templates, and the as_visualization knowledge section. Test against a synthetic
request file end-to-end. Once green, migrate the three v2ecoli legacy entries.

Order matters: A unblocks C (the decorator must exist before the skill can use
it); B unblocks the user-facing flow; C completes the loop.
