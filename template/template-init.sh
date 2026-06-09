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
"""build_core() — wraps process_bigraph.allocate_core().

Imports declared in workspace.yaml are auto-discovered by allocate_core()
once they're pip-installed in the workspace venv. Use the dashboard's
Install button on a Registry catalog entry, or run
`.venv/bin/pip install -e <path>` manually. No manual register_link()
boilerplate needed for standard pbg-* packages.
"""
from process_bigraph import allocate_core


def build_core():
    return allocate_core()
EOF
  echo "created $PACKAGE_PATH/{__init__.py,core.py}"
fi

# vivarium-dashboard isn't on PyPI yet. Pin it via [tool.uv.sources] to its
# public git repo. We ALWAYS use the git source — never a committed local path
# — because a committed path (relative or absolute) breaks `uv pip install` on
# every other machine: CI, Docker, and collaborators all lack the sibling
# checkout and hit "Distribution not found at: file:///.../vivarium-dashboard".
# For local dev against a sibling checkout, override with an editable install
# into your venv instead (no committed local path required):
#     uv pip install -e ../vivarium-dashboard
# Skip cleanly if pyproject.toml already has a [tool.uv.sources] block
# (don't clobber user edits).
VIVARIUM_GIT_URL="https://github.com/vivarium-collective/vivarium-dashboard.git"
VIVARIUM_GIT_REF="${VIVARIUM_DASHBOARD_REF:-main}"
if [ -f pyproject.toml ] \
   && ! grep -q '^\[tool\.uv\.sources\]' pyproject.toml \
   && grep -q '"vivarium-dashboard"' pyproject.toml; then
  printf '\n[tool.uv.sources]\nvivarium-dashboard = { git = "%s", branch = "%s" }\n' \
    "$VIVARIUM_GIT_URL" "$VIVARIUM_GIT_REF" >> pyproject.toml
  echo "pinned vivarium-dashboard to git source: $VIVARIUM_GIT_URL@$VIVARIUM_GIT_REF"
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
