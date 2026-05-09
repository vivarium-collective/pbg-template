#!/usr/bin/env python3
"""Render the workspace dashboard once. Run this whenever workspace state changes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib.report import render_workspace_report

if __name__ == "__main__":
    out = render_workspace_report()
    print(f"rendered {out}")
