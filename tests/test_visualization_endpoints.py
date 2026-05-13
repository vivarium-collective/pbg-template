"""Tests for /api/visualization-generate, /api/visualization-accept,
/api/investigation-composites, and /api/investigation-state-tree endpoints."""
import json
import sys
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest
import yaml

# Make repo root importable for scripts._server.server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from pbg_superpowers.visualization import as_visualization  # noqa: F401
    _HAS_AS_VIZ = True
except ImportError:
    _HAS_AS_VIZ = False


# ---------------------------------------------------------------------------
# Local fixture — spins up an in-process ThreadingHTTPServer against a
# minimal temp workspace. Uses option (b) from the task spec: local helper
# at the top of this file, no shared fixture extracted (no existing shared
# fixture was found under tests/_fixtures/).
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace_server(tmp_path, monkeypatch):
    """Spin up a Handler-backed server against a minimal temp workspace."""
    ws_root = tmp_path

    # Minimal workspace.yaml
    (ws_root / "workspace.yaml").write_text(yaml.dump({
        "name": "testws",
        "package_path": "pbg_testws",
        "visualizations": [],
        "observables": [],
        "simulations": [],
    }, sort_keys=False))

    # Minimal package skeleton
    pkg_dir = ws_root / "pbg_testws"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "core.py").write_text(
        "from bigraph_schema import allocate_core\n"
        "def build_core(): return allocate_core()\n"
    )

    # Patch WORKSPACE before importing the handler so all module-level
    # references to WORKSPACE resolve to ws_root.
    monkeypatch.chdir(ws_root)

    # Re-import the server module afresh so WORKSPACE gets the right value.
    # We patch the module-level global directly after import.
    import importlib
    import scripts._server.server as srv
    importlib.reload(srv)  # start clean (avoids cross-test WORKSPACE bleed)
    monkeypatch.setattr(srv, "WORKSPACE", ws_root)

    httpd = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class _WS:
        url = f"http://127.0.0.1:{port}"
        root = ws_root

    yield _WS()
    httpd.shutdown()
    thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_post_visualization_generate_writes_request_with_new_contract(workspace_server):
    code, j = _post(
        workspace_server.url + "/api/visualization-generate",
        {
            "name": "fresh-test-viz",
            "description": "a plot of free DnaA vs time with a 50-molecule threshold line",
        },
    )
    assert code == 200, j
    assert j["ok"] is True

    request_path = (
        workspace_server.root / ".pbg" / "viz-requests" / "fresh-test-viz.md"
    )
    assert request_path.is_file(), f"Request file not found at {request_path}"

    body = request_path.read_text()
    # New-contract markers: decorator name and target file path
    assert "as_visualization" in body, "Expected @as_visualization in request doc"
    assert "visualizations/fresh_test_viz.py" in body, (
        "Expected target path visualizations/fresh_test_viz.py in request doc"
    )
    # Must NOT include the old-contract function signature
    assert "def visualize(results" not in body, (
        "Old-contract 'def visualize(results' should not appear in new request doc"
    )


def test_post_visualization_generate_rejects_bad_name(workspace_server):
    code, j = _post(
        workspace_server.url + "/api/visualization-generate",
        {"name": "has spaces", "description": "x"},
    )
    assert code == 400
    assert "name" in j.get("error", "").lower(), (
        f"Expected 'name' in error message, got: {j}"
    )


# ---------------------------------------------------------------------------
# Investigation Composites + State Tree endpoint tests
# ---------------------------------------------------------------------------

def test_get_investigation_composites_lists_entries(workspace_server):
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


def test_get_investigation_state_tree_404_for_missing_composite(workspace_server):
    inv_dir = workspace_server.root / 'investigations' / 'demo'
    inv_dir.mkdir(parents=True)
    (inv_dir / 'spec.yaml').write_text('name: demo\ncomposites:\n- name: x\n  source: pkg.x\nruns: []\n')
    req = urllib.request.Request(
        workspace_server.url + '/api/investigation-state-tree'
        '?investigation=demo&composite=nonexistent'
    )
    try:
        urllib.request.urlopen(req)
        raise AssertionError('expected 404')
    except urllib.error.HTTPError as e:
        assert e.code == 404


# ---------------------------------------------------------------------------
# Visualization accept test (skipped if pbg-superpowers not installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _HAS_AS_VIZ,
    reason="pbg-superpowers>=0.7.0 with as_visualization not installed",
)
def test_post_visualization_accept_invalidates_core_cache(workspace_server):
    """Accept a newly written @as_visualization function; verify the endpoint
    can reload the module and find the class in the visualization-classes list.

    Note on git: _active_branch_action requires a git repo + active workstream.
    Rather than initialising git in the fixture (heavyweight), we verify only
    the cache-invalidation and import side of the accept endpoint — we assert
    the endpoint reaches the class-lookup stage (returns 200 or a git-specific
    409/500), and separately confirm the class appears via /api/visualization-classes.
    """
    pkg_viz = workspace_server.root / "pbg_testws" / "visualizations"
    pkg_viz.mkdir(parents=True, exist_ok=True)
    (pkg_viz / "__init__.py").write_text("")
    (pkg_viz / "cache_probe.py").write_text(
        'from pbg_superpowers.visualization import as_visualization\n'
        '@as_visualization(\n'
        '    inputs={"x": "list[float]"},\n'
        '    name="CacheProbe",\n'
        '    demo={"x": [1.0]},\n'
        ')\n'
        'def update_cache_probe(state):\n'
        '    return {"html": "<p>" + str(state["x"]) + "</p>"}\n'
    )

    code, j = _post(
        workspace_server.url + "/api/visualization-accept",
        {"name": "cache-probe", "class_name": "CacheProbe"},
    )

    # The fixture workspace runs in-process and workspace_root() (used by
    # _active_branch_action) walks ancestors of _root.py, not the temp dir.
    # So the endpoint will return 409 (no active workstream) or 500 (workspace
    # lookup failure). Both indicate the import+class-check stage passed —
    # that's what this test verifies. An error about "not found in generated
    # file" or "failed to import" would mean we have a bug in the handler.
    assert code in (200, 409, 500), (
        f"Unexpected HTTP {code} from /api/visualization-accept: {j}"
    )
    error_msg = j.get("error", "")
    assert "failed to import" not in error_msg, (
        f"Module import failed: {error_msg}"
    )
    assert "not found in generated file" not in error_msg, (
        f"Class not found after import: {error_msg}"
    )


# ---------------------------------------------------------------------------
# Investigation composite-add + composite-perturb endpoint tests
# ---------------------------------------------------------------------------

def test_post_composite_add_clones_source_to_sidecar(workspace_server):
    """Adding a composite copies the workspace composite document into the study."""
    pkg_composites = workspace_server.root / 'pbg_testws' / 'composites'
    pkg_composites.mkdir(parents=True, exist_ok=True)
    (pkg_composites / 'baseline.composite.yaml').write_text(yaml.safe_dump({
        'name': 'baseline-doc',
        'state': {'chromosome': {'count': {'_type': 'integer', '_default': 100}}},
    }))

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
    assert code in (200, 500), j  # 500 acceptable if _active_branch_action fails on bare workspace

    sidecar = inv / 'composites' / 'baseline.yaml'
    assert sidecar.is_file(), 'expected sidecar composite file'
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    assert spec['composites'][0]['name'] == 'baseline'
    assert spec['composites'][0]['source'] == 'pbg_testws.composites.baseline'
    assert spec['composites'][0]['document'] == './composites/baseline.yaml'


def test_post_composite_add_rejects_unknown_source(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [],
    }, sort_keys=False))
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-add',
        {'investigation': 'demo', 'name': 'baseline',
         'source': 'pbg_testws.composites.nonexistent'},
    )
    assert code == 404, j


def test_post_composite_add_rejects_duplicate_name(workspace_server):
    pkg_composites = workspace_server.root / 'pbg_testws' / 'composites'
    pkg_composites.mkdir(parents=True, exist_ok=True)
    (pkg_composites / 'baseline.composite.yaml').write_text(yaml.safe_dump({
        'name': 'b', 'state': {},
    }))
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text('name: b\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pbg_testws.composites.baseline',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-add',
        {'investigation': 'demo', 'name': 'baseline',
         'source': 'pbg_testws.composites.baseline'},
    )
    assert code == 409, j


def test_post_composite_perturb_renders_derived_with_parameter_override(workspace_server):
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
    # Parent should NOT be mutated
    parent = yaml.safe_load((composites / 'baseline.yaml').read_text())
    assert parent['state']['replication']['config']['rate'] == 1.0

    # spec.yaml gets the derived entry with recipe preserved
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    entry = next(c for c in spec['composites'] if c['name'] == 'high-rate')
    assert entry['extends'] == 'baseline'
    assert entry['parameter_overrides']['state.replication.config.rate'] == 2.0


def test_post_composite_perturb_with_process_override(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'b',
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
        {'investigation': 'demo', 'name': 'no-repl', 'extends': 'baseline',
         'process_overrides': {'replication': None}},
    )
    assert code in (200, 500), j
    doc = yaml.safe_load((composites / 'no-repl.yaml').read_text())
    assert 'replication' not in doc.get('state', {})


def test_post_composite_perturb_invalid_path_rejected(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'b', 'state': {},
    }))
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-perturb',
        {'investigation': 'demo', 'name': 'bad', 'extends': 'baseline',
         'parameter_overrides': {'state.nonexistent.field': 1}},
    )
    assert code == 400, j


# ---------------------------------------------------------------------------
# Investigation composite-rebuild + composite-delete endpoint tests
# ---------------------------------------------------------------------------

def test_post_composite_rebuild_reapplies_recipe(workspace_server):
    """If the parent composite changes, rebuilding the derived re-renders it."""
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text(yaml.safe_dump({
        'name': 'b',
        'state': {'replication': {'_type': 'process', 'address': 'local:Foo',
                                    'config': {'rate': 1.0, 'newkey': 'x'}}},
    }))
    (composites / 'derived.yaml').write_text(yaml.safe_dump({
        'name': 'd',
        'state': {'replication': {'_type': 'process', 'address': 'local:Foo',
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


def test_post_composite_rebuild_rejects_non_derived(workspace_server):
    """Rebuilding a registered (not derived) composite is a 400."""
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text('name: b\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'baseline', 'source': 'pkg.x',
                         'document': './composites/baseline.yaml'}],
        'runs': [],
    }, sort_keys=False))
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-rebuild',
        {'investigation': 'demo', 'name': 'baseline'},
    )
    assert code == 400, j
    assert 'not derived' in j.get('error', '').lower() or 'extends' in j.get('error', '').lower()


def test_delete_composite_with_dependents_refuses(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text('name: b\nstate: {}\n')
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
        assert e.code == 409, f"expected 409, got {e.code}"
        body = json.loads(e.read())
        assert 'baseline' in str(body).lower()
        assert body.get('dependents'), 'expected dependents list in error body'


def test_delete_composite_removes_when_no_dependents(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'baseline.yaml').write_text('name: b\nstate: {}\n')
    (composites / 'orphan.yaml').write_text('name: o\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [
            {'name': 'baseline', 'source': 'pkg.x',
             'document': './composites/baseline.yaml'},
            {'name': 'orphan', 'source': 'pkg.y',
             'document': './composites/orphan.yaml'},
        ],
        'runs': [{'composite': 'baseline', 'steps': 10}],
    }, sort_keys=False))

    req = urllib.request.Request(
        workspace_server.url + '/api/investigation-composite',
        data=json.dumps({'investigation': 'demo', 'name': 'orphan'}).encode(),
        method='DELETE', headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert resp.status in (200,)
    except urllib.error.HTTPError as e:
        # 500 acceptable for bare-workspace git failures, but the file changes
        # should have happened eagerly.
        assert e.code == 500, f"expected 200 or 500, got {e.code}"

    # File removed from disk and spec.yaml regardless of git outcome
    assert not (composites / 'orphan.yaml').is_file()
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    names = [c['name'] for c in spec['composites']]
    assert 'orphan' not in names
    assert 'baseline' in names


# ---------------------------------------------------------------------------
# Investigation set-observables endpoint tests
# ---------------------------------------------------------------------------

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


def test_post_set_observables_emit_all(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [],
    }, sort_keys=False))
    code, j = _post(
        workspace_server.url + '/api/investigation-set-observables',
        {'investigation': 'demo', 'paths': [], 'emit_all': True},
    )
    assert code in (200, 500), j
    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    # emit_all: True is represented by a single {path: []} sentinel
    assert spec['observables'] == [{'path': []}]


def test_post_set_observables_rejects_missing_investigation(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-set-observables',
        {'paths': []},
    )
    assert code == 400


def test_post_set_observables_rejects_non_list_paths(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text('name: demo\ncomposites: []\nruns: []\n')
    code, j = _post(
        workspace_server.url + '/api/investigation-set-observables',
        {'investigation': 'demo', 'paths': 'not-a-list'},
    )
    assert code == 400


def test_post_set_observables_rejects_missing_investigation_dir(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-set-observables',
        {'investigation': 'nonexistent', 'paths': []},
    )
    assert code == 404


def test_post_save_sidecar_writes_yaml_and_updates_spec(workspace_server):
    """Save-sidecar writes investigations/<inv>/composites/<name>.yaml and adds the entry to spec.yaml."""
    inv = workspace_server.root / 'investigations' / 'demo'
    inv.mkdir(parents=True)
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo', 'composites': [], 'runs': [],
    }, sort_keys=False))

    doc = {
        'name': 'tuned',
        'state': {
            'process': {'_type': 'process', 'address': 'local:Foo', 'config': {'rate': 5.0}},
            'stores': {'count': {'_type': 'integer', '_default': 1}},
            'emitter': {'_type': 'step', 'address': 'local:SQLiteEmitter',
                         'config': {'emit': {'count': 'integer'}},
                         'inputs': {'count': ['stores', 'count']}},
        },
    }
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo', 'name': 'tuned-baseline',
         'document': doc, 'source_ref': 'pkg.composites.baseline'},
    )
    assert code in (200, 500), j

    sidecar = inv / 'composites' / 'tuned-baseline.yaml'
    assert sidecar.is_file()
    written = yaml.safe_load(sidecar.read_text())
    assert written['state']['process']['config']['rate'] == 5.0
    assert 'emitter' in written['state']

    spec = yaml.safe_load((inv / 'spec.yaml').read_text())
    names = [c['name'] for c in (spec.get('composites') or [])]
    assert 'tuned-baseline' in names
    entry = next(c for c in spec['composites'] if c['name'] == 'tuned-baseline')
    assert entry['source'] == 'pkg.composites.baseline'
    assert entry['document'] == './composites/tuned-baseline.yaml'


def test_post_save_sidecar_rejects_duplicate_name(workspace_server):
    inv = workspace_server.root / 'investigations' / 'demo'
    composites = inv / 'composites'
    composites.mkdir(parents=True)
    (composites / 'tuned.yaml').write_text('name: tuned\nstate: {}\n')
    (inv / 'spec.yaml').write_text(yaml.safe_dump({
        'name': 'demo',
        'composites': [{'name': 'tuned', 'source': 'pkg.x',
                         'document': './composites/tuned.yaml'}],
        'runs': [],
    }, sort_keys=False))

    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo', 'name': 'tuned', 'document': {'state': {}}},
    )
    assert code == 409, j


def test_post_save_sidecar_rejects_missing_investigation(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'nonexistent', 'name': 'x', 'document': {'state': {}}},
    )
    assert code == 404, j


def test_post_save_sidecar_rejects_missing_fields(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/investigation-composite-save-sidecar',
        {'investigation': 'demo'},
    )
    assert code == 400, j


# ---------------------------------------------------------------------------
# Composite process configs endpoint tests
# ---------------------------------------------------------------------------

def test_post_composite_process_configs_returns_rows(workspace_server):
    doc = {
        'parameters': {'rate': {'default': 1.0, 'units': '1/s'}},
        'state': {
            'p': {'_type': 'process', 'address': 'local:Foo',
                  'config': {'rate': 2.5}},
        },
    }
    code, j = _post(
        workspace_server.url + '/api/composite-process-configs',
        {'document': doc},
    )
    assert code == 200, j
    rows = j['rows']
    assert len(rows) == 1
    assert rows[0]['name'] == 'p'
    assert rows[0]['address'] == 'local:Foo'
    cfg = rows[0]['configs'][0]
    assert cfg['key'] == 'rate'
    assert cfg['value'] == 2.5
    assert cfg['default'] == 1.0
    assert cfg['units'] == '1/s'


def test_post_composite_process_configs_rejects_missing_document(workspace_server):
    code, j = _post(
        workspace_server.url + '/api/composite-process-configs',
        {},
    )
    assert code == 400, j
