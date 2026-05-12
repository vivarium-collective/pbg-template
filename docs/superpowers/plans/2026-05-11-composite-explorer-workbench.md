# Composite Explorer Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Composite Explorer page into a per-spec workbench with in-page tabs for Wiring | History | Compare | State, SQLite-backed run persistence via process_bigraph's SQLiteEmitter, multi-run trajectory overlay, full state-tree exploration with snapshot-to-initial, a pop-out window, and a `/pbg-explore <spec-id>` skill launcher.

**Architecture:** New backend module `scripts/_lib/composite_runs.py` owns the SQLite database (`.pbg/composite-runs.db`) — schema bootstrap, `runs_meta` table CRUD, and a helper that injects a `SQLiteEmitter` Step into a resolved state dict. `scripts/_server/server.py` gains three GET endpoints (`/api/composite-runs`, `/api/composite-run/<id>`, `/api/composite-run/<id>/state`) and modifies the existing `/api/composite-test-run` to persist every run. The Composite Explorer page in `index.html.j2` gains an in-page tab strip (Wiring | History | Compare | State); JS in `walkthrough.js` handles tab switching, fetching run history, rendering Plotly overlay comparisons, browsing state trees, and snapshotting state into the Parameters editor. A new `/pbg-explore` skill in `pbg-superpowers` launches the explorer URL after ensuring the dashboard server is up.

**Tech Stack:** Python 3.11+ stdlib + SQLite (via process_bigraph.emitter.SQLiteEmitter), vanilla JS (no framework — matches existing walkthrough.js style), Plotly via CDN (already loaded by the dashboard for other panels). Tests use pytest. Spec doc: `docs/superpowers/specs/2026-05-11-composite-explorer-workbench-design.md`.

**File structure:**

| File | Action | Responsibility |
|---|---|---|
| `scripts/_lib/composite_runs.py` | create | DB connection, schema bootstrap, metadata CRUD, query helpers, SQLiteEmitter injection |
| `scripts/_server/server.py` | modify | Modify `_post_composite_test_run`; add 3 GET handlers |
| `scripts/_templates/index.html.j2` | modify | Add in-page tab strip + 4 panels around existing `#page-composite-explore` content |
| `scripts/_server/walkthrough.js` | modify | Tab switching + new JS for History / Compare / State / Snapshot / Pop-out |
| `scripts/_templates/_assets/style.css` | modify | Tab strip, state tree, diff cells, compare legend |
| `tests/test_composite_runs.py` | create | Unit tests for the new module |
| `tests/test_composite_explorer_api.py` | create | End-to-end backend lifecycle test |
| `../pbg-superpowers/skills/pbg-explore/SKILL.md` | create | Terminal launcher skill |
| `../pbg-superpowers/plugin.yaml` | modify | Register the new skill |

---

### Task 1: Backend data layer — `composite_runs.py` module + schema + metadata CRUD

**Files:**
- Create: `scripts/_lib/composite_runs.py`
- Test: `tests/test_composite_runs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composite_runs.py
"""Unit tests for scripts._lib.composite_runs."""
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_PARENT = Path(__file__).parent.parent
if str(_SCRIPTS_PARENT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_PARENT))

from scripts._lib.composite_runs import (
    connect, save_metadata, complete_metadata, query_runs, query_run,
)


def test_schema_bootstrap(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "runs_meta" in tables


def test_save_and_query_metadata(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(
        conn,
        spec_id="pkg.composites.demo",
        run_id="pkg.composites.demo__1715470512__abc123",
        params={"rate": 0.5},
        label="rate=0.5",
        started_at=1715470512.0,
    )
    runs = query_runs(conn, spec_id="pkg.composites.demo")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "pkg.composites.demo__1715470512__abc123"
    assert runs[0]["label"] == "rate=0.5"
    assert runs[0]["status"] == "running"


def test_complete_metadata_updates_status(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="s", run_id="r1", params={}, label="",
                  started_at=0.0)
    complete_metadata(conn, run_id="r1", n_steps=10, status="completed")
    runs = query_runs(conn, spec_id="s")
    assert runs[0]["status"] == "completed"
    assert runs[0]["n_steps"] == 10
    assert runs[0]["completed_at"] is not None


def test_query_runs_filtered_by_spec_id(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="A", run_id="r1", params={}, label="",
                  started_at=1.0)
    save_metadata(conn, spec_id="B", run_id="r2", params={}, label="",
                  started_at=2.0)
    save_metadata(conn, spec_id="A", run_id="r3", params={}, label="",
                  started_at=3.0)
    runs_a = query_runs(conn, spec_id="A")
    assert sorted(r["run_id"] for r in runs_a) == ["r1", "r3"]


def test_query_runs_returns_newest_first(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="A", run_id="r_old", params={}, label="",
                  started_at=1.0)
    save_metadata(conn, spec_id="A", run_id="r_new", params={}, label="",
                  started_at=10.0)
    runs = query_runs(conn, spec_id="A")
    assert runs[0]["run_id"] == "r_new"


def test_query_run_returns_empty_when_no_history(tmp_path):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    # No SQLiteEmitter ran against this DB yet → history table empty.
    save_metadata(conn, spec_id="s", run_id="r1", params={}, label="",
                  started_at=0.0)
    trajectory = query_run(conn, run_id="r1")
    assert trajectory == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/eranagmon/code/pbg-template && python -m pytest tests/test_composite_runs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts._lib.composite_runs'`

- [ ] **Step 3: Implement `composite_runs.py`**

Create `scripts/_lib/composite_runs.py`:

```python
"""SQLite-backed persistence for Composite Explorer runs.

Owns `.pbg/composite-runs.db`. Bootstraps the `runs_meta` table (run-level
metadata) alongside the `history` table that `process_bigraph.emitter.SQLiteEmitter`
owns (per-step state rows, partitioned by `simulation_id`).

A run's `simulation_id` and our `run_id` are the same string by convention:
    `<spec_id>__<unix-epoch-int>__<6-hex-chars>`
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path


_SCHEMA_RUNS_META = """
CREATE TABLE IF NOT EXISTS runs_meta (
    run_id        TEXT PRIMARY KEY,
    spec_id       TEXT NOT NULL,
    label         TEXT,
    params_json   TEXT,
    started_at    REAL NOT NULL,
    completed_at  REAL,
    n_steps       INTEGER,
    status        TEXT NOT NULL
);
"""

_INDEX_RUNS_META = """
CREATE INDEX IF NOT EXISTS idx_runs_meta_spec ON runs_meta(spec_id);
"""


def connect(db_file: str | Path) -> sqlite3.Connection:
    """Open the runs DB and ensure the metadata schema exists."""
    db_file = Path(db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA_RUNS_META)
    conn.execute(_INDEX_RUNS_META)
    conn.commit()
    return conn


def generate_run_id(spec_id: str, params: dict | None = None,
                    now: float | None = None) -> str:
    """Build a deterministic-shape run id: `<spec_id>__<ts>__<hash6>`."""
    ts = int(now if now is not None else time.time())
    payload = json.dumps({"spec_id": spec_id, "params": params or {},
                          "ts": ts}, sort_keys=True)
    short = hashlib.sha1(payload.encode()).hexdigest()[:6]
    return f"{spec_id}__{ts}__{short}"


def save_metadata(conn: sqlite3.Connection, *, spec_id: str, run_id: str,
                  params: dict | None, label: str, started_at: float) -> None:
    """Insert a new run row with status='running'."""
    conn.execute(
        "INSERT INTO runs_meta "
        "(run_id, spec_id, label, params_json, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, spec_id, label, json.dumps(params or {}),
         started_at, "running"),
    )
    conn.commit()


def complete_metadata(conn: sqlite3.Connection, *, run_id: str,
                      n_steps: int, status: str) -> None:
    """Mark an existing run as completed (or failed)."""
    conn.execute(
        "UPDATE runs_meta "
        "SET completed_at=?, n_steps=?, status=? WHERE run_id=?",
        (time.time(), n_steps, status, run_id),
    )
    conn.commit()


def query_runs(conn: sqlite3.Connection, *, spec_id: str) -> list[dict]:
    """List runs for one spec_id, newest first."""
    rows = conn.execute(
        "SELECT run_id, spec_id, label, params_json, started_at, "
        "completed_at, n_steps, status FROM runs_meta "
        "WHERE spec_id=? ORDER BY started_at DESC",
        (spec_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d.pop("params_json") or "{}")
        except json.JSONDecodeError:
            d["params"] = {}
        out.append(d)
    return out


def query_run(conn: sqlite3.Connection, *, run_id: str) -> list[dict]:
    """Return the trajectory `[{step, time, state}, ...]` for one run.

    Reads from the `history` table owned by process_bigraph.emitter.SQLiteEmitter.
    If that table doesn't exist yet (no SQLiteEmitter has ever written to this
    DB), returns an empty list.
    """
    has_history = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
    ).fetchone()
    if not has_history:
        return []
    rows = conn.execute(
        "SELECT step, time, state FROM history WHERE simulation_id=? "
        "ORDER BY step ASC",
        (run_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["state"] = json.loads(d["state"]) if d["state"] else {}
        except json.JSONDecodeError:
            d["state"] = {}
        out.append(d)
    return out


def query_run_state(conn: sqlite3.Connection, *, run_id: str,
                    step: int) -> dict | None:
    """Return the single state dict at one step, or None if missing."""
    has_history = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
    ).fetchone()
    if not has_history:
        return None
    row = conn.execute(
        "SELECT state FROM history WHERE simulation_id=? AND step=?",
        (run_id, step),
    ).fetchone()
    if not row or not row["state"]:
        return None
    try:
        return json.loads(row["state"])
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_runs.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib/composite_runs.py tests/test_composite_runs.py
git commit -m "feat: composite_runs.py — SQLite persistence for explorer runs"
```

---

### Task 2: SQLiteEmitter injection helper

**Files:**
- Modify: `scripts/_lib/composite_runs.py` (append)
- Test: `tests/test_composite_runs.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_composite_runs.py`)

```python
from scripts._lib.composite_runs import inject_sqlite_emitter


def _example_state_with_emitter():
    return {
        "increase": {
            "_type": "process",
            "address": "local:IncreaseProcess",
            "config": {"rate": 2.0},
            "inputs": {"level": ["stores", "level"]},
            "outputs": {"level": ["stores", "level"]},
            "interval": 1.0,
        },
        "stores": {"level": 1.0},
        "emitter": {
            "_type": "step",
            "address": "local:RAMEmitter",
            "config": {"emit": {"level": "float"}},
            "inputs": {"level": ["stores", "level"]},
        },
    }


def test_inject_sqlite_emitter_adds_step():
    state = _example_state_with_emitter()
    out = inject_sqlite_emitter(state, run_id="r1", db_file="/tmp/x.db")
    # Original state unchanged
    assert "_sqlite_emitter" not in state
    # New emitter present in returned state
    assert "_sqlite_emitter" in out
    sql_em = out["_sqlite_emitter"]
    assert sql_em["_type"] == "step"
    assert sql_em["address"] == "local:SQLiteEmitter"
    assert sql_em["config"]["simulation_id"] == "r1"
    assert sql_em["config"]["db_file"] == "/tmp/x.db"


def test_inject_sqlite_emitter_copies_existing_emitter_inputs():
    """When the spec already declares an emitter, the SQLite emitter should
    consume the same input ports so persistence captures the same observables."""
    state = _example_state_with_emitter()
    out = inject_sqlite_emitter(state, run_id="r1", db_file="/tmp/x.db")
    assert out["_sqlite_emitter"]["inputs"] == {"level": ["stores", "level"]}
    assert out["_sqlite_emitter"]["config"]["emit"] == {"level": "float"}


def test_inject_sqlite_emitter_no_emitter_in_spec():
    """When the spec has no emitter, inject a SQLite emitter with an empty
    schema — the run still persists step counts even without observables."""
    state = {
        "p": {"_type": "process", "address": "local:Foo",
              "outputs": {}, "interval": 1.0},
        "stores": {},
    }
    out = inject_sqlite_emitter(state, run_id="r1", db_file="/tmp/x.db")
    assert "_sqlite_emitter" in out
    assert out["_sqlite_emitter"]["config"]["emit"] == {}
    assert out["_sqlite_emitter"]["inputs"] == {}


def test_inject_sqlite_emitter_idempotent():
    state = _example_state_with_emitter()
    once = inject_sqlite_emitter(state, run_id="r1", db_file="/tmp/x.db")
    twice = inject_sqlite_emitter(once, run_id="r1", db_file="/tmp/x.db")
    assert once == twice
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_composite_runs.py::test_inject_sqlite_emitter_adds_step -v`
Expected: FAIL with `ImportError: cannot import name 'inject_sqlite_emitter'`

- [ ] **Step 3: Implement the helper** — append to `scripts/_lib/composite_runs.py`:

```python
def inject_sqlite_emitter(state: dict, *, run_id: str,
                          db_file: str) -> dict:
    """Return a copy of `state` with a SQLiteEmitter step appended.

    The injected step consumes the same input ports declared by the first
    `_type='step'` entry whose `address` ends with `Emitter` — so the
    SQLiteEmitter captures the same observables the spec's primary emitter
    already declared. When no such step exists, the SQLiteEmitter is added
    with an empty `emit` schema and no inputs (step counts persist anyway).

    Idempotent: a second call with the same run_id is a no-op.
    """
    if "_sqlite_emitter" in state:
        existing = state["_sqlite_emitter"]
        if (existing.get("config", {}).get("simulation_id") == run_id
                and existing.get("config", {}).get("db_file") == db_file):
            return state

    emit_schema: dict = {}
    inputs: dict = {}
    for key, node in state.items():
        if not isinstance(node, dict):
            continue
        if node.get("_type") != "step":
            continue
        addr = node.get("address", "")
        if not addr.endswith("Emitter") and "emitter" not in addr.lower():
            continue
        emit_schema = dict((node.get("config") or {}).get("emit") or {})
        inputs = dict(node.get("inputs") or {})
        break

    new_state = dict(state)
    new_state["_sqlite_emitter"] = {
        "_type": "step",
        "address": "local:SQLiteEmitter",
        "config": {
            "emit": emit_schema,
            "db_file": db_file,
            "simulation_id": run_id,
        },
        "inputs": inputs,
    }
    return new_state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_runs.py -v`
Expected: PASS — all 10 tests green (6 from Task 1 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib/composite_runs.py tests/test_composite_runs.py
git commit -m "feat: inject_sqlite_emitter helper for transparent run persistence"
```

---

### Task 3: Modify `/api/composite-test-run` to persist every run

**Files:**
- Modify: `scripts/_server/server.py` (find `_post_composite_test_run`; full method replaced)
- Test: `tests/test_composite_explorer_api.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_composite_explorer_api.py`:

```python
"""End-to-end test of the Composite Explorer's run-lifecycle API.

Spins up the dashboard server in-process against a fixture workspace and
exercises POST /api/composite-test-run and the three new GET endpoints.
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
import socket
import subprocess

import pytest

_REPO_ROOT = Path(__file__).parent.parent

FIXTURE_WORKSPACE = _REPO_ROOT / "tests" / "_fixtures" / "ws_increase_demo"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Render a tiny fixture workspace and start the dashboard server."""
    if not FIXTURE_WORKSPACE.is_dir():
        pytest.skip(f"Fixture workspace not present at {FIXTURE_WORKSPACE}")
    # Copy fixture to tmp so writes (DB, reports) don't pollute the repo
    import shutil
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_WORKSPACE, ws)
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(_REPO_ROOT / "scripts" / "_server" / "server.py"),
         "--workspace", str(ws), "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Wait for the server-info file to appear (server writes it on bind)
    info_path = ws / ".pbg" / "server" / "server-info"
    for _ in range(40):
        if info_path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=2)
        pytest.fail(f"server did not start:\nstdout:\n{out.decode()}\n"
                    f"stderr:\n{err.decode()}")
    yield {"url": f"http://127.0.0.1:{port}", "ws": ws}
    proc.terminate()
    proc.wait(timeout=5)


def _post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode())


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def test_test_run_persists_and_returns_simulation_id(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    status, body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.5}, "steps": 5,
    })
    assert status == 200
    assert "simulation_id" in body
    assert body.get("steps") == 5
    # DB row exists
    db_file = server["ws"] / ".pbg" / "composite-runs.db"
    assert db_file.is_file()


def test_list_runs_includes_the_persisted_run(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.5}, "steps": 5,
    })
    status, body = _get(f"{base}/api/composite-runs?"
                        f"spec_id={urllib.parse.quote(spec_id)}")
    assert status == 200
    runs = body["runs"]
    assert len(runs) >= 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["n_steps"] >= 1


def test_fetch_single_run_trajectory(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, post_body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {}, "steps": 4,
    })
    run_id = post_body["simulation_id"]
    status, body = _get(f"{base}/api/composite-run/{urllib.parse.quote(run_id)}")
    assert status == 200
    assert "trajectory" in body
    assert len(body["trajectory"]) >= 1


def test_fetch_state_at_step(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, post_body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {}, "steps": 3,
    })
    run_id = post_body["simulation_id"]
    status, body = _get(
        f"{base}/api/composite-run/{urllib.parse.quote(run_id)}/state?step=1")
    assert status == 200
    assert "state" in body
    assert isinstance(body["state"], dict)


def test_distinct_runs_get_distinct_ids(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, b1 = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 1.0}, "steps": 2,
    })
    _, b2 = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.0}, "steps": 2,
    })
    assert b1["simulation_id"] != b2["simulation_id"]
```

- [ ] **Step 2: Create the fixture workspace**

```bash
mkdir -p tests/_fixtures/ws_increase_demo/pbg_ws_increase_demo/composites
mkdir -p tests/_fixtures/ws_increase_demo/.pbg/server
```

Write `tests/_fixtures/ws_increase_demo/workspace.yaml`:

```yaml
schema_version: 2
name: ws_increase_demo
package_path: pbg_ws_increase_demo
phases: []
observables: []
visualizations: []
simulations: []
datasets: []
references_bib: references/papers.bib
server:
  enabled: true
```

Write `tests/_fixtures/ws_increase_demo/pbg_ws_increase_demo/__init__.py`:

```python
"""Fixture workspace package: a trivial IncreaseProcess composite for testing."""
```

Write `tests/_fixtures/ws_increase_demo/pbg_ws_increase_demo/processes.py`:

```python
from process_bigraph import Process


class IncreaseProcess(Process):
    """Trivial linear-growth process for the explorer test fixture."""
    config_schema = {'rate': {'_type': 'float', '_default': 1.0}}

    def inputs(self):
        return {'level': 'float'}

    def outputs(self):
        return {'level': 'float'}

    def update(self, state, interval=1.0):
        rate = (self.config or {}).get('rate', 1.0)
        return {'level': state.get('level', 0.0) * rate}
```

Write `tests/_fixtures/ws_increase_demo/pbg_ws_increase_demo/core.py`:

```python
from process_bigraph import allocate_core
from process_bigraph.emitter import RAMEmitter
from pbg_ws_increase_demo.processes import IncreaseProcess


def build_core():
    core = allocate_core()
    core.register_link('IncreaseProcess', IncreaseProcess)
    core.register_link('RAMEmitter', RAMEmitter)
    return core
```

Write `tests/_fixtures/ws_increase_demo/pbg_ws_increase_demo/composites/increase-demo.composite.yaml`:

```yaml
name: increase-demo
description: "Trivial linear-growth fixture for the Composite Explorer test suite."
requires:
  processes: [IncreaseProcess, RAMEmitter]
parameters:
  rate:
    type: float
    default: 2.0
    description: "Multiplicative factor applied to level each step"
  initial_level:
    type: float
    default: 1.0
    description: "Starting value for the level store"
state:
  increase:
    _type: process
    address: "local:IncreaseProcess"
    config:
      rate: "${rate}"
    inputs:
      level: ["stores", "level"]
    outputs:
      level: ["stores", "level"]
    interval: 1.0
  stores:
    level: "${initial_level}"
  emitter:
    _type: step
    address: "local:RAMEmitter"
    config:
      emit:
        level: "float"
    inputs:
      level: ["stores", "level"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_composite_explorer_api.py -v`
Expected: FAIL — `test_test_run_persists_and_returns_simulation_id` either gets no `simulation_id` field or the DB file doesn't appear.

- [ ] **Step 4: Modify `_post_composite_test_run` in `scripts/_server/server.py`**

Locate `_post_composite_test_run` (around line 2233 — search for `def _post_composite_test_run`). Replace the whole method with:

```python
    def _post_composite_test_run(self, body: dict):
        """POST /api/composite-test-run — run a composite for N steps, persist
        to .pbg/composite-runs.db via an injected SQLiteEmitter, return
        {simulation_id, results, steps}."""
        _ws_add_to_sys_path()
        from scripts._lib.composite_lookup import substitute_parameters, find_composite_path
        from scripts._lib import composite_runs as cr

        spec_id = (body.get("id") or "").strip()
        overrides = body.get("overrides") or {}
        steps = int(body.get("steps") or 5)
        label = (body.get("label") or "").strip() or _auto_label(overrides)

        if not spec_id:
            return self._json({"error": "missing id"}, 400)

        ws_data = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text())
        pkg = ws_data.get("package_path") or ("pbg_" + ws_data.get("name", "").replace("-", "_"))
        path = find_composite_path(WORKSPACE, pkg, spec_id)
        if path is None:
            return self._json({"error": "spec file not found"}, 404)

        text = path.read_text()
        spec = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
        state = substitute_parameters(spec.get("state") or {},
                                       spec.get("parameters") or {},
                                       overrides)

        # Persistence wiring
        db_file = str(WORKSPACE / ".pbg" / "composite-runs.db")
        run_id = cr.generate_run_id(spec_id, overrides)
        state = cr.inject_sqlite_emitter(state, run_id=run_id, db_file=db_file)

        # Subprocess-style run via the same path the existing /api/composite-test-run used.
        # Match existing pattern: composite.run(steps) + flatten tuple keys.
        py = sys.executable
        script = textwrap.dedent(f"""
            import json, sys, traceback
            try:
                from {pkg}.core import build_core
                from process_bigraph import Composite, gather_emitter_results
                from process_bigraph.emitter import SQLiteEmitter
                core = build_core()
                core.register_link('SQLiteEmitter', SQLiteEmitter)
                composite = Composite({{'state': {json.dumps(state)}}}, core=core)
                composite.run({steps})
                results = gather_emitter_results(composite)
                # Flatten tuple keys to JSON-friendly dotted strings
                out = {{}}
                for path_tuple, entries in results.items():
                    key = '.'.join(str(p) for p in path_tuple)
                    out[key] = entries
                print('@@@RESULTS@@@')
                print(json.dumps(out, default=str))
            except Exception as e:
                print('@@@ERROR@@@')
                print(traceback.format_exc())
        """)

        # Save metadata before running so the row exists even on crash
        conn = cr.connect(db_file)
        cr.save_metadata(conn, spec_id=spec_id, run_id=run_id,
                          params=overrides, label=label,
                          started_at=__import__("time").time())

        try:
            result = subprocess.run([py, "-c", script], cwd=WORKSPACE,
                                     capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="failed")
            return self._json({"simulation_id": run_id,
                                "error": "test run timed out"}, 200)

        out = result.stdout
        if "@@@ERROR@@@" in out:
            cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="failed")
            traceback_text = out.split("@@@ERROR@@@", 1)[1].strip()
            return self._json({"simulation_id": run_id, "error": "run failed",
                                "traceback": traceback_text}, 200)

        try:
            results = json.loads(out.split("@@@RESULTS@@@", 1)[1].strip())
        except (IndexError, json.JSONDecodeError):
            cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="failed")
            return self._json({"simulation_id": run_id,
                                "error": "could not parse run output",
                                "stdout": out, "stderr": result.stderr}, 200)

        cr.complete_metadata(conn, run_id=run_id, n_steps=steps, status="completed")
        return self._json({"simulation_id": run_id, "results": results,
                            "steps": steps}, 200)
```

Add this helper near the top of `server.py` (next to other private helpers):

```python
def _auto_label(overrides: dict) -> str:
    """Build a short human label from non-default override values."""
    if not overrides:
        return "defaults"
    parts = [f"{k}={v}" for k, v in sorted(overrides.items())]
    return ", ".join(parts)[:80]
```

- [ ] **Step 5: Run tests — first three should pass**

Run: `python -m pytest tests/test_composite_explorer_api.py::test_test_run_persists_and_returns_simulation_id -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/_server/server.py tests/test_composite_explorer_api.py \
        tests/_fixtures/ws_increase_demo
git commit -m "feat: persist composite test runs via SQLiteEmitter injection"
```

---

### Task 4: GET `/api/composite-runs?spec_id=X`

**Files:**
- Modify: `scripts/_server/server.py` (add handler + dispatch entry)

- [ ] **Step 1: Confirm the failing test already exists** (from Task 3)

Run: `python -m pytest tests/test_composite_explorer_api.py::test_list_runs_includes_the_persisted_run -v`
Expected: FAIL (handler not yet implemented).

- [ ] **Step 2: Add the handler in `server.py`** (next to `_get_composites` near line 2159)

```python
    def _get_composite_runs(self):
        """GET /api/composite-runs?spec_id=X — list runs for one composite spec."""
        from urllib.parse import urlparse, parse_qs
        _ws_add_to_sys_path()
        from scripts._lib import composite_runs as cr

        qs = parse_qs(urlparse(self.path).query)
        spec_id = (qs.get("spec_id") or [""])[0]
        if not spec_id:
            return self._json({"runs": [], "error": "missing spec_id"}, 400)

        db_file = WORKSPACE / ".pbg" / "composite-runs.db"
        if not db_file.is_file():
            return self._json({"runs": []}, 200)
        conn = cr.connect(db_file)
        runs = cr.query_runs(conn, spec_id=spec_id)
        return self._json({"runs": runs}, 200)
```

- [ ] **Step 3: Wire dispatch in `do_GET`** (around line 475 where other `/api/...` checks live, before `/api/composites`)

```python
        if self.path.startswith("/api/composite-runs"):
            return self._get_composite_runs()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_explorer_api.py::test_list_runs_includes_the_persisted_run -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: GET /api/composite-runs — list runs by spec_id"
```

---

### Task 5: GET `/api/composite-run/<run_id>`

**Files:**
- Modify: `scripts/_server/server.py`

- [ ] **Step 1: Confirm failing test exists**

Run: `python -m pytest tests/test_composite_explorer_api.py::test_fetch_single_run_trajectory -v`
Expected: FAIL.

- [ ] **Step 2: Add handler + dispatch in `server.py`**

Handler (after `_get_composite_runs`):

```python
    def _get_composite_run(self):
        """GET /api/composite-run/<run_id> — return trajectory list."""
        _ws_add_to_sys_path()
        from scripts._lib import composite_runs as cr

        path_only = self.path.split("?", 1)[0]
        rest = path_only[len("/api/composite-run/"):]
        # Strip a trailing '/state' if a more specific route should handle it;
        # this handler matches the bare /api/composite-run/<id> form.
        if "/" in rest:
            return self._json({"error": "use /state subpath"}, 400)
        run_id = rest

        db_file = WORKSPACE / ".pbg" / "composite-runs.db"
        if not db_file.is_file():
            return self._json({"error": "no run database"}, 404)
        conn = cr.connect(db_file)
        trajectory = cr.query_run(conn, run_id=run_id)
        if not trajectory:
            return self._json({"error": "run not found"}, 404)
        return self._json({"run_id": run_id, "trajectory": trajectory}, 200)
```

Dispatch in `do_GET` (BEFORE the broader `/api/composite-run` check we'll add for state — order matters):

```python
        if self.path.startswith("/api/composite-run/") and "/state" in self.path:
            return self._get_composite_run_state()
        if self.path.startswith("/api/composite-run/"):
            return self._get_composite_run()
```

- [ ] **Step 3: Run tests to verify pass**

Run: `python -m pytest tests/test_composite_explorer_api.py::test_fetch_single_run_trajectory -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: GET /api/composite-run/<run_id> — fetch full trajectory"
```

---

### Task 6: GET `/api/composite-run/<run_id>/state?step=N`

**Files:**
- Modify: `scripts/_server/server.py`

- [ ] **Step 1: Confirm failing test exists**

Run: `python -m pytest tests/test_composite_explorer_api.py::test_fetch_state_at_step -v`
Expected: FAIL.

- [ ] **Step 2: Add handler**

```python
    def _get_composite_run_state(self):
        """GET /api/composite-run/<run_id>/state?step=N — single state snapshot."""
        from urllib.parse import urlparse, parse_qs
        _ws_add_to_sys_path()
        from scripts._lib import composite_runs as cr

        u = urlparse(self.path)
        # path: /api/composite-run/<run_id>/state
        path_only = u.path
        prefix = "/api/composite-run/"
        rest = path_only[len(prefix):]
        if not rest.endswith("/state"):
            return self._json({"error": "bad route"}, 400)
        run_id = rest[: -len("/state")]
        qs = parse_qs(u.query)
        step_raw = (qs.get("step") or ["0"])[0]
        try:
            step = int(step_raw)
        except ValueError:
            return self._json({"error": "step must be int"}, 400)

        db_file = WORKSPACE / ".pbg" / "composite-runs.db"
        if not db_file.is_file():
            return self._json({"error": "no run database"}, 404)
        conn = cr.connect(db_file)
        state = cr.query_run_state(conn, run_id=run_id, step=step)
        if state is None:
            return self._json({"error": "state not found for run+step"}, 404)
        return self._json({"run_id": run_id, "step": step,
                            "state": state}, 200)
```

(Dispatch entry was already added in Task 5.)

- [ ] **Step 3: Run tests to verify pass**

Run: `python -m pytest tests/test_composite_explorer_api.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 4: Commit**

```bash
git add scripts/_server/server.py
git commit -m "feat: GET /api/composite-run/<id>/state?step=N — state at step"
```

---

### Task 7: HTML — wrap explorer in tab strip + four panels

**Files:**
- Modify: `scripts/_templates/index.html.j2` (around line 587, the `<section id="page-composite-explore">`)

- [ ] **Step 1: Identify the current section**

Open `scripts/_templates/index.html.j2` and find `<section id="page-composite-explore" class="page" data-page="composite-explore">`. Read its full contents (currently `<h2>` title + `<p>` lead + `#ce-loading` + `#ce-main` with panels for Wiring/Diagram/Parameters/State/Test/Create).

- [ ] **Step 2: Replace its inner contents with the tabbed layout**

```html
<!-- ===== PAGE: COMPOSITE EXPLORER ===== -->
<section id="page-composite-explore" class="page" data-page="composite-explore">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
    <h2 class="page-title" style="margin:0">Composite explorer</h2>
    <button class="btn-mini" onclick="_ceOpenPopout()" title="Open this composite in its own window">Pop out</button>
  </div>
  <p class="page-lead">Inspect the wiring of a composite, edit its parameters, run short test simulations, browse run history, and compare trajectories across runs.</p>

  <div id="ce-loading" class="empty-state">Loading composite&hellip;</div>

  <div id="ce-main" style="display:none">

    <!-- In-page tab strip -->
    <div class="ce-tab-strip" role="tablist">
      <button class="ce-tab active" data-tab="wiring"  onclick="_ceSwitchTab('wiring')">Wiring</button>
      <button class="ce-tab"        data-tab="history" onclick="_ceSwitchTab('history')">History <span class="ce-tab-badge" id="ce-history-count"></span></button>
      <button class="ce-tab"        data-tab="compare" onclick="_ceSwitchTab('compare')" style="display:none">Compare <span class="ce-tab-badge" id="ce-compare-count"></span></button>
      <button class="ce-tab"        data-tab="state"   onclick="_ceSwitchTab('state')">State</button>
    </div>

    <!-- TAB: Wiring (current contents preserved) -->
    <div class="ce-tab-panel active" data-tab="wiring">
      <div class="panel">
        <h3 id="ce-name"></h3>
        <p id="ce-description" class="muted"></p>
        <p><strong>ID:</strong> <code id="ce-id"></code></p>
      </div>
      <div class="panel">
        <h3>Wiring diagram <button class="btn-mini" onclick="_ceUpdateDiagram()">Update diagram</button></h3>
        <div id="ce-diagram" style="max-height:600px;overflow:auto;background:#fafafa;border:1px solid #e5e7eb;border-radius:4px;padding:8px">
          <p class="empty-state">No diagram yet&hellip;</p>
        </div>
      </div>
      <div class="panel">
        <h3>Parameters</h3>
        <div id="ce-parameters"></div>
      </div>
      <details class="panel">
        <summary><strong>Resolved state (JSON)</strong></summary>
        <pre id="ce-state-json" style="background:#f8f8f8;padding:10px;border-radius:4px;overflow-x:auto;font-size:0.82em"></pre>
      </details>
      <div class="panel">
        <h3>Test run</h3>
        <p class="panel-lead">Run the composite for a short number of steps. Every run is saved to <code>.pbg/composite-runs.db</code> and appears in the History tab.</p>
        <label>Steps <input type="number" id="ce-steps" value="5" min="1" max="100" style="width:80px;display:inline-block;margin-left:8px"></label>
        <button class="action-btn" onclick="_ceTestRun()">Test run</button>
        <div id="ce-test-results" style="margin-top:12px"></div>
      </div>
      <div class="panel" style="background:#eff6ff">
        <h3>Create simulation</h3>
        <p class="panel-lead">Promote these parameter values into a simulation entry in workspace.yaml.</p>
        <button class="action-btn" onclick="_cePromoteSimulation()">Create simulation from these values</button>
      </div>
    </div>

    <!-- TAB: History -->
    <div class="ce-tab-panel" data-tab="history">
      <div class="panel">
        <h3>Run history</h3>
        <p class="panel-lead">Past runs of this composite (newest first). Check 2+ to compare.</p>
        <div id="ce-history-body"><p class="empty-state">No runs yet — click <em>Test run</em> on the Wiring tab.</p></div>
      </div>
    </div>

    <!-- TAB: Compare -->
    <div class="ce-tab-panel" data-tab="compare">
      <div class="panel">
        <h3>Compare runs <button class="btn-mini" onclick="_ceClearCompareSelection()">Clear selection</button></h3>
        <div id="ce-compare-body"><p class="empty-state">Pick 2+ runs in the History tab.</p></div>
      </div>
    </div>

    <!-- TAB: State -->
    <div class="ce-tab-panel" data-tab="state">
      <div class="panel">
        <h3>State at step <span id="ce-state-step-label">0</span></h3>
        <div id="ce-state-controls"><p class="empty-state">Select a run from the History tab to explore its state.</p></div>
        <div id="ce-state-tree" class="ce-state-tree" style="margin-top:12px"></div>
        <div id="ce-state-actions" style="display:none;margin-top:12px">
          <button class="action-btn" onclick="_ceSnapshotToInitial()">Use this state as initial values</button>
          <div id="ce-snapshot-report" style="margin-top:8px;font-size:0.85em"></div>
        </div>
      </div>
    </div>

  </div>
</section>
```

- [ ] **Step 3: Visual smoke check** — render the dashboard and confirm the tab strip + panels load (no JS yet):

```bash
cd /Users/eranagmon/code/pbg-template
# Render index.html via a workspace; easiest is to copy this file to v2ecoli
cp scripts/_templates/index.html.j2 ../v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
# Open the URL from .pbg/server/server-info and verify all 4 tabs render
```

Expected: Composite Explorer page loads; Wiring tab is active and shows the same contents as before; other tabs are visible but empty/static.

- [ ] **Step 4: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_templates/index.html.j2
git commit -m "feat: in-page tab strip on Composite Explorer (Wiring|History|Compare|State)"
```

---

### Task 8: CSS — tab strip + state tree + diff cells

**Files:**
- Modify: `scripts/_templates/_assets/style.css` (append a new section near the existing `#ce-diagram` block)

- [ ] **Step 1: Append CSS to `style.css`**

```css
/* ── Composite explorer — workbench tabs (v0.5.4) ────────────────────── */
.ce-tab-strip{
  display:flex; gap:2px; margin:12px 0; padding:0;
  border-bottom:2px solid #e5e7eb;
}
.ce-tab{
  background:transparent; border:none; padding:8px 16px;
  font-size:0.9em; font-weight:500; color:#64748b; cursor:pointer;
  border-bottom:2px solid transparent; margin-bottom:-2px;
}
.ce-tab:hover{ color:#1e293b; background:#f8fafc }
.ce-tab.active{
  color:#1e293b; border-bottom-color:#3b82f6; font-weight:600;
}
.ce-tab-badge{
  display:inline-block; background:#e2e8f0; color:#475569;
  border-radius:9999px; padding:0 6px; margin-left:4px;
  font-size:0.75em; font-weight:600;
}
.ce-tab-panel{ display:none }
.ce-tab-panel.active{ display:block }

/* State tree (collapsible JSON) */
.ce-state-tree{
  font-family:"SF Mono",Menlo,Monaco,monospace;
  font-size:0.82em; line-height:1.5;
  background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;
  padding:10px 14px; max-height:520px; overflow:auto;
}
.ce-jt-key{ color:#7c3aed; font-weight:600 }
.ce-jt-str{ color:#059669 }
.ce-jt-num{ color:#2563eb }
.ce-jt-bool{ color:#d97706 }
.ce-jt-null{ color:#94a3b8 }
.ce-jt-toggle{ cursor:pointer; user-select:none; color:#94a3b8; margin-right:4px }
.ce-jt-toggle:hover{ color:#1e293b }
.ce-jt-collapsed{ display:none }
.ce-jt-bracket{ color:#64748b }

/* History table */
#ce-history-body table{ width:100%; border-collapse:collapse; font-size:0.85em }
#ce-history-body th, #ce-history-body td{ padding:6px 8px; border-bottom:1px solid #e5e7eb; text-align:left }
#ce-history-body th{ background:#f8fafc; font-weight:600 }
.ce-history-status{ display:inline-block; padding:2px 8px; border-radius:9999px; font-size:0.75em; font-weight:600 }
.ce-history-status.completed{ background:#d1fae5; color:#065f46 }
.ce-history-status.running{ background:#fef3c7; color:#92400e }
.ce-history-status.failed{ background:#fee2e2; color:#991b1b }

/* Compare diff table */
.ce-diff-table{ width:100%; border-collapse:collapse; font-size:0.85em; margin-top:12px }
.ce-diff-table th, .ce-diff-table td{ padding:6px 8px; border:1px solid #e5e7eb }
.ce-diff-table td.differs{ background:#fef9c3 }
.ce-compare-legend{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; font-size:0.85em }
.ce-compare-legend .swatch{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:middle }
```

- [ ] **Step 2: Render dashboard, visual smoke check**

```bash
cp scripts/_templates/_assets/style.css ../v2ecoli-chromosome-rep1/scripts/_templates/_assets/style.css
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Open the dashboard, navigate to Composite Explorer. Expected: tab strip styled (blue underline on active tab), inactive tabs muted gray.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_templates/_assets/style.css
git commit -m "feat: CSS for explorer tab strip, state tree, history, diff cells"
```

---

### Task 9: JS — `_ceSwitchTab` + Pop-out button wiring

**Files:**
- Modify: `scripts/_server/walkthrough.js` (in the `// Composite explorer (v0.5.1)` block around line 1256)

- [ ] **Step 1: Add tab-switch + pop-out functions** (insert after `_initCompositeExplorer` near line 1280)

```javascript
  function _ceSwitchTab(tab) {
    document.querySelectorAll('.ce-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.ce-tab-panel').forEach(function(p) {
      p.classList.toggle('active', p.dataset.tab === tab);
    });
    // Lazy-load each tab's content on first switch
    if (tab === 'history' && !window._ceHistoryLoaded) {
      window._ceHistoryLoaded = true;
      _ceLoadHistory();
    }
    if (tab === 'compare' && window._ceCompareSet && window._ceCompareSet.size >= 2) {
      _ceRenderCompare();
    }
  }
  window._ceSwitchTab = _ceSwitchTab;

  function _ceOpenPopout() {
    if (!window._ceCurrent || !window._ceCurrent.id) return;
    var url = location.pathname + '?focus=composite-explore&id=' +
              encodeURIComponent(window._ceCurrent.id);
    var w = window.open(url, '_blank', 'width=1200,height=900');
    if (!w) {
      // Popup blocked — same-tab fallback
      window.location.search = '?focus=composite-explore&id=' +
                                encodeURIComponent(window._ceCurrent.id);
    }
  }
  window._ceOpenPopout = _ceOpenPopout;
```

- [ ] **Step 2: Sync + render + smoke test**

```bash
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Open dashboard → Composite Explorer → Click each tab. Expected: tab strip switches active state; panels show/hide correctly. Click Pop out → new window opens with focus mode.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: _ceSwitchTab + _ceOpenPopout — tab navigation and pop-out window"
```

---

### Task 10: JS — History tab data + render

**Files:**
- Modify: `scripts/_server/walkthrough.js`

- [ ] **Step 1: Add history functions** (insert after the pop-out function)

```javascript
  // ─── History tab ──────────────────────────────────────────────────────
  window._ceRuns = {};            // run_id → run dict (cache)
  window._ceCompareSet = new Set();// selected run_ids for Compare

  function _ceLoadHistory() {
    var id = window._ceCurrent.id;
    fetch('/api/composite-runs?spec_id=' + encodeURIComponent(id))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var runs = data.runs || [];
        var body = document.getElementById('ce-history-body');
        var countBadge = document.getElementById('ce-history-count');
        if (countBadge) countBadge.textContent = '(' + runs.length + ')';
        if (!runs.length) {
          body.innerHTML = '<p class="empty-state">No runs yet — click <em>Test run</em> on the Wiring tab.</p>';
          return;
        }
        runs.forEach(function(r) { window._ceRuns[r.run_id] = r; });
        var rows = runs.map(_ceRenderHistoryRow).join('');
        body.innerHTML =
          '<table><thead><tr>' +
            '<th style="width:30px"></th><th>Label</th><th>Params</th>' +
            '<th>Started</th><th>Steps</th><th>Status</th><th></th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table>';
      });
  }
  window._ceLoadHistory = _ceLoadHistory;

  function _ceRenderHistoryRow(run) {
    var checked = window._ceCompareSet.has(run.run_id) ? 'checked' : '';
    var paramStr = Object.keys(run.params || {})
      .map(function(k) { return k + '=' + run.params[k]; }).join(', ') || '—';
    var startedStr = new Date(run.started_at * 1000).toLocaleString();
    return '<tr>' +
      '<td><input type="checkbox" ' + checked +
        ' onchange="_ceToggleCompareSelection(\'' + _esc(run.run_id) + '\', this.checked)"></td>' +
      '<td>' + _esc(run.label || '') + '</td>' +
      '<td><code>' + _esc(paramStr) + '</code></td>' +
      '<td>' + _esc(startedStr) + '</td>' +
      '<td>' + (run.n_steps || 0) + '</td>' +
      '<td><span class="ce-history-status ' + _esc(run.status) + '">' + _esc(run.status) + '</span></td>' +
      '<td><button class="btn-mini" onclick="_ceViewRun(\'' + _esc(run.run_id) + '\')">View</button></td>' +
    '</tr>';
  }

  function _ceViewRun(run_id) {
    window._ceSelectedRunId = run_id;
    _ceSwitchTab('state');
    _ceLoadState(run_id, 0);
  }
  window._ceViewRun = _ceViewRun;

  function _ceToggleCompareSelection(run_id, checked) {
    if (checked) window._ceCompareSet.add(run_id);
    else window._ceCompareSet.delete(run_id);
    var badge = document.getElementById('ce-compare-count');
    var tabBtn = document.querySelector('.ce-tab[data-tab="compare"]');
    var count = window._ceCompareSet.size;
    if (badge) badge.textContent = count > 0 ? '(' + count + ')' : '';
    if (tabBtn) tabBtn.style.display = count >= 2 ? '' : 'none';
  }
  window._ceToggleCompareSelection = _ceToggleCompareSelection;

  function _ceClearCompareSelection() {
    window._ceCompareSet.clear();
    document.querySelectorAll('input[type="checkbox"][onchange*="_ceToggleCompareSelection"]')
      .forEach(function(cb) { cb.checked = false; });
    _ceToggleCompareSelection('', false);  // refresh badge + tab visibility
  }
  window._ceClearCompareSelection = _ceClearCompareSelection;
```

- [ ] **Step 2: Update `_ceTestRun` to refresh history after run completes**

Find `_ceTestRun` (around line 1358). At the end of the success branch (after `resultsEl.innerHTML = resultsHtml;`), add:

```javascript
        // Persist + refresh history
        window._ceHistoryLoaded = false;  // force re-fetch on next visit
        if (document.querySelector('.ce-tab-panel[data-tab="history"]').classList.contains('active')) {
          _ceLoadHistory();
        }
```

- [ ] **Step 3: Sync + manual test**

```bash
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

In dashboard: Composite Explorer → Wiring → click Test run (use the increase-demo if available). Then History tab — expect a new row showing the run. Click a checkbox — Compare tab badge appears once 2 checked.

- [ ] **Step 4: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: History tab — list, filter-by-checkbox, view run"
```

---

### Task 11: JS — Compare tab (Plotly overlay + diff table)

**Files:**
- Modify: `scripts/_server/walkthrough.js`

- [ ] **Step 1: Add compare functions** (after the history functions)

```javascript
  // ─── Compare tab ──────────────────────────────────────────────────────
  var _CE_COMPARE_PALETTE = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b',
                              '#8b5cf6', '#06b6d4', '#84cc16', '#ec4899'];

  function _ceRenderCompare() {
    var ids = Array.from(window._ceCompareSet);
    if (ids.length < 2) return;
    var body = document.getElementById('ce-compare-body');
    body.innerHTML = '<p class="empty-state">Loading&hellip;</p>';
    Promise.all(ids.map(function(id) {
      return fetch('/api/composite-run/' + encodeURIComponent(id))
        .then(function(r) { return r.json(); });
    })).then(function(results) {
      var runs = ids.map(function(id, i) {
        return { run_id: id, meta: window._ceRuns[id] || {},
                  trajectory: results[i].trajectory || [],
                  color: _CE_COMPARE_PALETTE[i % _CE_COMPARE_PALETTE.length] };
      });

      // Find observable keys (numeric leaves) across all trajectories
      var observables = {};
      runs.forEach(function(run) {
        run.trajectory.forEach(function(point) {
          Object.keys(point.state || {}).forEach(function(k) {
            var v = point.state[k];
            if (typeof v === 'number') observables[k] = true;
          });
        });
      });
      var obsList = Object.keys(observables);

      // Legend
      var legend = '<div class="ce-compare-legend">' + runs.map(function(run) {
        return '<span><span class="swatch" style="background:' + run.color + '"></span>' +
                _esc(run.meta.label || run.run_id.slice(-12)) + '</span>';
      }).join('') + '</div>';

      // One chart div per observable
      var chartContainers = obsList.map(function(k) {
        return '<div id="ce-cmp-' + _esc(k) + '" style="height:280px;margin-bottom:12px"></div>';
      }).join('');

      // Param diff table
      var allKeys = new Set();
      runs.forEach(function(run) {
        Object.keys(run.meta.params || {}).forEach(function(k) { allKeys.add(k); });
      });
      var paramKeys = Array.from(allKeys);
      var diffHead = '<tr><th>parameter</th>' + runs.map(function(run) {
        return '<th style="border-bottom:3px solid ' + run.color + '">' +
                _esc(run.meta.label || run.run_id.slice(-12)) + '</th>';
      }).join('') + '</tr>';
      var diffRows = paramKeys.map(function(k) {
        var values = runs.map(function(run) { return (run.meta.params || {})[k]; });
        var uniq = new Set(values.map(function(v) { return JSON.stringify(v); }));
        var differs = uniq.size > 1;
        return '<tr><td><code>' + _esc(k) + '</code></td>' +
                values.map(function(v) {
                  return '<td' + (differs ? ' class="differs"' : '') + '>' +
                          _esc(String(v === undefined ? '—' : v)) + '</td>';
                }).join('') + '</tr>';
      }).join('');
      var diffTable = '<table class="ce-diff-table"><thead>' + diffHead +
                      '</thead><tbody>' + diffRows + '</tbody></table>';

      body.innerHTML = legend + chartContainers + diffTable;

      // Plot each observable
      obsList.forEach(function(k) {
        var traces = runs.map(function(run) {
          var times = run.trajectory.map(function(p) { return p.time; });
          var ys = run.trajectory.map(function(p) { return p.state[k]; });
          return { x: times, y: ys, type: 'scatter', mode: 'lines',
                    name: run.meta.label || run.run_id.slice(-12),
                    line: { color: run.color, width: 2 } };
        });
        Plotly.newPlot('ce-cmp-' + k, traces, {
          title: { text: k, font: { size: 13 } },
          margin: { l: 55, r: 15, t: 35, b: 40 },
          showlegend: false,
        }, { responsive: true, displayModeBar: false });
      });
    }).catch(function(err) {
      body.innerHTML = '<span style="color:#c00">Failed to fetch runs: ' + _esc(String(err)) + '</span>';
    });
  }
  window._ceRenderCompare = _ceRenderCompare;
```

- [ ] **Step 2: Sync + manual test**

```bash
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

In dashboard: run a composite twice with different parameters → History tab → check both rows → Compare tab. Expect: legend with two colors, one Plotly chart per numeric observable, diff table with parameter rows where changed values highlight yellow.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: Compare tab — N-run Plotly overlay + parameter diff table"
```

---

### Task 12: JS — State tab (tree renderer + step slider)

**Files:**
- Modify: `scripts/_server/walkthrough.js`

- [ ] **Step 1: Add state-tree + state-loading functions**

```javascript
  // ─── State tab ────────────────────────────────────────────────────────
  window._ceTrajectoryCache = {};  // run_id → trajectory array

  function _ceLoadState(run_id, step) {
    var cached = window._ceTrajectoryCache[run_id];
    if (cached) {
      _ceShowState(run_id, step, cached);
      return;
    }
    fetch('/api/composite-run/' + encodeURIComponent(run_id))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var trajectory = data.trajectory || [];
        window._ceTrajectoryCache[run_id] = trajectory;
        _ceShowState(run_id, step, trajectory);
      });
  }
  window._ceLoadState = _ceLoadState;

  function _ceShowState(run_id, step, trajectory) {
    var ctrls = document.getElementById('ce-state-controls');
    var tree = document.getElementById('ce-state-tree');
    var actions = document.getElementById('ce-state-actions');
    if (!trajectory.length) {
      ctrls.innerHTML = '<p class="empty-state">No state recorded for this run.</p>';
      tree.innerHTML = '';
      actions.style.display = 'none';
      return;
    }
    var maxStep = trajectory.length - 1;
    var safeStep = Math.max(0, Math.min(step, maxStep));
    ctrls.innerHTML =
      '<label>run: <code>' + _esc(run_id) + '</code></label>' +
      '<br><label>step: <input type="range" id="ce-state-slider" min="0" max="' +
        maxStep + '" value="' + safeStep + '"' +
        ' oninput="_ceShowState(\'' + _esc(run_id) + '\', parseInt(this.value), window._ceTrajectoryCache[\'' + _esc(run_id) + '\'])"></label> ' +
      '<span id="ce-state-step-val">step ' + safeStep + ' of ' + maxStep + '</span>';
    document.getElementById('ce-state-step-label').textContent = safeStep;
    var pt = trajectory[safeStep];
    tree.innerHTML = '';
    _ceRenderStateTree(pt && pt.state || {}, tree, 0);
    actions.style.display = '';
    window._ceCurrentStateForSnapshot = pt && pt.state || {};
  }
  window._ceShowState = _ceShowState;

  function _ceRenderStateTree(obj, container, depth) {
    var node = _ceRenderJSON(obj, depth);
    if (typeof node === 'string') container.innerHTML = node;
    else { container.innerHTML = ''; container.appendChild(node); }
  }
  window._ceRenderStateTree = _ceRenderStateTree;

  function _ceRenderJSON(obj, depth) {
    if (obj === null) return '<span class="ce-jt-null">null</span>';
    if (typeof obj === 'boolean') return '<span class="ce-jt-bool">' + obj + '</span>';
    if (typeof obj === 'number') return '<span class="ce-jt-num">' + obj + '</span>';
    if (typeof obj === 'string') return '<span class="ce-jt-str">"' + _esc(obj) + '"</span>';
    if (Array.isArray(obj)) {
      if (obj.length === 0) return '<span class="ce-jt-bracket">[]</span>';
      if (depth >= 5) return '<span class="ce-jt-bracket">[…' + obj.length + ' items]</span>';
      var id = 'ce-jt-' + Math.random().toString(36).slice(2, 9);
      var html = '<span class="ce-jt-toggle" onclick="_ceToggleJt(\'' + id + '\')">&blacktriangledown;</span>';
      html += '<span class="ce-jt-bracket">[</span><span style="color:#94a3b8;font-size:0.85em"> ' + obj.length + ' items</span>';
      html += '<div id="' + id + '" style="margin-left:1.2em">';
      obj.forEach(function(v, i) {
        html += '<div>' + _ceRenderJSON(v, depth + 1) + (i < obj.length - 1 ? ',' : '') + '</div>';
      });
      html += '</div><span class="ce-jt-bracket">]</span>';
      return html;
    }
    if (typeof obj === 'object') {
      var keys = Object.keys(obj);
      if (keys.length === 0) return '<span class="ce-jt-bracket">{}</span>';
      if (depth >= 5) return '<span class="ce-jt-bracket">{…' + keys.length + ' keys}</span>';
      var id = 'ce-jt-' + Math.random().toString(36).slice(2, 9);
      var html = '<span class="ce-jt-toggle" onclick="_ceToggleJt(\'' + id + '\')">&blacktriangledown;</span>';
      html += '<span class="ce-jt-bracket">{</span>';
      html += '<div id="' + id + '" style="margin-left:1.2em">';
      keys.forEach(function(k, i) {
        html += '<div><span class="ce-jt-key">' + _esc(k) + '</span>: ' +
                _ceRenderJSON(obj[k], depth + 1) + (i < keys.length - 1 ? ',' : '') + '</div>';
      });
      html += '</div><span class="ce-jt-bracket">}</span>';
      return html;
    }
    return String(obj);
  }

  function _ceToggleJt(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('ce-jt-collapsed');
  }
  window._ceToggleJt = _ceToggleJt;
```

- [ ] **Step 2: Sync + manual test**

```bash
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Run a composite test, switch to History, click View on the row → State tab loads with a step slider at 0 and a JSON tree. Drag the slider → tree re-renders without network call.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: State tab — collapsible JSON tree + step slider"
```

---

### Task 13: JS — Snapshot to initial

**Files:**
- Modify: `scripts/_server/walkthrough.js`

- [ ] **Step 1: Add snapshot function**

```javascript
  // ─── Snapshot to initial ──────────────────────────────────────────────
  function _ceSnapshotToInitial() {
    var state = window._ceCurrentStateForSnapshot || {};
    var paramInputs = document.querySelectorAll('#ce-parameters input[data-param]');
    var matched = [], skipped = [];
    function walk(obj, prefix) {
      Object.keys(obj || {}).forEach(function(k) {
        var v = obj[k];
        var path = prefix ? prefix + '.' + k : k;
        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
          walk(v, path);
        } else {
          // Try to find a parameter input whose name matches the leaf key
          var target = null;
          paramInputs.forEach(function(inp) {
            if (inp.dataset.param === k) target = inp;
          });
          if (!target) {
            skipped.push({ path: path, reason: 'no matching parameter' });
            return;
          }
          var declaredType = target.dataset.type;
          var ok = (declaredType === 'float' && typeof v === 'number')
                || (declaredType === 'int'   && typeof v === 'number' && Number.isInteger(v))
                || (declaredType === 'string' && typeof v === 'string')
                || (declaredType === 'bool'  && typeof v === 'boolean');
          if (!ok) {
            skipped.push({ path: path, reason: 'type mismatch (' + declaredType + ' vs ' + typeof v + ')' });
            return;
          }
          target.value = v;
          matched.push({ path: path, value: v });
        }
      });
    }
    walk(state, '');
    var report = document.getElementById('ce-snapshot-report');
    var skippedHtml = skipped.length
      ? '<details style="margin-top:4px"><summary>Show ' + skipped.length + ' skipped</summary><ul style="font-size:0.85em">' +
          skipped.map(function(s) { return '<li><code>' + _esc(s.path) + '</code> — ' + _esc(s.reason) + '</li>'; }).join('') +
        '</ul></details>'
      : '';
    report.innerHTML = 'Mapped ' + matched.length + ' of ' +
                       (matched.length + skipped.length) + ' leaves. ' + skippedHtml;
    _ceSwitchTab('wiring');
  }
  window._ceSnapshotToInitial = _ceSnapshotToInitial;
```

- [ ] **Step 2: Sync + manual test**

```bash
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

Run a composite (e.g., dnaa-binding) → State tab → pick a step → click "Use this state as initial values" → expect to switch to Wiring tab with parameter inputs populated where leaf names matched, and a "Mapped X of Y" report visible on the State tab next time you go back.

- [ ] **Step 3: Commit**

```bash
cd /Users/eranagmon/code/pbg-template
git add scripts/_server/walkthrough.js
git commit -m "feat: snapshot-to-initial — walk state, populate matching parameter inputs"
```

---

### Task 14: Skill — `/pbg-explore <spec-id>`

**Files:**
- Create: `../pbg-superpowers/skills/pbg-explore/SKILL.md`
- Modify: `../pbg-superpowers/plugin.yaml`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p /Users/eranagmon/code/pbg-superpowers/skills/pbg-explore
```

Write `/Users/eranagmon/code/pbg-superpowers/skills/pbg-explore/SKILL.md`:

````markdown
---
name: pbg-explore
description: Launch the dashboard's Composite Explorer for a specific composite spec id. Ensures the dashboard server is up, opens the explorer URL in focus mode. Usage: `/pbg-explore <spec-id>`.
---

# /pbg-explore — Launch the Composite Explorer for one spec

Open the dashboard's Composite Explorer page focused on one composite spec, starting the dashboard server first if needed.

## Inputs

- `<spec-id>` (required) — e.g., `pbg_chromosome_rep1.composites.dnaa-binding`

## Steps

1. Walk up from the current directory to find `workspace.yaml`. Fail with a clear message if not found.
2. Check whether `.pbg/server/server-info` exists and the URL inside it responds to `GET /api/composites` with HTTP 200. If yes, reuse that server.
3. Otherwise, run `bash scripts/serve.sh` in the background. Poll `.pbg/server/server-info` for up to 30 seconds. If it never appears, dump the server stdout/stderr and exit non-zero.
4. Read the URL from `server-info`.
5. Open `<url>?focus=composite-explore&id=<spec-id>` in the user's default browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows).

## Reference

The explorer page UI is described in `pbg-template/docs/superpowers/specs/2026-05-11-composite-explorer-workbench-design.md`.

## Example

```bash
/pbg-explore pbg_caspule.composites.bond-network-with-viz
```

Opens the bond-network-with-viz composite in a focus-mode window. The dashboard's other tabs (Workspace inputs, Registry, etc.) are hidden — only the Composite Explorer is visible.
````

- [ ] **Step 2: Register the skill in `plugin.yaml`**

Add `pbg-explore` to the `skills:` list in `/Users/eranagmon/code/pbg-superpowers/plugin.yaml`.

- [ ] **Step 3: Manual smoke test**

From any v2ecoli-chromosome-rep1 prompt:
- Stop the v2ecoli dashboard server if it's running.
- Invoke `/pbg-explore pbg_caspule.composites.bond-network-demo`.
- Expect: serve.sh starts, server-info appears, browser opens to the focus-mode explorer URL.

- [ ] **Step 4: Commit (in pbg-superpowers)**

```bash
cd /Users/eranagmon/code/pbg-superpowers
git add skills/pbg-explore/SKILL.md plugin.yaml
git commit -m "feat: /pbg-explore — launch Composite Explorer for one spec id"
git push 2>&1 | tail -3
```

---

### Task 15: Sync + final verification + push pbg-template

**Files:**
- Modify: `../v2ecoli-chromosome-rep1/scripts/_server/server.py`
- Modify: `../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js`
- Modify: `../v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2`
- Modify: `../v2ecoli-chromosome-rep1/scripts/_templates/_assets/style.css`
- Modify: `../v2ecoli-chromosome-rep1/scripts/_lib/composite_lookup.py` (no-change check)
- Create: `../v2ecoli-chromosome-rep1/scripts/_lib/composite_runs.py`

- [ ] **Step 1: Final sync to v2ecoli**

```bash
cd /Users/eranagmon/code/pbg-template
cp scripts/_lib/composite_runs.py ../v2ecoli-chromosome-rep1/scripts/_lib/composite_runs.py
cp scripts/_server/server.py ../v2ecoli-chromosome-rep1/scripts/_server/server.py
cp scripts/_server/walkthrough.js ../v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp scripts/_templates/index.html.j2 ../v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cp scripts/_templates/_assets/style.css ../v2ecoli-chromosome-rep1/scripts/_templates/_assets/style.css
cd ../v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all
```

- [ ] **Step 2: Restart v2ecoli dashboard**

```bash
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep .pbg/server | awk '{print $2}' | xargs -I {} kill {} 2>/dev/null
rm -f .pbg/server/server-info
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
cat .pbg/server/server-info
```

- [ ] **Step 3: Manual verification checklist**

In the v2ecoli dashboard, on the Composite Explorer page:

- [ ] Tab strip renders with four tabs (Wiring | History | Compare | State); Wiring is active.
- [ ] Click Test run on Wiring — completes; History tab badge increments.
- [ ] History tab shows the new row with status "completed".
- [ ] Run a *second* test with a different parameter — both runs appear in History.
- [ ] Check both rows in History — Compare tab appears (badge "2") and overlay charts render with two colors.
- [ ] Diff table highlights the changed parameter.
- [ ] Click View on a History row — switches to State tab, slider at 0, JSON tree visible.
- [ ] Drag slider — tree re-renders without network activity (cached).
- [ ] Click "Use this state as initial values" — switches to Wiring; matching parameter inputs populated; mapped/skipped report visible back on State tab.
- [ ] Click Pop out — new window opens at the focus-mode URL (no sidebar).
- [ ] Stop + restart the server — History tab still shows all runs (persistence verified).

- [ ] **Step 4: Commit v2ecoli sync**

```bash
git add scripts/_lib/composite_runs.py scripts/_server/server.py \
        scripts/_server/walkthrough.js scripts/_templates/index.html.j2 \
        scripts/_templates/_assets/style.css
git commit -m "fix: refresh to pbg-template v0.5.4 — Composite Explorer Workbench"
git push 2>&1 | tail -3
```

- [ ] **Step 5: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git push 2>&1 | tail -3
```

---

## Self-review notes

- **Spec coverage:** Every section of the spec maps to at least one task: data layer (1, 2), three endpoints (4, 5, 6), modified test-run handler (3), tab strip + CSS (7, 8, 9), History (10), Compare (11), State + tree + slider (12), Snapshot (13), Pop-out (9 — included with `_ceSwitchTab`), Skill (14), Sync + manual checklist (15).
- **Backwards compatibility:** Task 3 preserves the existing response shape and adds `simulation_id` as a new field. Workspaces with no `.pbg/composite-runs.db` get it auto-bootstrapped on first run.
- **No placeholders.** Every test, every change, every step has the actual code or command.
- **Type consistency:** `simulation_id` and `run_id` are used interchangeably (same string by design — explained in the spec under Data model). Frontend uses `run_id`; backend internal helper uses `run_id` parameter; response field is `simulation_id`. The naming asymmetry is intentional to match the legacy `_get_composites` response shape and the SQLiteEmitter's config field.
