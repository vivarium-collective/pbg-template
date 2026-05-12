"""Investigation spec loading, validation, and simulation expansion.

An Investigation is a directory at ``investigations/<name>/`` containing a
``spec.yaml`` plus generated artifacts (``runs.db``, ``viz/<name>.html``,
``data/*.csv``, ``notes.md``). This module owns:

  - load_spec(path): parse + validate a single spec.yaml
  - expand_simulations(spec): flatten the three simulation kinds into runs

The orchestration (run a composite for each expanded run, persist via
SQLiteEmitter, render visualizations) lives in further functions added in
subsequent tasks.
"""
from __future__ import annotations
import itertools
from pathlib import Path
from typing import Any

import yaml


class InvestigationSpecError(ValueError):
    """Raised when an investigation spec.yaml fails validation."""


_VALID_KINDS = {"single", "sweep", "seeds"}
_REQUIRED_TOP_LEVEL = ("name", "composite")
_VALID_STATUSES = {"planned", "running", "ran", "complete", "failed", "invalid"}
# Status semantics:
#   planned  — user created the investigation but hasn't run it yet
#   running  — orchestrator is mid-execution
#   ran      — runs completed without error; user hasn't drawn conclusions
#   complete — user-set; signals "I've analyzed the results and we're done"
#   failed   — at least one run failed
#   invalid  — spec.yaml didn't validate


def load_spec(path: Path) -> dict:
    """Parse + validate ``investigations/<name>/spec.yaml``.

    Raises:
        InvestigationSpecError: on any structural problem.
    """
    text = Path(path).read_text()
    try:
        spec = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise InvestigationSpecError(f"malformed YAML: {e}") from e

    if not isinstance(spec, dict):
        raise InvestigationSpecError("spec must be a YAML mapping at top level")

    for field in _REQUIRED_TOP_LEVEL:
        if field not in spec or not spec[field]:
            raise InvestigationSpecError(f"missing required field: {field}")

    sims = spec.get("simulations") or []
    if not isinstance(sims, list):
        raise InvestigationSpecError("simulations must be a list")

    for i, sim in enumerate(sims):
        if not isinstance(sim, dict):
            raise InvestigationSpecError(f"simulations[{i}] must be a mapping")
        if not sim.get("name"):
            raise InvestigationSpecError(f"simulations[{i}].name is required")
        kind = sim.get("kind")
        if kind not in _VALID_KINDS:
            raise InvestigationSpecError(
                f"simulations[{i}].kind must be one of {sorted(_VALID_KINDS)}; got {kind!r}"
            )
        if kind == "sweep":
            sweep_over = sim.get("sweep_over") or {}
            if not isinstance(sweep_over, dict) or not sweep_over:
                raise InvestigationSpecError(
                    f"simulations[{i}].sweep_over must be a non-empty mapping"
                )
            for k, vals in sweep_over.items():
                if not isinstance(vals, list) or not vals:
                    raise InvestigationSpecError(
                        f"simulations[{i}].sweep_over.{k} must be a non-empty list"
                    )
        elif kind == "seeds":
            n = sim.get("n_seeds", 0)
            if not isinstance(n, int) or n < 1:
                raise InvestigationSpecError(
                    f"simulations[{i}].n_seeds must be a positive integer; got {n!r}"
                )
        steps = sim.get("steps", 0)
        if not isinstance(steps, int) or steps < 1:
            raise InvestigationSpecError(
                f"simulations[{i}].steps must be a positive integer"
            )

    observables = spec.get("observables") or []
    if not isinstance(observables, list):
        raise InvestigationSpecError("observables must be a list")

    visualizations = spec.get("visualizations") or []
    if not isinstance(visualizations, list):
        raise InvestigationSpecError("visualizations must be a list")
    for i, viz in enumerate(visualizations):
        if not isinstance(viz, dict):
            raise InvestigationSpecError(f"visualizations[{i}] must be a mapping")
        if not viz.get("name"):
            raise InvestigationSpecError(f"visualizations[{i}].name is required")
        if not viz.get("address"):
            raise InvestigationSpecError(f"visualizations[{i}].address is required")

    return spec


def expand_simulations(spec: dict) -> list[dict]:
    """Flatten ``spec.simulations`` into a list of concrete runs.

    Each returned entry has keys:
      sim_name: str  — name of the originating simulation block
      run_label: str — unique label within the simulation (e.g. 'rate=0.1', 'seed=2')
      overrides: dict — composite parameter overrides for this run
      steps: int     — number of composite ticks
    """
    out: list[dict] = []
    for sim in spec.get("simulations") or []:
        kind = sim["kind"]
        steps = int(sim["steps"])
        if kind == "single":
            out.append({
                "sim_name": sim["name"],
                "run_label": "single",
                "overrides": dict(sim.get("overrides") or {}),
                "steps": steps,
            })
        elif kind == "sweep":
            sweep_over = sim["sweep_over"]
            base = sim.get("base_overrides") or {}
            keys = list(sweep_over.keys())
            value_lists = [sweep_over[k] for k in keys]
            for combo in itertools.product(*value_lists):
                ovr = dict(base)
                for k, v in zip(keys, combo):
                    ovr[k] = v
                label = ", ".join(f"{k}={ovr[k]}" for k in keys)
                out.append({
                    "sim_name": sim["name"],
                    "run_label": label,
                    "overrides": ovr,
                    "steps": steps,
                })
        elif kind == "seeds":
            n = int(sim["n_seeds"])
            base = sim.get("base_overrides") or {}
            for k in range(n):
                ovr = dict(base)
                ovr["seed"] = k
                out.append({
                    "sim_name": sim["name"],
                    "run_label": f"seed={k}",
                    "overrides": ovr,
                    "steps": steps,
                })
    return out


# ----------------------------------------------------------------------------
# Results aggregation + overlay resolution
# ----------------------------------------------------------------------------

import csv
import json
import sqlite3


def gather_results(spec: dict, db_path: Path) -> dict:
    """Read the investigation's runs.db and group trajectories by sim_name.

    Returns: {<sim_name>: {"runs": [{"run_id", "params", "trajectory"}, ...]}}

    Trajectory shape: [{"step", "time", "state"}, ...] where ``state`` is a
    parsed JSON dict (whatever SQLiteEmitter wrote).
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, dict] = {}
        # Check whether the SQLiteEmitter ever wrote a history row. If every
        # run failed before the first emit, the history table won't exist
        # — return empty-trajectory results so visualizations can show a
        # warning rather than crashing.
        has_history = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
        ).fetchone() is not None
        # All metadata rows for this investigation
        meta_rows = conn.execute(
            "SELECT run_id, sim_name, params_json FROM runs_meta"
        ).fetchall()
        run_meta: dict[str, dict] = {}
        for row in meta_rows:
            try:
                params = json.loads(row["params_json"] or "{}")
            except json.JSONDecodeError:
                params = {}
            run_meta[row["run_id"]] = {
                "sim_name": row["sim_name"] or "default",
                "params": params,
            }
        # Trajectories per run — skip the history query entirely if the
        # SQLiteEmitter never wrote a row (table absent).
        for run_id, meta in run_meta.items():
            if has_history:
                traj_rows = conn.execute(
                    "SELECT step, global_time AS time, state FROM history "
                    "WHERE simulation_id=? ORDER BY step ASC",
                    (run_id,),
                ).fetchall()
            else:
                traj_rows = []
            traj = []
            for tr in traj_rows:
                try:
                    state = json.loads(tr["state"]) if tr["state"] else {}
                except json.JSONDecodeError:
                    state = {}
                traj.append({"step": tr["step"], "time": tr["time"], "state": state})
            sim_name = meta["sim_name"]
            out.setdefault(sim_name, {"runs": []})
            out[sim_name]["runs"].append({
                "run_id": run_id, "params": meta["params"], "trajectory": traj,
            })
    finally:
        conn.close()
    return out


# ----------------------------------------------------------------------------
# Visualization v2 — emitter-driven, composite-dispatched
# ----------------------------------------------------------------------------

def gather_emitter_outputs(db_path: Path) -> dict:
    """Flatten runs.db into per-observable trajectories + emitter schemas.

    Returns:
        {
          "schemas": {<run_id>: {<observable>: <type_str>}, ...},
          "by_sim": {<sim_name>: [{run_id, sim_name, params, observables}, ...]},
        }
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return {"schemas": {}, "by_sim": {}}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        meta_rows = conn.execute(
            "SELECT run_id, sim_name, params_json FROM runs_meta"
        ).fetchall()
        run_meta = {}
        for r in meta_rows:
            try:
                params = json.loads(r["params_json"] or "{}")
            except json.JSONDecodeError:
                params = {}
            run_meta[r["run_id"]] = {
                "sim_name": r["sim_name"] or "default",
                "params": params,
            }

        schemas = {}
        try:
            sim_rows = conn.execute(
                "SELECT simulation_id, emit_schema FROM simulations"
            ).fetchall()
            for r in sim_rows:
                if r["emit_schema"]:
                    try:
                        schemas[r["simulation_id"]] = json.loads(r["emit_schema"])
                    except json.JSONDecodeError:
                        pass
        except sqlite3.OperationalError:
            pass

        by_sim = {}
        has_history = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
        ).fetchone() is not None
        for run_id, meta in run_meta.items():
            observables = {}
            if has_history:
                rows = conn.execute(
                    "SELECT step, global_time, state FROM history "
                    "WHERE simulation_id=? ORDER BY step ASC",
                    (run_id,),
                ).fetchall()
                for row in rows:
                    try:
                        state = json.loads(row["state"]) if row["state"] else {}
                    except json.JSONDecodeError:
                        continue
                    for k, v in state.items():
                        observables.setdefault(k, []).append(v)
                    # Only fall back to global_time if state doesn't carry a "time" key
                    if "time" not in state:
                        observables.setdefault("time", []).append(row["global_time"])
            sim_name = meta["sim_name"]
            by_sim.setdefault(sim_name, []).append({
                "run_id": run_id,
                "sim_name": sim_name,
                "params": meta["params"],
                "observables": observables,
            })
        return {"schemas": schemas, "by_sim": by_sim}
    finally:
        conn.close()


def build_viz_composite(viz_spec: dict, gathered: dict, core_registry: dict) -> dict:
    """Build the small composite that dispatches one visualization."""
    address = viz_spec["address"]
    class_key = address.split(":", 1)[1] if ":" in address else address
    viz_class = core_registry.get(class_key)
    if viz_class is None:
        raise KeyError(f"Visualization class not registered: {address}")

    config = dict(viz_spec.get("config") or {})
    inputs_map = config.get("inputs_map") or {}
    sources = config.get("sources")

    try:
        instance = viz_class.__new__(viz_class)
        declared_inputs = instance.inputs()
    except Exception:
        declared_inputs = {}

    candidate_runs = []
    by_sim = gathered.get("by_sim") or {}
    for sim_name, runs in by_sim.items():
        if sources and sim_name not in sources:
            continue
        candidate_runs.extend(runs)

    inputs_store = {}
    run_labels = []
    for port, port_type in declared_inputs.items():
        observable_name = inputs_map.get(port, port)
        per_run_values = []
        for run in candidate_runs:
            vals = run.get("observables", {}).get(observable_name)
            if vals is None:
                continue
            per_run_values.append(vals)
            params = run.get("params") or {}
            label = ", ".join(f"{k}={v}" for k, v in sorted(params.items())) \
                    or run["run_id"][-8:]
            if label not in run_labels:
                run_labels.append(label)
        if port_type == "list[float]":
            if len(per_run_values) == 1:
                inputs_store[port] = per_run_values[0]
            else:
                inputs_store[port] = per_run_values
        elif port_type == "float":
            inputs_store[port] = per_run_values[0][-1] if per_run_values else None
        elif port_type == "list[list[float]]":
            inputs_store[port] = per_run_values
        else:
            inputs_store[port] = per_run_values[0] if per_run_values else None

    inputs_store["_run_labels"] = run_labels

    return {
        "inputs_store": inputs_store,
        "output_store": "",
        "visualization": {
            "_type": "step",
            "address": address,
            "config": {k: v for k, v in config.items() if k not in ("inputs_map", "sources")},
            "inputs": {port: ["inputs_store", port] for port in declared_inputs},
            "outputs": {"html": ["output_store"]},
        },
    }


def load_overlays(spec: dict, viz_config: dict, ws_root: Path,
                  investigation_name: str) -> list[dict]:
    """Resolve each overlay entry into a uniform payload.

    Args:
        spec: the parent investigation spec (for context if needed)
        viz_config: the visualization dict, expected to have an 'overlays' list
        ws_root: workspace root path (overlay files are resolved relative to
                 investigations/<investigation_name>/)
        investigation_name: directory name of the current investigation

    Returns: list of overlay payload dicts. Failed lookups become
        {"kind": "warning", "message": "..."} so visualizations can either
        skip them or annotate the figure.
    """
    overlays = viz_config.get("overlays") or []
    payload: list[dict] = []
    inv_dir = Path(ws_root) / "investigations" / investigation_name

    for ov in overlays:
        kind = ov.get("kind")
        if kind == "reference-range":
            payload.append({
                "kind": "reference-range",
                "y_min": ov.get("y_min"),
                "y_max": ov.get("y_max"),
                "label": ov.get("label", "reference range"),
            })
        elif kind == "experimental-points":
            data_rel = ov.get("data") or ""
            data_path = inv_dir / data_rel
            if not data_path.is_file():
                payload.append({
                    "kind": "warning",
                    "message": f"experimental-points file missing: {data_rel}",
                })
                continue
            x_col = ov.get("x_column", "x")
            y_col = ov.get("y_column", "y")
            try:
                with data_path.open() as fh:
                    reader = csv.DictReader(fh)
                    points = [{"x": r.get(x_col), "y": r.get(y_col)} for r in reader]
            except Exception as e:
                payload.append({
                    "kind": "warning",
                    "message": f"experimental-points read failed: {e}",
                })
                continue
            payload.append({
                "kind": "experimental-points",
                "label": ov.get("label", "experimental"),
                "points": points,
            })
        elif kind == "cross-investigation-series":
            other_name = ov.get("investigation", "")
            other_db = Path(ws_root) / "investigations" / other_name / "runs.db"
            if not other_db.is_file():
                payload.append({
                    "kind": "warning",
                    "message": f"cross-investigation reference not found: {other_name}",
                })
                continue
            other_obs = ov.get("observable", "")
            xs, ys = [], []
            conn = sqlite3.connect(str(other_db))
            try:
                rows = conn.execute(
                    "SELECT global_time, state FROM history ORDER BY step ASC"
                ).fetchall()
                for tm, st in rows:
                    try:
                        s = json.loads(st) if st else {}
                    except json.JSONDecodeError:
                        continue
                    if other_obs in s:
                        xs.append(tm)
                        ys.append(s[other_obs])
            finally:
                conn.close()
            if not xs:
                payload.append({
                    "kind": "warning",
                    "message": f"cross-investigation observable not present: {other_obs} in {other_name}",
                })
                continue
            payload.append({
                "kind": "cross-investigation-series",
                "label": ov.get("label", f"{other_name}.{other_obs}"),
                "style": ov.get("style", "dashed-line"),
                "x": xs, "y": ys,
            })
        else:
            payload.append({
                "kind": "warning",
                "message": f"unknown overlay kind: {kind!r}",
            })
    return payload


# ----------------------------------------------------------------------------
# Spec status updater + run lock + orchestrator
# ----------------------------------------------------------------------------

import datetime


def update_spec_status(ws_root: Path, name: str, *, status: str,
                       last_run: str | None = None) -> None:
    """Update the status + last_run fields in investigations/<name>/spec.yaml.

    Preserves the rest of the spec verbatim by parsing → mutating → re-dumping.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; must be one of {sorted(_VALID_STATUSES)}")
    spec_path = Path(ws_root) / "investigations" / name / "spec.yaml"
    spec = yaml.safe_load(spec_path.read_text()) or {}
    spec["status"] = status
    if last_run is not None:
        spec["last_run"] = last_run
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))


def _lock_path(ws_root: Path, name: str) -> Path:
    return Path(ws_root) / "investigations" / name / ".run.lock"


def acquire_run_lock(ws_root: Path, name: str) -> bool:
    """Try to acquire an exclusive run lock for one investigation.

    Returns True if acquired, False if another run is already in progress.
    """
    lock = _lock_path(ws_root, name)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = lock.open("x")
        fd.write(str(datetime.datetime.utcnow()))
        fd.close()
        return True
    except FileExistsError:
        return False


def release_run_lock(ws_root: Path, name: str) -> None:
    """Release the run lock. No-op if the lock doesn't exist."""
    lock = _lock_path(ws_root, name)
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


def run_investigation(ws_root: Path, name: str, *,
                      run_one_composite: callable,
                      core_registry: dict,
                      build_and_run=None) -> dict:
    """Top-level orchestrator. Returns a summary dict.

    Args:
        ws_root: workspace root path
        name: investigation directory name
        run_one_composite: callable(spec_id, overrides, steps, sim_name,
            run_id, db_file) -> {"status": "completed"|"failed", "error"?: str}
            (injected so the orchestrator can be unit-tested with a mock;
            in production the server passes a function that resolves the
            composite + subprocess-runs it the same way _post_composite_test_run does)
        core_registry: process_bigraph core.link_registry — used to look up
            Visualization classes by address (e.g. "local:TimeSeriesPlot")
        build_and_run: optional callable(doc, core_registry) -> str passed through
            to render_visualizations.  When None and the spec has no visualizations,
            the viz pass is skipped cleanly.  When None but visualizations are
            present, render_visualizations raises ValueError.

    Side effects: writes runs.db + viz/<name>.html, updates spec.yaml.
    Each invocation APPENDS new runs to runs.db (does not clear prior runs).

    Returns:
        {name, n_runs, n_visualizations, status, viz_paths, errors}
    """
    from scripts._lib import composite_runs as cr

    ws_root = Path(ws_root)
    inv_dir = ws_root / "investigations" / name
    spec_path = inv_dir / "spec.yaml"
    spec = load_spec(spec_path)  # raises InvestigationSpecError on bad shape

    if not acquire_run_lock(ws_root, name):
        return {"name": name, "error": "investigation is already running",
                "status": "running"}

    try:
        update_spec_status(ws_root, name, status="running")
        db_file = str(inv_dir / "runs.db")
        conn = cr.connect(db_file)
        # Add sim_name column to runs_meta if our local copy doesn't have it.
        try:
            conn.execute("ALTER TABLE runs_meta ADD COLUMN sim_name TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        # Expand + run each simulation
        expanded = expand_simulations(spec)
        errors: list[dict] = []
        any_failed = False
        import time as _time
        for run in expanded:
            run_id = cr.generate_run_id(spec["composite"], run["overrides"])
            cr.save_metadata(conn, spec_id=spec["composite"], run_id=run_id,
                              params=run["overrides"],
                              label=run["run_label"],
                              started_at=_time.time())
            # Stamp sim_name on the row
            conn.execute("UPDATE runs_meta SET sim_name=? WHERE run_id=?",
                          (run["sim_name"], run_id))
            conn.commit()
            res = run_one_composite(
                spec_id=spec["composite"],
                overrides=run["overrides"],
                steps=run["steps"],
                sim_name=run["sim_name"],
                run_id=run_id,
                db_file=db_file,
            )
            if res.get("status") == "completed":
                cr.complete_metadata(conn, run_id=run_id, n_steps=run["steps"],
                                      status="completed")
            else:
                any_failed = True
                cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="failed")
                errors.append({"run_id": run_id, "error": res.get("error", "")})
        conn.close()

        # Visualization pass — skipped cleanly when build_and_run is None and
        # spec has no visualizations (backward-compat with tests that omit both).
        viz_paths = render_visualizations(spec, inv_dir, name,
                                          core_registry=core_registry,
                                          build_and_run=build_and_run)

        # 'ran' = runs finished without error; user explicitly sets 'complete'
        # after analyzing results (avoids over-claiming "complete" before the
        # researcher has drawn conclusions).
        final_status = "ran" if not any_failed else "failed"
        update_spec_status(ws_root, name, status=final_status,
                           last_run=datetime.datetime.utcnow().isoformat())

        return {
            "name": name,
            "n_runs": len(expanded),
            "n_visualizations": len(viz_paths),
            "status": final_status,
            "viz_paths": [str(p) for p in viz_paths],
            "errors": errors,
        }
    except Exception:
        update_spec_status(ws_root, name, status="failed")
        raise
    finally:
        release_run_lock(ws_root, name)


def render_visualizations(spec: dict, inv_dir: Path, name: str, *,
                          core_registry: dict,
                          build_and_run=None) -> list[Path]:
    """Render every viz in ``spec.visualizations`` against the investigation's runs.db.

    For each viz:
      1. Build the viz composite via ``build_viz_composite``.
      2. Run it for 1 step via ``build_and_run(doc, core_registry) -> str``.
      3. Write the resulting HTML to ``<inv_dir>/viz/<viz_name>.html``.
      4. On any error, write an error stub HTML (other vizzes still render).

    Args:
        spec: investigation spec dict
        inv_dir: path to the investigation directory (contains runs.db)
        name: investigation name (used only for error messages / doc purposes)
        core_registry: mapping of class key -> Visualization class
        build_and_run: callable(doc, core_registry) -> str that runs the composite
            and returns an HTML string.  Must be provided when there are
            visualizations to render; raises ValueError otherwise.
    """
    inv_dir = Path(inv_dir)
    viz_dir = inv_dir / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)

    visualizations = spec.get("visualizations") or []
    if not visualizations:
        return []

    if build_and_run is None:
        raise ValueError(
            "render_visualizations requires a build_and_run hook "
            "(production path: see server._post_investigation_run_viz_hook)."
        )

    gathered = gather_emitter_outputs(inv_dir / "runs.db")
    paths = []
    for viz_spec in visualizations:
        target = viz_dir / f"{viz_spec['name']}.html"
        try:
            doc = build_viz_composite(viz_spec, gathered, core_registry)
            html = build_and_run(doc, core_registry)
        except Exception as e:
            html = (
                f'<p style="color:#991b1b">Failed to render '
                f'<code>{viz_spec.get("name", "?")}</code>: '
                f'<code>{type(e).__name__}: {e}</code></p>'
            )
        target.write_text(html)
        paths.append(target)
    return paths
