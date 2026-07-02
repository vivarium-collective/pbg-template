#!/usr/bin/env bash
# Renders .j2 files in the current directory using simple sed substitution.
# For users who clicked "Use this template" on github.com/vivarium-collective/pbg-template
# without installing the pbg-superpowers plugin.
set -euo pipefail

if ! command -v uv &> /dev/null; then
  echo "ERROR: uv is required. Install with: brew install uv  OR  pip install uv" >&2
  exit 1
fi

WS_NAME_DEFAULT="$(basename "$PWD")"
read -rp "workspace name [$WS_NAME_DEFAULT]: " WS_NAME
WS_NAME="${WS_NAME:-$WS_NAME_DEFAULT}"

if [[ ! "$WS_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: workspace name must match [A-Za-z0-9._-]+" >&2
  exit 1
fi

TODAY="$(date -u +%Y-%m-%d)"
PLUGIN_VERSION="0.4.16"
# Python package name for the workspace: hyphens become underscores
PACKAGE_PATH="pbg_${WS_NAME//-/_}"

# Render every .j2 file in the workspace root (skip scripts/ — those are
# runtime Jinja2 templates for the dashboard renderer, not init-time files)
find . -name '*.j2' -type f -not -path './.git/*' -not -path './scripts/*' | while read -r tpl; do
  out="${tpl%.j2}"
  sed \
    -e "s/{{ *workspace_name *}}/$WS_NAME/g" \
    -e "s/{{ *package_path *}}/$PACKAGE_PATH/g" \
    -e "s/{{ *today *}}/$TODAY/g" \
    -e "s/{{ *plugin_version *}}/$PLUGIN_VERSION/g" \
    -e "s/{{ *generated_at *}}/$TODAY/g" \
    "$tpl" > "$out"
  rm "$tpl"
  echo "rendered $tpl -> $out"
done

# Scaffold the workspace's Python package if not already present. The Registry
# tab imports {{ package_path }}.core to call build_core(); without this the
# dashboard shows an "ImportError" for every fresh workspace.
if [ ! -d "$PACKAGE_PATH" ]; then
  mkdir -p "$PACKAGE_PATH"
  cat > "$PACKAGE_PATH/__init__.py" <<EOF
"""$PACKAGE_PATH — workspace Python package."""
EOF
  cat > "$PACKAGE_PATH/core.py" <<'EOF'
"""build_core() — the workspace core that composites and tests run against.

`process_bigraph.allocate_core()` auto-discovers processes/types from *installed
distributions* that depend on bigraph-schema (it scans
``importlib.metadata.packages_distributions()``). That works for sibling
``pbg-*`` wrapper packages installed as regular wheels, but it does NOT see this
workspace's own package when it is installed *editable* (``pip install -e .`` —
the way CI and local dev install it): an editable install records only a
``.pth`` shim in its ``RECORD``, so ``packages_distributions()`` never maps this
package back to its distribution and the discovery scan skips it entirely. The
result is that any Process/Step defined IN this package is missing from the
core's link registry, and a composite addressing ``local:<ProcessName>`` fails
at build with::

    Exception: no link found at address: {'protocol': 'local', 'data': '<ProcessName>'}

So we register this workspace's own Process/Step classes explicitly here. The
registration is idempotent (a class already provided by auto-discovery — e.g. in
a non-editable / Docker install — is left untouched), so ``build_core()`` is
correct regardless of how the workspace was installed. A fresh scaffold with no
process classes yet is a clean no-op.
"""
from __future__ import annotations

import importlib
import pkgutil

from process_bigraph import Process, Step, allocate_core


def _iter_own_process_classes():
    """Yield (name, cls) for each Process/Step subclass defined in THIS package.

    Walks only this package's own top-level modules (resolved from ``__package__``
    so no name is hard-coded). Defensive: an import error in any single module is
    swallowed so one broken module never breaks ``build_core()``. A brand-new
    package with no process classes simply yields nothing.
    """
    package_name = __package__
    if not package_name:
        return
    try:
        package = importlib.import_module(package_name)
    except Exception:
        return
    search_paths = getattr(package, "__path__", None)
    if search_paths is None:
        return
    seen = set()
    for module_info in pkgutil.iter_modules(search_paths, package_name + "."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception:
            # A module that fails to import (e.g. an optional heavy dep missing)
            # must not take down the whole core build.
            continue
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, (Process, Step)):
                continue
            if obj is Process or obj is Step:
                continue
            # Only register classes actually DEFINED in this package, not ones
            # imported into a module from elsewhere (e.g. the base classes).
            if not getattr(obj, "__module__", "").startswith(package_name):
                continue
            if obj.__name__ in seen:
                continue
            seen.add(obj.__name__)
            yield obj.__name__, obj


def register_workspace_processes(core):
    """Register this workspace's own Process/Step classes into ``core``.

    Idempotent: a name already present in ``core.link_registry`` (e.g. provided
    by auto-discovery in a non-editable install) is left untouched.
    """
    for name, cls in _iter_own_process_classes():
        if name not in core.link_registry:
            core.register_link(name, cls)
    return core


def build_core(core=None):
    """Return a process-bigraph core with this workspace's processes registered.

    This is the canonical core for the workspace: composites that address
    ``local:<ProcessName>`` (and the test suite) must build their ``Composite``
    against a core returned from here, not a bare ``allocate_core()``.
    """
    if core is None:
        core = allocate_core()
    register_workspace_processes(core)
    return core
EOF
  echo "created $PACKAGE_PATH/{__init__.py,core.py}"
fi

# vivarium-workbench isn't on PyPI yet. Pin it via [tool.uv.sources] to its
# public git repo. We ALWAYS use the git source — never a committed local path
# — because a committed path (relative or absolute) breaks `uv pip install` on
# every other machine: CI, Docker, and collaborators all lack the sibling
# checkout and hit "Distribution not found at: file:///.../vivarium-workbench".
# For local dev against a sibling checkout, override with an editable install
# into your venv instead (no committed local path required):
#     uv pip install -e ../vivarium-workbench
# Skip cleanly if pyproject.toml already has a [tool.uv.sources] block
# (don't clobber user edits).
VIVARIUM_GIT_URL="https://github.com/vivarium-collective/vivarium-dashboard.git"
VIVARIUM_GIT_REF="${VIVARIUM_WORKBENCH_REF:-main}"
if [ -f pyproject.toml ] \
   && ! grep -q '^\[tool\.uv\.sources\]' pyproject.toml \
   && grep -q '"vivarium-workbench"' pyproject.toml; then
  printf '\n[tool.uv.sources]\nvivarium-workbench = { git = "%s", branch = "%s" }\n' \
    "$VIVARIUM_GIT_URL" "$VIVARIUM_GIT_REF" >> pyproject.toml
  echo "pinned vivarium-workbench to git source: $VIVARIUM_GIT_URL@$VIVARIUM_GIT_REF"
fi

# Remove the init script itself once we're done
echo "removing template-init.sh"
rm -f template-init.sh

echo
echo "✓ workspace '$WS_NAME' initialized"
echo
echo "📋 Next steps are in: NEXT_STEPS.md"
echo
echo "Quick setup:"
echo "  1. git init -b main && git add -A && git commit -m 'feat: workspace bootstrap'"
echo "  2. uv venv .venv && source .venv/bin/activate && uv pip install -e \".[dev]\""
echo "  3. python scripts/lint-workspace.py    # should print 'workspace lint: OK'"
echo "  4. bash scripts/serve.sh               # open the dashboard"
echo
echo "Inside the dashboard, click 'Start workstream' to begin a feature branch."
echo "Every action you take commits to that branch; push and open one PR when ready."
echo
echo "Full guide: NEXT_STEPS.md"
