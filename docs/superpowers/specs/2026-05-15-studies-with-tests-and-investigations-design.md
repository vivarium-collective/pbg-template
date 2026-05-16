# Studies-with-tests + Investigations as plans

**Date:** 2026-05-15
**Status:** Approved for implementation
**STATUS:** Investigations dropped 2026-05-16 — only the Studies-with-tests portion of this spec is implemented. See git log for the removal commit.
**Owner:** Eran (process-bigraph workspaces)
**Builds on:**
- `2026-05-12-study-model-design.md` (Study v3 — baseline / variants / interventions / runs / viz / conclusion).
- `2026-05-11-investigations-design.md` (historical: legacy v2 Investigation = single-composite recipe; superseded by Study v3).

This spec is purely additive. Existing Study v3 specs keep working; the new fields default to empty.

## Vocabulary additions

| Term | Definition |
|---|---|
| **Test** | A pytest function in `studies/<slug>/tests/test_*.py`. Receives a `run` fixture giving access to the study's latest run trajectory + metadata. Asserts a behavioral expectation. |
| **Investigation** | An ordered chain of Studies forming a research plan. Lives at `investigations/<slug>/investigation.yaml`. The term "Investigation" is reclaimed for this higher-level concept — the legacy v2 Investigation is fully migrated to Study v3 and no longer carries the name. |
| **Gate** | Per-study flag on an Investigation entry. When `gate: tests-pass`, the next entry stays `blocked` until the current study's tests pass AND ≥1 run exists. |
| **Reference** | A markdown document linked from an Investigation and/or Study. Per-section anchors are addressable. |
| **Implementation tasks** | Free-text narrative on a Study describing what an agent should build. Sourced from planning documents (e.g. the multi-phase PDF). |

## Problem

Two gaps in the current Study v3 model:

1. **No behavioral expectations.** A Study has objective + hypothesis + runs + viz + conclusion. There's no place to record "DnaA count should land between 300 and 800 per cell" as machine-checkable. v2ecoli's PR #28 (`feat/replication-initiation-detail`) reinvented this ad-hoc with per-phase pytest files and a hand-rolled HTML status report. The pattern works; it should be a first-class feature.
2. **No way to express a plan that spans many Studies.** A research plan like the DnaA replication-initiation work has 6–8 sequential sub-questions, each implementable as a Study, each gated on the previous. Today that lives in a PR description or an out-of-tree planning doc. There's no spec the dashboard can render and no spec an agent can consume.

The user-facing observation: "Studies should add tests which are behavioral expectations put into Python code as asserts; show them passing when they pass. Investigations are strings of studies which Claude Code agents can implement."

## Goals

- **Tests as a first-class Study field.** Each Study has a `tests/` subdirectory with real pytest files. The dashboard discovers, runs, and surfaces pass/fail per Study.
- **A `run` fixture.** Tests receive a `Run` wrapper bound to the study's latest emitter row, exposing trajectory + parameters + metadata.
- **Investigation as a top-level concept.** Each Investigation references an ordered list of study slugs with status and optional gates. Lives at `investigations/<slug>/investigation.yaml`.
- **Investigation page in the dashboard.** Top-level "Investigations" tab, detail view with sequential study cards (status icons, `n/N tests passing`, gate indicators).
- **`/pbg-implement-study` skill.** Single-shot agent invocation: read the study spec + references + tests, implement until pytest is green, advance the next gated study.
- **No migration cost for existing Studies.** Schema_version bumps from 3 to 4; new fields default to empty; v3 specs load through a transparent upgrade.

## Non-goals (this design)

- **DAG investigations.** Investigations are ordered lists. Parallel branches and explicit `depends_on` are deferred.
- **Tests authored from the dashboard.** Tests are real Python files; users edit them in their editor. The dashboard runs and displays results — it does not write test code.
- **Auto-promoting molecular-reference facts.** Codified facts (e.g. v2ecoli's `molecular_reference.py`) stay workspace-local. The Investigation references markdown documents; structured fact tables are downstream of those.
- **Investigation-level visualizations.** Visualizations stay per-Study. A cross-study summary view is a follow-up.
- **Investigation-level conclusions.** Each Study has its own conclusion. An overall Investigation writeup is a follow-up (the Investigation's `objective` + `hypothesis` are the minimum framing).
- **Cross-workspace investigation references.** Investigations are workspace-local.

## Architecture

### File layout

```
workspace/
├── studies/
│   ├── dnaA-expression-dynamics/
│   │   ├── study.yaml                    # schema_version: 4
│   │   ├── runs.db                       # per-study SQLite (existing)
│   │   ├── viz/                          # rendered viz HTML (existing)
│   │   └── tests/                        # NEW
│   │       ├── conftest.py               # imports run fixture
│   │       ├── test_steady_state.py
│   │       └── test_dilution.py
│   ├── dnaA-atp-hydrolysis/
│   └── …
├── investigations/                       # NEW directory
│   └── dnaA-replication-initiation/
│       └── investigation.yaml            # schema_version: 1
├── docs/
│   └── references/                       # NEW convention; arbitrary path is fine
│       ├── replication_initiation_molecular_info.md
│       └── chromosome-replication-plan.md
└── workspace.yaml                        # unchanged
```

### `study.yaml` — schema_version 4

All existing v3 fields preserved. New fields:

```yaml
schema_version: 4                          # bumped from 3
name: dnaA-expression-dynamics
objective: …                               # existing
status: …                                  # existing
baseline: […]                              # existing
variants: […]                              # existing
interventions: […]                         # existing
runs: […]                                  # existing
visualizations: […]                        # existing
conclusion: …                              # existing

# NEW
implementation_tasks: |                    # narrative; what an agent should build
  1. Add dnaA transcription events.
  2. Add dnaA mRNA degradation.
  3. Add DnaA translation.
  ...
references:                                # docs to consult; per-section anchors optional
  - file: docs/references/replication_initiation_molecular_info.md
    section: dnaA-promoter
  - file: docs/references/replication_initiation_molecular_info.md
    section: DnaA-boxes
tests:
  auto_discover: true                      # pick up studies/<slug>/tests/test_*.py
  data_source: latest_run                  # what `run` binds to: latest_run | first_run | all_runs
  pytest_args: []                          # optional extra args (e.g. ["-k", "steady"])
  last_results:                            # auto-managed by the runner; not hand-edited
    timestamp: 2026-05-15T18:42:00Z
    passed: 4
    failed: 0
    skipped: 0
    duration_s: 2.3
```

### `investigation.yaml` — schema_version 1

```yaml
schema_version: 1
name: dnaA-replication-initiation
objective: |
  Build a mechanistic DnaA cycle and replication-initiation model on v2ecoli,
  replacing the existing mass-threshold initiation heuristic.
hypothesis: |
  A DnaA-ATP titration + box-binding mechanism reproduces emergent
  initiation timing without an explicit mass threshold.
status: in-progress                        # planned | in-progress | complete | archived
references:
  - file: docs/references/replication_initiation_molecular_info.md
    label: "Molecular reference"
  - file: docs/references/chromosome-replication-plan.md
    label: "Multi-phase plan (source PDF)"
studies:
  - study: dnaA-expression-dynamics
    status: in-progress                    # planned | in-progress | blocked | complete
    gate: tests-pass                       # next study waits on this one
  - study: dnaA-atp-hydrolysis
    status: planned
    gate: tests-pass
  - study: dnaA-box-binding
    status: planned
    gate: tests-pass
  - study: replication-mechanism
    status: planned
    gate: tests-pass
  - study: rida-ddah-dars
    status: planned
  - study: seqa-sequestration
    status: planned
  - study: cooperativity
    status: planned
  - study: validation
    status: planned
```

**Status semantics:**

- `planned` — not yet started.
- `in-progress` — agent is working / study has runs but tests not all green.
- `blocked` — previous study has `gate: tests-pass` and is not yet complete.
- `complete` — all tests pass AND ≥1 run exists.

Status is **derived** by the dashboard, not stored on disk. The on-disk value is initial intent; the rendered status reflects current test/run state.

**Gate semantics:**

- `gate: tests-pass` (the only value in v1) — next study stays `blocked` until: (a) all of this study's tests pass, AND (b) ≥1 run exists in `runs.db`. A study with zero tests cannot satisfy the gate (vacuous green is disallowed).
- Absence of `gate:` — next study is never blocked by this one.

### Run fixture

A `Run` wrapper backed by the study's `runs.db`. Lives in `pbg_template.testing.run_fixture`:

```python
# pbg_template/testing/run_fixture.py
import pytest, sqlite3, numpy as np, pandas as pd, yaml
from pathlib import Path

class Run:
    def __init__(self, db_path: Path, run_id: str | None = None):
        self._db = sqlite3.connect(db_path)
        self._run_id = run_id or _latest_run_id(self._db)
        self._meta = _load_meta(self._db, self._run_id)

    # Metadata
    @property
    def params(self) -> dict: return self._meta['params']
    @property
    def seed(self) -> int | None: return self._meta.get('seed')
    @property
    def status(self) -> str: return self._meta['status']
    @property
    def n_steps(self) -> int: return self._meta['n_steps']
    @property
    def variant(self) -> str | None: return self._meta.get('variant')
    @property
    def composite(self) -> str: return self._meta['composite']

    # Trajectory
    @property
    def time(self) -> np.ndarray: ...
    def observable(self, name: str) -> np.ndarray: ...
    def final(self, name: str) -> float:    return self.observable(name)[-1]
    def initial(self, name: str) -> float:  return self.observable(name)[0]
    def cv(self, name: str) -> float:
        x = self.observable(name); return float(x.std() / x.mean()) if x.mean() else float('nan')
    @property
    def trajectory(self) -> pd.DataFrame: ...   # full table

@pytest.fixture
def run(request) -> Run:
    """Latest run of the study under test. Path resolution: walk up from
    the test file until a study.yaml is found."""
    study_dir = _find_study_dir(Path(request.fspath))
    return Run(study_dir / 'runs.db')
```

A `conftest.py` in `studies/<slug>/tests/` imports this fixture so users don't need to wire it themselves:

```python
# studies/<slug>/tests/conftest.py
from pbg_template.testing.run_fixture import run  # re-export pytest fixture
```

(The conftest is scaffolded by `/pbg-study new` and by the v3→v4 migration.)

`data_source` values:

- `latest_run` (default) — `run` is the most-recent row in `runs.db`.
- `first_run` — earliest row.
- `all_runs` — `run` becomes an iterable of `Run` objects; pytest parametrizes.

### Test runner endpoint

```
POST /api/study-tests-run {study}
→ subprocess.run([
    sys.executable, '-m', 'pytest',
    f'studies/{study}/tests/',
    '--json-report', f'--json-report-file=.pbg/study-test-results/{study}.json',
    '-q', *spec['tests'].get('pytest_args', []),
  ])
→ Parses the JSON report. Returns:
  {
    summary: {passed, failed, skipped, duration_s},
    tests:  [{nodeid, outcome, duration, message?, traceback?}],
  }
→ Writes spec.tests.last_results back to study.yaml.
```

Concurrency: per-study `.pbg/study-test-results/<slug>.lock`. Second concurrent run returns 409.

### Investigation endpoints

The legacy `/api/investigation-*` routes are already in use for Studies (Studies were called "Investigations" in v2). To avoid collisions, the new endpoints use the `/api/plan*` prefix. The user-facing UI labels still read "Investigations"; "plan" is an internal naming choice for routes + module identifiers.

| Method + path | Body | Purpose |
|---|---|---|
| `GET /api/plans` | — | All investigations: name, status, study count, references. |
| `GET /api/plan/<slug>` | — | Full investigation.yaml + per-study derived status + per-study test summary. |
| `POST /api/plan-create` | `{name, objective?, hypothesis?, studies[], references?}` | Scaffolds `investigations/<slug>/investigation.yaml`. |
| `POST /api/plan-set-meta` | `{slug, objective?, hypothesis?, status?}` | Selective metadata update. |
| `POST /api/plan-study-add` | `{slug, study, position?, gate?}` | Appends or inserts. |
| `POST /api/plan-study-remove` | `{slug, study}` | Removes from the list. |
| `POST /api/plan-study-set-status` | `{slug, study, status}` | Manual override (status is normally derived). |
| `POST /api/plan-reference-add` | `{slug, file, label?}` | Appends to references. |
| `DELETE /api/plan` | `{slug}` | Removes the directory. |

Status derivation lives server-side: GET endpoints render `derived_status` per study from current test results + run-count, NOT from the on-disk value. The `set-status` endpoint writes a manual override (`status_override:`) which the server then respects until the underlying conditions are met again — escape hatch for "I know better; mark this done."

The legacy `/api/investigations` endpoint (which lists Studies) stays as-is; it now coexists with the new `/api/plans`.

### Dashboard UX

**Top-level "Investigations" tab** (new, in the main nav).

- List of all `investigations/<slug>/investigation.yaml`. Each row: name, status pill, `n_complete / n_total` studies, last-activity timestamp.
- "+ New investigation" button → modal with name + (optional) study slugs to seed.

**Investigation detail page:**

```
┌─────────────────────────────────────────────────────────┐
│ ← Investigations    dnaA-replication-initiation         │
│                                                         │
│ Status: in-progress (3/8 studies complete)              │
│                                                         │
│ Objective: …                                            │
│ Hypothesis: …                                           │
│ References:                                             │
│   📄 Molecular reference                                │
│   📄 Multi-phase plan (source PDF)                      │
│                                                         │
│ Studies (sequential):                                   │
│ ┌───────────────────────────────────────────────────┐   │
│ │ ✅ 1. dnaA-expression-dynamics       4/4 tests    │   │
│ │ ✅ 2. dnaA-atp-hydrolysis            3/3 tests    │   │
│ │ ✅ 3. dnaA-box-binding               7/7 tests    │   │
│ │ 🔄 4. replication-mechanism          2/4 tests    │   │ ← in progress
│ │ ⏸  5. rida-ddah-dars         blocked (gate)      │   │
│ │ ⏸  6. seqa-sequestration     blocked              │   │
│ │ ⏸  7. cooperativity          blocked              │   │
│ │ ⏸  8. validation             blocked              │   │
│ └───────────────────────────────────────────────────┘   │
│                                                         │
│ Each card: click → Study detail page.                   │
└─────────────────────────────────────────────────────────┘
```

**Study detail — new Tests tab:**

- Header: `auto_discover: true`, `data_source: latest_run`.
- Test list: one row per discovered test, with last-result icon (✅/❌/⏭).
- "Run tests" button → calls `/api/study-tests-run`, refreshes on completion.
- Per-test expand: traceback or assertion-failure message.
- "No runs yet" placeholder when `runs.db` is empty; tests are listed but greyed out with a hint "run the study first."

### `/pbg-implement-study` skill

In `pbg-superpowers/skills/pbg-implement-study/SKILL.md`. Input: study slug + (optional) investigation slug.

Flow:

1. Load `studies/<slug>/study.yaml`: objective, implementation_tasks, references, current test summary.
2. Resolve `references[]` → read the named markdown sections into context.
3. Read `studies/<slug>/tests/test_*.py` — the behavioral spec.
4. Read the baseline composite (`study.yaml.baseline[0].composite` → resolve via workspace catalog).
5. Plan the implementation (which processes to add/modify, which composite wiring changes).
6. Implement iteratively:
   - Write/edit code.
   - Run `pytest studies/<slug>/tests/`.
   - Read failures, fix, repeat.
7. When green: run the study itself (via `/api/study-run-baseline` or equivalent) to populate `runs.db`.
8. Re-run tests against the new run. When still green, mark `study.yaml.status = complete`.
9. If an Investigation references this study with `gate: tests-pass`, the dashboard automatically unblocks the next entry.

The skill is the canonical entry point; ad-hoc agent invocations also work because everything (spec, references, tests, composite) is on disk and self-describing.

## v2ecoli instantiation (proves the model)

This section is the concrete first use. Lives as the test of the design.

### Reference extraction

Convert the two PDFs to markdown with stable section anchors:

- **`docs/references/replication_initiation_molecular_info.md`** (from PDF 2). Sections (H2 anchors): `oriC`, `dnaA-promoter`, `DnaA-boxes`, `RIDA`, `DDAH`, `DARS1-and-DARS2`, `intrinsic-ATPase`, `dissociation-after-replication`.
- **`docs/references/chromosome-replication-plan.md`** (from PDF 1). Sections per study with the Implementation Tasks / Read-outs / Expected behavior / References blocks preserved verbatim.

Codified facts already exist at `v2ecoli/data/replication_initiation/molecular_reference.py` from PR #28 — these stay; tests can import them. The markdown is the human-readable mirror; the Python module is the machine-readable mirror.

### Studies created from the plan PDF

| Slug | From PDF | Existing tests (PR #28) |
|---|---|---|
| `dnaA-expression-dynamics` | Study 1 | (none yet — author DnaA count range, mRNA CV, dilution drop) |
| `dnaA-atp-hydrolysis` | Study 2 | `tests/test_dnaA_nucleotide_pool.py` |
| `dnaA-box-binding` | Study 3 | `tests/test_dnaA_binding.py`, `tests/test_dnaA_box_regions.py` |
| `replication-mechanism` | Study 4 | `tests/test_initiation_dnaA_gate.py` |
| `rida-ddah-dars` | Study 5 | `tests/test_rida.py`, `tests/test_ddah.py`, `tests/test_dars.py` |
| `seqa-sequestration` | Study 6 | `tests/test_seqA_sequestration.py` |
| `cooperativity` | Phase 7 (placeholder in PDF) | (none — author after Study 6) |
| `validation` | Phase 8 (placeholder in PDF) | `tests/test_replication_initiation_reference.py`, growth tests |

Each Study gets:

- `study.yaml` with `implementation_tasks` lifted from the PDF section.
- `references:` pointing to the relevant sections of the molecular-info markdown.
- A `tests/` directory with the listed tests moved (not copied) from `v2ecoli/tests/`.
- A baseline composite reference: the `replication_initiation` architecture from PR #28.

### Investigation

`investigations/dnaA-replication-initiation/investigation.yaml` lists the eight studies in order, with `gate: tests-pass` on studies 1–4 (the studies the PDF treats as gating). Studies 5–8 don't gate the next entry (they're more exploratory in the plan).

### PR #28 sequencing

Decision: **merge PR #28 first, then carve into studies in a follow-up PR.** Rationale:

- PR #28's 30-commit history is carefully phased and worth preserving in `git log`.
- The mechanism (processes, composite, listeners) needs to land regardless of how it's organized.
- The carve-up is purely organizational — moving test files into per-study directories, authoring study.yaml + investigation.yaml — and is a low-risk follow-up.
- The monolithic HTML report (`docs/replication_initiation_report.html`) gets retired in the follow-up PR; the Investigation detail page replaces it.

## Data flow

### Create an investigation with seed studies

1. User clicks "+ New investigation" on the Investigations tab.
2. Modal: name, objective, hypothesis, study list (multi-select from existing study slugs, or "create new").
3. POST `/api/investigation-create` → server writes `investigations/<slug>/investigation.yaml`, scaffolds any new studies, returns the new investigation.
4. Redirect to the Investigation detail page.

### Run tests for a study

1. User opens Study detail → Tests tab → clicks "Run tests".
2. POST `/api/study-tests-run {study}` → server shells out to pytest, collects JSON report, writes `last_results` to `study.yaml`.
3. UI refreshes the per-test rows.

### Investigation status updates after a study advances

1. User runs the study (existing run flow).
2. User runs the study's tests; some now pass.
3. Investigation detail page polls `GET /api/investigation/<slug>` → server re-derives status for every entry based on current test results + run counts.
4. If a `gate: tests-pass` study becomes complete, the next entry's status flips from `blocked` to whatever its on-disk value is (default `planned`).

### Agent implements a study

1. User invokes `/pbg-implement-study dnaA-expression-dynamics`.
2. The skill loads the spec, references, tests, baseline composite into context.
3. Agent plans, then iterates code-edit → pytest → fix.
4. Once green, agent runs the study (populates `runs.db`).
5. Agent re-runs tests against fresh data; if still green, sets `study.yaml.status = complete`.
6. Dashboard's polling picks up the new state; next Investigation entry unblocks.

## Error handling

- **`study.yaml.tests.auto_discover: true` but `tests/` is missing.** Tests endpoint returns `{summary: {passed: 0, failed: 0, skipped: 0}, tests: []}` with a notice. Gate logic treats this as "no tests" (cannot satisfy `gate: tests-pass`).
- **`pytest` exits non-zero with no JSON report.** Endpoint returns 500 + the stderr captured. UI surfaces in a banner.
- **`runs.db` missing when a test reads `run`.** The fixture raises `RunNotAvailableError`. pytest reports this as a failure with a clear message — tests cannot pass without a run.
- **Reference file missing.** Investigation detail page renders a broken-link icon next to the missing file; doesn't block other operations.
- **Investigation references a study slug that doesn't exist.** Entry renders as "missing study: <slug>" with a "Create study" CTA. Gate logic treats it as `blocked`.
- **Two concurrent `/api/study-tests-run` on the same study.** Second returns 409; UI shows "tests already running."
- **Manual `set-status` override.** Stored as `status_override: <value>` alongside the studies entry on disk. The server respects it until the underlying conditions match the override (then drops it).

## Testing

**Schema migration:**
- `test_migrate_v3_study_to_v4_adds_empty_tests_block`
- `test_migrate_v3_study_to_v4_preserves_all_existing_fields`
- `test_migrate_v3_study_to_v4_idempotent`
- `test_load_study_yaml_v4_accepts_new_fields`

**Run fixture:**
- `test_run_fixture_loads_latest_row`
- `test_run_fixture_exposes_params_seed_status`
- `test_run_fixture_observable_returns_numpy_array`
- `test_run_fixture_data_source_first_run`
- `test_run_fixture_data_source_all_runs_parametrizes`
- `test_run_fixture_raises_when_runs_db_missing`

**Test runner endpoint:**
- `test_post_study_tests_run_returns_summary`
- `test_post_study_tests_run_writes_last_results`
- `test_post_study_tests_run_handles_no_tests_directory`
- `test_post_study_tests_run_concurrent_request_returns_409`
- `test_post_study_tests_run_pytest_crash_returns_500_with_stderr`

**Investigation endpoints:**
- `test_post_investigation_create_writes_yaml`
- `test_get_investigation_derives_blocked_status_for_gated_study`
- `test_get_investigation_advances_when_gate_satisfied`
- `test_get_investigation_zero_tests_cannot_satisfy_gate`
- `test_post_investigation_study_add_appends`
- `test_post_investigation_study_remove_refuses_if_only_study`
- `test_delete_investigation_removes_directory`

**End-to-end (pbg-template fixture workspace):**
- `test_e2e_create_investigation_run_study_advance_gate` — create a 2-study investigation; run study 1; run its tests (green); study 2 unblocks.
- `test_e2e_v3_v4_migration_via_dashboard_open` — open a v3 study via the dashboard; assert migration runs in-memory; disk file rewrites on next save.

**v2ecoli end-to-end (separate verification):**
- After v2ecoli is converted: open the dnaA-replication-initiation investigation, run each study, watch gates advance.

## Backwards compatibility

- **v3 study.yaml loads as v4 in-memory.** `migrate_v3_to_v4` adds the empty `tests:`/`references:`/`implementation_tasks:` blocks. Disk file is rewritten on the next save (study mutation).
- **Existing `/api/investigations` endpoint** (which lists Studies) stays. The new investigations-list endpoint is `/api/investigations-list`. UI gets a new "Investigations" menu entry alongside the existing "Studies" entry.
- **Tests subdirectory is opt-in.** Studies without `tests/` simply have zero tests and report `{summary: 0/0/0}`. Gate logic treats them as non-advanceable, which is the correct behavior.
- **Investigation directory is opt-in.** Workspaces without `investigations/` show an empty Investigations tab.

## Implementation rollout

**Phase 1 — Schema + Run fixture + test runner endpoint (pbg-template):**
- v3→v4 migration helper.
- `pbg_template.testing.run_fixture` module + conftest scaffolding.
- `POST /api/study-tests-run` endpoint.
- Per-study Tests tab UI in Study detail page.

**Phase 2 — Investigation type (pbg-template):**
- `investigation.yaml` validator.
- Investigation endpoints (list, get, create, set-meta, study-add/remove/set-status, reference-add, delete).
- Status derivation logic (run-count + test-pass + gate).

**Phase 3 — Investigations tab (pbg-template):**
- Top-level menu entry.
- List page.
- Detail page with sequential study cards.
- New-investigation modal.

**Phase 4 — `/pbg-implement-study` skill (pbg-superpowers):**
- SKILL.md authoring.
- Reference-loading helper (resolve `file: …, section: …` to text).
- Iteration loop wrapper around pytest + study-run.

**Phase 5 — v2ecoli content (after PR #28 merges):**
- Extract PDFs to `docs/references/*.md`.
- Author 8 studies; move PR #28's test files into per-study `tests/` directories.
- Create `investigations/dnaA-replication-initiation/investigation.yaml`.
- Retire `docs/replication_initiation_report.html`; link the Investigation detail page from the README.

**Phase 6 — Verify end-to-end on v2ecoli:**
- Walk through every study via the dashboard.
- Run `/pbg-implement-study cooperativity` (the one study without prior PR #28 work) as the real test of the agent skill.

## Related follow-up (separate spec needed): expanded Variant scope

This spec keeps the existing Study v3 Variant model unchanged (`parameter_overrides` only). Eran has confirmed that the Variant model needs to be expanded to support:

- **Initial-state overrides** (current state values at composite construction).
- **Process configuration overrides** including pathway-level edits (config keys inside a process, not just top-level params).
- **Plugging in new modules** — adding a process not present in the baseline.
- **Replacing modules** — swapping a process implementation (partially scoped in `multi-composite-investigations-design.md` as `process_overrides:`, but not implemented in v3).

This expansion is **its own spec** — it touches the composite-derivation system, not the test/investigation surface this spec defines. Studies-with-tests and Investigations-as-plans land independently of variant-scope expansion.

When expanded-variant lands, no schema change to this spec is required: the test fixture, runner, and investigation chain all operate over the run output, not the variant recipe.

## Out of scope (follow-ups)

- **DAG investigations** with `depends_on:` per study.
- **Investigation-level visualizations** (cross-study summary plots).
- **Investigation-level conclusion** (single markdown blob).
- **Cross-workspace Investigation references.**
- **Auto-extracting molecular facts from PDFs** into structured Python (today this is manual; codified facts live at `v2ecoli/data/replication_initiation/molecular_reference.py`).
- **Dashboard test authoring** (in-browser test editor).
- **CI integration** — auto-running study tests on PR open. Today tests run on demand from the dashboard or in a local pytest invocation.
- **Investigation templates** — clone an existing investigation as the starting point for a new one.
