#!/usr/bin/env bash
# Stage 8: lay out the multi-phase plan for the workspace.
# Writes phases/plan.md and one phases/phase-N.md per phase.
# v0.3.0: no per-model scoping — phases live at workspace root.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found; run from workspace root" >&2; exit 1; }

read -rp "how many phases? " N
[[ "$N" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: must be positive integer" >&2; exit 1; }

PHASES_JSON="["
for i in $(seq 1 "$N"); do
  read -rp "phase $i name: " PNAME
  read -rp "phase $i one-line objective: " POBJ
  PREREQ="[$((i-1))]"
  [ "$i" = "1" ] && PREREQ="[]"
  COMMA=","
  [ "$i" = "1" ] && COMMA=""
  PHASES_JSON="${PHASES_JSON}${COMMA}{\"n\": $i, \"name\": \"$PNAME\", \"objective\": \"$POBJ\", \"prereq_phases\": $PREREQ, \"acceptance_tests\": []}"
done
PHASES_JSON="${PHASES_JSON}]"

python3 -c "
import sys, json
sys.path.insert(0, 'scripts')
from _lib.phase_files import create_initial_plan
from pathlib import Path
phases_dir = Path('$WS_ROOT') / 'phases'
create_initial_plan(phases_dir, 'workspace', json.loads('''$PHASES_JSON'''))
print(f'wrote phases/plan.md and phases/phase-N.md for $N phases')
"

# Also update workspace.yaml top-level phases[]
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from _lib.workspace_yaml import load_workspace, save_workspace
from pathlib import Path
import yaml
ws = load_workspace(Path('$WS_ROOT/workspace.yaml'))
phases_dir = Path('$WS_ROOT/phases')
existing = {p['n']: p for p in (ws.get('phases') or [])}
for f in sorted(phases_dir.glob('phase-*.md')):
    text = f.read_text()
    parts = text.split('---')
    if len(parts) >= 2:
        fm = yaml.safe_load(parts[1])
        n = fm.get('n', fm.get('phase'))
        if n is not None:
            existing[n] = {'n': n, 'name': fm['name'], 'status': fm['status']}
ws['phases'] = sorted(existing.values(), key=lambda p: p['n'])
save_workspace(Path('$WS_ROOT/workspace.yaml'), ws)
print('updated workspace.yaml.phases')
"

python3 scripts/lint-workspace.py
echo "✓ Phase plan written. Next: scripts/start-phase.sh 1 to begin Phase 1."
