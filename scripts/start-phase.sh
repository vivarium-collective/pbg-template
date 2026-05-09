#!/usr/bin/env bash
# Stage 9..N: open phase <n> for implementation.
# Marks status: in_progress and generates tests/test_phases.py from the frontmatter.
# v0.3.0: operates on phases/ at workspace root (no per-model scoping).
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found; run from workspace root" >&2; exit 1; }

N="${1:-}"
if [ -z "$N" ]; then
  echo "usage: scripts/start-phase.sh <n>" >&2
  exit 1
fi

PHASE_MD="$WS_ROOT/phases/phase-$N.md"
[ -f "$PHASE_MD" ] || { echo "ERROR: $PHASE_MD does not exist (run scripts/add-phase-plan.sh first)" >&2; exit 1; }

python3 -c "
import sys
sys.path.insert(0, 'scripts')
from _lib.phase_md import parse_phase_md, render_phase_md
from _lib.phase_gate import generate_test_module
from pathlib import Path

phase_md = Path('$PHASE_MD')
fm, body = parse_phase_md(phase_md.read_text())

# Gate-prereq check: phase n requires phase n-1 to be gate_passed
if $N > 1:
    prev = phase_md.with_name(f'phase-{$N - 1}.md')
    if prev.exists():
        prev_fm, _ = parse_phase_md(prev.read_text())
        if not prev_fm.get('gate_passed'):
            sys.exit(f\"ERROR: phase {$N - 1} gate has not passed; cannot start phase $N\")

# Mark in_progress
fm['status'] = 'in_progress'
phase_md.write_text(render_phase_md(fm, body))

# Generate tests/test_phases.py at workspace root
tests_dir = Path('$WS_ROOT/tests')
tests_dir.mkdir(parents=True, exist_ok=True)
generate_test_module(fm, tests_dir / 'test_phases.py')
print(f'phase $N opened; status: in_progress; tests/test_phases.py generated')
"

echo "✓ Phase $N is open. Implement the test bodies in tests/test_phases.py and update each acceptance_tests[*].status in the frontmatter as they pass."
echo "When ready, run: scripts/evaluate-phase-gate.sh $N"
