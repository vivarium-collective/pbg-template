#!/usr/bin/env python3
"""Org-wide view of which workspaces have stale generated CI workflows.

A companion to ``template/scripts/check-workflow-freshness.py``: that script runs
INSIDE one workspace's CI; this one scans MANY workspaces from viva-template and
reports which have drifted. It compares each repo's stamped workflow hashes
against viva-template's CURRENT template hashes (read from this checkout's
``template/.github/workflows/``).

Repository contents are read through the ``gh`` CLI (``gh api``), so it needs a
``GITHUB_TOKEN`` with read access to the target repos — which the bundled
``workflow-drift-report.yml`` workflow provides. Individual repo/API errors are
tolerated so one unreachable repo never sinks the whole report.

Output is a Markdown table written to stdout and, when running in Actions, to
``$GITHUB_STEP_SUMMARY``. Exit code is 0 unless ``--fail-on-drift`` is passed and
drift was found.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_WORKFLOWS = REPO_ROOT / "template" / ".github" / "workflows"
CHECKER_PATH = REPO_ROOT / "template" / "scripts" / "check-workflow-freshness.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_workflow_freshness",
                                                  CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _gh_json(args: list[str]) -> object | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True,
                             check=True, timeout=60).stdout
        return json.loads(out) if out.strip() else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, FileNotFoundError):
        return None


def current_template_hashes() -> dict[str, str]:
    """Map template filename -> current canonical hash (from this checkout)."""
    hashes: dict[str, str] = {}
    for path in TEMPLATE_WORKFLOWS.iterdir():
        if path.is_file():
            hashes[path.name] = checker.canonical_hash(path.read_text())
    return hashes


def list_org_repos(org: str, limit: int) -> list[str]:
    data = _gh_json(["repo", "list", org, "--no-archived", "--limit", str(limit),
                     "--json", "name"])
    if not data:
        return []
    return [f"{org}/{r['name']}" for r in data]


def repo_workflow_stamps(full_name: str) -> list[tuple[str, dict]]:
    """Return [(workflow_filename, stamp_dict)] for a repo's stamped workflows."""
    listing = _gh_json(["api", f"repos/{full_name}/contents/.github/workflows"])
    if not isinstance(listing, list):
        return []
    results: list[tuple[str, dict]] = []
    for entry in listing:
        name = entry.get("name", "")
        if not (name.endswith((".yml", ".yaml"))):
            continue
        blob = _gh_json(["api", entry["url"]])
        if not isinstance(blob, dict) or "content" not in blob:
            continue
        try:
            text = base64.b64decode(blob["content"]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        stamp = checker.parse_stamp(text)
        if stamp is not None:
            results.append((name, stamp))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default="vivarium-collective",
                        help="GitHub org to scan (default: vivarium-collective).")
    parser.add_argument("--repos", nargs="*", default=None,
                        help="explicit owner/repo list (skips org enumeration).")
    parser.add_argument("--limit", type=int, default=300,
                        help="max repos to enumerate from the org.")
    parser.add_argument("--fail-on-drift", action="store_true",
                        help="exit non-zero if any workspace is stale.")
    args = parser.parse_args(argv)

    template_hashes = current_template_hashes()
    repos = args.repos or list_org_repos(args.org, args.limit)

    rows: list[tuple[str, str, str, str]] = []  # repo, workflow, template, status
    drift = 0
    scanned_stamped = 0
    for full_name in repos:
        for wf_name, stamp in repo_workflow_stamps(full_name):
            scanned_stamped += 1
            tmpl = stamp["template"]
            current = template_hashes.get(tmpl)
            if current is None:
                status = "unknown-template"
            elif stamp["sha256"] == current:
                status = "fresh"
            else:
                status = "STALE"
                drift += 1
            rows.append((full_name, wf_name, tmpl, status))

    lines = ["# Workspace workflow drift report", ""]
    if not repos:
        lines.append("_No repositories scanned (gh unavailable or empty org)._")
    elif scanned_stamped == 0:
        lines.append(f"_Scanned {len(repos)} repo(s); none carry "
                     "viva-template-stamped workflows yet._")
    else:
        lines.append(f"Scanned **{len(repos)}** repo(s); "
                     f"**{scanned_stamped}** stamped workflow(s); "
                     f"**{drift}** stale.")
        lines.append("")
        lines.append("| Repository | Workflow | Template | Status |")
        lines.append("|---|---|---|---|")
        for repo, wf, tmpl, status in sorted(rows):
            badge = {"fresh": "✅ fresh", "STALE": "⚠️ **STALE**"}.get(status, status)
            lines.append(f"| {repo} | {wf} | {tmpl} | {badge} |")
    report = "\n".join(lines) + "\n"

    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(report)

    if args.fail_on_drift and drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
