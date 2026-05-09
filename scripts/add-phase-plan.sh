#!/usr/bin/env bash
# Stage 8: lay out the multi-phase plan for a model.
# Writes models/<model>/phases/plan.md and one phase-N.md per phase.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found; run from workspace root" >&2; exit 1; }

read -rp "model name: " MODEL
[ -d "$WS_ROOT/models/$MODEL" ] || { echo "ERROR: models/$MODEL/ does not exist" >&2; exit 1; }

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
phases_dir = Path('$WS_ROOT') / 'models' / '$MODEL' / 'phases'
create_initial_plan(phases_dir, '$MODEL', json.loads('''$PHASES_JSON'''))
print(f'wrote {phases_dir}/plan.md and phase-N.md for $N phases')
"

# Also update workspace.yaml to register phases
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from _lib.workspace_yaml import load_workspace, save_workspace
from pathlib import Path
ws = load_workspace(Path('$WS_ROOT/workspace.yaml'))
model = ws['models'].get('$MODEL')
if not model:
    sys.exit(\"ERROR: '$MODEL' not registered in workspace.yaml.models — run /pbg-add-model first\")
model.setdefault('phases', [])
model['stages']['phase_plan'] = {'status': 'complete', 'pr': None, 'completed': '$(date -u +%Y-%m-%d)'}
import yaml
phases_dir = Path('$WS_ROOT/models/$MODEL/phases')
existing = {p['n']: p for p in model['phases']}
for f in sorted(phases_dir.glob('phase-*.md')):
    text = f.read_text()
    fm_text = text.split('---')[1]
    fm = yaml.safe_load(fm_text)
    n = fm['n'] if 'n' in fm else fm.get('phase')
    existing[n] = {'n': n, 'name': fm['name'], 'status': fm['status'], 'pr': None, 'gate_passed': fm['gate_passed']}
model['phases'] = sorted(existing.values(), key=lambda p: p['n'])
save_workspace(Path('$WS_ROOT/workspace.yaml'), ws)
print('updated workspace.yaml.models.$MODEL.phases')
"

python3 scripts/lint-workspace.py
echo "✓ phase plan written. Next: scripts/start-phase.sh $MODEL 1 to begin Phase 1."
