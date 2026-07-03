# pbg-template

Workspace scaffold for **Process-Bigraph** multiscale modeling. Each scaffolded
workspace is a self-contained research repo: a Python package, study specs,
composite documents, references, and the JSON schemas the dashboard and lint
tools validate against.

## Getting Started

Two paths, depending on whether you want AI assistance.

### Path A — Standalone (recommended starting point)

Use this template directly. No plugin, no Claude Code required.

1. Click **Use this template** on github.com/vivarium-collective/pbg-template
   (or `git clone https://github.com/vivarium-collective/pbg-template my-workspace`).
2. Initialize and install:

       cd my-workspace
       bash use-this-template-init.sh        # prompts for workspace name, renders .j2 files
       uv venv .venv && source .venv/bin/activate
       uv pip install -e ".[dev]"            # pulls in vivarium-workbench
       python3 scripts/lint-workspace.py     # should print "workspace lint: OK"

3. Launch the dashboard:

       bash scripts/serve.sh                 # or: vivarium-workbench serve --workspace .

   Open the URL it prints. See the generated `NEXT_STEPS.md` for a guided tour,
   and the [vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench)
   README for the dashboard's own feature walkthrough.

### Path B — AI-augmented (via the pbg-superpowers Claude Code plugin)

Want AI-assisted authoring? Install the
[pbg-superpowers](https://github.com/vivarium-collective/pbg-superpowers)
Claude Code plugin; running `/pbg-workspace my-project` from inside Claude
Code clones this template and bootstraps a workspace with conversational
study, composite, and visualization authoring on top. See the
[pbg-superpowers Getting Started](https://github.com/vivarium-collective/pbg-superpowers#getting-started)
for the full walkthrough.

### What to expect

A scaffolded workspace is a regular Python project. `pbg_<slug>/` holds your
code (composites, processes, visualizations); `studies/` and `composites/`
hold YAML specs; `references/` is your bibliography and claims log; and
`.pbg/schemas/` validates everything via `scripts/lint-workspace.py`. The
dashboard reads and writes these files, and you can edit them by hand —
both flows stay in sync. Every change the dashboard makes is a git commit
on your current branch, so you get a full audit trail of how your study
evolved.

## Canonical workspace organization

A scaffolded workspace separates **project code** (a normal Python project, at
the repo root) from **research state** (the directories the dashboard, skills,
and `lint-workspace.py` read and write). This split is the canonical layout.

**Project code — stays at the repo root:**

| Path | What it is |
|---|---|
| `pbg_<slug>/` | your Python package — `core.py` exposes `build_core()`; composites, processes, and visualizations live here |
| `scripts/` | `lint-workspace.py`, `serve.sh` (launches the dashboard), helpers |
| `tests/` | your test suite |
| `docs/` | project documentation |
| `pyproject.toml`, `README.md`, `workspace.yaml` | standard repo-root files |

**Research state — the pbg directories:**

| Path | What it is |
|---|---|
| `studies/` | research-question specs, one folder per study (`study.schema.json`) |
| `investigations/` | collections of studies with a DAG (`investigation.schema.json`) |
| `composites/` | runnable process-bigraph documents |
| `references/` | bibliography (`papers.bib`) + claims log + PDFs |
| `datasets/` | curated input data |
| `notes/` | field records (friction logs, walkthroughs, per-paper notes) |
| `experiments/` | ad-hoc experiment runs |
| `reports/` | generated HTML reports + `figures/` |
| `.pbg/` | machine state — `schemas/` (validators), run DBs, dashboard/server state |

### Where these directories live — the `layout:` map

Directory locations are not hardcoded: tooling resolves them through a
**`layout:`** map in `workspace.yaml`. **New workspaces ship nested** — the
research directories are grouped under a tidy `workspace/` subtree, while the
hidden `.pbg/` machine state stays at the root (like `.git/`):

```yaml
layout:
  studies: workspace/studies
  investigations: workspace/investigations
  composites: workspace/composites
  references: workspace/references
  datasets: workspace/datasets
  notes: workspace/notes
  experiments: workspace/experiments
  reports: workspace/reports
```

The `layout:` block is purely a set of overrides: **any key you remove falls
back to its conventional flat top-level name** (`studies` → `studies/`). So you
can flatten the layout, move directories elsewhere, or relocate `scripts`,
`tests`, `docs`, even the `package` — and a workspace with *no* `layout:` block
at all uses the classic flat layout, which is why every pre-existing workspace
keeps working untouched.

The dashboard, the `/pbg-*` skills, and `lint-workspace.py` all honor this map
(via the shared `WorkspacePaths` resolver), so you can relocate any directory —
including `scripts`, `tests`, `docs`, and the `package` — without touching code.

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
- **[vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench)** — the local web UI for browsing composites, running studies, and rendering visualizations against a scaffolded workspace.

## License

TBD — license file pending before 1.0.
