"""Make template/scripts/_lib importable as `scripts._lib` for pbg-template's own tests.

Tests live at repo root; the code they test moved into template/ as part of
the payload-boundary restructure. This conftest is the single place that
knows the layout.
"""
from __future__ import annotations
import sys
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent.parent / "template"
if str(_TEMPLATE_DIR) not in sys.path:
    sys.path.insert(0, str(_TEMPLATE_DIR))
