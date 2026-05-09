#!/usr/bin/env bash
# Optional dashboard server. Renders the workspace dashboard once and serves
# it locally so you can browse it. Idempotent. Ctrl-C to stop.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: run from workspace root" >&2; exit 1; }

# Render the dashboard once
python3 "$WS_ROOT/scripts/render-dashboard.py"

# Pick a free port
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')

mkdir -p "$WS_ROOT/.pbg/server/content" "$WS_ROOT/.pbg/server/state"
cat > "$WS_ROOT/.pbg/server/server-info" <<EOF
{"port": ${PORT}, "host": "127.0.0.1", "url": "http://localhost:${PORT}",
 "screen_dir": "$WS_ROOT/.pbg/server/content", "state_dir": "$WS_ROOT/.pbg/server/state"}
EOF

echo
echo "Workspace dashboard: http://localhost:${PORT}"
echo "   (Ctrl-C to stop)"
echo

exec python3 "$WS_ROOT/scripts/_server/server.py" --workspace "$WS_ROOT" --port "$PORT"
