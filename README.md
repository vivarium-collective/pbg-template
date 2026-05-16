# pbg-template

Workspace scaffold for **Process-Bigraph** multiscale modeling. Each scaffolded
workspace is a self-contained research repo: a Python package, study specs,
composite documents, references, and the JSON schemas the dashboard and lint
tools validate against.

Two ways to use it:

1. **With the [pbg-superpowers](https://github.com/vivarium-collective/pbg-superpowers) Claude Code plugin** — AI-assisted authoring flow.
2. **Standalone via GitHub "Use this template"** — vanilla workspace, no plugin required.

## Quick start (with plugin)

Install the plugin, then from any directory:

    /pbg-workspace my-research-workspace

## Quick start (standalone)

Click **Use this template** on github.com/vivarium-collective/pbg-template,
clone your new repo, then:

    bash use-this-template-init.sh   # prompts for workspace name, renders .j2 files
    uv venv .venv && source .venv/bin/activate
    uv pip install -e ".[dev]"
    python3 scripts/lint-workspace.py   # should print "workspace lint: OK"

See the generated `NEXT_STEPS.md` for the full tour.

## What a scaffolded workspace contains

- `workspace.yaml` — canonical state (observables, simulations, imports, …).
- `pbg_<slug>/` — your Python package (`core.py` exposes `build_core()`; add composites and visualizations here).
- `studies/` — research-question specs (one folder per study; see `study.schema.json`).
- `composites/` — runnable process-bigraph documents.
- `references/`, `datasets/` — bibliography + curated data.
- `.pbg/schemas/` — validators the dashboard and `lint-workspace.py` check against.
- `scripts/` — `lint-workspace.py`, `serve.sh` (launches the dashboard), helpers.

## Schemas

The authoritative validators live in `template/.pbg/schemas/` and are copied
into every scaffolded workspace:

- `workspace.schema.json` — top-level `workspace.yaml` shape.
- `study.schema.json` — the 8-section canonical Study structure (Design → Build → Simulate → Evaluate → Decide), including follow-up proposals for Decide-phase loops.
- `investigation.schema.json` — Investigations as collections of studies with a DAG via `pipeline_gate.prerequisites`.

Schemas are pinned at scaffold time. `/pbg-workspace` overwrites them with the
plugin's current version; standalone users get whatever was last synced here.

## Companion repos

- **[pbg-superpowers](https://github.com/vivarium-collective/pbg-superpowers)** — the Claude Code plugin that wraps this template with scaffolding + Studies + Visualizations skills. Use it for the AI-assisted authoring flow.
- **[vivarium-dashboard](https://github.com/vivarium-collective/vivarium-dashboard)** — the local web UI for browsing composites, running studies, and rendering visualizations against a scaffolded workspace.

## License

MIT.
