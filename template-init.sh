#!/usr/bin/env bash
# Renders .j2 files in the current directory using simple sed substitution.
# For users who clicked "Use this template" on github.com/vivarium-collective/pbg-template
# without installing the pbg-superpowers plugin.
set -euo pipefail

WS_NAME_DEFAULT="$(basename "$PWD")"
read -rp "workspace name [$WS_NAME_DEFAULT]: " WS_NAME
WS_NAME="${WS_NAME:-$WS_NAME_DEFAULT}"

if [[ ! "$WS_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: workspace name must match [A-Za-z0-9._-]+" >&2
  exit 1
fi

TODAY="$(date -u +%Y-%m-%d)"
PLUGIN_VERSION="0.1.1"

# Render every .j2 file in the workspace
find . -name '*.j2' -type f -not -path './.git/*' | while read -r tpl; do
  out="${tpl%.j2}"
  sed \
    -e "s/{{ *workspace_name *}}/$WS_NAME/g" \
    -e "s/{{ *today *}}/$TODAY/g" \
    -e "s/{{ *plugin_version *}}/$PLUGIN_VERSION/g" \
    -e "s/{{ *generated_at *}}/$TODAY/g" \
    "$tpl" > "$out"
  rm "$tpl"
  echo "rendered $tpl -> $out"
done

# Remove the init script itself once we're done
echo "removing template-init.sh"
rm -f template-init.sh

echo
echo "✓ workspace '$WS_NAME' initialized"
echo
echo "📋 Next steps are in: NEXT_STEPS.md"
echo
echo "Quick setup:"
echo "  1. git init && git add -A && git commit -m 'feat(stage-0): workspace bootstrap'"
echo "  2. uv venv .venv && source .venv/bin/activate && uv pip install -e \".[dev]\""
echo "  3. python scripts/lint-workspace.py    # should print 'workspace lint: OK'"
echo
echo "Then open NEXT_STEPS.md to walk through stages 0.5 → 9..N."
