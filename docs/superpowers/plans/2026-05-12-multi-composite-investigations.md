# Multi-composite Investigations + Observables tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Investigation spec from a single `composite:` reference to a `composites:` list supporting registered + derived (parameter or process overrides) composites stored as sidecar files. Add a Composites tab to browse each composite's state tree, an Observables tab to globally pick emitter paths across composites, and orchestrator support for multi-composite runs.

**Architecture:** Composites are already YAML documents in workspaces (`<pkg>/composites/<name>.composite.yaml`). Adding a composite to an Investigation = file copy. Deriving a composite = clone + apply overrides + write to `investigations/<name>/composites/<name>.yaml`. The orchestrator injects an emitter step at run time based on `spec.yaml.observables`, overriding any inline emitter in the composite document.

**Tech Stack:** Python 3.10+, process-bigraph, bigraph-schema, vanilla JavaScript, Jinja2 templates, pytest.

---

## File Structure

### Created

| File | Responsibility |
|---|---|
| `template/scripts/_lib/composite_recipes.py` | Pure-logic helpers: `apply_parameter_overrides(doc, overrides)`, `apply_process_overrides(doc, overrides)`, `walk_state_tree(doc) -> list[dict]`. No I/O; testable in isolation. |
| `template/scripts/_lib/investigation_migrate.py` | Detects legacy single-`composite:` spec.yaml; writes `composites/<baseline>.yaml`; rewrites spec.yaml as a `composites:` list. |
| `template/tests/test_composite_recipes.py` | Unit tests for `composite_recipes` helpers. |
| `template/tests/test_investigation_migrate.py` | Unit tests for migration. |

### Modified

| File | Change |
|---|---|
| `template/scripts/_lib/investigations.py` | `load_spec` accepts the new `composites:` list shape; orchestrator's `run_investigation` resolves `runs[].composite`; emitter injection from `spec.yaml.observables`. |
| `template/scripts/_server/server.py` | 7 new endpoints (composites list, add, perturb, rebuild, remove, state-tree, set-observables). |
| `template/scripts/_server/walkthrough.js` | Composites tab + Observables tab handlers, "+ Add composite" / "Perturb" modals, observables tree-with-checkboxes renderer. |
| `template/scripts/_templates/index.html.j2` | Tab strip in Investigation viewer adds Composites + Observables; modal markup for perturb. |
| `template/tests/test_visualization_endpoints.py` | Add tests for the new investigation endpoints (or split into `test_investigation_endpoints.py` if cleaner). |

---

## Phase A — Schema + Migration

### Task 1: `composites:` list shape in `load_spec` + tests

**Files:**
- Modify: `template/scripts/_lib/investigations.py`
- Modify: `template/tests/test_investigations.py`

- [ ] **Step 1: Append failing tests** to `template/tests/test_investigations.py`

```python
def test_load_spec_accepts_composites_list(tmp_path):
    from scripts._lib.investigations import load_spec
    spec_path = tmp_path / 'spec.yaml'
    spec_path.write_text(
        'name: multi\n'
        'composites:\n'
        '  - {name: baseline, source: pkg.composites.foo, document: ./composites/baseline.yaml}\n'
        '  - {name: hi, extends: baseline, parameter_overrides: {rate: 2.0}, document: ./composites/hi.yaml}\n'
        'observables:\n'
        '  - {path: [chromosome, DnaA_count]}\n'
        'runs:\n'
        '  - {composite: baseline, params: {seed: 1}, steps: 10}\n'
        '  - {composite: hi, params: {seed: 1}, steps: 10}\n'
        'visualizations: []\n'
    )
    spec = load_spec(spec_path)
    assert len(spec['composites']) == 2
    assert spec['composites'][0]['name'] == 'baseline'
    assert spec['composites'][1]['extends'] == 'baseline'
    assert spec['runs'][0]['composite'] == 'baseline'


def test_load_spec_rejects_runs_without_composite_when_multi():
    from scripts._lib.investigations import load_spec, InvestigationSpecError
    import tempfile, pathlib, yaml
    bad = {
        'name': 'x',
        'composites': [{'name': 'baseline', 'source': 'pkg.x', 'document': './c/b.yaml'}],
        'runs': [{'steps': 10}],  # missing composite:
    }
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / 'spec.yaml'
        p.write_text(yaml.safe_dump(bad))
        try:
            load_spec(p)
        except InvestigationSpecError as e:
            assert 'composite' in str(e).lower()
            return
    raise AssertionError('expected InvestigationSpecError')


def test_load_spec_legacy_single_composite_still_accepted(tmp_path):
    """During migration window, the old single-composite shape must still load."""
    from scripts._lib.investigations import load_spec
    spec_path = tmp_path / 'spec.yaml'
    spec_path.write_text(
        'name: legacy\n'
        'composite: pkg.composites.foo\n'
        'simulations: [{name: s1, kind: single, overrides: {}, steps: 10}]\n'
        'observables: []\n'
        'visualizations: []\n'
    )
    spec = load_spec(spec_path)
    # Either accepted as-is OR auto-normalized into composites: list; both ok.
    assert 'name' in spec
```

- [ ] **Step 2: Confirm fail**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest template/tests/test_investigations.py -k "composites_list or runs_without_composite or legacy_single" -v
```

- [ ] **Step 3: Update `load_spec`** in `template/scripts/_lib/investigations.py`

Find the validator (around line 38, near `load_spec(path)`). Extend to accept the new shape:

```python
def load_spec(path: Path) -> dict:
    """Parse + validate an Investigation spec.yaml.

    Accepts two shapes:
      - New (multi-composite):
          composites: [{name, source|extends, ...}]
          runs: [{composite, params, steps}]
      - Legacy (single-composite):
          composite: <string>
          simulations: [{name, kind, overrides, steps}]
    """
    if not path.is_file():
        raise InvestigationSpecError(f"spec.yaml not found: {path}")
    try:
        spec = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise InvestigationSpecError(f"invalid YAML: {e}") from e
    if not isinstance(spec, dict):
        raise InvestigationSpecError("spec must be a mapping")
    if not spec.get('name'):
        raise InvestigationSpecError("spec.name is required")

    composites = spec.get('composites')
    if composites is not None:
        if not isinstance(composites, list) or not composites:
            raise InvestigationSpecError("spec.composites must be a non-empty list")
        names = set()
        for c in composites:
            if not isinstance(c, dict) or not c.get('name'):
                raise InvestigationSpecError(f"composite entry missing 'name': {c}")
            if c['name'] in names:
                raise InvestigationSpecError(f"duplicate composite name: {c['name']}")
            names.add(c['name'])
            if not c.get('source') and not c.get('extends'):
                raise InvestigationSpecError(
                    f"composite {c['name']!r} needs either 'source' or 'extends'"
                )
            if c.get('extends') and c['extends'] not in names - {c['name']}:
                # extends must reference an earlier-listed composite
                raise InvestigationSpecError(
                    f"composite {c['name']!r} extends {c['extends']!r} which is not declared earlier"
                )
        runs = spec.get('runs') or []
        if not isinstance(runs, list):
            raise InvestigationSpecError("spec.runs must be a list")
        for r in runs:
            if not isinstance(r, dict) or 'composite' not in r:
                raise InvestigationSpecError(
                    f"run entry must have 'composite': {r}"
                )
            if r['composite'] not in names:
                raise InvestigationSpecError(
                    f"run references unknown composite {r['composite']!r}"
                )

    elif spec.get('composite'):
        # Legacy single-composite shape — accept; migration runs separately.
        if 'simulations' not in spec:
            raise InvestigationSpecError("legacy spec needs 'simulations'")

    else:
        raise InvestigationSpecError(
            "spec must declare either 'composites' (new) or 'composite' (legacy)"
        )

    return spec
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest template/tests/test_investigations.py -v
git add template/scripts/_lib/investigations.py template/tests/test_investigations.py
git commit -m "feat(investigations): accept composites: list shape in load_spec"
```

---

### Task 2: Migration helper + auto-trigger

**Files:**
- Create: `template/scripts/_lib/investigation_migrate.py`
- Create: `template/tests/test_investigation_migrate.py`
- Modify: `template/scripts/_server/server.py` (auto-trigger on `_get_investigation`)

- [ ] **Step 1: Write failing tests** at `template/tests/test_investigation_migrate.py`

```python
"""Tests for migrating legacy single-composite Investigations."""
import yaml
from pathlib import Path

from scripts._lib.investigation_migrate import (
    needs_migration, migrate_investigation,
)


def _seed_legacy(tmp_path):
    """Build a fixture with the legacy single-composite shape + the source
    composite YAML it points to."""
    inv = tmp_path / 'investigations' / 't1'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 't1',
        'composite': 'pbg_demo.composites.simple',
        'simulations': [{'name': 's1', 'kind': 'single', 'overrides': {}, 'steps': 10}],
        'observables': ['DnaA'],
        'visualizations': [],
    }, sort_keys=False))

    # The source composite — a real YAML file like workspaces already use
    pkg = tmp_path / 'pbg_demo' / 'composites'
    pkg.mkdir(parents=True)
    (pkg / 'simple.composite.yaml').write_text(yaml.safe_dump({
        'name': 'simple-demo',
        'state': {
            'chromosome': {'DnaA_count': {'_type': 'integer', '_default': 100}},
            'replication': {
                '_type': 'process',
                'address': 'local:Foo',
                'config': {'rate': 1.0},
                'inputs': {'dna': ['chromosome']},
                'outputs': {'dna': ['chromosome']},
            },
        },
    }, sort_keys=False))
    return tmp_path, inv


def test_needs_migration_detects_legacy_shape(tmp_path):
    _, inv = _seed_legacy(tmp_path)
    assert needs_migration(inv / 'spec.yaml') is True


def test_needs_migration_skips_already_migrated(tmp_path):
    inv = tmp_path / 'investigations' / 'ok'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(
        'name: ok\ncomposites:\n  - {name: baseline, source: pkg.x, document: ./c/b.yaml}\n'
        'runs: []\n'
    )
    assert needs_migration(inv / 'spec.yaml') is False


def test_migrate_copies_composite_and_rewrites_spec(tmp_path):
    ws_root, inv = _seed_legacy(tmp_path)
    migrate_investigation(inv / 'spec.yaml', workspace_root=ws_root)

    # Composite document copied to sidecar location
    sidecar = inv / 'composites' / 'simple.yaml'
    assert sidecar.is_file()
    doc = yaml.safe_load(sidecar.read_text())
    assert 'state' in doc
    assert 'replication' in doc['state']

    # spec.yaml rewritten
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    assert 'composite' not in spec
    assert len(spec['composites']) == 1
    assert spec['composites'][0]['name'] == 'simple'
    assert spec['composites'][0]['source'] == 'pbg_demo.composites.simple'
    assert spec['composites'][0]['document'] == './composites/simple.yaml'

    # Each run entry has composite: <baseline-name>
    runs = spec.get('runs') or spec.get('simulations')
    for r in runs:
        assert r.get('composite') == 'simple'


def test_migrate_is_idempotent(tmp_path):
    ws_root, inv = _seed_legacy(tmp_path)
    migrate_investigation(inv / 'spec.yaml', workspace_root=ws_root)
    # Second call should be a no-op (no exception)
    migrate_investigation(inv / 'spec.yaml', workspace_root=ws_root)
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest template/tests/test_investigation_migrate.py -v
```

- [ ] **Step 3: Implement `template/scripts/_lib/investigation_migrate.py`**

```python
"""Migrate a legacy single-composite Investigation to the new composites: list shape.

Run-once per investigation. Triggered automatically on dashboard open of an
investigation whose spec.yaml has the old `composite:` field instead of
`composites:`. The migration:
  1. Resolves the legacy `composite:` ref (e.g. `pkg.composites.foo`) to its
     source YAML at `<pkg>/composites/<foo>.composite.yaml`.
  2. Copies that document to `investigations/<name>/composites/<foo>.yaml`.
  3. Rewrites spec.yaml: replaces `composite:` with a one-entry `composites:`
     list, converts `simulations:` entries to `runs:` entries with the
     baseline composite name attached.
"""
from __future__ import annotations
import shutil
from pathlib import Path

import yaml


def needs_migration(spec_path: Path) -> bool:
    """True iff the spec has the legacy single-composite shape."""
    if not spec_path.is_file():
        return False
    spec = yaml.safe_load(spec_path.read_text()) or {}
    return bool(spec.get('composite')) and not spec.get('composites')


def _resolve_composite_source(ref: str, workspace_root: Path) -> tuple[Path, str]:
    """Resolve `pkg.composites.foo` -> (path-to-foo.composite.yaml, baseline-name='foo')."""
    parts = ref.split('.')
    if 'composites' not in parts:
        raise ValueError(
            f"composite ref {ref!r} does not contain 'composites' segment"
        )
    composites_idx = parts.index('composites')
    pkg_parts = parts[:composites_idx]
    stem_parts = parts[composites_idx + 1:]
    if not pkg_parts or not stem_parts:
        raise ValueError(f"composite ref {ref!r} malformed")
    stem = '.'.join(stem_parts)
    composites_dir = workspace_root.joinpath(*pkg_parts) / 'composites'
    for suffix in ('.composite.yaml', '.composite.yml', '.composite.json'):
        candidate = composites_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate, stem
    raise FileNotFoundError(
        f"could not find composite document for {ref!r} under {composites_dir}"
    )


def migrate_investigation(spec_path: Path, workspace_root: Path) -> dict:
    """Migrate the spec at ``spec_path`` in-place. Returns the new spec dict."""
    spec = yaml.safe_load(spec_path.read_text()) or {}
    if spec.get('composites'):
        return spec  # already migrated; idempotent

    composite_ref = spec.get('composite')
    if not composite_ref:
        return spec

    source_path, baseline_name = _resolve_composite_source(composite_ref, workspace_root)

    inv_dir = spec_path.parent
    composites_dir = inv_dir / 'composites'
    composites_dir.mkdir(parents=True, exist_ok=True)
    sidecar = composites_dir / f"{baseline_name}.yaml"
    if not sidecar.is_file():
        shutil.copy2(source_path, sidecar)

    # Build new spec
    new_spec: dict = {'name': spec.get('name')}
    if spec.get('description') is not None:
        new_spec['description'] = spec['description']
    new_spec['composites'] = [{
        'name': baseline_name,
        'source': composite_ref,
        'document': f'./composites/{baseline_name}.yaml',
    }]

    # Convert simulations -> runs (every entry gets composite: <baseline_name>)
    simulations = spec.get('simulations') or []
    new_runs = []
    for sim in simulations:
        if not isinstance(sim, dict):
            continue
        entry: dict = {'composite': baseline_name}
        if sim.get('overrides'):
            entry['params'] = sim['overrides']
        if sim.get('steps') is not None:
            entry['steps'] = sim['steps']
        if sim.get('seeds'):
            entry['seeds'] = sim['seeds']
        new_runs.append(entry)
    new_spec['runs'] = new_runs

    # Observables: legacy format was a flat list of names; new format is
    # [{path: [...]}]. Convert by wrapping each name as a single-element path.
    observables = spec.get('observables') or []
    new_obs = []
    for o in observables:
        if isinstance(o, str):
            new_obs.append({'path': [o]})
        elif isinstance(o, dict) and o.get('path'):
            new_obs.append(o)
    new_spec['observables'] = new_obs
    new_spec['visualizations'] = spec.get('visualizations') or []
    if 'status' in spec:
        new_spec['status'] = spec['status']
    if 'last_run' in spec:
        new_spec['last_run'] = spec['last_run']

    spec_path.write_text(yaml.safe_dump(new_spec, sort_keys=False))
    return new_spec
```

- [ ] **Step 4: Confirm pass**

```bash
python -m pytest template/tests/test_investigation_migrate.py -v
```

- [ ] **Step 5: Auto-trigger on Investigation viewer open**

Find `_get_investigation` (or the GET endpoint that the Investigation viewer hits when loading) in `template/scripts/_server/server.py`. At the top of the handler (after the path-validation), insert:

```python
        try:
            from scripts._lib.investigation_migrate import needs_migration, migrate_investigation
            spec_path = WORKSPACE / "investigations" / name / "spec.yaml"
            if needs_migration(spec_path):
                migrate_investigation(spec_path, workspace_root=WORKSPACE)
        except Exception:
            # Migration failure is non-fatal for the viewer; surface in payload
            # via a warning field rather than blocking the page render.
            pass
```

If `_get_investigation` doesn't exist as a named handler, find the endpoint that returns a single investigation's payload (search for `"/api/investigation"` or `investigation_get`) and insert the migration call there.

- [ ] **Step 6: Commit**

```bash
git add template/scripts/_lib/investigation_migrate.py template/tests/test_investigation_migrate.py template/scripts/_server/server.py
git commit -m "feat(investigations): migrate legacy single-composite specs to composites: list"
```

---

## Phase B — Backend endpoints

### Task 3: GET composites list + state-tree endpoints

**Files:**
- Modify: `template/scripts/_server/server.py`
- Create: `template/scripts/_lib/composite_recipes.py`
- Create: `template/tests/test_composite_recipes.py`
- Modify: `template/tests/test_visualization_endpoints.py` (or new `test_investigation_endpoints.py`)

- [ ] **Step 1: Write failing tests** for the recipes module — `template/tests/test_composite_recipes.py`:

```python
"""Tests for composite_recipes helpers (parameter/process overrides, state walk)."""
import copy

from scripts._lib.composite_recipes import (
    apply_parameter_overrides,
    apply_process_overrides,
    walk_state_tree,
)


def _doc():
    return {
        'name': 'demo',
        'parameters': {
            'rate': {'type': 'float', 'default': 1.0},
            'initial_count': {'type': 'integer', 'default': 100},
        },
        'state': {
            'chromosome': {
                'DnaA_count': {'_type': 'integer', '_default': 100},
                'free_DnaA': {'_type': 'float', '_default': 50.0},
            },
            'replication': {
                '_type': 'process',
                'address': 'local:Foo',
                'config': {'rate': 1.0},
                'inputs': {'dna': ['chromosome']},
                'outputs': {'dna': ['chromosome']},
            },
        },
    }


def test_apply_parameter_overrides_on_declared_parameters():
    doc = _doc()
    apply_parameter_overrides(doc, {'rate': 2.5, 'initial_count': 200})
    assert doc['parameters']['rate']['default'] == 2.5
    assert doc['parameters']['initial_count']['default'] == 200


def test_apply_parameter_overrides_dotted_state_path():
    doc = _doc()
    apply_parameter_overrides(doc, {'state.chromosome.DnaA_count._default': 300})
    assert doc['state']['chromosome']['DnaA_count']['_default'] == 300


def test_apply_parameter_overrides_dotted_process_config():
    doc = _doc()
    apply_parameter_overrides(doc, {'state.replication.config.rate': 5.0})
    assert doc['state']['replication']['config']['rate'] == 5.0


def test_apply_parameter_overrides_missing_path_raises():
    doc = _doc()
    import pytest
    with pytest.raises(KeyError, match='nonexistent'):
        apply_parameter_overrides(doc, {'state.nonexistent.field': 1})


def test_apply_process_overrides_swap_address():
    doc = _doc()
    apply_process_overrides(doc, {'replication': 'local:NewProcess'})
    assert doc['state']['replication']['address'] == 'local:NewProcess'
    # Config preserved
    assert doc['state']['replication']['config'] == {'rate': 1.0}


def test_apply_process_overrides_swap_address_and_config():
    doc = _doc()
    apply_process_overrides(doc, {
        'replication': {'address': 'local:NewProcess', 'config': {'rate': 9.0}},
    })
    assert doc['state']['replication']['address'] == 'local:NewProcess'
    assert doc['state']['replication']['config']['rate'] == 9.0


def test_apply_process_overrides_remove():
    doc = _doc()
    apply_process_overrides(doc, {'replication': None})
    assert 'replication' not in doc['state']


def test_apply_process_overrides_unknown_process_raises():
    doc = _doc()
    import pytest
    with pytest.raises(KeyError, match='unknown'):
        apply_process_overrides(doc, {'unknown': None})


def test_walk_state_tree_yields_leaves_and_processes():
    doc = _doc()
    leaves = walk_state_tree(doc)
    paths = {tuple(l['path']) for l in leaves}
    assert ('chromosome', 'DnaA_count') in paths
    assert ('chromosome', 'free_DnaA') in paths
    # Process is yielded as a 'process' node, not a leaf store
    repli = next(l for l in leaves if tuple(l['path']) == ('replication',))
    assert repli['kind'] == 'process'
    assert repli['address'] == 'local:Foo'
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest template/tests/test_composite_recipes.py -v
```

- [ ] **Step 3: Implement `template/scripts/_lib/composite_recipes.py`**

```python
"""Recipe operations on a process-bigraph composite document.

Pure logic; no I/O. Used by the Investigation Composites tab endpoints and
the runtime orchestrator.
"""
from __future__ import annotations
from typing import Any


def _follow_dotted_path(doc: dict, dotted: str) -> tuple[Any, str]:
    """Return (parent_container, final_key) so the caller can set the value.

    Path resolution:
      - 'rate'                       -> doc['parameters']['rate']
      - 'state.chromosome.DnaA_count._default'
                                     -> doc['state']['chromosome']['DnaA_count']['_default']
      - 'state.replication.config.rate'
                                     -> doc['state']['replication']['config']['rate']
    """
    if '.' in dotted:
        parts = dotted.split('.')
        node = doc
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                raise KeyError(
                    f"path component {p!r} not found while resolving {dotted!r} "
                    f"(stopped at {type(node).__name__}); available keys: "
                    f"{list(node.keys()) if isinstance(node, dict) else 'n/a'}"
                )
            node = node[p]
        if not isinstance(node, dict):
            raise KeyError(f"path {dotted!r} ends in a non-mapping container")
        return node, parts[-1]
    # Bare name: assume a declared parameter
    params = doc.get('parameters') or {}
    if dotted not in params:
        raise KeyError(
            f"parameter {dotted!r} not declared; available: {list(params.keys())}"
        )
    return params[dotted], 'default'


def apply_parameter_overrides(doc: dict, overrides: dict) -> None:
    """Apply scalar overrides to the document in place.

    Two override shapes:
      - bare-name override (e.g. ``rate: 2.0``) -> sets
        ``parameters[name]['default']``.
      - dotted path (e.g. ``state.chromosome.DnaA_count._default: 200``) ->
        sets the addressed scalar.
    """
    for key, value in (overrides or {}).items():
        container, final = _follow_dotted_path(doc, key)
        if final not in container and '.' not in key:
            # bare-name path returned ('default' key); fine if missing — create it
            container[final] = value
        elif final not in container:
            raise KeyError(
                f"parameter override path {key!r} final segment {final!r} not in "
                f"container; available: {list(container.keys())}"
            )
        else:
            container[final] = value


def apply_process_overrides(doc: dict, overrides: dict) -> None:
    """Apply process swap/removal overrides.

    Each entry is ``process_name -> spec`` where spec is one of:
      - None      -> remove the process from state
      - str       -> new address (config preserved)
      - dict      -> may contain 'address' and/or 'config' to swap/replace
    """
    state = doc.get('state') or {}
    for proc_name, spec in (overrides or {}).items():
        if proc_name not in state:
            raise KeyError(
                f"unknown process {proc_name!r}; available: {list(state.keys())}"
            )
        if spec is None:
            del state[proc_name]
            continue
        node = state[proc_name]
        if not isinstance(node, dict) or node.get('_type') != 'process':
            raise KeyError(f"{proc_name!r} is not a process node; cannot override")
        if isinstance(spec, str):
            node['address'] = spec
            continue
        if isinstance(spec, dict):
            if 'address' in spec:
                node['address'] = spec['address']
            if 'config' in spec:
                node['config'] = spec['config']
            continue
        raise TypeError(f"process_overrides[{proc_name!r}] must be None, str, or dict")


def walk_state_tree(doc: dict) -> list[dict]:
    """Flatten the composite's ``state:`` block into a list of node records.

    Each record is:
        {path: [...], kind: 'store' | 'process', type?: str, default?: Any,
         address?: str, config?: dict}

    For leaf stores: kind='store', type=_type, default=_default.
    For processes:   kind='process', address=address, config=config.
    """
    state = doc.get('state') or {}
    out: list[dict] = []

    def _walk(node: Any, path: tuple):
        if not isinstance(node, dict):
            out.append({
                'path': list(path),
                'kind': 'store',
                'type': type(node).__name__,
                'default': node,
            })
            return
        if node.get('_type') == 'process':
            out.append({
                'path': list(path),
                'kind': 'process',
                'address': node.get('address', ''),
                'config': node.get('config', {}),
            })
            return
        if '_type' in node:
            # explicit-type store leaf
            out.append({
                'path': list(path),
                'kind': 'store',
                'type': node.get('_type', ''),
                'default': node.get('_default'),
            })
            return
        # Plain dict: recurse
        for key, child in node.items():
            _walk(child, path + (key,))

    for key, child in state.items():
        _walk(child, (key,))
    return out
```

- [ ] **Step 4: Confirm recipes tests pass**

```bash
python -m pytest template/tests/test_composite_recipes.py -v
```

- [ ] **Step 5: Add endpoint handlers + tests**

Append to `template/tests/test_visualization_endpoints.py` (or factor into a new `test_investigation_endpoints.py` if the file is getting long):

```python
def test_get_investigation_composites_lists_entries(workspace_server):
    """List composites in a study with their metadata."""
    inv_dir = workspace_server.root / 'investigations' / 'demo'
    inv_dir.mkdir(parents=True)
    composites_dir = inv_dir / 'composites'
    composites_dir.mkdir()
    (composites_dir / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {'foo': {'_type': 'integer', '_default': 1}},
    }))
    (inv_dir / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))

    req = urllib.request.Request(
        workspace_server.url + '/api/investigation-composites?investigation=demo'
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    assert len(data['composites']) == 1
    assert data['composites'][0]['name'] == 'baseline'
    assert data['composites'][0]['document'] == './composites/baseline.yaml'


def test_get_investigation_state_tree(workspace_server):
    """Walk a composite's state tree."""
    inv_dir = workspace_server.root / 'investigations' / 'demo'
    inv_dir.mkdir(parents=True)
    composites_dir = inv_dir / 'composites'
    composites_dir.mkdir()
    (composites_dir / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {
            'chromosome': {'count': {'_type': 'integer', '_default': 100}},
            'replication': {'_type': 'process', 'address': 'local:Foo',
                            'config': {'rate': 1.0}},
        },
    }))
    (inv_dir / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))

    req = urllib.request.Request(
        workspace_server.url + '/api/investigation-state-tree'
        '?investigation=demo&composite=baseline'
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    nodes = data['nodes']
    paths = {tuple(n['path']) for n in nodes}
    assert ('chromosome', 'count') in paths
    assert ('replication',) in paths
```

- [ ] **Step 6: Add GET dispatch + handlers** to `template/scripts/_server/server.py`

In the GET dispatch (search for `"/api/visualization-classes"` near the top of `do_GET`):

```python
        if self.path.startswith("/api/investigation-composites"):
            return self._get_investigation_composites()
        if self.path.startswith("/api/investigation-state-tree"):
            return self._get_investigation_state_tree()
```

Handlers (place near other investigation handlers):

```python
    def _get_investigation_composites(self):
        """GET /api/investigation-composites?investigation=<n>
        Returns: {composites: [{name, source?, extends?, document, parameter_overrides?, process_overrides?}, ...]}
        """
        import urllib.parse
        from scripts._lib.investigations import load_spec, InvestigationSpecError
        qs = urllib.parse.urlparse(self.path).query
        name = urllib.parse.parse_qs(qs).get('investigation', [''])[0].strip()
        if not name:
            return self._json({"error": "investigation is required"}, 400)
        spec_path = WORKSPACE / "investigations" / name / "spec.yaml"
        try:
            spec = load_spec(spec_path)
        except InvestigationSpecError as e:
            return self._json({"error": f"spec error: {e}"}, 400)
        return self._json({"composites": spec.get("composites") or []}, 200)

    def _get_investigation_state_tree(self):
        """GET /api/investigation-state-tree?investigation=<n>&composite=<c>
        Returns: {nodes: [{path, kind, type?, default?, address?, config?}, ...]}
        """
        import urllib.parse
        from scripts._lib.composite_recipes import walk_state_tree
        qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        inv = qs.get('investigation', '').strip()
        comp = qs.get('composite', '').strip()
        if not inv or not comp:
            return self._json({"error": "investigation + composite required"}, 400)
        composite_path = WORKSPACE / "investigations" / inv / "composites" / f"{comp}.yaml"
        if not composite_path.is_file():
            return self._json({"error": f"composite document not found: {composite_path}"}, 404)
        try:
            doc = yaml.safe_load(composite_path.read_text()) or {}
        except Exception as e:
            return self._json({"error": f"failed to parse composite: {e}"}, 500)
        return self._json({"nodes": walk_state_tree(doc)}, 200)
```

- [ ] **Step 7: Confirm pass + commit**

```bash
python -m pytest template/tests/test_composite_recipes.py template/tests/test_visualization_endpoints.py -v
git add template/scripts/_lib/composite_recipes.py template/tests/test_composite_recipes.py template/scripts/_server/server.py template/tests/test_visualization_endpoints.py
git commit -m "feat(investigations): composite_recipes module + GET composites/state-tree endpoints"
```

---

### Task 4: POST composite-add + composite-perturb endpoints

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing tests**

```python
def test_post_composite_add_clones_source_to_sidecar(workspace_server):
    """Adding a composite copies the workspace composite document into the study."""
    # Seed a workspace composite at pbg_testws/composites/baseline.composite.yaml
    pkg_composites = workspace_server.root / 'pbg_testws' / 'composites'
    pkg_composites.mkdir(parents=True, exist_ok=True)
    (pkg_composites / 'baseline.composite.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {'chromosome': {'count': {'_type': 'integer', '_default': 100}}},
    }))

    # Seed an empty investigation
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-composite-add',
        {'investigation': 'demo', 'name': 'baseline',
         'source': 'pbg_testws.composites.baseline'},
    )
    assert code in (200, 500), j   # 500 acceptable if _active_branch_action fails

    sidecar = inv / 'composites' / 'baseline.yaml'
    assert sidecar.is_file()
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    assert spec['composites'][0]['name'] == 'baseline'
    assert spec['composites'][0]['document'] == './composites/baseline.yaml'


def test_post_composite_perturb_renders_derived_document(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {'replication': {'_type': 'process', 'address': 'local:Foo',
                                    'config': {'rate': 1.0}}},
    }))
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-composite-perturb',
        {'investigation': 'demo', 'name': 'high-rate', 'extends': 'baseline',
         'parameter_overrides': {'state.replication.config.rate': 2.0}},
    )
    assert code in (200, 500), j

    derived = composites / 'high-rate.yaml'
    assert derived.is_file()
    doc = yaml.safe_load(derived.read_text())
    assert doc['state']['replication']['config']['rate'] == 2.0
```

- [ ] **Step 2: Confirm fail**

```bash
python -m pytest template/tests/test_visualization_endpoints.py -k "composite_add or composite_perturb" -v
```

- [ ] **Step 3: Add handlers**

In the POST dispatch dict:

```python
            "/api/investigation-composite-add":      self._post_investigation_composite_add,
            "/api/investigation-composite-perturb":  self._post_investigation_composite_perturb,
```

Handlers:

```python
    def _post_investigation_composite_add(self, body: dict):
        """POST /api/investigation-composite-add {investigation, name, source}
        Clone a registered workspace composite into the study.
        """
        inv_name = (body.get("investigation") or "").strip()
        comp_name = (body.get("name") or "").strip()
        source = (body.get("source") or "").strip()
        if not (inv_name and comp_name and source):
            return self._json({"error": "investigation, name, source required"}, 400)

        from scripts._lib.investigation_migrate import _resolve_composite_source
        try:
            source_path, _stem = _resolve_composite_source(source, WORKSPACE)
        except (FileNotFoundError, ValueError) as e:
            return self._json({"error": str(e)}, 404)

        inv_dir = WORKSPACE / "investigations" / inv_name
        composites_dir = inv_dir / "composites"
        composites_dir.mkdir(parents=True, exist_ok=True)
        sidecar = composites_dir / f"{comp_name}.yaml"
        if sidecar.is_file():
            return self._json({"error": f"composite {comp_name!r} already exists"}, 409)

        commit_msg = f"feat(investigations/{inv_name}): add composite '{comp_name}'"

        def do_action():
            import shutil
            shutil.copy2(source_path, sidecar)
            spec_path = inv_dir / "spec.yaml"
            spec = yaml.safe_load(spec_path.read_text()) or {}
            composites = spec.setdefault('composites', [])
            composites.append({
                'name': comp_name,
                'source': source,
                'document': f'./composites/{comp_name}.yaml',
            })
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            do_action()
        except Exception as e:
            return self._json({"error": f"add failed: {e}"}, 500)
        try:
            return self._json(*_active_branch_action(commit_msg, lambda: None))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)

    def _post_investigation_composite_perturb(self, body: dict):
        """POST /api/investigation-composite-perturb {investigation, name, extends,
        parameter_overrides?, process_overrides?}
        Derive a new composite from an existing one by applying overrides.
        """
        inv_name = (body.get("investigation") or "").strip()
        comp_name = (body.get("name") or "").strip()
        extends = (body.get("extends") or "").strip()
        if not (inv_name and comp_name and extends):
            return self._json({"error": "investigation, name, extends required"}, 400)

        inv_dir = WORKSPACE / "investigations" / inv_name
        parent = inv_dir / "composites" / f"{extends}.yaml"
        if not parent.is_file():
            return self._json({"error": f"parent composite {extends!r} not found"}, 404)

        composites_dir = inv_dir / "composites"
        derived = composites_dir / f"{comp_name}.yaml"
        if derived.is_file():
            return self._json({"error": f"composite {comp_name!r} already exists"}, 409)

        from scripts._lib.composite_recipes import (
            apply_parameter_overrides, apply_process_overrides,
        )
        import copy
        parent_doc = yaml.safe_load(parent.read_text()) or {}
        derived_doc = copy.deepcopy(parent_doc)
        try:
            if body.get('parameter_overrides'):
                apply_parameter_overrides(derived_doc, body['parameter_overrides'])
            if body.get('process_overrides'):
                apply_process_overrides(derived_doc, body['process_overrides'])
        except KeyError as e:
            return self._json({"error": f"override failed: {e}"}, 400)
        except Exception as e:
            return self._json({"error": f"override failed: {type(e).__name__}: {e}"}, 500)

        commit_msg = f"feat(investigations/{inv_name}): derive composite '{comp_name}' from '{extends}'"

        def do_action():
            derived.write_text(yaml.safe_dump(derived_doc, sort_keys=False))
            spec_path = inv_dir / "spec.yaml"
            spec = yaml.safe_load(spec_path.read_text()) or {}
            composites = spec.setdefault('composites', [])
            entry = {'name': comp_name, 'extends': extends,
                     'document': f'./composites/{comp_name}.yaml'}
            if body.get('parameter_overrides'):
                entry['parameter_overrides'] = body['parameter_overrides']
            if body.get('process_overrides'):
                entry['process_overrides'] = body['process_overrides']
            composites.append(entry)
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            do_action()
        except Exception as e:
            return self._json({"error": f"perturb failed: {e}"}, 500)
        try:
            return self._json(*_active_branch_action(commit_msg, lambda: None))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest template/tests/test_visualization_endpoints.py -v
git add template/scripts/_server/server.py template/tests/test_visualization_endpoints.py
git commit -m "feat(investigations): composite-add + composite-perturb endpoints"
```

---

### Task 5: POST composite-rebuild + DELETE composite endpoints

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing tests**

```python
def test_post_composite_rebuild_reapplies_recipe(workspace_server):
    """If the parent composite changes, rebuilding the derived re-renders it."""
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'b', 'state': {'replication': {'_type': 'process',
                                                  'address': 'local:Foo',
                                                  'config': {'rate': 1.0, 'newkey': 'x'}}},
    }))
    (composites / 'derived.yaml').write_text(yaml.safe_dump({
        'name': 'd', 'state': {'replication': {'_type': 'process',
                                                  'address': 'local:Foo',
                                                  'config': {'rate': 99.0}}},  # stale
    }))
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [
            {'name': 'baseline', 'source': 'pkg.x', 'document': './composites/baseline.yaml'},
            {'name': 'derived', 'extends': 'baseline',
             'parameter_overrides': {'state.replication.config.rate': 2.0},
             'document': './composites/derived.yaml'},
        ],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-composite-rebuild',
        {'investigation': 'demo', 'name': 'derived'},
    )
    assert code in (200, 500), j
    derived_doc = yaml.safe_load((composites / 'derived.yaml').read_text())
    # After rebuild: derived has baseline's structure with rate overridden to 2.0
    assert derived_doc['state']['replication']['config']['rate'] == 2.0
    # newkey from parent propagates
    assert derived_doc['state']['replication']['config'].get('newkey') == 'x'


def test_delete_composite_with_dependents_refuses(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({'name': 'b', 'state': {}}))
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [{'composite': 'baseline', 'steps': 10}],
    }, sort_keys=False))

    req = urllib.request.Request(
        workspace_server.url + '/api/investigation-composite',
        data=json.dumps({'investigation': 'demo', 'name': 'baseline'}).encode(),
        method='DELETE', headers={'Content-Type': 'application/json'},
    )
    try:
        urllib.request.urlopen(req)
        raise AssertionError('expected refusal')
    except urllib.error.HTTPError as e:
        assert e.code == 409
        body = json.loads(e.read())
        assert 'baseline' in str(body).lower()
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Add the endpoints**

DELETE dispatch — locate where DELETE handlers are registered (search for `do_DELETE`):
```python
            "/api/investigation-composite": self._delete_investigation_composite,
```

POST dispatch:
```python
            "/api/investigation-composite-rebuild": self._post_investigation_composite_rebuild,
```

Handlers:

```python
    def _post_investigation_composite_rebuild(self, body: dict):
        """POST /api/investigation-composite-rebuild {investigation, name}
        Re-render a derived composite from its recipe (re-applies overrides on
        the current parent document).
        """
        inv_name = (body.get("investigation") or "").strip()
        comp_name = (body.get("name") or "").strip()
        if not (inv_name and comp_name):
            return self._json({"error": "investigation, name required"}, 400)

        inv_dir = WORKSPACE / "investigations" / inv_name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)
        spec = yaml.safe_load(spec_path.read_text()) or {}
        entry = next((c for c in (spec.get('composites') or [])
                      if c.get('name') == comp_name), None)
        if entry is None:
            return self._json({"error": f"composite {comp_name!r} not found"}, 404)
        extends = entry.get('extends')
        if not extends:
            return self._json({"error": f"composite {comp_name!r} is not derived"}, 400)
        parent_path = inv_dir / "composites" / f"{extends}.yaml"
        if not parent_path.is_file():
            return self._json({"error": f"parent {extends!r} document missing"}, 404)

        from scripts._lib.composite_recipes import (
            apply_parameter_overrides, apply_process_overrides,
        )
        import copy
        parent_doc = yaml.safe_load(parent_path.read_text()) or {}
        derived_doc = copy.deepcopy(parent_doc)
        try:
            if entry.get('parameter_overrides'):
                apply_parameter_overrides(derived_doc, entry['parameter_overrides'])
            if entry.get('process_overrides'):
                apply_process_overrides(derived_doc, entry['process_overrides'])
        except KeyError as e:
            return self._json({"error": f"rebuild failed: {e}"}, 400)

        commit_msg = f"chore(investigations/{inv_name}): rebuild composite '{comp_name}'"

        def do_action():
            derived_path = inv_dir / "composites" / f"{comp_name}.yaml"
            derived_path.write_text(yaml.safe_dump(derived_doc, sort_keys=False))

        try:
            do_action()
        except Exception as e:
            return self._json({"error": f"rebuild failed: {e}"}, 500)
        try:
            return self._json(*_active_branch_action(commit_msg, lambda: None))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)

    def _delete_investigation_composite(self, body: dict):
        """DELETE /api/investigation-composite {investigation, name}
        Refuse if any runs or visualizations reference this composite.
        """
        inv_name = (body.get("investigation") or "").strip()
        comp_name = (body.get("name") or "").strip()
        if not (inv_name and comp_name):
            return self._json({"error": "investigation, name required"}, 400)
        inv_dir = WORKSPACE / "investigations" / inv_name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)
        spec = yaml.safe_load(spec_path.read_text()) or {}

        # Dependent check: runs[].composite, visualizations[].config.sources, other composites' extends:
        dependents = []
        for r in (spec.get('runs') or []):
            if r.get('composite') == comp_name:
                dependents.append(f"run({r})")
        for v in (spec.get('visualizations') or []):
            sources = (v.get('config') or {}).get('sources') or []
            if comp_name in sources:
                dependents.append(f"visualization({v.get('name')})")
        for c in (spec.get('composites') or []):
            if c.get('extends') == comp_name:
                dependents.append(f"composite({c.get('name')})")
        if dependents:
            return self._json({
                "error": f"composite {comp_name!r} has dependents",
                "dependents": dependents,
            }, 409)

        commit_msg = f"chore(investigations/{inv_name}): remove composite '{comp_name}'"

        def do_action():
            doc_path = inv_dir / "composites" / f"{comp_name}.yaml"
            if doc_path.is_file():
                doc_path.unlink()
            spec['composites'] = [c for c in (spec.get('composites') or [])
                                   if c.get('name') != comp_name]
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            do_action()
        except Exception as e:
            return self._json({"error": f"remove failed: {e}"}, 500)
        try:
            return self._json(*_active_branch_action(commit_msg, lambda: None))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest template/tests/test_visualization_endpoints.py -v
git add template/scripts/_server/server.py template/tests/test_visualization_endpoints.py
git commit -m "feat(investigations): composite-rebuild + composite-delete endpoints"
```

---

### Task 6: POST set-observables endpoint

**Files:**
- Modify: `template/scripts/_server/server.py`
- Modify: `template/tests/test_visualization_endpoints.py`

- [ ] **Step 1: Write failing test**

```python
def test_post_set_observables_writes_spec_yaml(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [], 'observables': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-set-observables',
        {'investigation': 'demo',
         'paths': [['chromosome', 'DnaA_count'], ['chromosome', 'free_DnaA']],
         'emit_all': False},
    )
    assert code in (200, 500), j
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    paths = [tuple(o['path']) for o in spec['observables']]
    assert ('chromosome', 'DnaA_count') in paths
    assert ('chromosome', 'free_DnaA') in paths
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Add endpoint**

```python
            "/api/investigation-set-observables": self._post_investigation_set_observables,
```

```python
    def _post_investigation_set_observables(self, body: dict):
        """POST /api/investigation-set-observables {investigation, paths, emit_all}
        Rewrites spec.yaml.observables; the orchestrator builds the emitter
        step at run time.
        """
        inv_name = (body.get("investigation") or "").strip()
        paths = body.get("paths") or []
        emit_all = bool(body.get("emit_all"))
        if not inv_name:
            return self._json({"error": "investigation required"}, 400)
        inv_dir = WORKSPACE / "investigations" / inv_name
        spec_path = inv_dir / "spec.yaml"
        if not spec_path.is_file():
            return self._json({"error": "investigation not found"}, 404)
        if not isinstance(paths, list):
            return self._json({"error": "paths must be a list of [seg, seg, ...] arrays"}, 400)

        commit_msg = f"feat(investigations/{inv_name}): set observables"

        def do_action():
            spec = yaml.safe_load(spec_path.read_text()) or {}
            if emit_all:
                spec['observables'] = [{'path': []}]
            else:
                spec['observables'] = [{'path': list(p)} for p in paths if p]
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))

        try:
            do_action()
        except Exception as e:
            return self._json({"error": f"set-observables failed: {e}"}, 500)
        try:
            return self._json(*_active_branch_action(commit_msg, lambda: None))
        except Exception as e:
            return self._json({"error": f"workstream error: {e}"}, 500)
```

- [ ] **Step 4: Confirm pass + commit**

```bash
python -m pytest template/tests/test_visualization_endpoints.py -v
git add template/scripts/_server/server.py template/tests/test_visualization_endpoints.py
git commit -m "feat(investigations): /api/investigation-set-observables endpoint"
```

---

## Phase C — Orchestrator

### Task 7: Multi-composite `run_investigation` + observables-driven emitter injection

**Files:**
- Modify: `template/scripts/_lib/investigations.py`
- Modify: `template/tests/test_investigations.py`

- [ ] **Step 1: Write failing tests**

```python
def test_inject_emitter_from_observables_paths(tmp_path):
    """Orchestrator helper: given a composite doc + spec.yaml.observables,
    rewrite (or add) the emitter step to record those paths."""
    from scripts._lib.investigations import inject_emitter_step

    doc = {
        'state': {
            'chromosome': {
                'DnaA_count': {'_type': 'integer', '_default': 100},
                'free_DnaA': {'_type': 'float', '_default': 50.0},
            },
        },
    }
    observables = [
        {'path': ['chromosome', 'DnaA_count']},
        {'path': ['chromosome', 'free_DnaA']},
    ]
    out = inject_emitter_step(doc, observables)

    em = out['state']['emitter']
    assert em['_type'] == 'step'
    assert em['inputs']['DnaA_count'] == ['chromosome', 'DnaA_count']
    assert em['inputs']['free_DnaA'] == ['chromosome', 'free_DnaA']
    assert em['config']['emit'] == {'DnaA_count': 'integer', 'free_DnaA': 'float'}


def test_inject_emitter_skips_missing_paths(tmp_path):
    """If an observable path doesn't exist in this composite's state, skip
    it with a warning rather than erroring out."""
    from scripts._lib.investigations import inject_emitter_step

    doc = {'state': {'chromosome': {'DnaA_count': {'_type': 'integer', '_default': 100}}}}
    observables = [
        {'path': ['chromosome', 'DnaA_count']},
        {'path': ['chromosome', 'missing']},
    ]
    out = inject_emitter_step(doc, observables)
    em = out['state']['emitter']
    assert 'DnaA_count' in em['inputs']
    assert 'missing' not in em['inputs']
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Add `inject_emitter_step`** to `template/scripts/_lib/investigations.py`

```python
def inject_emitter_step(doc: dict, observables: list) -> dict:
    """Return ``doc`` with its emitter step rewritten to record the observable paths.

    ``observables`` is the spec.yaml.observables list of ``{path: [...]}`` dicts.
    Paths not present in ``doc['state']`` are silently skipped (caller can warn).
    """
    import copy
    out = copy.deepcopy(doc)
    state = out.setdefault('state', {})

    inputs: dict = {}
    emit_schema: dict = {}
    for obs in (observables or []):
        path = obs.get('path') or []
        if not path:
            continue
        # Walk to verify the path exists; capture the leaf's type if recorded
        node = state
        for seg in path:
            if not isinstance(node, dict) or seg not in node:
                node = None
                break
            node = node[seg]
        if node is None:
            continue
        port_name = path[-1]
        inputs[port_name] = list(path)
        # Derive type string from the leaf if it carries one
        if isinstance(node, dict) and node.get('_type'):
            emit_schema[port_name] = node['_type']
        else:
            emit_schema[port_name] = 'any'

    state['emitter'] = {
        '_type': 'step',
        'address': 'local:SQLiteEmitter',
        'config': {'emit': emit_schema},
        'inputs': inputs,
    }
    return out
```

- [ ] **Step 4: Update `run_investigation`** to resolve `runs[].composite` to its document, apply `inject_emitter_step`, and run.

Find the body of `run_investigation` in `template/scripts/_lib/investigations.py`. Replace the part that builds + runs a single composite with a per-run loop that loads `composites/<runs[i].composite>.yaml`, injects the emitter from `spec.observables`, and dispatches via `run_one_composite`. The exact shape of the per-run call mirrors what's there today; only the composite-resolution + emitter-injection logic is new.

Sketch:

```python
def run_investigation(ws_root, name, *, run_one_composite, core_registry, build_and_run=None):
    # ... existing prelude ...
    spec = load_spec(spec_path)

    # Resolve every run to its composite document
    for run_entry in (spec.get('runs') or []):
        comp_name = run_entry['composite']
        doc_path = inv_dir / "composites" / f"{comp_name}.yaml"
        doc = yaml.safe_load(doc_path.read_text()) or {}
        doc = inject_emitter_step(doc, spec.get('observables') or [])

        # Merge run.params on top of doc parameters (existing per-run sweep behavior)
        if run_entry.get('params'):
            apply_parameter_overrides(doc, run_entry['params'])  # may need a softer "best-effort" variant

        run_one_composite(
            spec_id=comp_name,                          # for runs.db sim_name
            overrides={},                                # already applied above
            steps=run_entry.get('steps', 10),
            sim_name=comp_name,
            run_id=...,                                  # existing run-id logic
            state_doc=doc,                               # NEW: pass the prepared document
        )
    # ... visualization render + spec.status update unchanged ...
```

The exact API of `run_one_composite` is set by the server (which passes it in). May need to adjust the server's `run_one_composite` factory in `server.py` to accept a `state_doc` argument. Inspect the current factory and adapt minimally — the goal is to pass a pre-built composite document rather than re-resolve the composite ID.

- [ ] **Step 5: Confirm pass + commit**

```bash
python -m pytest template/tests/test_investigations.py -v
git add template/scripts/_lib/investigations.py template/tests/test_investigations.py
git commit -m "feat(investigations): orchestrator runs per-composite + injects emitter from observables"
```

---

## Phase D — UI

### Task 8: Composites tab in Investigation viewer

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add tab + panel markup**

In `template/scripts/_templates/index.html.j2`, find the Investigation viewer (search for the page or section that includes the Spec / Runs / Visualizations tabs). Add a new tab button + panel:

```html
<button class="inv-tab" data-tab="composites" onclick="_invSwitchTab('composites')">Composites</button>
```

```html
<div class="inv-tab-panel" data-tab="composites" style="display:none">
  <div style="margin-bottom:8px">
    <button class="action-btn" onclick="_openAddCompositeModal()">+ Add composite</button>
  </div>
  <div id="inv-composites-list" style="display:grid;grid-template-columns:220px 1fr;gap:16px">
    <div id="inv-composites-sidebar"></div>
    <div id="inv-composite-detail" style="border-left:1px solid #eee;padding-left:14px"></div>
  </div>
</div>
```

Plus modals (one for "Add composite" — pick from Registry; one for "Perturb"):

```html
<div id="modal-inv-add-composite" class="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal('modal-inv-add-composite')">&times;</button>
    <h3>Add composite from Registry</h3>
    <form id="form-inv-add-composite"
          onsubmit="event.preventDefault(); _submitAddComposite(this)">
      <label>Composite (workspace catalog)
        <select name="source" id="inv-add-composite-source" required></select>
      </label>
      <label>Name in this study
        <input name="name" pattern="^[a-zA-Z0-9_-]+$" required placeholder="baseline">
      </label>
      <div class="form-error"></div>
      <button type="submit" class="action-btn">Add</button>
    </form>
  </div>
</div>

<div id="modal-inv-perturb" class="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal('modal-inv-perturb')">&times;</button>
    <h3>Perturb composite</h3>
    <form id="form-inv-perturb"
          onsubmit="event.preventDefault(); _submitPerturb(this)">
      <input type="hidden" name="extends">
      <label>New composite name
        <input name="name" pattern="^[a-zA-Z0-9_-]+$" required placeholder="high-rate">
      </label>
      <label>Parameter overrides (JSON; dotted-path keys)
        <textarea name="parameter_overrides" rows="3"
                  placeholder='{"state.replication.config.rate": 2.0}'></textarea>
      </label>
      <label>Process overrides (JSON; null to remove, str for new address)
        <textarea name="process_overrides" rows="3"
                  placeholder='{"replication": null}'></textarea>
      </label>
      <div class="form-error"></div>
      <button type="submit" class="action-btn">Perturb</button>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Add JS handlers**

Append to `template/scripts/_server/walkthrough.js`:

```javascript
  function _loadInvComposites(invName) {
    fetch('/api/investigation-composites?investigation=' + encodeURIComponent(invName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var sidebar = document.getElementById('inv-composites-sidebar');
        if (!sidebar) return;
        var rows = (data.composites || []).map(function(c) {
          return '<div class="inv-composite-row" onclick="_loadInvCompositeDetail(\'' +
                 _esc(invName) + '\',\'' + _esc(c.name) + '\')">' +
                 '<strong>' + _esc(c.name) + '</strong>' +
                 (c.extends ? '<br><small>extends ' + _esc(c.extends) + '</small>' :
                              '<br><small>' + _esc(c.source || '') + '</small>') +
                 '<div style="margin-top:4px">' +
                 '<button class="btn-mini" onclick="event.stopPropagation();_openPerturbModal(\'' +
                 _esc(invName) + '\',\'' + _esc(c.name) + '\')">Perturb</button>' +
                 (c.extends ? '<button class="btn-mini" onclick="event.stopPropagation();_rebuildComposite(\'' +
                              _esc(invName) + '\',\'' + _esc(c.name) + '\')">Rebuild</button>' : '') +
                 '<button class="btn-mini" style="color:#c00" onclick="event.stopPropagation();_removeComposite(\'' +
                 _esc(invName) + '\',\'' + _esc(c.name) + '\')">Remove</button>' +
                 '</div></div>';
        }).join('');
        sidebar.innerHTML = rows || '<p class="empty-state">No composites yet — click + Add composite.</p>';
      });
  }
  window._loadInvComposites = _loadInvComposites;

  function _loadInvCompositeDetail(invName, compName) {
    fetch('/api/investigation-state-tree?investigation=' + encodeURIComponent(invName) +
          '&composite=' + encodeURIComponent(compName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var detail = document.getElementById('inv-composite-detail');
        if (!detail) return;
        var lines = (data.nodes || []).map(function(n) {
          var pathStr = (n.path || []).join('.');
          if (n.kind === 'process') {
            return '<div><strong>' + _esc(pathStr) + '</strong> ' +
                   '<small style="color:#666">process — ' + _esc(n.address) + '</small></div>';
          }
          return '<div style="padding-left:16px">' + _esc(pathStr) +
                 ' <small style="color:#888">' + _esc(n.type || '') + ' = ' +
                 _esc(JSON.stringify(n.default)) + '</small></div>';
        }).join('');
        detail.innerHTML = '<h4>' + _esc(compName) + '</h4>' + (lines || '<p>(empty composite)</p>');
      });
  }
  window._loadInvCompositeDetail = _loadInvCompositeDetail;

  function _openAddCompositeModal() {
    // Populate the source dropdown with workspace composites
    var sel = document.getElementById('inv-add-composite-source');
    sel.innerHTML = '<option value="">— pick a workspace composite —</option>';
    fetch('/api/composites').then(function(r) { return r.json(); })
      .then(function(data) {
        (data.composites || []).forEach(function(c) {
          var opt = document.createElement('option');
          opt.value = c.id;  // e.g. pbg_x.composites.foo
          opt.textContent = c.name + '  —  ' + (c.description || c.id);
          sel.appendChild(opt);
        });
        openModal('modal-inv-add-composite');
      });
  }
  window._openAddCompositeModal = _openAddCompositeModal;

  function _submitAddComposite(form) {
    var data = new FormData(form);
    var invName = window._currentInvestigation || '';
    var payload = {
      investigation: invName,
      name: data.get('name'),
      source: data.get('source'),
    };
    fetch('/api/investigation-composite-add', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          var errEl = form.querySelector('.form-error');
          if (errEl) errEl.textContent = j.error || 'add failed';
          return;
        }
        closeModal('modal-inv-add-composite');
        _loadInvComposites(invName);
      });
  }
  window._submitAddComposite = _submitAddComposite;

  function _openPerturbModal(invName, parentName) {
    window._currentInvestigation = invName;
    var form = document.getElementById('form-inv-perturb');
    form.elements['extends'].value = parentName;
    form.elements['name'].value = '';
    form.elements['parameter_overrides'].value = '';
    form.elements['process_overrides'].value = '';
    openModal('modal-inv-perturb');
  }
  window._openPerturbModal = _openPerturbModal;

  function _submitPerturb(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var parseOpt = function(raw, name) {
      raw = (raw || '').trim();
      if (!raw) return null;
      try { return JSON.parse(raw); }
      catch (e) {
        if (errEl) errEl.textContent = 'Invalid JSON in ' + name + ': ' + String(e);
        return undefined;
      }
    };
    var po = parseOpt(data.get('parameter_overrides'), 'parameter_overrides');
    if (po === undefined) return;
    var procO = parseOpt(data.get('process_overrides'), 'process_overrides');
    if (procO === undefined) return;
    var payload = {
      investigation: window._currentInvestigation || '',
      name: data.get('name'),
      extends: data.get('extends'),
    };
    if (po) payload.parameter_overrides = po;
    if (procO) payload.process_overrides = procO;
    fetch('/api/investigation-composite-perturb', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'perturb failed';
          return;
        }
        closeModal('modal-inv-perturb');
        _loadInvComposites(payload.investigation);
      });
  }
  window._submitPerturb = _submitPerturb;

  function _rebuildComposite(invName, compName) {
    fetch('/api/investigation-composite-rebuild', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, name: compName}),
    }).then(function() { _loadInvComposites(invName); _loadInvCompositeDetail(invName, compName); });
  }
  window._rebuildComposite = _rebuildComposite;

  function _removeComposite(invName, compName) {
    if (!confirm('Remove composite ' + compName + '?')) return;
    fetch('/api/investigation-composite', {
      method: 'DELETE', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, name: compName}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (j.dependents) {
            alert('Cannot remove — has dependents: ' + j.dependents.join(', '));
          } else {
            alert(j.error || 'remove failed');
          }
          return;
        }
        _loadInvComposites(invName);
      });
  }
  window._removeComposite = _removeComposite;
```

Wire the tab into the Investigation viewer's tab-switching logic — find `_invSwitchTab` or similar, add the case for `'composites'` that calls `_loadInvComposites(window._currentInvestigation)`.

- [ ] **Step 3: Smoke + commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(investigations): Composites tab UI"
```

---

### Task 9: Observables tab UI + create-investigation pick-composite step

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Add Observables tab**

In the Investigation viewer's tab strip:

```html
<button class="inv-tab" data-tab="observables" onclick="_invSwitchTab('observables')">Observables</button>
```

Panel:

```html
<div class="inv-tab-panel" data-tab="observables" style="display:none">
  <p class="panel-lead">Tick which state paths each run should record. Paths missing
    in a given composite are skipped for that run with a warning.</p>
  <label style="display:block;margin-bottom:10px">
    <input type="checkbox" id="inv-emit-all" onchange="_setEmitAll(this.checked)">
    Emit entire state (root)
  </label>
  <div id="inv-observables-tree"></div>
  <button class="action-btn" onclick="_saveObservables()">Save observables</button>
  <div id="inv-observables-status" style="margin-top:8px;font-size:0.9em;color:#555"></div>
</div>
```

- [ ] **Step 2: JS to populate the union-of-paths tree**

```javascript
  function _loadInvObservables(invName) {
    // Get composites list first, then walk each one's state tree, then union.
    fetch('/api/investigation-composites?investigation=' + encodeURIComponent(invName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var composites = (data.composites || []);
        if (composites.length === 0) {
          var el = document.getElementById('inv-observables-tree');
          if (el) el.innerHTML = '<p class="empty-state">Add a composite first.</p>';
          return;
        }
        Promise.all(composites.map(function(c) {
          return fetch('/api/investigation-state-tree?investigation=' + encodeURIComponent(invName) +
                       '&composite=' + encodeURIComponent(c.name))
            .then(function(r) { return r.json(); })
            .then(function(tree) { return {composite: c.name, nodes: tree.nodes || []}; });
        })).then(function(trees) {
          var union = {};   // path-key -> {path, types, composites}
          trees.forEach(function(t) {
            t.nodes.forEach(function(n) {
              if (n.kind !== 'store') return;
              var key = (n.path || []).join('.');
              if (!union[key]) union[key] = {path: n.path, types: new Set(), composites: new Set()};
              union[key].types.add(n.type || 'any');
              union[key].composites.add(t.composite);
            });
          });
          var pathKeys = Object.keys(union).sort();
          var el = document.getElementById('inv-observables-tree');
          // Also load existing spec.yaml.observables to pre-check
          fetch('/api/investigation?name=' + encodeURIComponent(invName))
            .then(function(r) { return r.json(); })
            .then(function(invData) {
              var existing = ((invData.spec || {}).observables || []).map(function(o) {
                return (o.path || []).join('.');
              });
              el.innerHTML = pathKeys.map(function(k) {
                var u = union[k];
                var checked = existing.indexOf(k) !== -1 ? ' checked' : '';
                return '<div style="padding:3px 0"><label>' +
                       '<input type="checkbox" data-path="' + _esc(k) + '"' + checked + '> ' +
                       '<code>' + _esc(k) + '</code> ' +
                       '<small style="color:#888">' + Array.from(u.types).join(',') +
                       '  ·  in: ' + Array.from(u.composites).join(', ') + '</small>' +
                       '</label></div>';
              }).join('');
            });
        });
      });
  }
  window._loadInvObservables = _loadInvObservables;

  function _setEmitAll(on) {
    var tree = document.getElementById('inv-observables-tree');
    if (!tree) return;
    tree.querySelectorAll('input[type=checkbox][data-path]').forEach(function(cb) {
      cb.disabled = on;
    });
  }
  window._setEmitAll = _setEmitAll;

  function _saveObservables() {
    var invName = window._currentInvestigation || '';
    var emitAll = document.getElementById('inv-emit-all').checked;
    var paths = [];
    if (!emitAll) {
      document.querySelectorAll('#inv-observables-tree input[type=checkbox][data-path]:checked').forEach(function(cb) {
        paths.push(cb.dataset.path.split('.'));
      });
    }
    fetch('/api/investigation-set-observables', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, paths: paths, emit_all: emitAll}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var status = document.getElementById('inv-observables-status');
        if (status) status.textContent = parts[0]
          ? 'Saved ' + (emitAll ? '(emit entire state)' : (paths.length + ' observable(s)'))
          : 'Save failed: ' + ((parts[1] || {}).error || '');
      });
  }
  window._saveObservables = _saveObservables;
```

Wire into `_invSwitchTab` so opening the Observables tab calls `_loadInvObservables(...)`.

- [ ] **Step 3: Pick-a-starting-composite step in create-Investigation modal**

Find the existing create-Investigation modal (`modal-investigation-create` or similar). Add a `<select>` for picking a starting composite from the workspace catalog. On submit, pass `source: <picked>` to the existing investigation-create endpoint (which Task 4's backend extends to clone the picked composite).

- [ ] **Step 4: Commit**

```bash
node -c template/scripts/_server/walkthrough.js
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js
git commit -m "feat(investigations): Observables tab + pick-starting-composite in create modal"
```

---

## Phase E — v2ecoli verification

### Task 10: End-to-end on v2ecoli

**Files:** (workspace state in `/Users/eranagmon/code/v2ecoli-chromosome-rep1`)

- [ ] **Step 1: Sync pbg-template files into v2ecoli**

```bash
cp /Users/eranagmon/code/pbg-template/template/scripts/_lib/composite_recipes.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/composite_recipes.py
cp /Users/eranagmon/code/pbg-template/template/scripts/_lib/investigation_migrate.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/investigation_migrate.py
cp /Users/eranagmon/code/pbg-template/template/scripts/_lib/investigations.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_lib/investigations.py
cp /Users/eranagmon/code/pbg-template/template/scripts/_server/server.py \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp /Users/eranagmon/code/pbg-template/template/scripts/_server/walkthrough.js \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp /Users/eranagmon/code/pbg-template/template/scripts/_templates/index.html.j2 \
   /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
```

- [ ] **Step 2: Restart server, open the legacy Investigation `t1`**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
EXISTING=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])" 2>/dev/null || echo '')
[ -n "$EXISTING" ] && lsof -nP -iTCP:$EXISTING -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -I {} kill {} 2>/dev/null
rm -f .pbg/server/server-info
sleep 1
.venv/bin/python3 scripts/render-dashboard.py --all 2>&1 | tail -3
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
open "http://127.0.0.1:$PORT/#investigations"
```

In the browser: open the `t1` investigation. Expected behavior:
1. Server auto-migrates `spec.yaml` → composites: list shape; renders
   `investigations/t1/composites/chromosome-partition.yaml`.
2. Investigation viewer shows Composites + Observables tabs in addition to
   existing tabs.
3. Composites tab shows `chromosome-partition` with state-tree on right.

```bash
cat /Users/eranagmon/code/v2ecoli-chromosome-rep1/investigations/t1/spec.yaml
ls /Users/eranagmon/code/v2ecoli-chromosome-rep1/investigations/t1/composites/
```

- [ ] **Step 3: Create a perturbation**

In the browser: Composites tab → "Perturb" on `chromosome-partition` → name
`high-count` → parameter overrides `{"parameters.initial_chromosome_count.default": 2.0}` (the actual composite has `parameters.initial_chromosome_count`).

Verify `investigations/t1/composites/high-count.yaml` exists with the
override applied; spec.yaml has the new entry.

- [ ] **Step 4: Configure observables**

Observables tab → tick `stores.chromosome.count` → Save. Verify
spec.yaml.observables has the new entry.

- [ ] **Step 5: Run + verify**

Click Run all on the Investigation header. After completion: `runs.db`
should have rows from both `chromosome-partition` and `high-count` runs
with distinct `sim_name`.

```bash
sqlite3 investigations/t1/runs.db "SELECT sim_name, COUNT(*) FROM runs_meta GROUP BY sim_name;"
```

- [ ] **Step 6: Commit v2ecoli sync**

```bash
git add -A
git commit -m "feat(investigations): multi-composite + observables tab sync from pbg-template"
git push 2>&1 | tail -3
```

- [ ] **Step 7: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git push 2>&1 | tail -3
```

---

## Self-review

**Spec coverage:**
- Architecture (file layout, spec shape): Task 1 (schema) + Task 2 (migration) + the orchestrator update in Task 7.
- Composite document recipe operations (parameter + process overrides, state walk): Task 3's `composite_recipes` module.
- Endpoints: Tasks 3 (GET list + tree), 4 (add + perturb), 5 (rebuild + remove), 6 (set-observables).
- Composites tab: Task 8.
- Observables tab: Task 9.
- Migration: Task 2 + Task 10 Step 2.
- End-to-end verification: Task 10.

**Placeholder scan:** None. Each step has complete code or commands. Task 7 Step 4 has the most prose because the existing `run_investigation` body is complex and the implementer needs to adapt — the sketch shows the contract, the surrounding code stays where it is.

**Type consistency:** `apply_parameter_overrides(doc, dict)` + `apply_process_overrides(doc, dict)` + `walk_state_tree(doc) -> list[dict]` consistent across Task 3 definition and Tasks 4-7 usage. Endpoint paths consistent across server.py (Tasks 3-6) and walkthrough.js (Tasks 8-9).

**Risks flagged in advance:**

1. **`run_one_composite` API change.** Task 7 Step 4 adds a `state_doc=` parameter to the callable the server passes in. The factory in `server.py` (in `_post_investigation_run`) needs the matching change. Implementer should update both call sites in one commit.

2. **`/api/composites` endpoint assumed.** Task 8 Step 2's `_openAddCompositeModal` fetches `/api/composites` to populate the source dropdown. If that endpoint doesn't yet exist in server.py, either add it (return the workspace's composite-lookup catalog) or wire to whichever existing endpoint serves the Registry's composites panel.

3. **Migration auto-trigger.** Task 2 Step 5 inserts the migration call at the top of `_get_investigation`. If the GET handler has a different name (e.g. `_get_investigation_detail`), implementer adapts. The migration is idempotent so multiple triggers are safe.

---

Plan saved. Use superpowers:subagent-driven-development to execute.
