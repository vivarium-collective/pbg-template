"""Generate plan.md and phase-N.md skeletons from a high-level plan dict."""
from __future__ import annotations
from pathlib import Path

from .phase_md import render_phase_md, parse_phase_md


_BODY_TEMPLATE = """## Phase {n}: {name}

### Objective
{objective}

### Required Biological Knowledge
- Mechanisms needed:
- Source documents/papers:
- Known unknowns:
- Expert questions:

### Implementation Tasks

### Readouts / Visualizations

### Expected Behavior

### Acceptance Tests

### Failure Modes

### Phase Gate

### Deliverables
"""


def create_initial_plan(phases_dir: Path, model_name: str, phases: list[dict]) -> None:
    """Write plan.md (umbrella) and one phase-N.md per phase to phases_dir."""
    phases_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in phases:
        rows.append(f"| {p['n']} | {p['name']} | {p.get('objective','')} | planned |")
    plan_md = "\n".join([
        f"# {model_name} · multi-phase plan",
        "",
        "Current focus: **(none yet)**",
        "",
        "| # | Name | Objective | Status |",
        "|---|------|-----------|--------|",
        *rows,
        "",
        "## Dependency notes",
        "",
        "## Open expert questions (cross-phase)",
        "",
    ])
    (phases_dir / "plan.md").write_text(plan_md)
    for p in phases:
        write_phase_file(phases_dir, p)


def write_phase_file(phases_dir: Path, phase: dict) -> None:
    """Write phase-{n}.md with the supplied frontmatter dict + a body skeleton."""
    fm = {
        "phase": phase["n"],
        "name": phase["name"],
        "status": phase.get("status", "planned"),
        "prereq_phases": phase.get("prereq_phases", []),
        "gate_passed": False,
        "acceptance_tests": phase.get("acceptance_tests", []),
    }
    body = _BODY_TEMPLATE.format(
        n=phase["n"], name=phase["name"], objective=phase.get("objective", ""),
    )
    (phases_dir / f"phase-{phase['n']}.md").write_text(render_phase_md(fm, body))


def parse_plan_status(phase_md_path: Path) -> dict:
    """Return the parsed frontmatter dict from a phase-N.md file path."""
    fm, _ = parse_phase_md(phase_md_path.read_text())
    return fm
