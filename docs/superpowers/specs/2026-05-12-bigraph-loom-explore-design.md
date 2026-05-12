# bigraph-loom-explore — read-only modular wiring viewer

**Date:** 2026-05-12
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Supersedes:** `_render_composite_svg` (bigraph-viz/graphviz subprocess) in the pbg-template Composite Explorer; the text-only state-tree renderer in the Investigation Composites tab.

## Problem

Two places in the pbg-template dashboard show composite structure today, each
with real limitations:

1. **Composite Explorer (workspace tab):** renders the composite via
   `bigraph-viz` shelling out to graphviz → static SVG. Subprocess overhead
   per render, no interactivity (no hover, no click-to-inspect, no
   expand/collapse), no readable node detail.
2. **Investigation Composites tab (newly built):** server returns a flat
   list of `{path, kind, type, default}` records; the frontend draws a
   text-only indented list. No wiring view at all.

The `bigraph-loom` project already implements an interactive React Flow
viewer with custom node renderers (`ProcessNode`, `StoreNode`), a layout
algorithm, and an Inspector — but it's built as a full editor (drag wires,
add stores, edit configs, multi-user sessions, JSON editor, Library panel).
For dashboard-side composite *exploration* we want the visualization without
the editing surface.

## Goals

- **Reuse loom's visualization core** (`ProcessNode`, `StoreNode`, layout
  algorithm) so the two tools stay visually consistent and improvements to
  the node renderers flow to both.
- **Read-only viewer.** No edit affordances. Clicking a node opens a simple
  inspector showing type/config/path. No drag-to-wire, no
  add-store/add-process, no JSON editor, no Library.
- **Standalone embeddable bundle.** Ships as a pre-built static asset
  (`dist/`). No Python server; no React build step in the dashboard's
  pipeline. The dashboard mounts it via `<iframe>`.
- **Drop-in replacement** for both bigraph-viz in the Composite Explorer
  and the text-tree in the Investigation Composites tab. Same component,
  two mount points.

## Non-goals

- **Editing.** No drag wires, no node creation/deletion, no config edits,
  no JSON-text editor.
- **Library / file management.** No browse-saved-composites, no save/load.
- **Multi-user sessions.** Single-browser, isolated state.
- **Jupyter integration.** Future possibility; not in scope here.
- **Hierarchy editing** (move-into / nest).

## Architecture

### New sibling package: `bigraph-loom-explore`

```
bigraph-loom-explore/
├── README.md
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx                  # entry point; mounts <App />
│   ├── App.tsx                   # top-level: canvas + inspector + toolbar
│   ├── api.ts                    # postMessage protocol (load composite, emit events)
│   ├── layout.ts                 # copied from bigraph-loom; auto-layout
│   ├── nodes/
│   │   ├── ProcessNode.tsx       # copied from bigraph-loom (read-only mode)
│   │   └── StoreNode.tsx         # copied from bigraph-loom (read-only mode)
│   ├── panels/
│   │   └── InspectorPanel.tsx    # read-only inspector (no Edit/JSON tabs)
│   └── types.ts                  # composite-state types
├── public/                       # any static assets (icons, etc.)
└── dist/                         # built output (gitignored; published artifact)
```

**Lives at:** `/Users/eranagmon/code/bigraph-loom-explore/` (sibling to
bigraph-loom). New git repo, vivarium-collective org once stable.

**Tech:** React 18 + TypeScript + Vite + `@xyflow/react` (React Flow) — matches
bigraph-loom's stack so node components can be lifted with minimal edits.

**Initial extraction strategy:** copy `ProcessNode.tsx`, `StoreNode.tsx`, and
`layout.ts` from bigraph-loom verbatim, then strip:
- All edit affordances (drag handles, +/- buttons, address-edit inputs)
- All non-Inspector panels
- Multi-user session imports
- File-load / library wiring

`InspectorPanel.tsx` is a fresh, simpler version — no Edit tab, no JSON tab.

### postMessage protocol

Dashboard ↔ iframe communication is one-way for data, two-way for events.

**Dashboard → iframe (load a composite):**
```javascript
iframe.contentWindow.postMessage({
  type: 'composite:load',
  state: {/* the composite state dict — same shape Composite() consumes */},
  metadata: {name: 'baseline', context: 'investigation:t1'},  // optional
}, '*');
```

**Iframe → dashboard (ready signal + click events):**
```javascript
parent.postMessage({type: 'explore:ready'}, '*');           // sent after mount
parent.postMessage({                                          // sent on node click
  type: 'explore:inspect',
  path: ['stores', 'chromosome'],
  kind: 'store' | 'process',
  details: {/* type, config, address, etc. */},
}, '*');
```

The dashboard can listen to `explore:inspect` to highlight related rows in
adjacent panels (e.g., Observables tab pre-tick the clicked path).

### URL-param mode (fallback for sharable links)

When the dashboard sets `<iframe src="/loom-explore/index.html?composite=<base64>">`,
the viewer decodes and renders without a postMessage round-trip. Useful for
direct links in notes; the dashboard's normal mode is postMessage.

### Build + distribution

bigraph-loom-explore is a static bundle. Build pipeline:

```bash
cd bigraph-loom-explore
npm install
npm run build          # → dist/{index.html, assets/*.js, assets/*.css}
```

**Versioned distribution.** Tags trigger an npm publish AND a GitHub
release with `dist/` zipped. pbg-template's installer pulls the published
zip pinned to a version (set in `template/scripts/_catalog/modules.json`
or a dedicated `loom-explore-version` field).

**Vendoring step at workspace scaffold time.** When a workspace is created
from pbg-template (or upgraded), the scaffold script downloads the pinned
loom-explore release and unpacks it to
`<workspace>/scripts/_assets/loom-explore/`. No build step in the workspace.

### pbg-template integration

**Static-asset serving.** The existing dashboard server already serves
`reports/assets/*`. Add a route that serves `scripts/_assets/loom-explore/`
under `/loom-explore/`. Iframe srcs use that path.

**Composite Explorer (workspace tab):**

Replace the `<img>`/SVG container that today shows
`_render_composite_svg`'s output with:

```html
<iframe id="composite-explore-frame"
        src="/loom-explore/index.html"
        style="width:100%;height:560px;border:1px solid #ddd;background:#fff">
</iframe>
```

When the page loads a composite (existing `/api/composite-state?id=...` or
similar), JS posts the state to the iframe:

```javascript
iframe.addEventListener('load', () => {
  // Wait for explore:ready, then send the composite
  window.addEventListener('message', (ev) => {
    if (ev.data?.type === 'explore:ready') {
      iframe.contentWindow.postMessage({
        type: 'composite:load',
        state: currentCompositeState,
        metadata: {name: currentCompositeName},
      }, '*');
    }
  });
});
```

**Investigation Composites tab:**

The right pane currently renders a text-only state tree. Replace with the
same iframe, scoped to the selected composite:

- Sidebar click on composite name → fetch `composites/<name>.yaml`,
  parse, postMessage to the iframe.

### Feature-flag rollout

While loom-explore is unstable, gate the iframe behind a workspace.yaml
flag:

```yaml
ui:
  composite_view: loom-explore   # or 'bigraph-viz' (fallback)
```

Server endpoint inspects this flag; frontend reads it from a new
`/api/ui-config` endpoint and conditionally renders iframe vs. SVG.
Default: `loom-explore` once we ship a tagged release.

### Removal of bigraph-viz

Once loom-explore is the default for ≥2 sessions of real use with no
regressions, `_render_composite_svg` and the `bigraph-viz` dependency in
`pyproject.toml` are removed. The Python-side composite-state endpoint
stays — loom-explore consumes it.

## Data flow

**Composite Explorer (workspace) loading a registered composite:**

1. User opens Composite Explorer → picks `chromosome-partition` from the
   list.
2. Dashboard fetches `/api/composite-state?id=pbg_chromosome_rep1.composites.chromosome-partition`
   → returns parsed state dict.
3. iframe is mounted; on `explore:ready` event, dashboard posts the state.
4. Inside iframe: React Flow renders the composite. User can click nodes
   to inspect, drag to pan, scroll to zoom.

**Investigation Composites tab loading a derived composite:**

1. User picks `high-count` in the sidebar.
2. Dashboard fetches the document directly:
   `/investigations/t1/composites/high-count.yaml` → parsed.
3. Iframe (already mounted in the panel) receives a new postMessage with
   the new state.
4. View updates. Inspector state is reset.

**Inspector click event:**

1. User clicks the `replication` process node.
2. iframe posts `{type: 'explore:inspect', path: ['replication'],
   kind: 'process', details: {address: 'local:DnaAReplisome', config: {...}}}`.
3. Dashboard receives → uses it for cross-panel highlighting (e.g., on the
   Observables tab, the row at that path could highlight).

## Error handling

- **No composite state supplied.** Viewer shows
  `"Waiting for composite data…"` placeholder; no React Flow render.
- **Malformed state JSON.** Viewer shows
  `"Invalid composite state: <short error>"` with a Retry button that
  re-requests ready.
- **Process node references unregistered address.** Loom already handles
  this gracefully (shows the node as a generic-styled box with the
  address label); the explore variant inherits this.
- **iframe src 404.** Dashboard's mounting JS detects the iframe failed
  to load and falls back to the legacy SVG render with a small banner
  saying "interactive view unavailable; showing static SVG".

## Testing

**bigraph-loom-explore (new repo):**
- `vitest` unit tests for `layout.ts` (mirrors loom's tests if present)
- `playwright` smoke: render the bundle in a headless browser, postMessage
  a fixture composite, assert nodes appear, click a node, assert
  `explore:inspect` is posted back.
- Bundle-size budget: dist/ stays under a documented cap (say 600KB
  gzipped) so the iframe loads fast.

**pbg-template:**
- `test_static_assets_serves_loom_explore`: server returns the
  `/loom-explore/index.html` and an asset file with 200.
- `test_composite_state_endpoint_shape`: the existing endpoint that
  returns composite state dicts must match loom-explore's expected
  schema. Add a fixture + round-trip assertion.
- Frontend: visual smoke at Task 5 (manual; the iframe should render
  the chromosome-partition composite without errors).

## Backwards compatibility

- **bigraph-viz dependency** remains in `pyproject.toml` until the
  feature-flag default flips and ≥2 sessions of real use pass. Then
  it's removed in a follow-up.
- **`_render_composite_svg`** stays as a fallback path triggered by
  the feature flag or by an iframe load failure.
- **Existing composite-state endpoints** don't change shape. The viewer
  is purely additive on the frontend.

## Implementation rollout

**Phase A — bigraph-loom-explore repo bootstrap**
- Create the repo + Vite/React scaffold.
- Copy `ProcessNode`, `StoreNode`, `layout.ts` from bigraph-loom; strip
  edit affordances.
- Build a minimal Inspector (read-only).
- Implement the postMessage protocol.
- Build the static bundle; smoke-test in a standalone HTML page.

**Phase B — bundle distribution**
- Tag `v0.1.0`, attach the built `dist/` zip to the GitHub release.
- Add a scaffold step (or CLI helper) in pbg-template to download +
  unpack the release into `scripts/_assets/loom-explore/`.

**Phase C — pbg-template integration**
- Server: serve `/loom-explore/` static assets.
- Composite Explorer: replace SVG with iframe; wire postMessage.
- Investigation Composites tab: replace text tree with iframe (sidebar
  click loads new state via postMessage).
- Feature flag `ui.composite_view` in workspace.yaml; default
  `loom-explore`.

**Phase D — v2ecoli verification**
- Sync, restart, open the Composite Explorer on `chromosome-partition`
  → confirm interactive view loads, click-to-inspect works.
- Open `t1` investigation → Composites tab → click each of
  `chromosome-partition`, `high-count`, `low-count` → confirm view
  updates.
- Confirm `explore:inspect` postMessage round-trips (for now, log to
  console; cross-panel highlighting is a follow-up).

**Phase E — cleanup**
- After ≥2 sessions confirm stability, remove `bigraph-viz` from
  `pyproject.toml` and delete `_render_composite_svg`.

## Out of scope (follow-ups)

- **Cross-panel highlighting.** Use `explore:inspect` events to
  auto-tick the Observables tab when the user clicks a store node.
- **Layout persistence.** Save the user's manual node positions per
  composite in workspace.yaml (`composites/<name>.layout.json` or
  similar).
- **Visualization preview integration.** When previewing a visualization
  via the Workspace panel, render the viz's input-port wiring with
  loom-explore.
- **Jupyter embed.** loom-explore could ship a Jupyter widget that
  mirrors the dashboard's iframe pattern. Defer until the bundle is
  stable.
- **Hierarchy view (loom feature).** Useful for nested composites; not
  needed for flat exploration today.
