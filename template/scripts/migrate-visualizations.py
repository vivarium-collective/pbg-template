#!/usr/bin/env python3
"""Inspect or apply legacy workspace.yaml visualization migrations.

Usage:
    python3 scripts/migrate-visualizations.py            # print plan, exit
    python3 scripts/migrate-visualizations.py --apply    # apply auto-convertible

This is the CLI mirror of the dashboard's /api/visualization-migration-plan +
/api/visualization-migrate endpoints. Use it for headless workflows or as an
alternative to the dashboard's migration banner.
"""
from __future__ import annotations
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

import yaml

# Make scripts/_lib importable — same pattern as render-dashboard.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib.migrations import classify_viz_entry  # noqa: E402


def _find_workspace_root(start: Path) -> Path | None:
    """Walk up from *start* until a directory containing workspace.yaml is found."""
    p = start.resolve()
    while p != p.parent:
        if (p / "workspace.yaml").is_file():
            return p
        p = p.parent
    return None


def _list_registered_classes(ws_root: Path, ws: dict) -> set:
    """Best-effort listing of registered Visualization class names.

    Uses a subprocess so the workspace package doesn't need to be importable
    in this interpreter — same approach as lint-workspace.py's _try_get_registry.
    Returns an empty set when introspection fails.
    """
    pkg = ws.get("package_path") or ("pbg_" + ws.get("name", "").replace("-", "_"))
    script = f"""
import json, sys
try:
    from {pkg}.core import build_core
    core = build_core()
    # Try various registry APIs in order of preference.
    try:
        names = sorted(core.link_registry)
    except Exception:
        try:
            names = sorted(core.process_registry.list())
        except Exception:
            try:
                names = sorted(core.process_registry.registry.keys())
            except Exception:
                names = []
    print(json.dumps(names))
except Exception as e:
    print(json.dumps([]))
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ws_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.stdout.strip():
            last_line = result.stdout.strip().split("\n")[-1]
            names = json.loads(last_line)
            if isinstance(names, list):
                return set(names)
    except Exception as e:
        print(f"warning: could not load registry ({e}); proceeding with empty set",
              file=sys.stderr)
    return set()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to workspace.yaml; default is dry-run.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root (default: walk up from CWD until workspace.yaml is found).",
    )
    args = parser.parse_args()

    ws_root = args.workspace or _find_workspace_root(Path.cwd())
    if ws_root is None:
        print(
            "error: workspace.yaml not found in any ancestor of the current directory.\n"
            "Use --workspace to specify the workspace root explicitly.",
            file=sys.stderr,
        )
        return 1

    ws_file = ws_root / "workspace.yaml"
    if not ws_file.is_file():
        print(f"error: workspace.yaml not found at {ws_file}", file=sys.stderr)
        return 1

    ws = yaml.safe_load(ws_file.read_text()) or {}
    entries = ws.get("visualizations") or []
    registered = _list_registered_classes(ws_root, ws)

    # Build plan.
    plan: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        result = classify_viz_entry(entry, registered, workspace_root=ws_root)
        result = dict(result)
        result["name"] = entry.get("name")
        plan.append(result)

    print(f"Migration plan ({len(plan)} entries):")
    for c in plan:
        line = f"  - {c['name']}: {c['action']}"
        if c.get("target_class"):
            line += f"  -> {c['target_class']}"
        if c.get("reason"):
            line += f"  ({c['reason']})"
        if c.get("legacy_path"):
            line += f"  [legacy: {c['legacy_path']}]"
        print(line)

    if not args.apply:
        print("\n(dry run — re-run with --apply to write changes)")
        return 0

    # Apply auto-convertible entries.
    now = datetime.datetime.now(datetime.timezone.utc)
    log_lines = [f"# CLI migration {now.isoformat()}"]
    changed = False
    for c in plan:
        if c["action"] != "auto-convert-to-class-backed":
            log_lines.append(f"- {c['name']}: skip ({c['action']})")
            continue
        idx = next(
            (i for i, e in enumerate(entries)
             if isinstance(e, dict) and e.get("name") == c["name"]),
            None,
        )
        if idx is None:
            continue
        before = dict(entries[idx])
        entries[idx] = {
            "name": c["name"],
            "class": c["target_class"],
            "config": {},
        }
        log_lines.append(
            f"- {c['name']}: auto-convert -> class={c['target_class']} (was: {before})"
        )
        changed = True

    # Write log unconditionally (records what was skipped too).
    log_dir = ws_root / ".pbg" / "migrations"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"{ts}-cli.log"
    log_path.write_text("\n".join(log_lines) + "\n")
    print(f"\nLog written to {log_path}")

    if changed:
        ws["visualizations"] = entries
        ws_file.write_text(yaml.safe_dump(ws, sort_keys=False))
        print("workspace.yaml updated.")
    else:
        print("No auto-convertible entries; workspace.yaml unchanged.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
