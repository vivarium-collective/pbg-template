#!/usr/bin/env python3
"""Render the workspace dashboard (single dashboard, v0.3.0)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib.report import render_workspace_report

if __name__ == "__main__":
    ws_out = render_workspace_report()
    print(f"rendered {ws_out}")
