#!/usr/bin/env bash
# Renders .j2 files in the current directory using simple sed substitution.
# For users who clicked "Use this template" on github.com/eagmon/pbg-template
# without installing the pbg-superpowers plugin.
set -euo pipefail

WS_NAME_DEFAULT="$(basename "$PWD")"
read -rp "workspace name [$WS_NAME_DEFAULT]: " WS_NAME
WS_NAME="${WS_NAME:-$WS_NAME_DEFAULT}"

TODAY="$(date -u +%Y-%m-%d)"
PLUGIN_VERSION="0.1.0"

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
echo "  next:  python scripts/lint-workspace.py  &&  git add -A && git commit -m 'workspace bootstrap'"
