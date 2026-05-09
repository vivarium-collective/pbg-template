#!/usr/bin/env python3
"""Render the workspace dashboard. With --all, also render every per-model report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib.report import render_workspace_report, render_model_report
from _lib.workspace_yaml import load_workspace

if __name__ == "__main__":
    ws_out = render_workspace_report()
    print(f"rendered {ws_out}")
    if "--all" in sys.argv[1:]:
        ws = load_workspace(Path("workspace.yaml"))
        for name in (ws.get("models") or {}).keys():
            try:
                m_out = render_model_report(name)
                print(f"rendered {m_out}")
            except Exception as e:
                print(f"  ! render-model-report({name}) failed: {e}", file=sys.stderr)
