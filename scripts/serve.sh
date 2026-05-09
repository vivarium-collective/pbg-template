#!/usr/bin/env bash
# Optional dashboard server. Renders the workspace dashboard once and serves
# it locally so you can browse it. Idempotent. Ctrl-C to stop.
set -euo pipefail

WS_ROOT="$(pwd)"
[ -f "$WS_ROOT/workspace.yaml" ] || { echo "ERROR: run from workspace root" >&2; exit 1; }

# Use the workspace's venv python so all workspace deps (pypdf, jinja2, etc.) are visible.
# Fall back to system python3 if no venv exists.
if [ -x "$WS_ROOT/.venv/bin/python3" ]; then
    PY="$WS_ROOT/.venv/bin/python3"
elif [ -x "$WS_ROOT/.venv/bin/python" ]; then
    PY="$WS_ROOT/.venv/bin/python"
else
    PY="python3"
    echo "warning: no .venv found at $WS_ROOT/.venv; using system python3 (workspace deps may be missing)" >&2
fi

# Render the workspace dashboard and all per-model reports
"$PY" "$WS_ROOT/scripts/render-dashboard.py" --all

# Pick a free port
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')

mkdir -p "$WS_ROOT/.pbg/server/content" "$WS_ROOT/.pbg/server/state"
cat > "$WS_ROOT/.pbg/server/server-info" <<EOF
{"port": ${PORT}, "host": "127.0.0.1", "url": "http://localhost:${PORT}",
 "screen_dir": "$WS_ROOT/.pbg/server/content", "state_dir": "$WS_ROOT/.pbg/server/state"}
EOF

echo
echo "Workspace dashboard: http://localhost:${PORT}"
echo "   (Ctrl-C to stop)"
echo

exec "$PY" "$WS_ROOT/scripts/_server/server.py" --workspace "$WS_ROOT" --port "$PORT"
