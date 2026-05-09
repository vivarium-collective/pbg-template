#!/usr/bin/env bash
# Stage 6: capture an expert-stated 'if X, then Y' acceptance test for a model.
# Appends to models/<model>/expert/acceptance.yaml.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: workspace.yaml not found; run from workspace root" >&2; exit 1; }

read -rp "model name: " MODEL
[ -d "$WS_ROOT/models/$MODEL" ] || { echo "ERROR: models/$MODEL/ does not exist" >&2; exit 1; }

mkdir -p "$WS_ROOT/models/$MODEL/expert"
ACC_PATH="$WS_ROOT/models/$MODEL/expert/acceptance.yaml"

read -rp "test ID (e.g. baseline.t1, phase-2.t3): " TEST_ID
[[ "$TEST_ID" =~ ^[a-zA-Z0-9.\-_]+$ ]] || { echo "ERROR: ID must match [a-zA-Z0-9.\\-_]+" >&2; exit 1; }

read -rp "statement (if X, then Y): " STMT
read -rp "perturbation (how to set up X): " PERT
read -rp "observable (how to check Y): " OBS

python3 -c "
import yaml
from pathlib import Path
p = Path('$ACC_PATH')
data = yaml.safe_load(p.read_text()) if p.exists() else {'tests': []}
data.setdefault('tests', [])
for t in data['tests']:
    if t.get('id') == '$TEST_ID':
        import sys
        sys.exit(f\"ERROR: test '$TEST_ID' already in acceptance.yaml; edit by hand to amend\")
data['tests'].append({
    'id': '$TEST_ID',
    'statement': '$STMT',
    'perturbation': '$PERT',
    'observable': '$OBS',
})
p.write_text(yaml.safe_dump(data, sort_keys=False))
print(f'wrote {p}')
"

echo "✓ acceptance test '$TEST_ID' added to models/$MODEL/expert/acceptance.yaml."
