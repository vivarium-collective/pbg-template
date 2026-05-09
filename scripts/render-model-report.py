#!/usr/bin/env python3
"""Render the per-model deep-dive report for one model.

Usage: python3 scripts/render-model-report.py <model-name>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib.report import render_model_report

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: scripts/render-model-report.py <model-name>")
    out = render_model_report(sys.argv[1])
    print(f"rendered {out}")
