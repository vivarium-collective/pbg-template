"""Tests for the generated-workflow drift guard.

viva-template stamps every GitHub Actions workflow it scaffolds into a workspace
with a provenance block recording the hash of its source template
(``scripts/check-workflow-freshness.py``). These tests prove:

* every template workflow shipped in ``template/.github/workflows/`` carries a
  stamp that matches its own content (viva-template's own ``--check-templates``
  self-check — the check wired into template-ci);
* a fresh scaffold (workflows copied/rendered from the current templates) PASSES
  the workspace drift check;
* a workspace whose upstream template has since moved on (or whose stamp was
  hand-edited) FAILS the drift check.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# viva-template self-consistency: the check wired into template-ci
# ---------------------------------------------------------------------------

def test_every_template_workflow_is_stamped_and_consistent():
    """Fresh scaffold passes: each template's stamp matches its own content."""
    rc = checker.mode_check_templates(TEMPLATE_WORKFLOWS)
    assert rc == 0, "template workflow stamps are stale — run --update"


def test_all_expected_workflows_present_and_stamped():
    for name in checker.TEMPLATE_WORKFLOWS:
        path = TEMPLATE_WORKFLOWS / name
        assert path.is_file(), f"missing template workflow: {name}"
        stamp = checker.parse_stamp(path.read_text())
        assert stamp is not None, f"{name} carries no provenance stamp"
        assert stamp["template"] == name
        assert stamp["sha256"] == checker.canonical_hash(path.read_text())


# ---------------------------------------------------------------------------
# Simulated scaffold → workspace drift check
# ---------------------------------------------------------------------------

def _scaffold_workspace_workflows(dest: Path) -> Path:
    """Reproduce what a scaffolder produces: copy the template workflows,
    rendering ``.j2`` (extension stripped, placeholders substituted). The
    provenance stamp carries no placeholders, so it survives rendering."""
    wf_dir = dest / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    subs = {"workspace_name": "demo-ws", "package_path": "viva_demo_ws",
            "today": "2026-01-01", "plugin_version": "0.0.0",
            "generated_at": "2026-01-01"}
    for src in TEMPLATE_WORKFLOWS.iterdir():
        text = src.read_text()
        if src.name.endswith(".j2"):
            for key, val in subs.items():
                text = re.sub(r"{{\s*" + key + r"\s*}}", val, text)
            out = wf_dir / src.name[: -len(".j2")]
        else:
            out = wf_dir / src.name
        out.write_text(text)
    return wf_dir


def test_fresh_scaffold_passes_drift_check(tmp_path):
    """A workspace scaffolded from the CURRENT templates is not stale."""
    wf_dir = _scaffold_workspace_workflows(tmp_path)
    rc = checker.mode_check_workspace(
        wf_dir, repo="unused", ref="unused", template_dir=TEMPLATE_WORKFLOWS)
    assert rc == 0


def test_upstream_drift_is_caught(tmp_path):
    """If viva-template's template moves on, the workspace copy is flagged."""
    wf_dir = _scaffold_workspace_workflows(tmp_path)

    # Simulate the template repo advancing: copy the current templates into a
    # reference dir, then change one of them (as if a template bug was fixed).
    upstream = tmp_path / "upstream-templates"
    upstream.mkdir()
    for src in TEMPLATE_WORKFLOWS.iterdir():
        (upstream / src.name).write_text(src.read_text())

    moved = upstream / "build-and-push.yml"
    body = checker.strip_provenance_block(moved.read_text())
    # Re-stamp the moved template to its NEW content hash — exactly what
    # `--update` does in viva-template after a real edit.
    moved.write_text(checker.apply_stamp(
        body + "\n      - name: a newly added CI step\n        run: echo hi\n",
        "build-and-push.yml"))

    rc = checker.mode_check_workspace(
        wf_dir, repo="unused", ref="unused", template_dir=upstream)
    assert rc == 1, "drift check should FAIL when upstream template changed"


def test_hand_edited_stamp_is_caught_by_self_check(tmp_path):
    """A hand-tampered stamp fails viva-template's own --check-templates."""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    src = TEMPLATE_WORKFLOWS / "publish-reports.yml"
    tampered = src.read_text().replace(
        checker.parse_stamp(src.read_text())["sha256"], "0" * 64)
    (wf_dir / "publish-reports.yml").write_text(tampered)
    rc = checker.mode_check_templates(wf_dir)
    assert rc == 1


def test_unreachable_upstream_is_non_fatal(tmp_path):
    """A template that cannot be retrieved is a warning, not a failure."""
    wf_dir = _scaffold_workspace_workflows(tmp_path)
    empty = tmp_path / "empty-templates"
    empty.mkdir()  # no files → every upstream lookup returns None
    rc = checker.mode_check_workspace(
        wf_dir, repo="unused", ref="unused", template_dir=empty)
    assert rc == 0
