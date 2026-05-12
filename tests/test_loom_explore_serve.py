"""Test that the loom-explore static bundle is served by the dashboard."""
import sys
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def workspace_server(tmp_path, monkeypatch):
    ws_root = tmp_path
    (ws_root / "workspace.yaml").write_text(yaml.dump({
        "name": "testws",
        "package_path": "pbg_testws",
    }, sort_keys=False))

    # Vendor a stub bundle for the test
    bundle_dir = ws_root / "scripts" / "_assets" / "loom-explore"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<html><body>loom-explore</body></html>")
    (bundle_dir / "assets").mkdir()
    (bundle_dir / "assets" / "stub.js").write_text("console.log('loom');")
    (bundle_dir / "assets" / "style.css").write_text("body { margin: 0; }")

    monkeypatch.chdir(ws_root)
    import importlib
    import scripts._server.server as srv
    importlib.reload(srv)
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


def test_loom_explore_index_served(workspace_server):
    with urllib.request.urlopen(workspace_server.url + "/loom-explore/index.html") as resp:
        assert resp.status == 200
        body = resp.read().decode()
        assert "loom-explore" in body


def test_loom_explore_root_redirects_to_index(workspace_server):
    """Visiting /loom-explore/ (trailing slash) should serve index.html."""
    try:
        with urllib.request.urlopen(workspace_server.url + "/loom-explore/") as resp:
            assert resp.status == 200
            body = resp.read().decode()
            assert "loom-explore" in body
    except urllib.error.HTTPError as e:
        # Acceptable if the server returns 200 directly; flag if 404
        assert e.code == 200, f"expected 200, got {e.code}"


def test_loom_explore_js_asset_served(workspace_server):
    with urllib.request.urlopen(workspace_server.url + "/loom-explore/assets/stub.js") as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type", "").startswith("application/javascript") or \
               resp.headers.get("Content-Type", "").startswith("text/javascript")
        body = resp.read().decode()
        assert "console.log" in body


def test_loom_explore_css_asset_served(workspace_server):
    with urllib.request.urlopen(workspace_server.url + "/loom-explore/assets/style.css") as resp:
        assert resp.status == 200
        assert "text/css" in (resp.headers.get("Content-Type", "") or "")


def test_loom_explore_path_traversal_refused(workspace_server):
    """A path with .. must be refused."""
    try:
        urllib.request.urlopen(workspace_server.url + "/loom-explore/../workspace.yaml")
        raise AssertionError("expected refusal")
    except urllib.error.HTTPError as e:
        assert e.code in (403, 404), f"expected 403/404, got {e.code}"


def test_loom_explore_missing_file_404(workspace_server):
    try:
        urllib.request.urlopen(workspace_server.url + "/loom-explore/assets/nonexistent.js")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
