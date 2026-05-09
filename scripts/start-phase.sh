#!/usr/bin/env bash
# Stage 9..N: open phase <n> for implementation.
# Marks status: in_progress and generates tests/test_phases.py from the frontmatter.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found; run from workspace root" >&2; exit 1; }

MODEL="${1:-}"
N="${2:-}"
if [ -z "$MODEL" ] || [ -z "$N" ]; then
  echo "usage: scripts/start-phase.sh <model-name> <n>" >&2
  exit 1
fi

PHASE_MD="$WS_ROOT/models/$MODEL/phases/phase-$N.md"
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

# Generate tests/test_phases.py
tests_dir = Path('$WS_ROOT/models/$MODEL/tests')
tests_dir.mkdir(parents=True, exist_ok=True)
generate_test_module(fm, tests_dir / 'test_phases.py')
print(f'phase $N opened; status: in_progress; tests/test_phases.py generated')
"

echo "✓ phase $N of $MODEL is open. Implement the test bodies in models/$MODEL/tests/test_phases.py and update each acceptance_tests[*].status in the frontmatter as they pass."
echo "When ready, run: scripts/evaluate-phase-gate.sh $MODEL $N"
