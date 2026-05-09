#!/usr/bin/env bash
# Stage 9..N: evaluate the Phase Gate for a phase.
# Reads acceptance_tests[*].status from the phase frontmatter and decides pass/fail.
# v0.3.0: operates on phases/ at workspace root (no per-model scoping).
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found" >&2; exit 1; }

N="${1:-}"
if [ -z "$N" ]; then
  echo "usage: scripts/evaluate-phase-gate.sh <n>" >&2
  exit 1
fi

PHASE_MD="$WS_ROOT/phases/phase-$N.md"
[ -f "$PHASE_MD" ] || { echo "ERROR: $PHASE_MD does not exist" >&2; exit 1; }

python3 -c "
import sys
sys.path.insert(0, 'scripts')
from _lib.phase_md import parse_phase_md, render_phase_md
from _lib.phase_gate import evaluate_gate
from _lib.workspace_yaml import load_workspace, save_workspace
from pathlib import Path

phase_md = Path('$PHASE_MD')
fm, body = parse_phase_md(phase_md.read_text())
result = evaluate_gate(fm)

if result.passed:
    fm['status'] = 'complete'
    fm['gate_passed'] = True
    print(f'GATE PASSED: {result.reason}')
else:
    fm['status'] = 'gate_pending'
    fm['gate_passed'] = False
    print(f'GATE NOT PASSED: {result.reason}')

phase_md.write_text(render_phase_md(fm, body))

# Mirror to workspace.yaml top-level phases[]
ws = load_workspace(Path('$WS_ROOT/workspace.yaml'))
phases = ws.get('phases') or []
for p in phases:
    if p.get('n') == $N:
        p['status'] = fm['status']
        p['gate_passed'] = fm['gate_passed']
        break
save_workspace(Path('$WS_ROOT/workspace.yaml'), ws)
print('workspace.yaml updated')
sys.exit(0 if result.passed else 2)
" || GATE_EXIT=$?

if [ "${GATE_EXIT:-0}" = "2" ]; then
  echo "✗ gate did not pass — fix failing tests and re-run."
  exit 2
fi

echo "✓ phase $N gate passed; status: complete."
