"""Task B1: verify that the rendered pyproject.toml makes pbg_<slug> a
pip-installable wheel package.

The test substitutes the j2 placeholders directly (same substitutions that
template-init.sh runs via sed), writes a minimal workspace to a tmp dir, and
builds a wheel. We assert the wheel contains the workspace package.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"
PYPROJECT_J2 = TEMPLATE / "pyproject.toml.j2"

# Fixed substitution values used for the test render
_WS_NAME = "demo"
_PKG_PATH = "pbg_demo"
_TODAY = "2026-01-01"
_PLUGIN_VERSION = "0.0.0"


def _render_pyproject(tmp: Path) -> Path:
    """Render pyproject.toml.j2 into tmp/ with stub placeholder values."""
    raw = PYPROJECT_J2.read_text()
    rendered = re.sub(r"\{\{ *workspace_name *\}\}", _WS_NAME, raw)
    rendered = re.sub(r"\{\{ *package_path *\}\}", _PKG_PATH, rendered)
    rendered = re.sub(r"\{\{ *today *\}\}", _TODAY, rendered)
    rendered = re.sub(r"\{\{ *plugin_version *\}\}", _PLUGIN_VERSION, rendered)
    rendered = re.sub(r"\{\{ *generated_at *\}\}", _TODAY, rendered)
    out = tmp / "pyproject.toml"
    out.write_text(rendered)
    return tmp


def _create_stub_package(ws: Path) -> None:
    """Create a minimal pbg_demo package so hatchling has something to package."""
    pkg = ws / _PKG_PATH
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('"""pbg_demo workspace package."""\n')


def test_wheel_contains_workspace_package(tmp_path):
    """The rendered pyproject.toml must produce a wheel containing pbg_<slug>."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _render_pyproject(ws)
    _create_stub_package(ws)

    wh_dir = tmp_path / "wh"
    wh_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wh_dir), str(ws)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"pip wheel failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    wheels = list(wh_dir.glob("*.whl"))
    assert wheels, f"No wheel produced in {wh_dir}"
    whl = wheels[0]

    names = zipfile.ZipFile(whl).namelist()
    assert any(n.startswith("pbg_") and n.endswith("__init__.py") for n in names), (
        f"Wheel does not contain pbg_*/__init__.py. Contents:\n{names}"
    )


def test_pyproject_has_no_bypass_selection():
    """The rendered pyproject.toml must not bypass wheel-package selection."""
    raw = PYPROJECT_J2.read_text()
    assert "bypass-selection" not in raw, (
        "pyproject.toml.j2 still has 'bypass-selection = true'; "
        "it should declare 'packages = [\"{{ package_path }}\"]' instead."
    )


def test_pyproject_declares_packages_target():
    """The template must explicitly set packages = [<package_path>]."""
    raw = PYPROJECT_J2.read_text()
    # Allow flexible whitespace around the mustache placeholder
    assert re.search(
        r'packages\s*=\s*\[\s*["\']?\{\{.*?package_path.*?\}\}["\']?\s*\]', raw
    ), (
        "pyproject.toml.j2 missing 'packages = [\"{{ package_path }}\"]' declaration. "
        f"Current [tool.hatch.build.targets.wheel] block:\n{raw}"
    )
