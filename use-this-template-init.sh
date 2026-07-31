#!/usr/bin/env bash
# GitHub "Use this template" entry point.
#
# Users who created their repo via the GitHub UI receive a copy of the
# entire viva-template tree — including viva-template's own tests/, docs/,
# and superpowers cruft. This script collapses template/* to repo root,
# removes viva-template's dev infra, then runs the normal render via
# template-init.sh.
#
# Users coming through the viva-superpowers /viva-workspace command never
# touch this script — the plugin scaffolder copies template/* directly.
set -euo pipefail

if [[ ! -d template ]]; then
  echo "ERROR: template/ directory missing. This script must run in a fresh" >&2
  echo "       copy of viva-template created via GitHub's 'Use this template'." >&2
  exit 1
fi

# Remove viva-template's own dev infra. We are not viva-template; we are a
# new workspace created from it.
rm -rf docs/superpowers .superpowers tests README.md

# Flatten template/* into repo root. Use shopt -s dotglob so .claude,
# .github, .pbg also move.
shopt -s dotglob nullglob
mv template/* .
shopt -u dotglob
rmdir template

# Hand off to the workspace render script (which now lives at repo root
# after flattening) and remove ourselves.
bash template-init.sh
rm -f use-this-template-init.sh
