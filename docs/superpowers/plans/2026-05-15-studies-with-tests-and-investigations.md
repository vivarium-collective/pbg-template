# Studies-with-tests + Investigations Implementation Plan (vivarium-dashboard foundation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the vivarium-dashboard side of `2026-05-15-studies-with-tests-and-investigations-design.md`: Study v4 schema with `tests:` / `references:` / `implementation_tasks:`; per-study pytest discovery + runner endpoint with a `Run` fixture; new Investigation-as-plan type with ordered chain + `gate: tests-pass` semantics; dashboard UI (Tests tab on Study; Investigations top-level tab).

**Architecture:** All implementation lives in `/Users/eranagmon/code/vivarium-dashboard/`. New module `vivarium_dashboard/lib/investigation_plans.py` for the chain concept (named "investigation plan" internally to disambiguate from the legacy `/api/investigation-*` routes that handle Studies). New module `vivarium_dashboard/lib/study_tests.py` for the pytest runner. New module `vivarium_dashboard/testing/run_fixture.py` for the pytest `Run` fixture (importable from user test files via `from vivarium_dashboard.testing import run`). v3→v4 migration extends `vivarium_dashboard/lib/spec_migration.py`. Routes added to `vivarium_dashboard/server.py`. UI: `static/study-detail.js` gains a Tests tab; new `static/investigations.js` for the Investigations top-level page; `templates/index.html.j2` gains the new section.

**API naming convention:** to avoid collision with the existing `/api/investigation-*` routes (which handle Studies), the new endpoints use the `/api/plan*` prefix. User-facing UI labels remain "Investigations".

**Tech stack:** Python 3.11, stdlib `http.server`, PyYAML, sqlite3, pytest, subprocess, vanilla JS, Jinja2.

---

## File structure (target end-state)

**Modified:**
- `vivarium_dashboard/lib/spec_migration.py` — adds `migrate_v3_to_v4`.
- `vivarium_dashboard/lib/investigations.py` — `load_spec` chains v3→v4 migration; `_validate_study_v3` becomes `_validate_study_v3_or_v4` and accepts the new fields.
- `vivarium_dashboard/server.py` — adds 11 new routes.
- `vivarium_dashboard/static/study-detail.js` — adds Tests tab logic.
- `vivarium_dashboard/static/walkthrough.js` — adds Investigations section loader.
- `vivarium_dashboard/static/style.css` — styles for test rows + investigation cards.
- `vivarium_dashboard/templates/index.html.j2` — adds Investigations menu link + `<section id="page-investigations">`.
- `vivarium_dashboard/templates/study-detail.html` — adds Tests tab markup.
- `pbg-template/template/.gitignore.j2` (or similar) — ignore `.pbg/study-test-results/`.

**Created:**
- `vivarium_dashboard/lib/study_tests.py` — pytest runner + last_results writeback.
- `vivarium_dashboard/lib/investigation_plans.py` — investigation.yaml validator, IO, status derivation.
- `vivarium_dashboard/testing/__init__.py` — re-exports `run` fixture.
- `vivarium_dashboard/testing/run_fixture.py` — `Run` class + pytest fixture + study_dir auto-discovery.
- `vivarium_dashboard/static/investigations.js` — Investigations list + detail page logic.
- `vivarium_dashboard/static/investigations.css` (optional — or appended to style.css).
- `tests/test_migrate_v3_to_v4.py`
- `tests/test_run_fixture.py`
- `tests/test_study_tests_endpoint.py`
- `tests/test_investigation_plans.py`
- `tests/test_investigation_plan_endpoints.py`
- `tests/test_e2e_tests_and_investigations.py`

---

## Phase A — Schema v3→v4 migration

### Task 1: Write `migrate_v3_to_v4` helper

**Files:**
- Create: `tests/test_migrate_v3_to_v4.py`
- Modify: `vivarium_dashboard/lib/spec_migration.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_v3_to_v4.py
"""Tests for v3 → v4 study spec migration (adds tests/references/implementation_tasks)."""
from vivarium_dashboard.lib.spec_migration import migrate_v3_to_v4


def test_migrate_v3_to_v4_adds_empty_tests_block():
    spec = {"schema_version": 3, "name": "s", "baseline": [], "variants": []}
    out = migrate_v3_to_v4(spec)
    assert out["schema_version"] == 4
    assert out["tests"] == {
        "auto_discover": True,
        "data_source": "latest_run",
        "pytest_args": [],
        "last_results": None,
    }


def test_migrate_v3_to_v4_adds_empty_references_and_implementation_tasks():
    spec = {"schema_version": 3, "name": "s", "baseline": []}
    out = migrate_v3_to_v4(spec)
    assert out["references"] == []
    assert out["implementation_tasks"] == ""


def test_migrate_v3_to_v4_preserves_all_existing_fields():
    spec = {
        "schema_version": 3,
        "name": "s",
        "objective": "x",
        "baseline": [{"name": "b", "composite": "c", "params": {}}],
        "variants": [{"name": "v", "base_composite": "b", "parameter_overrides": {"r": 2.0}}],
        "interventions": [{"name": "i", "description": "d"}],
        "runs": [{"run_id": "r1", "variant": None, "composite": "b", "label": "", "status": "completed", "n_steps": 100}],
        "visualizations": [{"name": "vz", "address": "local:V", "config": {}}],
        "conclusion": "yes",
    }
    out = migrate_v3_to_v4(spec)
    assert out["schema_version"] == 4
    assert out["objective"] == "x"
    assert out["baseline"] == spec["baseline"]
    assert out["variants"] == spec["variants"]
    assert out["interventions"] == spec["interventions"]
    assert out["runs"] == spec["runs"]
    assert out["visualizations"] == spec["visualizations"]
    assert out["conclusion"] == "yes"


def test_migrate_v3_to_v4_idempotent():
    spec_v4 = {
        "schema_version": 4,
        "name": "s",
        "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [],
        "implementation_tasks": "",
    }
    out = migrate_v3_to_v4(spec_v4)
    assert out == spec_v4  # identity


def test_migrate_v3_to_v4_preserves_existing_tests_block():
    spec = {
        "schema_version": 3,
        "name": "s",
        "baseline": [],
        "tests": {"auto_discover": False, "data_source": "first_run", "pytest_args": ["-k", "foo"], "last_results": {"passed": 1, "failed": 0, "skipped": 0, "duration_s": 0.1, "timestamp": "2026-05-15T18:42:00Z"}},
    }
    out = migrate_v3_to_v4(spec)
    assert out["tests"]["auto_discover"] is False
    assert out["tests"]["data_source"] == "first_run"
    assert out["tests"]["pytest_args"] == ["-k", "foo"]
    assert out["tests"]["last_results"]["passed"] == 1


def test_migrate_v3_to_v4_skips_non_v3_spec():
    spec = {"schema_version": 2, "name": "s"}
    out = migrate_v3_to_v4(spec)
    assert out["schema_version"] == 2  # untouched
```

- [ ] **Step 2: Run test, verify failure**

Run: `cd /Users/eranagmon/code/vivarium-dashboard && pytest tests/test_migrate_v3_to_v4.py -v`
Expected: ImportError / AttributeError on `migrate_v3_to_v4`.

- [ ] **Step 3: Implement the migration**

Append to `vivarium_dashboard/lib/spec_migration.py`:

```python
def migrate_v3_to_v4(spec: dict) -> dict:
    """Migrate a v3 study spec to v4 in-memory by adding the tests / references /
    implementation_tasks fields. Idempotent. Only touches specs with
    ``schema_version == 3``.
    """
    if spec.get("schema_version") != 3:
        return spec

    out = dict(spec)
    out["schema_version"] = 4

    existing_tests = out.get("tests") or {}
    out["tests"] = {
        "auto_discover": existing_tests.get("auto_discover", True),
        "data_source": existing_tests.get("data_source", "latest_run"),
        "pytest_args": existing_tests.get("pytest_args", []),
        "last_results": existing_tests.get("last_results"),
    }
    out.setdefault("references", [])
    out.setdefault("implementation_tasks", "")
    return out
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `pytest tests/test_migrate_v3_to_v4.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/eranagmon/code/vivarium-dashboard
git add vivarium_dashboard/lib/spec_migration.py tests/test_migrate_v3_to_v4.py
git commit -m "feat(spec): add v3→v4 study spec migration (tests + references + implementation_tasks)"
```

---

### Task 2: Chain v3→v4 into `load_spec`

**Files:**
- Modify: `vivarium_dashboard/lib/investigations.py:21,317` (import + call site)
- Create: `tests/test_load_spec_v4.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_load_spec_v4.py
import yaml, pathlib
from vivarium_dashboard.lib.investigations import load_spec


def test_load_spec_v3_yaml_returns_v4_in_memory(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "test-study",
        "baseline": [{"name": "b", "composite": "pkg.c", "params": {}}],
        "variants": [],
        "interventions": [],
        "runs": [],
        "visualizations": [],
        "conclusion": "",
        "objective": "",
        "parent_studies": [],
    }))
    spec = load_spec(spec_path)
    assert spec["schema_version"] == 4
    assert spec["tests"]["auto_discover"] is True
    assert spec["tests"]["data_source"] == "latest_run"
    assert spec["references"] == []
    assert spec["implementation_tasks"] == ""


def test_load_spec_v4_yaml_passes_through(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump({
        "schema_version": 4,
        "name": "test-study",
        "baseline": [{"name": "b", "composite": "pkg.c", "params": {}}],
        "variants": [],
        "interventions": [],
        "runs": [],
        "visualizations": [],
        "conclusion": "",
        "objective": "",
        "parent_studies": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [],
        "implementation_tasks": "",
    }))
    spec = load_spec(spec_path)
    assert spec["schema_version"] == 4
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_load_spec_v4.py -v`
Expected: assertion failure — `schema_version == 3`, not 4.

- [ ] **Step 3: Wire the migration**

In `vivarium_dashboard/lib/investigations.py`:

At the top (`import` section around line 21), change:
```python
from .spec_migration import migrate_study_to_v2_vocabulary, migrate_v2_to_v3
```
to:
```python
from .spec_migration import migrate_study_to_v2_vocabulary, migrate_v2_to_v3, migrate_v3_to_v4
```

At line 317 (inside `load_spec`, after `spec = migrate_v2_to_v3(spec)`), add:
```python
    spec = migrate_v3_to_v4(spec)
```

- [ ] **Step 4: Update the v3 validator to accept v4 too**

Find `_validate_study_v3` (search for its definition). Rename to `_validate_study_v3_or_v4`. In `load_spec`, change the version check:

```python
    # old:
    if spec.get("schema_version") == 3:
        _validate_study_v3(spec)
        return spec
    # new:
    if spec.get("schema_version") in (3, 4):
        _validate_study_v3_or_v4(spec)
        return spec
```

In `_validate_study_v3_or_v4`, add validation for the v4 fields (only if `schema_version == 4`):

```python
    if spec.get("schema_version") == 4:
        tests = spec.get("tests") or {}
        if not isinstance(tests, dict):
            raise InvestigationSpecError("tests must be a mapping")
        ds = tests.get("data_source", "latest_run")
        if ds not in ("latest_run", "first_run", "all_runs"):
            raise InvestigationSpecError(
                f"tests.data_source must be one of latest_run|first_run|all_runs, got {ds!r}"
            )
        if not isinstance(tests.get("pytest_args", []), list):
            raise InvestigationSpecError("tests.pytest_args must be a list")
        refs = spec.get("references") or []
        if not isinstance(refs, list):
            raise InvestigationSpecError("references must be a list")
        for i, ref in enumerate(refs):
            if not isinstance(ref, dict) or not ref.get("file"):
                raise InvestigationSpecError(f"references[{i}] must be a mapping with at least a 'file' key")
        if not isinstance(spec.get("implementation_tasks", ""), str):
            raise InvestigationSpecError("implementation_tasks must be a string")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/test_load_spec_v4.py tests/test_migrate_v3_to_v4.py -v`
Expected: 8 passed.

- [ ] **Step 6: Run the existing test suite to check for regressions**

Run: `pytest tests/ -x -q`
Expected: all green, no regressions.

- [ ] **Step 7: Commit**

```bash
git add vivarium_dashboard/lib/investigations.py tests/test_load_spec_v4.py
git commit -m "feat(spec): chain v3→v4 migration into load_spec; validate new v4 fields"
```

---

## Phase B — `Run` fixture module

### Task 3: Define the `Run` wrapper class

**Files:**
- Create: `vivarium_dashboard/testing/__init__.py`
- Create: `vivarium_dashboard/testing/run_fixture.py`
- Create: `tests/test_run_fixture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_fixture.py
"""Tests for the Run wrapper backing the pytest `run` fixture."""
import sqlite3, json
from pathlib import Path
import pytest
from vivarium_dashboard.testing.run_fixture import Run, RunNotAvailableError


def _make_runs_db(path: Path, *, runs: list[dict]) -> None:
    """Create a minimal runs.db with the given runs.

    Each run dict: {run_id, params, seed, status, n_steps, observables: {name: [values]}}
    """
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs_meta (
            run_id TEXT PRIMARY KEY,
            params TEXT,
            seed INTEGER,
            status TEXT,
            n_steps INTEGER,
            variant TEXT,
            composite TEXT,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            run_id TEXT,
            step INTEGER,
            observable TEXT,
            value REAL
        )
    """)
    for r in runs:
        conn.execute(
            "INSERT INTO runs_meta(run_id, params, seed, status, n_steps, variant, composite, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (r["run_id"], json.dumps(r.get("params", {})), r.get("seed"), r.get("status", "completed"),
             r.get("n_steps", 0), r.get("variant"), r.get("composite", "b"), r.get("timestamp", "")),
        )
        for obs_name, values in r.get("observables", {}).items():
            for step, v in enumerate(values):
                conn.execute(
                    "INSERT INTO history(run_id, step, observable, value) VALUES (?,?,?,?)",
                    (r["run_id"], step, obs_name, v),
                )
    conn.commit()
    conn.close()


def test_run_loads_latest_row(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[
        {"run_id": "old", "timestamp": "2026-05-14T00:00:00", "observables": {"x": [1.0]}},
        {"run_id": "new", "timestamp": "2026-05-15T00:00:00", "observables": {"x": [2.0]}},
    ])
    run = Run(db)
    assert run.observable("x")[-1] == 2.0


def test_run_exposes_params_seed_status(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[{
        "run_id": "r1", "params": {"rate": 2.0}, "seed": 42,
        "status": "completed", "n_steps": 100, "variant": "high-rate", "composite": "baseline",
    }])
    run = Run(db)
    assert run.params == {"rate": 2.0}
    assert run.seed == 42
    assert run.status == "completed"
    assert run.n_steps == 100
    assert run.variant == "high-rate"
    assert run.composite == "baseline"


def test_run_observable_returns_array(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[{"run_id": "r1", "observables": {"x": [1.0, 2.0, 3.0]}}])
    run = Run(db)
    import numpy as np
    arr = run.observable("x")
    assert isinstance(arr, np.ndarray)
    assert list(arr) == [1.0, 2.0, 3.0]


def test_run_final_initial_helpers(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[{"run_id": "r1", "observables": {"x": [1.0, 2.0, 3.0]}}])
    run = Run(db)
    assert run.final("x") == 3.0
    assert run.initial("x") == 1.0


def test_run_cv(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[{"run_id": "r1", "observables": {"x": [10.0, 10.0, 10.0]}}])
    run = Run(db)
    assert run.cv("x") == 0.0


def test_run_raises_when_db_missing(tmp_path):
    with pytest.raises(RunNotAvailableError):
        Run(tmp_path / "nonexistent.db")


def test_run_raises_when_no_runs(tmp_path):
    db = tmp_path / "runs.db"
    _make_runs_db(db, runs=[])
    with pytest.raises(RunNotAvailableError):
        Run(db)
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_run_fixture.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `Run` class**

`vivarium_dashboard/testing/__init__.py`:
```python
"""Test helpers for studies-with-tests. Import the `run` pytest fixture
from your study's tests/conftest.py:

    from vivarium_dashboard.testing import run  # noqa: F401
"""
from .run_fixture import Run, RunNotAvailableError, run

__all__ = ["Run", "RunNotAvailableError", "run"]
```

`vivarium_dashboard/testing/run_fixture.py`:
```python
"""Run wrapper + pytest fixture for study tests.

Tests in studies/<slug>/tests/test_*.py receive a `run` fixture that resolves
to a `Run` bound to the study's latest emitter row.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import yaml


class RunNotAvailableError(RuntimeError):
    """Raised when a study has no runs.db, no rows, or no requested run_id."""


class Run:
    """Wrapper around a single row in a study's runs.db."""

    def __init__(self, db_path: Path, run_id: str | None = None):
        db_path = Path(db_path)
        if not db_path.exists():
            raise RunNotAvailableError(f"runs.db not found at {db_path}")
        self._db_path = db_path
        self._db = sqlite3.connect(db_path)
        self._db.row_factory = sqlite3.Row
        self._run_id = run_id or self._latest_run_id()
        if self._run_id is None:
            raise RunNotAvailableError(f"runs.db at {db_path} contains no runs")
        self._meta = self._load_meta()

    def _latest_run_id(self) -> str | None:
        row = self._db.execute(
            "SELECT run_id FROM runs_meta ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["run_id"] if row else None

    def _load_meta(self) -> dict:
        row = self._db.execute(
            "SELECT * FROM runs_meta WHERE run_id = ?", (self._run_id,),
        ).fetchone()
        if row is None:
            raise RunNotAvailableError(f"run_id {self._run_id!r} not found")
        params = row["params"]
        return {
            "run_id": row["run_id"],
            "params": json.loads(params) if params else {},
            "seed": row["seed"],
            "status": row["status"],
            "n_steps": row["n_steps"] or 0,
            "variant": row["variant"],
            "composite": row["composite"],
            "timestamp": row["timestamp"],
        }

    # Metadata
    @property
    def run_id(self) -> str: return self._meta["run_id"]
    @property
    def params(self) -> dict: return self._meta["params"]
    @property
    def seed(self) -> int | None: return self._meta["seed"]
    @property
    def status(self) -> str: return self._meta["status"]
    @property
    def n_steps(self) -> int: return self._meta["n_steps"]
    @property
    def variant(self) -> str | None: return self._meta["variant"]
    @property
    def composite(self) -> str: return self._meta["composite"]

    # Trajectory
    def observable(self, name: str) -> np.ndarray:
        rows = self._db.execute(
            "SELECT step, value FROM history WHERE run_id = ? AND observable = ? ORDER BY step",
            (self._run_id, name),
        ).fetchall()
        return np.array([r["value"] for r in rows], dtype=float)

    @property
    def time(self) -> np.ndarray:
        rows = self._db.execute(
            "SELECT DISTINCT step FROM history WHERE run_id = ? ORDER BY step",
            (self._run_id,),
        ).fetchall()
        return np.array([r["step"] for r in rows], dtype=float)

    def final(self, name: str) -> float:
        arr = self.observable(name)
        if len(arr) == 0:
            raise KeyError(f"no values for observable {name!r}")
        return float(arr[-1])

    def initial(self, name: str) -> float:
        arr = self.observable(name)
        if len(arr) == 0:
            raise KeyError(f"no values for observable {name!r}")
        return float(arr[0])

    def cv(self, name: str) -> float:
        arr = self.observable(name)
        mean = float(arr.mean()) if len(arr) else 0.0
        return float(arr.std() / mean) if mean else float("nan")

    @property
    def trajectory(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT step, observable, value FROM history WHERE run_id = ?",
            self._db, params=(self._run_id,),
        ).pivot(index="step", columns="observable", values="value")


def _find_study_dir(test_file: Path) -> Path:
    """Walk up from a test file until study.yaml is found."""
    cur = test_file.resolve()
    if cur.is_file():
        cur = cur.parent
    for ancestor in [cur, *cur.parents]:
        if (ancestor / "study.yaml").is_file():
            return ancestor
    raise RunNotAvailableError(
        f"no study.yaml found walking up from {test_file}; "
        f"the `run` fixture must be invoked from inside a study directory"
    )


def _resolve_run(study_dir: Path, data_source: str) -> Run | list[Run]:
    db = study_dir / "runs.db"
    if data_source == "latest_run":
        return Run(db)
    if data_source == "first_run":
        run = Run(db)
        # override _run_id to the earliest
        row = run._db.execute(
            "SELECT run_id FROM runs_meta ORDER BY timestamp ASC LIMIT 1"
        ).fetchone()
        return Run(db, run_id=row["run_id"]) if row else run
    if data_source == "all_runs":
        # caller handles parametrization
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT run_id FROM runs_meta ORDER BY timestamp ASC").fetchall()
        conn.close()
        return [Run(db, run_id=r["run_id"]) for r in rows]
    raise ValueError(f"unknown data_source: {data_source!r}")


@pytest.fixture
def run(request) -> Run:
    """Latest run of the study under test. Reads study.yaml to discover
    `tests.data_source`; defaults to `latest_run`."""
    test_file = Path(str(request.fspath))
    study_dir = _find_study_dir(test_file)
    spec = yaml.safe_load((study_dir / "study.yaml").read_text()) or {}
    data_source = (spec.get("tests") or {}).get("data_source", "latest_run")
    if data_source == "all_runs":
        pytest.skip(
            "data_source: all_runs requires the test to use the parametrized "
            "`runs` fixture instead of `run`"
        )
    return _resolve_run(study_dir, data_source)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_run_fixture.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/testing/ tests/test_run_fixture.py
git commit -m "feat(testing): add Run wrapper + pytest `run` fixture for study tests"
```

---

### Task 4: Add `runs` parametrized fixture for `data_source: all_runs`

**Files:**
- Modify: `vivarium_dashboard/testing/run_fixture.py`
- Modify: `tests/test_run_fixture.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_run_fixture.py`:

```python
# Inline test of the `runs` fixture via subprocess pytest, since pytest's own
# fixture machinery is hard to invoke directly in a unit test.

import subprocess, sys, textwrap


def test_runs_fixture_parametrizes_over_all_runs(tmp_path):
    study = tmp_path / "studies" / "demo"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(
        "schema_version: 4\nname: demo\nbaseline: []\n"
        "tests: {auto_discover: true, data_source: all_runs, pytest_args: [], last_results: null}\n"
        "references: []\nimplementation_tasks: ''\n"
    )
    _make_runs_db(study / "runs.db", runs=[
        {"run_id": "a", "timestamp": "2026-05-14T00:00:00", "observables": {"x": [1.0]}},
        {"run_id": "b", "timestamp": "2026-05-15T00:00:00", "observables": {"x": [2.0]}},
    ])
    (study / "tests").mkdir()
    (study / "tests" / "conftest.py").write_text(
        "from vivarium_dashboard.testing import run, runs  # noqa: F401\n"
    )
    (study / "tests" / "test_demo.py").write_text(textwrap.dedent("""
        def test_each_run(runs):
            assert runs.final("x") in (1.0, 2.0)
    """))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(study / "tests"), "-v"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_run_fixture.py::test_runs_fixture_parametrizes_over_all_runs -v`
Expected: failure — `runs` fixture not defined.

- [ ] **Step 3: Add the parametrized `runs` fixture**

In `vivarium_dashboard/testing/run_fixture.py`, append:

```python
def _all_run_ids(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [r["run_id"] for r in conn.execute(
            "SELECT run_id FROM runs_meta ORDER BY timestamp ASC"
        ).fetchall()]
    finally:
        conn.close()


def pytest_generate_tests(metafunc):
    """Parametrize the `runs` fixture with one Run per row in runs.db
    when the study's data_source is `all_runs`."""
    if "runs" not in metafunc.fixturenames:
        return
    test_file = Path(str(metafunc.module.__file__))
    try:
        study_dir = _find_study_dir(test_file)
    except RunNotAvailableError:
        return
    spec = yaml.safe_load((study_dir / "study.yaml").read_text()) or {}
    if (spec.get("tests") or {}).get("data_source") != "all_runs":
        return
    db = study_dir / "runs.db"
    if not db.exists():
        return
    ids = _all_run_ids(db)
    metafunc.parametrize("runs", ids, ids=ids, indirect=True)


@pytest.fixture
def runs(request) -> Run:
    """Parametrized fixture: one Run per row in the study's runs.db.

    Activated when study.yaml has tests.data_source: all_runs. The
    `pytest_generate_tests` hook supplies the run_id parameter; this fixture
    converts it to a Run.
    """
    test_file = Path(str(request.fspath))
    study_dir = _find_study_dir(test_file)
    db = study_dir / "runs.db"
    return Run(db, run_id=request.param)
```

Update `vivarium_dashboard/testing/__init__.py`:
```python
from .run_fixture import Run, RunNotAvailableError, run, runs, pytest_generate_tests
__all__ = ["Run", "RunNotAvailableError", "run", "runs", "pytest_generate_tests"]
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_run_fixture.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/testing/ tests/test_run_fixture.py
git commit -m "feat(testing): parametrize `runs` fixture for data_source: all_runs"
```

---

## Phase C — Test runner endpoint

### Task 5: Implement `study_tests.py` runner

**Files:**
- Create: `vivarium_dashboard/lib/study_tests.py`
- Create: `tests/test_study_tests_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_study_tests_runner.py
"""Tests for the per-study pytest runner."""
import yaml
from pathlib import Path
from vivarium_dashboard.lib.study_tests import (
    run_study_tests, StudyTestsResult, StudyTestsConcurrentError,
)


def _make_study(workspace: Path, slug: str, *, test_body: str) -> Path:
    study = workspace / "studies" / slug
    (study / "tests").mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": slug, "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    (study / "tests" / "conftest.py").write_text(
        "from vivarium_dashboard.testing import run  # noqa: F401\n"
    )
    (study / "tests" / "test_demo.py").write_text(test_body)
    return study


def test_run_study_tests_no_tests_dir(tmp_path):
    study = tmp_path / "studies" / "demo"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "demo", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    result = run_study_tests(tmp_path, "demo")
    assert result.summary == {"passed": 0, "failed": 0, "skipped": 0, "duration_s": 0.0}
    assert result.tests == []
    assert result.note == "no tests directory"


def test_run_study_tests_collects_passing_test(tmp_path):
    _make_study(tmp_path, "demo", test_body="def test_one(): assert 1 == 1\n")
    result = run_study_tests(tmp_path, "demo")
    assert result.summary["passed"] == 1
    assert result.summary["failed"] == 0
    assert len(result.tests) == 1
    assert result.tests[0]["outcome"] == "passed"


def test_run_study_tests_collects_failing_test(tmp_path):
    _make_study(tmp_path, "demo", test_body="def test_fail(): assert 1 == 2\n")
    result = run_study_tests(tmp_path, "demo")
    assert result.summary["failed"] == 1
    assert result.tests[0]["outcome"] == "failed"
    assert "assert 1 == 2" in result.tests[0].get("message", "") or \
           "assert 1 == 2" in result.tests[0].get("traceback", "")


def test_run_study_tests_writes_last_results_to_yaml(tmp_path):
    _make_study(tmp_path, "demo", test_body="def test_one(): assert True\n")
    run_study_tests(tmp_path, "demo")
    spec = yaml.safe_load((tmp_path / "studies" / "demo" / "study.yaml").read_text())
    lr = spec["tests"]["last_results"]
    assert lr is not None
    assert lr["passed"] == 1
    assert "timestamp" in lr


def test_run_study_tests_concurrent_raises(tmp_path):
    import threading, time
    _make_study(tmp_path, "demo", test_body="import time\ndef test_slow(): time.sleep(0.5); assert True\n")
    results = []
    errors = []
    def worker():
        try:
            results.append(run_study_tests(tmp_path, "demo"))
        except StudyTestsConcurrentError as e:
            errors.append(e)
    t1 = threading.Thread(target=worker); t1.start()
    time.sleep(0.05)  # ensure t1 grabs the lock first
    t2 = threading.Thread(target=worker); t2.start()
    t1.join(); t2.join()
    assert len(results) == 1
    assert len(errors) == 1
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_study_tests_runner.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the runner**

```python
# vivarium_dashboard/lib/study_tests.py
"""Per-study pytest runner. Shells out to pytest with --json-report,
parses results, writes a compact summary into study.yaml.tests.last_results.
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml


class StudyTestsConcurrentError(RuntimeError):
    """Raised when a second test run is requested while one is already running."""


@dataclass
class StudyTestsResult:
    summary: dict        # {passed, failed, skipped, duration_s}
    tests: list[dict]    # [{nodeid, outcome, duration, message?, traceback?}]
    note: str | None = None
    raw_stderr: str = ""


def _study_paths(workspace: Path, slug: str) -> tuple[Path, Path, Path]:
    study_dir = Path(workspace) / "studies" / slug
    tests_dir = study_dir / "tests"
    spec_path = study_dir / "study.yaml"
    return study_dir, tests_dir, spec_path


@contextmanager
def _study_lock(workspace: Path, slug: str):
    lockdir = workspace / ".pbg" / "study-test-results"
    lockdir.mkdir(parents=True, exist_ok=True)
    lockfile = lockdir / f"{slug}.lock"
    if lockfile.exists():
        raise StudyTestsConcurrentError(f"tests already running for study {slug!r}")
    lockfile.write_text(str(os.getpid()))
    try:
        yield lockfile
    finally:
        try:
            lockfile.unlink()
        except FileNotFoundError:
            pass


def run_study_tests(workspace: Path, slug: str) -> StudyTestsResult:
    """Run pytest against studies/<slug>/tests/. Returns a StudyTestsResult.

    Writes a compact summary to study.yaml.tests.last_results.
    """
    workspace = Path(workspace)
    study_dir, tests_dir, spec_path = _study_paths(workspace, slug)
    if not spec_path.exists():
        raise FileNotFoundError(f"study not found: {spec_path}")

    spec = yaml.safe_load(spec_path.read_text()) or {}
    pytest_args = (spec.get("tests") or {}).get("pytest_args", []) or []

    if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
        result = StudyTestsResult(
            summary={"passed": 0, "failed": 0, "skipped": 0, "duration_s": 0.0},
            tests=[], note="no tests directory",
        )
        _write_last_results(spec_path, result)
        return result

    with _study_lock(workspace, slug):
        results_dir = workspace / ".pbg" / "study-test-results"
        results_dir.mkdir(parents=True, exist_ok=True)
        json_report = results_dir / f"{slug}.json"
        if json_report.exists():
            json_report.unlink()

        cmd = [
            sys.executable, "-m", "pytest", str(tests_dir),
            "--json-report", f"--json-report-file={json_report}",
            "-q", "--no-header", "--tb=short",
            *pytest_args,
        ]
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workspace))
        duration = time.time() - t0

        if not json_report.exists():
            # pytest crashed before writing the report
            result = StudyTestsResult(
                summary={"passed": 0, "failed": 0, "skipped": 0, "duration_s": duration},
                tests=[],
                note=f"pytest exited with code {proc.returncode}, no JSON report",
                raw_stderr=proc.stderr,
            )
            _write_last_results(spec_path, result)
            return result

        report = json.loads(json_report.read_text())
        tests = []
        for t in report.get("tests", []):
            entry = {
                "nodeid": t["nodeid"],
                "outcome": t["outcome"],
                "duration": t.get("duration", 0.0),
            }
            call = t.get("call") or {}
            if call.get("longrepr"):
                entry["traceback"] = call["longrepr"]
            if call.get("crash"):
                entry["message"] = call["crash"].get("message", "")
            tests.append(entry)
        summary = report.get("summary", {})
        result = StudyTestsResult(
            summary={
                "passed": summary.get("passed", 0),
                "failed": summary.get("failed", 0),
                "skipped": summary.get("skipped", 0),
                "duration_s": summary.get("duration", duration),
            },
            tests=tests,
        )
        _write_last_results(spec_path, result)
        return result


def _write_last_results(spec_path: Path, result: StudyTestsResult) -> None:
    spec = yaml.safe_load(spec_path.read_text()) or {}
    spec.setdefault("tests", {})
    spec["tests"]["last_results"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **result.summary,
    }
    tmp = spec_path.with_suffix(spec_path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(spec, sort_keys=False))
    os.replace(tmp, spec_path)
```

- [ ] **Step 4: Run, verify pass**

Run: `pip install pytest-json-report  # if not already` then `pytest tests/test_study_tests_runner.py -v`
Expected: 5 passed.

- [ ] **Step 5: Add `pytest-json-report` to pyproject.toml dev deps if missing**

Check `vivarium_dashboard/pyproject.toml` for `pytest-json-report`. If missing, add it under `[project.optional-dependencies] dev`.

- [ ] **Step 6: Commit**

```bash
git add vivarium_dashboard/lib/study_tests.py tests/test_study_tests_runner.py vivarium_dashboard/pyproject.toml
git commit -m "feat(tests): per-study pytest runner with last_results writeback + lock"
```

---

### Task 6: Wire `POST /api/study-tests-run` route

**Files:**
- Modify: `vivarium_dashboard/server.py`
- Create: `tests/test_study_tests_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_study_tests_endpoint.py
"""HTTP endpoint test for POST /api/study-tests-run."""
import json, yaml
from pathlib import Path
import pytest

# Reuse a server-test harness if one exists; otherwise call the handler
# directly. Many vivarium-dashboard tests already use a TestClient pattern —
# check tests/conftest.py and reuse.
from tests.conftest import dashboard_client  # adjust if differently named


def test_post_study_tests_run_returns_summary(tmp_path, dashboard_client):
    # Scaffold a workspace with a study that has one passing test.
    (tmp_path / "studies" / "demo" / "tests").mkdir(parents=True)
    (tmp_path / "studies" / "demo" / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "demo", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    (tmp_path / "studies" / "demo" / "tests" / "conftest.py").write_text("")
    (tmp_path / "studies" / "demo" / "tests" / "test_demo.py").write_text(
        "def test_one(): assert 1 + 1 == 2\n"
    )
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/study-tests-run", json={"study": "demo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["passed"] == 1
    assert body["summary"]["failed"] == 0
    assert body["tests"][0]["outcome"] == "passed"


def test_post_study_tests_run_writes_last_results(tmp_path, dashboard_client):
    (tmp_path / "studies" / "demo" / "tests").mkdir(parents=True)
    (tmp_path / "studies" / "demo" / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "demo", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    (tmp_path / "studies" / "demo" / "tests" / "test_demo.py").write_text(
        "def test_one(): assert True\n"
    )
    client = dashboard_client(workspace=tmp_path)
    client.post("/api/study-tests-run", json={"study": "demo"})
    spec = yaml.safe_load((tmp_path / "studies" / "demo" / "study.yaml").read_text())
    assert spec["tests"]["last_results"]["passed"] == 1


def test_post_study_tests_run_missing_study_returns_404(tmp_path, dashboard_client):
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/study-tests-run", json={"study": "nonexistent"})
    assert resp.status_code == 404
```

> **NOTE:** vivarium-dashboard's test harness pattern varies — inspect `tests/conftest.py` first. If there's no `dashboard_client` fixture, follow whatever pattern existing endpoint tests use (look at any existing `test_*endpoint*.py` or `test_server*.py` files for the pattern).

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_study_tests_endpoint.py -v`
Expected: 404 (route not wired yet) or ImportError.

- [ ] **Step 3: Add the route handler**

In `vivarium_dashboard/server.py`:

(a) Find the `do_POST` dispatcher (search for the existing `if self.path.startswith("/api/investigation-create")` pattern). Add a new dispatch entry:

```python
        if self.path == "/api/study-tests-run":
            return self._post_study_tests_run()
```

(b) Add the handler method near the other study/investigation handlers (insertion point: after the existing `_post_investigation_create` method, ~line 4448):

```python
    def _post_study_tests_run(self):
        """POST /api/study-tests-run {study} — run pytest against
        studies/<study>/tests/. Returns {summary, tests, note?}.
        """
        from .lib.study_tests import run_study_tests, StudyTestsConcurrentError
        body = self._read_json_body()
        slug = (body or {}).get("study")
        if not slug:
            return self._send_json(400, {"error": "missing 'study' in body"})
        spec_path = self._workspace / "studies" / slug / "study.yaml"
        if not spec_path.exists():
            return self._send_json(404, {"error": f"study not found: {slug}"})
        try:
            result = run_study_tests(self._workspace, slug)
        except StudyTestsConcurrentError as e:
            return self._send_json(409, {"error": str(e)})
        return self._send_json(200, {
            "summary": result.summary,
            "tests": result.tests,
            "note": result.note,
        })
```

> Replace `self._workspace`, `self._read_json_body`, `self._send_json` with whatever the actual helper names are in this codebase — grep for an existing POST handler to confirm.

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_study_tests_endpoint.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/server.py tests/test_study_tests_endpoint.py
git commit -m "feat(server): POST /api/study-tests-run endpoint"
```

---

## Phase D — Investigation plan validator + IO

### Task 7: Define `investigation_plans.py` with `load_plan` + validator

**Files:**
- Create: `vivarium_dashboard/lib/investigation_plans.py`
- Create: `tests/test_investigation_plans.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_investigation_plans.py
"""Tests for investigation_plans: load_plan, validators, status derivation."""
import yaml
from pathlib import Path
import pytest
from vivarium_dashboard.lib.investigation_plans import (
    load_plan, save_plan, InvestigationPlanError, derive_study_status,
)


def _write_plan(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_load_plan_minimal(tmp_path):
    p = tmp_path / "investigations" / "demo" / "investigation.yaml"
    _write_plan(p, {
        "schema_version": 1, "name": "demo",
        "studies": [{"study": "s1"}],
    })
    plan = load_plan(p)
    assert plan["name"] == "demo"
    assert plan["studies"][0]["study"] == "s1"


def test_load_plan_rejects_missing_schema_version(tmp_path):
    p = tmp_path / "investigations" / "demo" / "investigation.yaml"
    _write_plan(p, {"name": "demo", "studies": []})
    with pytest.raises(InvestigationPlanError, match="schema_version"):
        load_plan(p)


def test_load_plan_rejects_unknown_gate(tmp_path):
    p = tmp_path / "investigations" / "demo" / "investigation.yaml"
    _write_plan(p, {
        "schema_version": 1, "name": "demo",
        "studies": [{"study": "s1", "gate": "bogus"}],
    })
    with pytest.raises(InvestigationPlanError, match="gate"):
        load_plan(p)


def test_load_plan_rejects_duplicate_study(tmp_path):
    p = tmp_path / "investigations" / "demo" / "investigation.yaml"
    _write_plan(p, {
        "schema_version": 1, "name": "demo",
        "studies": [{"study": "s1"}, {"study": "s1"}],
    })
    with pytest.raises(InvestigationPlanError, match="duplicate"):
        load_plan(p)


def test_save_plan_atomic(tmp_path):
    p = tmp_path / "investigations" / "demo" / "investigation.yaml"
    _write_plan(p, {"schema_version": 1, "name": "demo", "studies": [{"study": "s1"}]})
    plan = load_plan(p)
    plan["objective"] = "new objective"
    save_plan(p, plan)
    assert "new objective" in p.read_text()


def test_derive_study_status_planned_when_no_evidence(tmp_path):
    # study.yaml exists with no last_results and no runs.db → planned
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "s1", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    status = derive_study_status(tmp_path, "s1", prev_satisfied_gate=True)
    assert status == "planned"


def test_derive_study_status_complete_when_tests_pass_and_run_exists(tmp_path):
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "s1", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [],
                  "last_results": {"passed": 3, "failed": 0, "skipped": 0, "duration_s": 0.1, "timestamp": "2026-05-15T18:42:00Z"}},
        "references": [], "implementation_tasks": "",
    }))
    # Fake a runs.db with at least one row
    import sqlite3
    conn = sqlite3.connect(study_dir / "runs.db")
    conn.execute("CREATE TABLE runs_meta (run_id TEXT)")
    conn.execute("INSERT INTO runs_meta VALUES ('r1')")
    conn.commit(); conn.close()
    status = derive_study_status(tmp_path, "s1", prev_satisfied_gate=True)
    assert status == "complete"


def test_derive_study_status_blocked_when_prev_gate_unsatisfied(tmp_path):
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "s1", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))
    status = derive_study_status(tmp_path, "s1", prev_satisfied_gate=False)
    assert status == "blocked"


def test_derive_study_status_in_progress_when_runs_but_tests_failing(tmp_path):
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "s1", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [],
                  "last_results": {"passed": 1, "failed": 2, "skipped": 0, "duration_s": 0.1, "timestamp": "2026-05-15T18:42:00Z"}},
        "references": [], "implementation_tasks": "",
    }))
    import sqlite3
    conn = sqlite3.connect(study_dir / "runs.db")
    conn.execute("CREATE TABLE runs_meta (run_id TEXT)")
    conn.execute("INSERT INTO runs_meta VALUES ('r1')")
    conn.commit(); conn.close()
    status = derive_study_status(tmp_path, "s1", prev_satisfied_gate=True)
    assert status == "in-progress"


def test_derive_study_status_zero_tests_cannot_satisfy_gate(tmp_path):
    # last_results.passed == 0 AND last_results.failed == 0 AND last_results.skipped == 0
    # → cannot be "complete" even if a run exists.
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": "s1", "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [],
                  "last_results": {"passed": 0, "failed": 0, "skipped": 0, "duration_s": 0.0, "timestamp": "x"}},
        "references": [], "implementation_tasks": "",
    }))
    import sqlite3
    conn = sqlite3.connect(study_dir / "runs.db")
    conn.execute("CREATE TABLE runs_meta (run_id TEXT)")
    conn.execute("INSERT INTO runs_meta VALUES ('r1')")
    conn.commit(); conn.close()
    status = derive_study_status(tmp_path, "s1", prev_satisfied_gate=True)
    assert status == "in-progress"  # has runs, no tests → not complete
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_investigation_plans.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the module**

```python
# vivarium_dashboard/lib/investigation_plans.py
"""Investigation-as-plan: an ordered chain of Studies forming a research plan.

On-disk: ``investigations/<slug>/investigation.yaml`` (schema_version: 1).
API prefix: ``/api/plan*`` (the name "Investigation" is overloaded with the
legacy Study endpoints; the new endpoints use "plan" to disambiguate).
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
import yaml


class InvestigationPlanError(ValueError):
    """Raised on structural problems in investigation.yaml."""


_VALID_GATES = {None, "tests-pass"}
_VALID_STATUS_OVERRIDES = {None, "planned", "in-progress", "blocked", "complete"}


def load_plan(path: Path) -> dict:
    """Parse + validate investigations/<slug>/investigation.yaml."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise InvestigationPlanError(f"malformed YAML: {e}") from e
    _validate_plan(data)
    return data


def save_plan(path: Path, data: dict) -> None:
    _validate_plan(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    os.replace(tmp, path)


def _validate_plan(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvestigationPlanError("plan must be a YAML mapping")
    if data.get("schema_version") != 1:
        raise InvestigationPlanError("schema_version must be 1")
    if not data.get("name"):
        raise InvestigationPlanError("missing required field: name")
    studies = data.get("studies", [])
    if not isinstance(studies, list):
        raise InvestigationPlanError("studies must be a list")
    seen = set()
    for i, entry in enumerate(studies):
        if not isinstance(entry, dict) or not entry.get("study"):
            raise InvestigationPlanError(f"studies[{i}] must be a mapping with a 'study' key")
        slug = entry["study"]
        if slug in seen:
            raise InvestigationPlanError(f"studies[{i}] duplicate study slug: {slug}")
        seen.add(slug)
        gate = entry.get("gate")
        if gate not in _VALID_GATES:
            raise InvestigationPlanError(f"studies[{i}].gate must be one of {_VALID_GATES}, got {gate!r}")
        ov = entry.get("status_override")
        if ov not in _VALID_STATUS_OVERRIDES:
            raise InvestigationPlanError(
                f"studies[{i}].status_override must be one of {_VALID_STATUS_OVERRIDES}, got {ov!r}"
            )
    refs = data.get("references", [])
    if not isinstance(refs, list):
        raise InvestigationPlanError("references must be a list")


def derive_study_status(workspace: Path, slug: str, *, prev_satisfied_gate: bool) -> str:
    """Compute the live status of a study in an investigation plan.

    Inputs:
    - workspace: workspace root.
    - slug: study slug under workspace/studies/.
    - prev_satisfied_gate: whether the previous gate-required study has satisfied
      its gate (or there was no previous gate). False ⇒ this entry is blocked.

    Returns one of: ``planned`` | ``in-progress`` | ``blocked`` | ``complete``.
    """
    if not prev_satisfied_gate:
        return "blocked"
    spec_path = workspace / "studies" / slug / "study.yaml"
    if not spec_path.exists():
        return "blocked"  # missing study
    spec = yaml.safe_load(spec_path.read_text()) or {}
    lr = (spec.get("tests") or {}).get("last_results") or None
    runs_db = workspace / "studies" / slug / "runs.db"
    has_run = runs_db.exists() and _runs_count(runs_db) > 0

    tests_pass = bool(lr) and lr.get("failed", 0) == 0 and (lr.get("passed", 0) > 0)
    if tests_pass and has_run:
        return "complete"
    if has_run or (lr is not None):
        return "in-progress"
    return "planned"


def _runs_count(db: Path) -> int:
    try:
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT COUNT(*) FROM runs_meta").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def gate_satisfied(workspace: Path, entry: dict) -> bool:
    """Whether this entry's gate is satisfied. For ``gate: tests-pass``,
    requires complete status; for no gate, always True."""
    if entry.get("gate") != "tests-pass":
        return True
    status = derive_study_status(workspace, entry["study"], prev_satisfied_gate=True)
    return status == "complete"


def list_plans(workspace: Path) -> list[dict]:
    """Return a summary list of all investigations/<slug>/investigation.yaml."""
    inv_dir = Path(workspace) / "investigations"
    if not inv_dir.is_dir():
        return []
    out = []
    for slug_dir in sorted(inv_dir.iterdir()):
        plan_path = slug_dir / "investigation.yaml"
        if not plan_path.exists():
            continue
        try:
            plan = load_plan(plan_path)
        except InvestigationPlanError:
            continue
        out.append({
            "slug": slug_dir.name,
            "name": plan.get("name", slug_dir.name),
            "objective": plan.get("objective", ""),
            "status": plan.get("status", "planned"),
            "n_studies": len(plan.get("studies", [])),
        })
    return out


def get_plan_detail(workspace: Path, slug: str) -> dict | None:
    """Return a plan with per-study derived status and gate-satisfaction info."""
    plan_path = Path(workspace) / "investigations" / slug / "investigation.yaml"
    if not plan_path.exists():
        return None
    plan = load_plan(plan_path)

    prev_satisfied = True
    enriched_studies = []
    for entry in plan.get("studies", []):
        if entry.get("status_override"):
            status = entry["status_override"]
        else:
            status = derive_study_status(workspace, entry["study"], prev_satisfied_gate=prev_satisfied)
        enriched = dict(entry)
        enriched["derived_status"] = status
        enriched_studies.append(enriched)
        # Update gate state for the NEXT entry.
        if entry.get("gate") == "tests-pass":
            prev_satisfied = (status == "complete")
        # Without a gate, the next entry is not blocked by this one.
        # prev_satisfied stays True.

    plan["studies"] = enriched_studies
    return plan
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_investigation_plans.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/lib/investigation_plans.py tests/test_investigation_plans.py
git commit -m "feat(plans): investigation-as-plan validator + IO + status derivation"
```

---

## Phase E — Investigation plan endpoints

### Task 8: List + detail endpoints

**Files:**
- Modify: `vivarium_dashboard/server.py`
- Create: `tests/test_plan_endpoints.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_endpoints.py
"""HTTP endpoint tests for the investigation-plan family."""
import json, yaml
from pathlib import Path
import pytest
from tests.conftest import dashboard_client  # adjust if differently named


def _scaffold_plan(ws: Path, slug: str, *, studies: list[dict], **kwargs) -> None:
    p = ws / "investigations" / slug / "investigation.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "name": slug, "studies": studies, **kwargs}
    p.write_text(yaml.safe_dump(data, sort_keys=False))


def _scaffold_study(ws: Path, slug: str) -> None:
    d = ws / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4, "name": slug, "baseline": [],
        "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
        "references": [], "implementation_tasks": "",
    }))


def test_get_plans_list(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "a", studies=[{"study": "s1"}])
    _scaffold_plan(tmp_path, "b", studies=[{"study": "s1"}, {"study": "s2"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.get("/api/plans")
    assert resp.status_code == 200
    plans = resp.json()
    slugs = sorted(p["slug"] for p in plans)
    assert slugs == ["a", "b"]


def test_get_plan_detail_returns_derived_statuses(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[
        {"study": "s1", "gate": "tests-pass"},
        {"study": "s2"},
    ])
    _scaffold_study(tmp_path, "s1")
    _scaffold_study(tmp_path, "s2")
    client = dashboard_client(workspace=tmp_path)
    resp = client.get("/api/plan/demo")
    assert resp.status_code == 200
    plan = resp.json()
    statuses = [s["derived_status"] for s in plan["studies"]]
    # s1 has no run + no last_results → planned
    # s2 is blocked because s1's gate is not satisfied
    assert statuses == ["planned", "blocked"]


def test_get_plan_detail_404(tmp_path, dashboard_client):
    client = dashboard_client(workspace=tmp_path)
    resp = client.get("/api/plan/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 404 / route not wired.

- [ ] **Step 3: Add the list + detail routes**

In `vivarium_dashboard/server.py`:

(a) In the GET dispatcher, add:
```python
        if self.path == "/api/plans":
            return self._get_plans_list()
        if self.path.startswith("/api/plan/"):
            return self._get_plan_detail(self.path.removeprefix("/api/plan/"))
```

(b) Handlers:
```python
    def _get_plans_list(self):
        from .lib.investigation_plans import list_plans
        return self._send_json(200, list_plans(self._workspace))

    def _get_plan_detail(self, slug: str):
        from .lib.investigation_plans import get_plan_detail
        plan = get_plan_detail(self._workspace, slug)
        if plan is None:
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        return self._send_json(200, plan)
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/server.py tests/test_plan_endpoints.py
git commit -m "feat(server): GET /api/plans + GET /api/plan/<slug>"
```

---

### Task 9: Create + delete + set-meta endpoints

**Files:**
- Modify: `vivarium_dashboard/server.py`
- Modify: `tests/test_plan_endpoints.py`

- [ ] **Step 1: Append failing tests**

```python
def test_post_plan_create(tmp_path, dashboard_client):
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-create", json={
        "name": "dnaA-replication",
        "objective": "build DnaA cycle",
        "studies": [{"study": "s1"}, {"study": "s2", "gate": "tests-pass"}],
    })
    assert resp.status_code == 201
    p = tmp_path / "investigations" / "dnaA-replication" / "investigation.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text())
    assert data["objective"] == "build DnaA cycle"
    assert data["studies"][1]["gate"] == "tests-pass"


def test_post_plan_create_rejects_duplicate(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-create", json={"name": "demo", "studies": []})
    assert resp.status_code == 409


def test_delete_plan(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.delete("/api/plan", json={"slug": "demo"})
    assert resp.status_code == 200
    assert not (tmp_path / "investigations" / "demo").exists()


def test_post_plan_set_meta(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-set-meta", json={
        "slug": "demo", "objective": "new obj", "hypothesis": "h", "status": "in-progress",
    })
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert data["objective"] == "new obj"
    assert data["hypothesis"] == "h"
    assert data["status"] == "in-progress"
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: new tests fail.

- [ ] **Step 3: Implement the routes**

In `server.py` POST dispatcher:
```python
        if self.path == "/api/plan-create":
            return self._post_plan_create()
        if self.path == "/api/plan-set-meta":
            return self._post_plan_set_meta()
```

In DELETE dispatcher (find the existing pattern for `/api/investigation` DELETE; replicate):
```python
        if self.path == "/api/plan":
            return self._delete_plan()
```

Handlers:
```python
    def _post_plan_create(self):
        from .lib.investigation_plans import save_plan, InvestigationPlanError
        body = self._read_json_body() or {}
        name = body.get("name")
        if not name:
            return self._send_json(400, {"error": "missing 'name'"})
        slug = name  # simple convention; UI can later derive separately
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if p.exists():
            return self._send_json(409, {"error": f"plan already exists: {slug}"})
        data = {
            "schema_version": 1,
            "name": name,
            "objective": body.get("objective", ""),
            "hypothesis": body.get("hypothesis", ""),
            "status": body.get("status", "planned"),
            "references": body.get("references", []),
            "studies": body.get("studies", []),
        }
        try:
            save_plan(p, data)
        except InvestigationPlanError as e:
            return self._send_json(400, {"error": str(e)})
        return self._send_json(201, {"slug": slug})

    def _post_plan_set_meta(self):
        from .lib.investigation_plans import load_plan, save_plan, InvestigationPlanError
        body = self._read_json_body() or {}
        slug = body.get("slug")
        if not slug:
            return self._send_json(400, {"error": "missing 'slug'"})
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if not p.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        data = load_plan(p)
        for k in ("objective", "hypothesis", "status"):
            if k in body:
                data[k] = body[k]
        try:
            save_plan(p, data)
        except InvestigationPlanError as e:
            return self._send_json(400, {"error": str(e)})
        return self._send_json(200, {"ok": True})

    def _delete_plan(self):
        import shutil
        body = self._read_json_body() or {}
        slug = body.get("slug")
        if not slug:
            return self._send_json(400, {"error": "missing 'slug'"})
        plan_dir = self._workspace / "investigations" / slug
        if not plan_dir.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        shutil.rmtree(plan_dir)
        return self._send_json(200, {"ok": True})
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/server.py tests/test_plan_endpoints.py
git commit -m "feat(server): POST /api/plan-create + plan-set-meta + DELETE /api/plan"
```

---

### Task 10: Study-list management endpoints (add / remove / set-status)

**Files:**
- Modify: `vivarium_dashboard/server.py`
- Modify: `tests/test_plan_endpoints.py`

- [ ] **Step 1: Append failing tests**

```python
def test_post_plan_study_add_appends(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-study-add", json={
        "slug": "demo", "study": "s2", "gate": "tests-pass",
    })
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert [s["study"] for s in data["studies"]] == ["s1", "s2"]
    assert data["studies"][1]["gate"] == "tests-pass"


def test_post_plan_study_add_inserts_at_position(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}, {"study": "s3"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-study-add", json={
        "slug": "demo", "study": "s2", "position": 1,
    })
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert [s["study"] for s in data["studies"]] == ["s1", "s2", "s3"]


def test_post_plan_study_add_rejects_duplicate(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-study-add", json={"slug": "demo", "study": "s1"})
    assert resp.status_code == 400


def test_post_plan_study_remove(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}, {"study": "s2"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-study-remove", json={"slug": "demo", "study": "s2"})
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert [s["study"] for s in data["studies"]] == ["s1"]


def test_post_plan_study_set_status_writes_override(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-study-set-status", json={
        "slug": "demo", "study": "s1", "status": "complete",
    })
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert data["studies"][0]["status_override"] == "complete"
```

- [ ] **Step 2: Verify failures**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 5 new tests fail.

- [ ] **Step 3: Implement the routes**

In POST dispatcher:
```python
        if self.path == "/api/plan-study-add":
            return self._post_plan_study_add()
        if self.path == "/api/plan-study-remove":
            return self._post_plan_study_remove()
        if self.path == "/api/plan-study-set-status":
            return self._post_plan_study_set_status()
```

Handlers:
```python
    def _post_plan_study_add(self):
        from .lib.investigation_plans import load_plan, save_plan, InvestigationPlanError
        body = self._read_json_body() or {}
        slug = body.get("slug"); study = body.get("study")
        if not slug or not study:
            return self._send_json(400, {"error": "missing 'slug' or 'study'"})
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if not p.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        data = load_plan(p)
        if any(s.get("study") == study for s in data.get("studies", [])):
            return self._send_json(400, {"error": f"study {study!r} already in plan"})
        entry = {"study": study}
        if body.get("gate"):
            entry["gate"] = body["gate"]
        pos = body.get("position")
        if pos is None:
            data["studies"].append(entry)
        else:
            data["studies"].insert(int(pos), entry)
        try:
            save_plan(p, data)
        except InvestigationPlanError as e:
            return self._send_json(400, {"error": str(e)})
        return self._send_json(200, {"ok": True})

    def _post_plan_study_remove(self):
        from .lib.investigation_plans import load_plan, save_plan
        body = self._read_json_body() or {}
        slug = body.get("slug"); study = body.get("study")
        if not slug or not study:
            return self._send_json(400, {"error": "missing 'slug' or 'study'"})
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if not p.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        data = load_plan(p)
        data["studies"] = [s for s in data.get("studies", []) if s.get("study") != study]
        save_plan(p, data)
        return self._send_json(200, {"ok": True})

    def _post_plan_study_set_status(self):
        from .lib.investigation_plans import load_plan, save_plan
        body = self._read_json_body() or {}
        slug = body.get("slug"); study = body.get("study"); status = body.get("status")
        if not slug or not study:
            return self._send_json(400, {"error": "missing 'slug' or 'study'"})
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if not p.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        data = load_plan(p)
        for s in data.get("studies", []):
            if s.get("study") == study:
                if status is None:
                    s.pop("status_override", None)
                else:
                    s["status_override"] = status
                break
        else:
            return self._send_json(404, {"error": f"study {study!r} not in plan"})
        save_plan(p, data)
        return self._send_json(200, {"ok": True})
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add vivarium_dashboard/server.py tests/test_plan_endpoints.py
git commit -m "feat(server): plan-study-add + remove + set-status endpoints"
```

---

### Task 11: Reference-add endpoint

**Files:**
- Modify: `vivarium_dashboard/server.py`
- Modify: `tests/test_plan_endpoints.py`

- [ ] **Step 1: Append failing test**

```python
def test_post_plan_reference_add(tmp_path, dashboard_client):
    _scaffold_plan(tmp_path, "demo", studies=[{"study": "s1"}])
    client = dashboard_client(workspace=tmp_path)
    resp = client.post("/api/plan-reference-add", json={
        "slug": "demo", "file": "docs/references/molecular.md", "label": "Molecular reference",
    })
    assert resp.status_code == 200
    data = yaml.safe_load((tmp_path / "investigations" / "demo" / "investigation.yaml").read_text())
    assert data["references"][0]["file"] == "docs/references/molecular.md"
    assert data["references"][0]["label"] == "Molecular reference"
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: new test fails.

- [ ] **Step 3: Implement**

In POST dispatcher:
```python
        if self.path == "/api/plan-reference-add":
            return self._post_plan_reference_add()
```

```python
    def _post_plan_reference_add(self):
        from .lib.investigation_plans import load_plan, save_plan
        body = self._read_json_body() or {}
        slug = body.get("slug"); ref_file = body.get("file")
        if not slug or not ref_file:
            return self._send_json(400, {"error": "missing 'slug' or 'file'"})
        p = self._workspace / "investigations" / slug / "investigation.yaml"
        if not p.exists():
            return self._send_json(404, {"error": f"plan not found: {slug}"})
        data = load_plan(p)
        data.setdefault("references", []).append({
            "file": ref_file,
            **({"label": body["label"]} if body.get("label") else {}),
        })
        save_plan(p, data)
        return self._send_json(200, {"ok": True})
```

- [ ] **Step 4: Verify pass + commit**

Run: `pytest tests/test_plan_endpoints.py -v`
Expected: 13 passed.

```bash
git add vivarium_dashboard/server.py tests/test_plan_endpoints.py
git commit -m "feat(server): plan-reference-add endpoint"
```

---

## Phase F — Dashboard UI: Tests tab on Study detail

### Task 12: Add Tests tab markup to study-detail.html

**Files:**
- Modify: `vivarium_dashboard/templates/study-detail.html`

- [ ] **Step 1: Read current template**

Run: `cat vivarium_dashboard/templates/study-detail.html | head -60`
Identify the tab nav (`<nav class="tabs">` or similar) and the tab panel area.

- [ ] **Step 2: Add the Tests tab**

In the tab nav, add:
```html
<button class="tab-button" data-tab="tests">Tests</button>
```

Below the existing tab panels, add:
```html
<div class="tab-panel" data-tab="tests" hidden>
  <div class="tests-header">
    <h3>Behavioral Tests</h3>
    <div class="tests-summary" id="tests-summary">— no test results yet —</div>
    <button id="run-tests-btn" class="btn-primary">Run tests</button>
  </div>
  <div class="tests-config">
    <span class="badge">auto_discover: <code id="tests-auto-discover">true</code></span>
    <span class="badge">data_source: <code id="tests-data-source">latest_run</code></span>
  </div>
  <ul class="tests-list" id="tests-list">
    <li class="placeholder">Click "Run tests" to discover and execute studies/&lt;slug&gt;/tests/test_*.py</li>
  </ul>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add vivarium_dashboard/templates/study-detail.html
git commit -m "feat(ui): add Tests tab markup to study-detail template"
```

---

### Task 13: Wire Tests tab JS

**Files:**
- Modify: `vivarium_dashboard/static/study-detail.js`

- [ ] **Step 1: Read current file to find tab-switching pattern**

Search the file for how tab buttons are handled today; follow the same pattern.

- [ ] **Step 2: Add Tests tab population + run logic**

Append:
```javascript
async function loadTestsTab(studySlug, spec) {
  // Pull config from spec.tests
  const cfg = (spec && spec.tests) || {};
  document.getElementById('tests-auto-discover').textContent = String(cfg.auto_discover ?? true);
  document.getElementById('tests-data-source').textContent = cfg.data_source || 'latest_run';
  const lr = cfg.last_results;
  const summary = document.getElementById('tests-summary');
  if (lr) {
    summary.innerHTML = `
      <span class="ok">${lr.passed} passed</span>
      / <span class="fail">${lr.failed} failed</span>
      / <span class="skip">${lr.skipped} skipped</span>
      <span class="muted">(${(lr.duration_s || 0).toFixed(2)}s, ${lr.timestamp || ''})</span>`;
  } else {
    summary.textContent = '— no test results yet —';
  }
}

async function runStudyTests(studySlug) {
  const btn = document.getElementById('run-tests-btn');
  btn.disabled = true; btn.textContent = 'Running…';
  try {
    const resp = await fetch('/api/study-tests-run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({study: studySlug}),
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert(`Test run failed: ${err.error || resp.status}`);
      return;
    }
    const body = await resp.json();
    renderTestResults(body);
  } finally {
    btn.disabled = false; btn.textContent = 'Run tests';
  }
}

function renderTestResults(body) {
  const list = document.getElementById('tests-list');
  list.innerHTML = '';
  if (body.note === 'no tests directory') {
    list.innerHTML = '<li class="placeholder">No tests/ directory found in this study.</li>';
    return;
  }
  for (const t of body.tests || []) {
    const li = document.createElement('li');
    li.className = `test-row test-${t.outcome}`;
    const icon = {passed: '✅', failed: '❌', skipped: '⏭'}[t.outcome] || '•';
    li.innerHTML = `
      <span class="test-icon">${icon}</span>
      <code class="test-nodeid">${t.nodeid}</code>
      <span class="test-duration">${(t.duration || 0).toFixed(3)}s</span>
      ${t.traceback ? `<details><summary>traceback</summary><pre>${escapeHtml(t.traceback)}</pre></details>` : ''}
    `;
    list.appendChild(li);
  }
  const s = body.summary || {};
  document.getElementById('tests-summary').innerHTML = `
    <span class="ok">${s.passed} passed</span>
    / <span class="fail">${s.failed} failed</span>
    / <span class="skip">${s.skipped} skipped</span>
    <span class="muted">(${(s.duration_s || 0).toFixed(2)}s)</span>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Wire the Run button — call from study-detail initialization (where the
// existing study slug is known).
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('run-tests-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      const slug = window.__currentStudySlug; // set by existing study-detail bootstrap
      if (slug) runStudyTests(slug);
    });
  }
});
```

- [ ] **Step 3: Hook `loadTestsTab` into the existing tab-switch logic**

Find where the study spec is loaded (e.g., `loadStudyDetail`); call `loadTestsTab(slug, spec)` when the Tests tab is activated.

- [ ] **Step 4: Add CSS to style.css**

```css
/* Tests tab */
.tests-header { display: flex; align-items: center; gap: 1rem; }
.tests-summary { flex: 1; }
.tests-summary .ok { color: #228B22; }
.tests-summary .fail { color: #B22222; }
.tests-summary .skip { color: #888; }
.tests-summary .muted { color: #888; font-size: 0.9em; }
.tests-config { margin: 0.5rem 0; display: flex; gap: 1rem; }
.tests-config .badge { background: #f0f0f0; padding: 0.2rem 0.5rem; border-radius: 4px; }
.tests-list { list-style: none; padding: 0; }
.test-row { padding: 0.4rem 0.6rem; margin: 0.2rem 0; border-radius: 4px; background: #fafafa; display: flex; gap: 0.6rem; align-items: center; }
.test-row.test-passed { border-left: 3px solid #228B22; }
.test-row.test-failed { border-left: 3px solid #B22222; }
.test-row.test-skipped { border-left: 3px solid #888; opacity: 0.7; }
.test-icon { font-size: 1.1em; }
.test-nodeid { flex: 1; font-family: monospace; font-size: 0.9em; }
.test-duration { color: #666; font-size: 0.85em; }
.test-row details pre { background: #fff; padding: 0.6rem; border: 1px solid #ddd; border-radius: 4px; max-height: 200px; overflow: auto; }
```

- [ ] **Step 5: Manual verification**

Start the dashboard, open any study, click the Tests tab, click "Run tests". Verify:
- If the study has no tests/ dir, the placeholder message appears.
- If a test file with one passing test exists, the row shows green.
- The summary updates.

- [ ] **Step 6: Commit**

```bash
git add vivarium_dashboard/static/study-detail.js vivarium_dashboard/static/style.css
git commit -m "feat(ui): Tests tab — run pytest from the dashboard, render results"
```

---

## Phase G — Dashboard UI: Investigations top-level tab

### Task 14: Add Investigations section to index template

**Files:**
- Modify: `vivarium_dashboard/templates/index.html.j2`

- [ ] **Step 1: Read the existing nav + section structure**

Identify the menu pattern (e.g., `<nav class="main-nav">…<a data-section="page-studies">Studies</a>…</nav>`) and the section pattern.

- [ ] **Step 2: Add the Investigations menu link**

In the main nav, add:
```html
<a class="menu-link" data-section="page-investigations" href="#investigations">Investigations</a>
```

Position: next to "Studies" (Investigations conceptually contains Studies).

- [ ] **Step 3: Add the Investigations section**

```html
<section id="page-investigations" class="page" hidden>
  <div class="page-header">
    <h2>Investigations</h2>
    <button id="new-investigation-btn" class="btn-primary">+ New investigation</button>
  </div>

  <ul id="investigations-list" class="investigation-list"></ul>

  <div id="investigation-detail" hidden>
    <button id="investigation-back" class="btn-text">← Investigations</button>
    <h3 id="investigation-title"></h3>
    <p class="muted" id="investigation-status"></p>
    <section class="meta">
      <h4>Objective</h4>
      <p id="investigation-objective"></p>
      <h4>Hypothesis</h4>
      <p id="investigation-hypothesis"></p>
      <h4>References</h4>
      <ul id="investigation-references"></ul>
    </section>
    <section class="study-cards">
      <h4>Studies (sequential)</h4>
      <ol id="investigation-study-cards"></ol>
    </section>
  </div>
</section>

<dialog id="new-investigation-dialog">
  <form method="dialog">
    <h3>New investigation</h3>
    <label>Name: <input type="text" id="new-inv-name" required></label><br>
    <label>Objective:<br><textarea id="new-inv-objective" rows="3"></textarea></label><br>
    <label>Hypothesis:<br><textarea id="new-inv-hypothesis" rows="3"></textarea></label><br>
    <label>Studies (comma-separated slugs):<br><input type="text" id="new-inv-studies"></label><br>
    <menu>
      <button value="cancel">Cancel</button>
      <button id="new-inv-submit" value="create">Create</button>
    </menu>
  </form>
</dialog>
```

- [ ] **Step 4: Commit**

```bash
git add vivarium_dashboard/templates/index.html.j2
git commit -m "feat(ui): add Investigations section markup + new-investigation dialog"
```

---

### Task 15: Investigations JS (list + detail render + create)

**Files:**
- Create: `vivarium_dashboard/static/investigations.js`
- Modify: `vivarium_dashboard/templates/index.html.j2` (script include)

- [ ] **Step 1: Write the JS module**

```javascript
// vivarium_dashboard/static/investigations.js
(function () {
  const state = { plans: [], activeSlug: null };

  async function loadInvestigations() {
    const resp = await fetch('/api/plans');
    state.plans = await resp.json();
    renderList();
  }

  function renderList() {
    const ul = document.getElementById('investigations-list');
    ul.innerHTML = '';
    if (!state.plans.length) {
      ul.innerHTML = '<li class="placeholder">No investigations yet. Click "+ New investigation" to start one.</li>';
      return;
    }
    for (const p of state.plans) {
      const li = document.createElement('li');
      li.className = 'investigation-card';
      li.innerHTML = `
        <a class="investigation-title">${escapeHtml(p.name)}</a>
        <span class="badge status-${p.status}">${p.status}</span>
        <span class="muted">${p.n_studies} studies</span>
        <p class="muted">${escapeHtml((p.objective || '').slice(0, 200))}</p>
      `;
      li.querySelector('.investigation-title').addEventListener('click', () => openInvestigation(p.slug));
      ul.appendChild(li);
    }
  }

  async function openInvestigation(slug) {
    state.activeSlug = slug;
    const resp = await fetch(`/api/plan/${encodeURIComponent(slug)}`);
    if (!resp.ok) { alert('Failed to load investigation'); return; }
    const plan = await resp.json();
    document.getElementById('investigations-list').hidden = true;
    document.getElementById('investigation-detail').hidden = false;
    document.getElementById('investigation-title').textContent = plan.name;
    document.getElementById('investigation-objective').textContent = plan.objective || '';
    document.getElementById('investigation-hypothesis').textContent = plan.hypothesis || '';
    const completes = plan.studies.filter(s => s.derived_status === 'complete').length;
    document.getElementById('investigation-status').textContent =
      `Status: ${plan.status || 'planned'} (${completes}/${plan.studies.length} studies complete)`;

    const refs = document.getElementById('investigation-references');
    refs.innerHTML = '';
    for (const r of plan.references || []) {
      const li = document.createElement('li');
      li.innerHTML = `📄 <a href="/${encodeHtmlAttr(r.file)}">${escapeHtml(r.label || r.file)}</a>`;
      refs.appendChild(li);
    }

    const cards = document.getElementById('investigation-study-cards');
    cards.innerHTML = '';
    for (let i = 0; i < plan.studies.length; i++) {
      const s = plan.studies[i];
      const li = document.createElement('li');
      const icon = {complete: '✅', 'in-progress': '🔄', blocked: '⏸', planned: '⏳'}[s.derived_status] || '•';
      const gateNote = s.gate ? `<span class="muted">(gate: ${s.gate})</span>` : '';
      li.className = `study-card study-${s.derived_status}`;
      li.innerHTML = `
        <span class="study-icon">${icon}</span>
        <a class="study-link">${i + 1}. ${escapeHtml(s.study)}</a>
        <span class="study-status">${s.derived_status}</span>
        ${gateNote}
      `;
      li.querySelector('.study-link').addEventListener('click', () => {
        location.hash = `#studies/${encodeURIComponent(s.study)}`;
      });
      cards.appendChild(li);
    }
  }

  function backToList() {
    document.getElementById('investigations-list').hidden = false;
    document.getElementById('investigation-detail').hidden = true;
    state.activeSlug = null;
  }

  async function createInvestigation() {
    const dialog = document.getElementById('new-investigation-dialog');
    dialog.showModal();
    document.getElementById('new-inv-submit').addEventListener('click', async (e) => {
      const name = document.getElementById('new-inv-name').value.trim();
      const objective = document.getElementById('new-inv-objective').value;
      const hypothesis = document.getElementById('new-inv-hypothesis').value;
      const studiesStr = document.getElementById('new-inv-studies').value;
      const studies = studiesStr.split(',').map(s => s.trim()).filter(Boolean).map(s => ({study: s}));
      if (!name) return;
      const resp = await fetch('/api/plan-create', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, objective, hypothesis, studies}),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert(`Failed: ${err.error}`); return;
      }
      loadInvestigations();
    }, {once: true});
  }

  function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function encodeHtmlAttr(s) { return escapeHtml(s); }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('new-investigation-btn')?.addEventListener('click', createInvestigation);
    document.getElementById('investigation-back')?.addEventListener('click', backToList);
  });

  // Expose for the page-router (existing menu-switching code in walkthrough.js).
  window.loadInvestigations = loadInvestigations;
})();
```

- [ ] **Step 2: Include in index.html.j2**

Add near the existing `<script>` tags:
```html
<script src="/static/investigations.js"></script>
```

- [ ] **Step 3: Wire into walkthrough.js navigation**

Find the existing section-switching code; when `page-investigations` is shown, call `window.loadInvestigations()`.

- [ ] **Step 4: Add CSS**

Append to `style.css`:
```css
.investigation-list { list-style: none; padding: 0; }
.investigation-card { padding: 0.8rem; border: 1px solid #ddd; border-radius: 6px; margin: 0.4rem 0; cursor: pointer; }
.investigation-card:hover { background: #f7f7f7; }
.investigation-card .investigation-title { font-weight: 600; cursor: pointer; }
.investigation-card .badge { margin-left: 0.5rem; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
.investigation-card .status-planned { background: #e0e0e0; }
.investigation-card .status-in-progress { background: #fff3cd; color: #856404; }
.investigation-card .status-complete { background: #d4edda; color: #155724; }
.study-cards ol { list-style: none; padding: 0; }
.study-card { display: flex; gap: 0.6rem; align-items: center; padding: 0.5rem 0.8rem; border: 1px solid #ddd; border-radius: 4px; margin: 0.3rem 0; }
.study-card.study-complete { border-left: 3px solid #228B22; }
.study-card.study-in-progress { border-left: 3px solid #f0ad4e; }
.study-card.study-blocked { border-left: 3px solid #888; opacity: 0.7; }
.study-card.study-planned { border-left: 3px solid #4a90e2; }
.study-card .study-link { cursor: pointer; flex: 1; }
.study-card .study-link:hover { text-decoration: underline; }
.study-card .study-status { color: #666; font-size: 0.9em; }
```

- [ ] **Step 5: Manual verification**

Start the dashboard. Verify:
- Investigations menu link appears.
- Clicking it loads the empty-state placeholder.
- "+ New investigation" opens the dialog.
- Creating an investigation with two study slugs appears in the list.
- Clicking it shows the detail page with sequential study cards (statuses derived).

- [ ] **Step 6: Commit**

```bash
git add vivarium_dashboard/static/investigations.js vivarium_dashboard/static/style.css vivarium_dashboard/templates/index.html.j2
git commit -m "feat(ui): Investigations tab — list, detail page, new-investigation dialog"
```

---

## Phase H — pbg-template scaffolding update

### Task 16: Update workspace template to include investigations/ directory

**Files:**
- Create: `pbg-template/template/investigations/.keep`
- Modify: `pbg-template/template/.gitignore.j2` (or whatever the gitignore template is) — add `.pbg/study-test-results/`

- [ ] **Step 1: Add scaffold directory**

```bash
cd /Users/eranagmon/code/pbg-template
mkdir -p template/investigations
touch template/investigations/.keep
```

- [ ] **Step 2: Add gitignore entry**

Find the workspace gitignore template (search `template/` for `.gitignore` or similar). Add:
```
# Per-study test-runner artifacts
.pbg/study-test-results/
```

- [ ] **Step 3: Commit (in pbg-template)**

```bash
cd /Users/eranagmon/code/pbg-template
git add template/investigations/.keep template/.gitignore  # adjust filename
git commit -m "feat(template): scaffold investigations/ dir + ignore study-test-results"
```

---

## Phase I — End-to-end test

### Task 17: Integration test — create plan, run study tests, observe status advance

**Files:**
- Create: `tests/test_e2e_tests_and_investigations.py`

- [ ] **Step 1: Write the E2E test**

```python
# tests/test_e2e_tests_and_investigations.py
"""End-to-end test: create a 2-study investigation, run study 1's tests,
observe that the next study's gate advances when tests pass.
"""
import yaml, json, sqlite3
from pathlib import Path
import pytest
from tests.conftest import dashboard_client  # adjust if differently named


def test_e2e_create_run_advance(tmp_path, dashboard_client):
    # 1) Scaffold two studies with stub run + test.
    for slug in ("s1", "s2"):
        d = tmp_path / "studies" / slug
        (d / "tests").mkdir(parents=True)
        (d / "study.yaml").write_text(yaml.safe_dump({
            "schema_version": 4, "name": slug, "baseline": [],
            "tests": {"auto_discover": True, "data_source": "latest_run", "pytest_args": [], "last_results": None},
            "references": [], "implementation_tasks": "",
        }))
        (d / "tests" / "conftest.py").write_text("")
        (d / "tests" / "test_demo.py").write_text("def test_one(): assert True\n")
        # Fake a runs.db row
        conn = sqlite3.connect(d / "runs.db")
        conn.execute("CREATE TABLE runs_meta (run_id TEXT, params TEXT, seed INTEGER, status TEXT, n_steps INTEGER, variant TEXT, composite TEXT, timestamp TEXT)")
        conn.execute("INSERT INTO runs_meta VALUES ('r1', '{}', NULL, 'completed', 0, NULL, 'b', '2026-05-15T00:00:00')")
        conn.commit(); conn.close()

    client = dashboard_client(workspace=tmp_path)

    # 2) Create the investigation.
    resp = client.post("/api/plan-create", json={
        "name": "demo",
        "studies": [{"study": "s1", "gate": "tests-pass"}, {"study": "s2"}],
    })
    assert resp.status_code == 201

    # 3) Before tests run: s1 has runs but no last_results → in-progress; s2 is blocked.
    plan = client.get("/api/plan/demo").json()
    assert [s["derived_status"] for s in plan["studies"]] == ["in-progress", "blocked"]

    # 4) Run s1's tests.
    resp = client.post("/api/study-tests-run", json={"study": "s1"})
    assert resp.status_code == 200
    assert resp.json()["summary"]["passed"] == 1

    # 5) Now s1 is complete and s2 should unblock.
    plan = client.get("/api/plan/demo").json()
    assert [s["derived_status"] for s in plan["studies"]] == ["complete", "in-progress"]
```

- [ ] **Step 2: Run, verify pass**

Run: `pytest tests/test_e2e_tests_and_investigations.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run the full test suite to check for regressions**

Run: `pytest tests/ -x -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_tests_and_investigations.py
git commit -m "test(e2e): plan-create + study-tests-run + gate-advance integration"
```

---

## Self-review

**Spec coverage:**
- v3→v4 migration ✓ (Task 1, 2)
- `tests:` field with `auto_discover`/`data_source`/`pytest_args`/`last_results` ✓ (Task 2 validator)
- `references:` field ✓ (Task 2 validator)
- `implementation_tasks:` field ✓ (Task 2 validator)
- `Run` wrapper class with metadata + trajectory ✓ (Task 3)
- `run` pytest fixture ✓ (Task 3)
- `runs` parametrized fixture for `all_runs` ✓ (Task 4)
- Path-walk `_find_study_dir` ✓ (Task 3)
- `POST /api/study-tests-run` ✓ (Task 6)
- Concurrent run → 409 ✓ (Task 5 lock + Task 6)
- `last_results` writeback to study.yaml ✓ (Task 5)
- `investigation.yaml` validator ✓ (Task 7)
- Status derivation (`planned` / `in-progress` / `blocked` / `complete`) ✓ (Task 7)
- Zero tests cannot satisfy gate ✓ (Task 7)
- `GET /api/plans` ✓ (Task 8)
- `GET /api/plan/<slug>` with derived status ✓ (Task 8)
- `POST /api/plan-create` ✓ (Task 9)
- `POST /api/plan-set-meta` ✓ (Task 9)
- `DELETE /api/plan` ✓ (Task 9)
- `POST /api/plan-study-add` / remove / set-status ✓ (Task 10)
- `POST /api/plan-reference-add` ✓ (Task 11)
- Study Tests tab UI ✓ (Tasks 12, 13)
- Investigations top-level tab UI ✓ (Tasks 14, 15)
- pbg-template scaffold update ✓ (Task 16)
- E2E test ✓ (Task 17)

**Endpoints renamed from spec:** the design doc said `/api/investigations-list`, `/api/investigation-create`, etc. The plan uses `/api/plans`, `/api/plan-create`, etc., to avoid collision with the existing `/api/investigation-*` routes that handle Studies. **The design spec needs a small inline edit to match** (one-line correction).

**Out-of-scope deferrals (consistent with spec):**
- `/pbg-implement-study` skill in pbg-superpowers → separate follow-up plan.
- v2ecoli content authoring (8 studies + reference markdown + investigation.yaml) → separate follow-up plan.
- DAG investigations, cross-workspace references, in-dashboard test authoring → spec marked out-of-scope.

**Placeholder scan:** Each step has concrete code. No "TBD". A few notes flagged with `>` callouts where the engineer needs to verify against an existing harness (e.g., the test client fixture name) — these are not placeholders, they're real instructions to inspect specific named files.

**Type consistency:**
- `StudyTestsResult` shape used in Task 5 matches the response body shape in Task 6 (`summary`, `tests`, `note?`).
- `derived_status` enum (`planned` / `in-progress` / `blocked` / `complete`) is consistent across Task 7 (derivation), Task 8 (API output), Task 15 (JS icon map).
- `Run.observable()` returns `np.ndarray` consistently.

---

## Notes for the engineer

1. **First step before starting Task 6:** read `tests/conftest.py` in vivarium-dashboard to understand the test client fixture pattern. Many tests assume a `dashboard_client` factory; if it doesn't exist by that name, adapt every test that imports it.
2. **Module-level imports vs lazy imports in `server.py`:** the existing codebase uses lazy imports inside handler methods (e.g., `from .lib.investigations import load_spec`). Follow that pattern; don't add top-level imports for the new modules.
3. **`self._workspace` placeholder:** the actual attribute name on the request handler may differ — grep an existing handler (e.g., `_get_investigations`) for the correct accessor.
4. **pytest-json-report:** Task 5 depends on this package. If the workspace already has it as a dev dep, skip the pyproject edit. Otherwise add it.
5. **Idempotency of v3→v4 migration on legacy disk files:** the migration only happens in-memory in `load_spec`. The on-disk file gets rewritten only on a save operation. This is intentional — readers of v3 files are unaffected until they're mutated.
6. **Backwards compat with the legacy `/api/investigation-*` routes:** none of the new routes use that prefix. The two route families coexist.
