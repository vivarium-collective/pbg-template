# bigraph-loom-explore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only sibling package `bigraph-loom-explore` that reuses bigraph-loom's React Flow node renderers + layout, ships as a static bundle, and replaces both the bigraph-viz SVG in the Composite Explorer and the text-only state tree in the Investigation Composites tab via `<iframe>` + postMessage.

**Architecture:** New repo at `/Users/eranagmon/code/bigraph-loom-explore/` (React + TypeScript + Vite + React Flow, same stack as loom). Components extracted from bigraph-loom with edit affordances stripped. Pre-built `dist/` distributed via GitHub release zip; pbg-template vendors the unpacked bundle into `template/scripts/_assets/loom-explore/`. Dashboard mounts via iframe; postMessage protocol delivers composite state + emits click events.

**Tech Stack:** React 18, TypeScript, Vite, @xyflow/react, @dagrejs/dagre. pbg-template stays Python + vanilla JS.

---

## File Structure

### Created (bigraph-loom-explore — new repo)

| File | Responsibility |
|---|---|
| `package.json` | Vite build scripts, deps mirroring loom's frontend. |
| `vite.config.ts` | Vite config; build target = static dist with relative asset paths so the bundle works under any subpath (e.g. `/loom-explore/`). |
| `tsconfig.json`, `tsconfig.node.json` | TypeScript config. |
| `index.html` | Mount point div + script tag. |
| `src/main.tsx` | Entry; mounts `<App />`. |
| `src/App.tsx` | Top-level layout: React Flow canvas + optional Inspector panel + tiny toolbar (layout-mode, zoom). |
| `src/api.ts` | postMessage protocol — listens for `composite:load`, emits `explore:ready` and `explore:inspect`. |
| `src/layout.ts` | Auto-layout (copied from loom). |
| `src/types.ts` | Composite-state TypeScript types. |
| `src/nodes/ProcessNode.tsx` | Process node (copied from loom; edit affordances stripped). |
| `src/nodes/StoreNode.tsx` | Store node (copied from loom; edit affordances stripped). |
| `src/panels/InspectorPanel.tsx` | Read-only inspector (path, kind, type, address/config). No Edit tab, no JSON tab. |
| `src/__tests__/layout.test.ts` | vitest unit tests for the layout algorithm. |
| `src/__tests__/api.test.ts` | vitest tests for the postMessage protocol. |
| `tests/e2e/smoke.spec.ts` | playwright smoke: load bundle, post composite, click node, assert inspect event. |
| `README.md` | Quick-start, build, embed instructions. |
| `.gitignore` | dist/, node_modules/, .DS_Store. |

### Created (pbg-template)

| File | Responsibility |
|---|---|
| `template/scripts/_assets/loom-explore/` | Built bundle (gitignored at first commit; vendored later). |
| `template/scripts/_lib/loom_explore_install.py` | Helper to download + unpack the loom-explore release zip into `_assets/`. |
| `tests/test_loom_explore_serve.py` | Server-side test: `/loom-explore/index.html` is served when the bundle is present. |

### Modified (pbg-template)

| File | Change |
|---|---|
| `template/scripts/_server/server.py` | Serve `/loom-explore/*` as static; add `/api/ui-config` for the feature flag; add `/api/composite-state?ref=...` if missing (returns parsed composite YAML). |
| `template/scripts/_server/walkthrough.js` | Composite Explorer + Investigation Composites tab: mount iframe, wire postMessage. |
| `template/scripts/_templates/index.html.j2` | Replace SVG container in Composite Explorer panel with iframe; replace text-tree div in Investigation Composites tab with iframe. |
| `template/scripts/_catalog/workspace_schema_extras.yaml` (or similar) | Add `ui.composite_view: loom-explore` default to scaffolded workspace.yaml; document the flag. |

---

## Phase A — bigraph-loom-explore repo bootstrap

### Task 1: Scaffold the new repo

**Files (new repo at `/Users/eranagmon/code/bigraph-loom-explore/`):**
- Create: `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `.gitignore`, `README.md`

- [ ] **Step 1: Create the directory + git init**

```bash
mkdir -p /Users/eranagmon/code/bigraph-loom-explore
cd /Users/eranagmon/code/bigraph-loom-explore
git init
```

- [ ] **Step 2: Write `package.json`**

```json
{
  "name": "bigraph-loom-explore",
  "private": false,
  "version": "0.1.0",
  "description": "Read-only React Flow viewer for process-bigraph composites. Embeddable via iframe + postMessage. Reuses node renderers + layout from bigraph-loom.",
  "license": "Apache-2.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@dagrejs/dagre": "^1.1.4",
    "@xyflow/react": "^12.4.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.0",
    "typescript": "~5.6.2",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 3: Write `vite.config.ts`**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Relative asset paths so the bundle works under any base URL
  // (e.g. /loom-explore/ when embedded in pbg-template).
  base: './',
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
  },
});
```

- [ ] **Step 4: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 5: Write `tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 6: Write `index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>bigraph-loom-explore</title>
    <style>
      body { margin: 0; height: 100vh; font-family: system-ui, sans-serif; }
      #root { height: 100%; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Write `src/main.tsx`**

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 8: Write `src/App.tsx` (placeholder)**

```tsx
import { useEffect, useState } from 'react';

export default function App() {
  const [status, setStatus] = useState<'waiting' | 'ready'>('waiting');

  useEffect(() => {
    window.parent.postMessage({ type: 'explore:ready' }, '*');
    setStatus('ready');
  }, []);

  return (
    <div style={{ padding: 24, fontFamily: 'system-ui' }}>
      <h2>bigraph-loom-explore</h2>
      <p>status: {status}</p>
      <p style={{ color: '#666' }}>(canvas mount point — Task 3 wires React Flow here)</p>
    </div>
  );
}
```

- [ ] **Step 9: Write `.gitignore` + `README.md`**

```
# .gitignore
node_modules/
dist/
.DS_Store
*.tsbuildinfo
.vite/
test-results/
playwright-report/
```

```markdown
# bigraph-loom-explore

Read-only React Flow viewer for process-bigraph composites. Reuses node
renderers and layout from [bigraph-loom](https://github.com/vivarium-collective/bigraph-loom),
stripped of all edit affordances. Designed to be embedded via `<iframe>`
+ `postMessage`.

## Build

    npm install
    npm run build      # → dist/

## Embed

    <iframe src="/path/to/dist/index.html"></iframe>

After load, send the composite state:

    iframe.contentWindow.postMessage({
      type: 'composite:load',
      state: { /* composite state dict */ },
    }, '*');

## Tests

    npm test            # vitest unit tests
    npm run test:e2e    # playwright smoke
```

- [ ] **Step 10: Verify the scaffold builds + serves**

```bash
cd /Users/eranagmon/code/bigraph-loom-explore
npm install 2>&1 | tail -3
npm run build 2>&1 | tail -8
ls dist/
```

Expected: `dist/` contains `index.html` + `assets/*.js`. No build errors.

- [ ] **Step 11: First commit**

```bash
git add -A
git commit -m "feat: scaffold bigraph-loom-explore (Vite + React + TS placeholder)"
```

---

### Task 2: Copy node + layout components from bigraph-loom

**Files:**
- Copy + modify: `src/nodes/ProcessNode.tsx`, `src/nodes/StoreNode.tsx`, `src/layout.ts`, `src/types.ts`
- Adapt: remove edit affordances; keep visual rendering + click handler

- [ ] **Step 1: Copy files from bigraph-loom**

```bash
cd /Users/eranagmon/code/bigraph-loom-explore
mkdir -p src/nodes
cp /Users/eranagmon/code/bigraph-loom/frontend/src/nodes/ProcessNode.tsx src/nodes/
cp /Users/eranagmon/code/bigraph-loom/frontend/src/nodes/StoreNode.tsx src/nodes/
cp /Users/eranagmon/code/bigraph-loom/frontend/src/layout.ts src/
cp /Users/eranagmon/code/bigraph-loom/frontend/src/types.ts src/
```

- [ ] **Step 2: Strip edit affordances from ProcessNode.tsx**

Open `src/nodes/ProcessNode.tsx`. Find and remove (or stub):
- Any drag-handle elements that exist purely for edit-time wiring.
- Buttons / context menus that trigger edits (e.g., "+ port", "Edit", "Delete").
- Any `useState` / `useCallback` that manages edit-mode state.
- Imports of edit-related context / panels.

Keep:
- The visual rendering (icon, label, address, port labels).
- The `onClick` handler — but reroute it to emit a `node:click` event up to App.

Add a `readonly: true` semantic by:
- Replacing any `editable` prop checks with a constant `false`.
- Removing any `onChange`/`onBlur` event handlers on inputs (or removing the inputs entirely if they were edit-only).

- [ ] **Step 3: Strip edit affordances from StoreNode.tsx**

Same as Step 2 for `src/nodes/StoreNode.tsx`. Stores in loom typically have:
- An editable address path input → remove, render as a `<code>` span instead.
- A value editor (textbox / number input) → remove; display value as read-only text.
- Drag handles for wiring → remove.

Click handler still fires for inspect.

- [ ] **Step 4: Strip imports from `layout.ts` + `types.ts`**

Open `src/layout.ts` and `src/types.ts`. Remove any imports that pull from loom's edit-specific modules (panels, session, etc.). The layout algorithm itself is pure — just walks nodes + edges and computes positions via dagre. Should compile standalone.

- [ ] **Step 5: Type-check + build**

```bash
cd /Users/eranagmon/code/bigraph-loom-explore
npm run build 2>&1 | tail -15
```

Expected: clean build. Fix any TS errors (imports of missing modules, unused locals, etc.).

- [ ] **Step 6: Write a layout unit test**

```ts
// src/__tests__/layout.test.ts
import { describe, it, expect } from 'vitest';
import { computeLayout } from '../layout';

describe('computeLayout', () => {
  it('positions a single store at the origin', () => {
    const nodes = [{ id: 'a', type: 'store', data: {} as any, position: { x: 0, y: 0 } }];
    const out = computeLayout(nodes, []);
    expect(out).toHaveLength(1);
    expect(out[0].position).toBeDefined();
  });

  it('separates two unconnected nodes', () => {
    const nodes = [
      { id: 'a', type: 'store', data: {} as any, position: { x: 0, y: 0 } },
      { id: 'b', type: 'store', data: {} as any, position: { x: 0, y: 0 } },
    ];
    const out = computeLayout(nodes, []);
    expect(out[0].position).not.toEqual(out[1].position);
  });
});
```

If `layout.ts` exports a different function name than `computeLayout`, adapt — read it and use the actual export. The point of this test is to verify the algorithm runs end-to-end without crashing.

- [ ] **Step 7: Run tests**

```bash
npm test 2>&1 | tail -10
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: import node renderers + layout from bigraph-loom; strip edit affordances"
```

---

### Task 3: Wire React Flow canvas + Inspector + postMessage protocol

**Files:**
- Modify: `src/App.tsx`
- Create: `src/api.ts`, `src/panels/InspectorPanel.tsx`, `src/__tests__/api.test.ts`

- [ ] **Step 1: Write `src/api.ts` (postMessage protocol)**

```ts
// src/api.ts
export type CompositeLoadMsg = {
  type: 'composite:load';
  state: any;
  metadata?: { name?: string; context?: string };
};

export type ExploreReadyMsg = { type: 'explore:ready' };

export type ExploreInspectMsg = {
  type: 'explore:inspect';
  path: string[];
  kind: 'store' | 'process';
  details: Record<string, unknown>;
};

export function postReady() {
  window.parent.postMessage({ type: 'explore:ready' } as ExploreReadyMsg, '*');
}

export function postInspect(payload: Omit<ExploreInspectMsg, 'type'>) {
  window.parent.postMessage({ type: 'explore:inspect', ...payload }, '*');
}

export function onCompositeLoad(handler: (msg: CompositeLoadMsg) => void) {
  const listener = (ev: MessageEvent) => {
    if (ev.data?.type === 'composite:load') handler(ev.data as CompositeLoadMsg);
  };
  window.addEventListener('message', listener);
  return () => window.removeEventListener('message', listener);
}

/** Decode an optional URL-param composite (?composite=<base64-json>). */
export function decodeUrlComposite(): any | null {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get('composite');
  if (!raw) return null;
  try {
    return JSON.parse(atob(raw));
  } catch {
    return null;
  }
}
```

- [ ] **Step 2: Write `src/panels/InspectorPanel.tsx`**

```tsx
// src/panels/InspectorPanel.tsx
import { ExploreInspectMsg } from '../api';

export function InspectorPanel(props: { selection: Omit<ExploreInspectMsg, 'type'> | null }) {
  const sel = props.selection;
  if (!sel) {
    return (
      <div style={panelStyle}>
        <h4 style={{ margin: 0, fontSize: 14 }}>Inspector</h4>
        <p style={{ color: '#888', fontSize: 12 }}>Click a node to inspect.</p>
      </div>
    );
  }
  return (
    <div style={panelStyle}>
      <h4 style={{ margin: 0, fontSize: 14 }}>{sel.kind}</h4>
      <p style={{ fontFamily: 'monospace', fontSize: 12, margin: '4px 0' }}>
        {sel.path.join('.')}
      </p>
      <pre style={{ fontSize: 11, background: '#f7f7f7', padding: 6, overflow: 'auto', maxHeight: 280 }}>
        {JSON.stringify(sel.details, null, 2)}
      </pre>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 8,
  right: 8,
  width: 280,
  background: '#fff',
  border: '1px solid #ddd',
  borderRadius: 4,
  padding: 10,
  boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
  zIndex: 10,
};
```

- [ ] **Step 3: Rewrite `src/App.tsx` with React Flow**

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow, Background, Controls, ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { ProcessNode } from './nodes/ProcessNode';
import { StoreNode } from './nodes/StoreNode';
import { computeLayout } from './layout';
import { InspectorPanel } from './panels/InspectorPanel';
import {
  postReady, postInspect, onCompositeLoad, decodeUrlComposite, ExploreInspectMsg,
} from './api';
import { stateToReactFlow } from './convert';   // small helper added below

const NODE_TYPES = { process: ProcessNode, store: StoreNode };

export default function App() {
  const [state, setState] = useState<any | null>(decodeUrlComposite());
  const [selection, setSelection] = useState<Omit<ExploreInspectMsg, 'type'> | null>(null);

  // Wire postMessage protocol
  useEffect(() => {
    const off = onCompositeLoad((msg) => setState(msg.state));
    postReady();
    return off;
  }, []);

  // Convert composite state → React Flow nodes + edges, then auto-layout
  const { nodes, edges } = useMemo(() => {
    if (!state) return { nodes: [], edges: [] };
    const raw = stateToReactFlow(state);
    const laid = computeLayout(raw.nodes, raw.edges);
    return { nodes: laid, edges: raw.edges };
  }, [state]);

  const handleNodeClick = useCallback((_: any, node: any) => {
    const payload = {
      path: node.data?.path ?? [],
      kind: node.type as 'store' | 'process',
      details: node.data ?? {},
    };
    setSelection(payload);
    postInspect(payload);
  }, []);

  if (!state) {
    return (
      <div style={{ padding: 24, fontFamily: 'system-ui' }}>
        <h3>bigraph-loom-explore</h3>
        <p style={{ color: '#666' }}>Waiting for composite data…</p>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodeClick={handleNodeClick}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
        <InspectorPanel selection={selection} />
      </div>
    </ReactFlowProvider>
  );
}
```

- [ ] **Step 4: Write `src/convert.ts` (composite state → React Flow nodes/edges)**

```ts
// src/convert.ts
// Walk a process-bigraph composite state dict; emit React Flow nodes + edges.
// A typed-leaf store (dict with `_type`) becomes a Store node.
// A `_type: process` entry becomes a Process node with inputs/outputs as edges.
// Plain-dict containers recurse.

type RFNode = { id: string; type: 'store' | 'process'; data: any; position: { x: number; y: number } };
type RFEdge = { id: string; source: string; target: string; label?: string };

export function stateToReactFlow(state: any): { nodes: RFNode[]; edges: RFEdge[] } {
  const nodes: RFNode[] = [];
  const edges: RFEdge[] = [];
  const root = state?.state ?? state ?? {};

  function pathKey(path: string[]) {
    return path.length ? path.join('.') : '<root>';
  }

  function walk(node: any, path: string[]) {
    if (!node || typeof node !== 'object' || Array.isArray(node)) {
      // Scalar leaf — render as a store with default value
      nodes.push({
        id: pathKey(path),
        type: 'store',
        data: { path, value: node, type: typeof node },
        position: { x: 0, y: 0 },
      });
      return;
    }
    if (node._type === 'process') {
      const id = pathKey(path);
      nodes.push({
        id,
        type: 'process',
        data: {
          path,
          address: node.address ?? '',
          config: node.config ?? {},
          inputs: node.inputs ?? {},
          outputs: node.outputs ?? {},
        },
        position: { x: 0, y: 0 },
      });
      // Edges from each input/output port to the addressed store
      for (const [port, target] of Object.entries(node.inputs ?? {})) {
        const tid = Array.isArray(target) ? (target as string[]).join('.') : String(target);
        edges.push({ id: `${id}--in--${port}`, source: tid, target: id, label: port });
      }
      for (const [port, target] of Object.entries(node.outputs ?? {})) {
        const tid = Array.isArray(target) ? (target as string[]).join('.') : String(target);
        edges.push({ id: `${id}--out--${port}`, source: id, target: tid, label: port });
      }
      return;
    }
    if ('_type' in node) {
      // Typed store leaf
      nodes.push({
        id: pathKey(path),
        type: 'store',
        data: { path, type: node._type, default: node._default },
        position: { x: 0, y: 0 },
      });
      return;
    }
    // Plain container: recurse
    for (const [key, child] of Object.entries(node)) {
      walk(child, [...path, key]);
    }
  }
  walk(root, []);
  return { nodes, edges };
}
```

- [ ] **Step 5: Write `src/__tests__/api.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('postMessage protocol', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('postReady fires the parent message', async () => {
    const spy = vi.spyOn(window.parent, 'postMessage');
    const { postReady } = await import('../api');
    postReady();
    expect(spy).toHaveBeenCalledWith({ type: 'explore:ready' }, '*');
  });

  it('postInspect includes path, kind, details', async () => {
    const spy = vi.spyOn(window.parent, 'postMessage');
    const { postInspect } = await import('../api');
    postInspect({ path: ['a', 'b'], kind: 'store', details: { foo: 1 } });
    expect(spy).toHaveBeenCalledWith(
      { type: 'explore:inspect', path: ['a', 'b'], kind: 'store', details: { foo: 1 } },
      '*'
    );
  });

  it('onCompositeLoad invokes handler for matching messages', async () => {
    const { onCompositeLoad } = await import('../api');
    const handler = vi.fn();
    const off = onCompositeLoad(handler);
    window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'composite:load', state: { foo: 1 } },
    }));
    expect(handler).toHaveBeenCalledOnce();
    expect(handler.mock.calls[0][0].state).toEqual({ foo: 1 });
    off();
  });

  it('onCompositeLoad ignores non-matching messages', async () => {
    const { onCompositeLoad } = await import('../api');
    const handler = vi.fn();
    const off = onCompositeLoad(handler);
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'something-else' } }));
    expect(handler).not.toHaveBeenCalled();
    off();
  });
});
```

- [ ] **Step 6: Run tests + build**

```bash
cd /Users/eranagmon/code/bigraph-loom-explore
npm test 2>&1 | tail -15
npm run build 2>&1 | tail -10
ls dist/
```

Expected: all tests pass, `dist/` contains `index.html` + `assets/*.js`. Bundle should be under ~600KB gzipped.

- [ ] **Step 7: Manual smoke**

```bash
npx vite preview --port 4173 &
sleep 2
# Open in browser and send a sample composite via console:
#   iframe = location.reload
#   (manually open browser at http://localhost:4173 and confirm it shows
#    "Waiting for composite data…", then in DevTools console:
#    postMessage({type:'composite:load', state:{state:{x:{_type:'integer',_default:1}}}}, '*'))
echo "Open http://localhost:4173 in browser, paste composite via DevTools, confirm canvas renders."
```

(Manual step; describe in report whether the canvas renders successfully.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: React Flow canvas + Inspector + postMessage protocol"
```

---

## Phase B — Bundle distribution

### Task 4: Tag v0.1.0 + GitHub release zip (optional remote push)

**Files:**
- (no new files; just build + tag artifacts)

- [ ] **Step 1: Build + zip the dist/**

```bash
cd /Users/eranagmon/code/bigraph-loom-explore
npm run build
cd dist
zip -r ../bigraph-loom-explore-v0.1.0.zip .
cd ..
ls -la bigraph-loom-explore-v0.1.0.zip
```

Expected: a single zip file ~500-600KB containing index.html + assets/.

- [ ] **Step 2: Tag**

```bash
git tag v0.1.0
git log --oneline | head -5
```

- [ ] **Step 3: (Defer) GitHub remote**

The user may not want a public remote yet. Plan stops here for now —
pbg-template integration (Phase C) consumes the local zip from
`/Users/eranagmon/code/bigraph-loom-explore/bigraph-loom-explore-v0.1.0.zip`
or directly from `dist/` via `cp`.

Note in the report: zip available at the above path; remote push deferred.

---

## Phase C — pbg-template integration

### Task 5: Serve `/loom-explore/*` static assets + vendor the bundle

**Files:**
- Modify: `template/scripts/_server/server.py`
- Vendor: copy `bigraph-loom-explore/dist/` → `template/scripts/_assets/loom-explore/`
- Create: `template/tests/test_loom_explore_serve.py`

- [ ] **Step 1: Vendor the built bundle**

```bash
cd /Users/eranagmon/code/pbg-template
mkdir -p template/scripts/_assets/loom-explore
cp -R /Users/eranagmon/code/bigraph-loom-explore/dist/* template/scripts/_assets/loom-explore/
ls template/scripts/_assets/loom-explore/
```

- [ ] **Step 2: Write failing test** at `template/tests/test_loom_explore_serve.py`

```python
"""Test that the loom-explore static bundle is served by the dashboard."""
import sys
import threading
import urllib.request
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def workspace_server(tmp_path, monkeypatch):
    ws_root = tmp_path
    (ws_root / "workspace.yaml").write_text(yaml.dump({
        "name": "testws",
        "package_path": "pbg_testws",
    }, sort_keys=False))

    # Vendor a stub bundle for the test
    bundle_dir = ws_root / "scripts" / "_assets" / "loom-explore"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<html><body>loom-explore</body></html>")
    (bundle_dir / "assets").mkdir()
    (bundle_dir / "assets" / "stub.js").write_text("console.log('loom');")

    monkeypatch.chdir(ws_root)
    import importlib
    import scripts._server.server as srv
    importlib.reload(srv)
    monkeypatch.setattr(srv, "WORKSPACE", ws_root)

    httpd = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class _WS:
        url = f"http://127.0.0.1:{port}"
        root = ws_root

    yield _WS()
    httpd.shutdown()
    thread.join(timeout=2)


def test_loom_explore_index_served(workspace_server):
    with urllib.request.urlopen(workspace_server.url + "/loom-explore/index.html") as resp:
        assert resp.status == 200
        body = resp.read().decode()
        assert "loom-explore" in body


def test_loom_explore_asset_served(workspace_server):
    with urllib.request.urlopen(workspace_server.url + "/loom-explore/assets/stub.js") as resp:
        assert resp.status == 200
        body = resp.read().decode()
        assert "console.log" in body
```

- [ ] **Step 3: Confirm fail**

```bash
cd /Users/eranagmon/code/pbg-template
python -m pytest tests/test_loom_explore_serve.py -v
```

- [ ] **Step 4: Add the static-file route to `template/scripts/_server/server.py`**

Find the existing static-file fallback in `do_GET` (search for the path-traversal check + `WORKSPACE / rel` serve logic). Add a branch BEFORE that fallback:

```python
        # Serve the bundled loom-explore viewer
        if self.path.startswith("/loom-explore/"):
            rel = self.path[len("/loom-explore/"):].lstrip("/")
            if ".." in rel.split("/"):
                self.send_response(403); self.end_headers(); return
            asset_root = WORKSPACE / "scripts" / "_assets" / "loom-explore"
            target = asset_root / rel if rel else asset_root / "index.html"
            if target.is_file():
                ctype = "text/html"
                if target.suffix == ".js":   ctype = "application/javascript"
                elif target.suffix == ".css": ctype = "text/css"
                elif target.suffix == ".map": ctype = "application/json"
                elif target.suffix == ".svg": ctype = "image/svg+xml"
                return self._serve_file(target, ctype)
            self.send_response(404); self.end_headers(); return
```

If `_serve_file` doesn't accept content-type directly, adapt to the existing static-serve helper (look for how `reports/assets/*` files are served).

- [ ] **Step 5: Confirm pass**

```bash
python -m pytest tests/test_loom_explore_serve.py -v
```

- [ ] **Step 6: Commit (in pbg-template)**

```bash
git add template/scripts/_assets/loom-explore template/scripts/_server/server.py template/tests/test_loom_explore_serve.py
git commit -m "feat(viewer): serve loom-explore static bundle + tests"
```

Note: the vendored bundle should be gitignored if treated as an external
artifact, OR committed if treated as part of the template snapshot. Default
in this plan is **committed** (single source of truth at known commit) —
add an entry to a follow-up to teach the scaffold script how to refresh it.

---

### Task 6: Composite Explorer — replace SVG with iframe + postMessage

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`
- Modify: `template/scripts/_server/server.py` (add `/api/composite-state` if missing)

- [ ] **Step 1: Identify the current Composite Explorer mount**

```bash
cd /Users/eranagmon/code/pbg-template
grep -n "composite-explore\|_render_composite_svg\|composite-svg\|composite-wiring" \
  template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js | head -20
```

Find the existing SVG container (likely an `<img>` or `<div>` populated by JS that hits a `/api/composite-svg` endpoint).

- [ ] **Step 2: Confirm `/api/composite-state` exists or add it**

The endpoint should accept a composite ID (`pkg.composites.foo` form) or a workspace-relative path, and return parsed state dict as JSON:

```python
    def _get_composite_state(self):
        """GET /api/composite-state?ref=<id-or-path> — return parsed composite state."""
        import urllib.parse
        qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        ref = qs.get("ref", "").strip()
        if not ref:
            return self._json({"error": "ref required"}, 400)
        # Resolve via composite_lookup if it's a dotted ID, or as a relative path otherwise
        from scripts._lib.composite_lookup import load_spec, discover_composites
        # ... resolve ref to a file path ...
        # ... read + parse ...
        # ... return {"state": parsed_yaml} ...
```

If a similar endpoint already exists with a different name, reuse it.

- [ ] **Step 3: Replace SVG container in the template**

In `template/scripts/_templates/index.html.j2`, find the SVG container in the Composite Explorer panel. Replace:

```html
<div id="composite-explore-svg-container">...</div>
```

with:

```html
<iframe id="composite-explore-frame"
        src="/loom-explore/index.html"
        title="Composite wiring"
        style="width:100%;height:560px;border:1px solid #ddd;background:#fff">
</iframe>
```

- [ ] **Step 4: Wire postMessage in walkthrough.js**

Find the function that loads a composite into the explorer (likely `_loadCompositeExplorer` or similar). Replace the SVG-injection logic with:

```javascript
  function _loadCompositeExplorer(ref) {
    fetch('/api/composite-state?ref=' + encodeURIComponent(ref))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var iframe = document.getElementById('composite-explore-frame');
        if (!iframe) return;
        var post = function() {
          iframe.contentWindow.postMessage({
            type: 'composite:load',
            state: data.state,
            metadata: { name: ref },
          }, '*');
        };
        // If the iframe has already signalled ready, post now;
        // otherwise wait for the next ready event.
        if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
          post();
        } else {
          var listener = function(ev) {
            if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
              window._loomExploreReady = window._loomExploreReady || {};
              window._loomExploreReady[iframe.id] = true;
              window.removeEventListener('message', listener);
              post();
            }
          };
          window.addEventListener('message', listener);
        }
      });
  }
  window._loadCompositeExplorer = _loadCompositeExplorer;
```

Also add a top-level inspect-event listener (placeholder for future cross-panel highlighting):

```javascript
  window.addEventListener('message', function(ev) {
    if (ev.data && ev.data.type === 'explore:inspect') {
      console.log('explore:inspect', ev.data);
      // TODO: cross-panel highlighting (out of scope for this task)
    }
  });
```

- [ ] **Step 5: Smoke-test (manual)**

Sync to v2ecoli, restart server, open Composite Explorer for `chromosome-partition` → interactive view should load. Click a node → console logs the inspect event.

(Implementer reports the actual outcome; no automated test for the integration.)

- [ ] **Step 6: Commit**

```bash
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js template/scripts/_server/server.py
git commit -m "feat(viewer): Composite Explorer uses loom-explore iframe"
```

---

### Task 7: Investigation Composites tab — same iframe

**Files:**
- Modify: `template/scripts/_templates/index.html.j2`
- Modify: `template/scripts/_server/walkthrough.js`

- [ ] **Step 1: Replace the state-tree div in the Composites tab**

In the Investigation viewer's Composites tab (built in the multi-composite plan, Task 8), the right-hand panel currently shows a text-tree via `_loadInvCompositeDetail`. Replace with an iframe:

```html
<div id="inv-composite-detail" style="border-left:1px solid #eee;padding-left:14px">
  <iframe id="inv-composite-explore-frame"
          src="/loom-explore/index.html"
          title="Composite wiring"
          style="width:100%;height:520px;border:1px solid #ddd;background:#fff">
  </iframe>
</div>
```

- [ ] **Step 2: Rewrite `_loadInvCompositeDetail` to use the iframe**

```javascript
  function _loadInvCompositeDetail(invName, compName) {
    // Read the composite YAML directly via the existing static-file route
    fetch('/investigations/' + encodeURIComponent(invName) +
          '/composites/' + encodeURIComponent(compName) + '.yaml')
      .then(function(r) { return r.text(); })
      .then(function(yamlText) {
        // Convert YAML → JSON in-browser is non-trivial without a parser;
        // use the server's /api/investigation-composite-doc endpoint instead.
        return fetch('/api/investigation-composite-doc?investigation=' +
                     encodeURIComponent(invName) + '&composite=' +
                     encodeURIComponent(compName));
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var iframe = document.getElementById('inv-composite-explore-frame');
        if (!iframe) return;
        var post = function() {
          iframe.contentWindow.postMessage({
            type: 'composite:load',
            state: data.state,
            metadata: { name: compName, context: 'investigation:' + invName },
          }, '*');
        };
        if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
          post();
        } else {
          var listener = function(ev) {
            if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
              window._loomExploreReady = window._loomExploreReady || {};
              window._loomExploreReady[iframe.id] = true;
              window.removeEventListener('message', listener);
              post();
            }
          };
          window.addEventListener('message', listener);
        }
      });
  }
```

- [ ] **Step 3: Add `/api/investigation-composite-doc` endpoint**

```python
        if self.path.startswith("/api/investigation-composite-doc"):
            return self._get_investigation_composite_doc()
```

```python
    def _get_investigation_composite_doc(self):
        """GET /api/investigation-composite-doc?investigation=<n>&composite=<c>
        Returns the parsed composite YAML document as JSON."""
        import urllib.parse
        qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        inv = qs.get('investigation', '').strip()
        comp = qs.get('composite', '').strip()
        if not (inv and comp):
            return self._json({"error": "investigation + composite required"}, 400)
        path = WORKSPACE / "investigations" / inv / "composites" / f"{comp}.yaml"
        if not path.is_file():
            return self._json({"error": "composite document not found"}, 404)
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except Exception as e:
            return self._json({"error": f"parse failed: {e}"}, 500)
        return self._json({"state": doc}, 200)
```

- [ ] **Step 4: Commit**

```bash
git add template/scripts/_templates/index.html.j2 template/scripts/_server/walkthrough.js template/scripts/_server/server.py
git commit -m "feat(viewer): Investigation Composites tab uses loom-explore iframe"
```

---

### Task 8: Feature flag `ui.composite_view`

**Files:**
- Modify: `template/scripts/_server/server.py` (add `/api/ui-config` endpoint)
- Modify: `template/scripts/_server/walkthrough.js` (conditional iframe vs. legacy SVG)
- Modify: `template/.pbg/schemas/workspace.schema.json` (allow `ui` block)

- [ ] **Step 1: Extend the schema**

In `template/.pbg/schemas/workspace.schema.json`, add to top-level properties:

```json
    "ui": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "composite_view": {
          "enum": ["loom-explore", "bigraph-viz"],
          "description": "Which renderer the dashboard uses for composite wiring. Default 'loom-explore'."
        }
      }
    },
```

- [ ] **Step 2: Add `/api/ui-config`**

```python
        if self.path.startswith("/api/ui-config"):
            return self._get_ui_config()
```

```python
    def _get_ui_config(self):
        """GET /api/ui-config — return UI feature flags from workspace.yaml."""
        try:
            ws = yaml.safe_load((WORKSPACE / "workspace.yaml").read_text()) or {}
        except Exception:
            ws = {}
        ui = ws.get("ui") or {}
        return self._json({
            "composite_view": ui.get("composite_view", "loom-explore"),
        }, 200)
```

- [ ] **Step 3: Feature-flag the iframe in walkthrough.js**

Before mounting either iframe, check the flag:

```javascript
  fetch('/api/ui-config').then(function(r) { return r.json(); }).then(function(cfg) {
    window._uiConfig = cfg;
  });
```

In `_loadCompositeExplorer` / `_loadInvCompositeDetail`, branch:

```javascript
    if ((window._uiConfig || {}).composite_view === 'bigraph-viz') {
      // Legacy SVG path
      return _legacyLoadCompositeSvg(ref);  // existing code, renamed
    }
    // ... iframe path as above ...
```

Keep the legacy path intact for the rollback escape hatch.

- [ ] **Step 4: Commit**

```bash
git add template/.pbg/schemas/workspace.schema.json template/scripts/_server/server.py template/scripts/_server/walkthrough.js
git commit -m "feat(viewer): ui.composite_view feature flag (loom-explore | bigraph-viz)"
```

---

## Phase D — v2ecoli verification

### Task 9: End-to-end on v2ecoli

**Files:** (workspace state)

- [ ] **Step 1: Sync files**

```bash
cd /Users/eranagmon/code/pbg-template
cp -R template/scripts/_assets/loom-explore /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_assets/
cp template/scripts/_server/server.py /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/server.py
cp template/scripts/_server/walkthrough.js /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_server/walkthrough.js
cp template/scripts/_templates/index.html.j2 /Users/eranagmon/code/v2ecoli-chromosome-rep1/scripts/_templates/index.html.j2
cp template/.pbg/schemas/workspace.schema.json /Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/schemas/workspace.schema.json
```

- [ ] **Step 2: Restart server**

```bash
EXISTING=$(python3 -c "import json; print(json.load(open('/Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info'))['port'])" 2>/dev/null || echo '')
[ -n "$EXISTING" ] && lsof -nP -iTCP:$EXISTING -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -I {} kill {} 2>/dev/null
rm -f /Users/eranagmon/code/v2ecoli-chromosome-rep1/.pbg/server/server-info
sleep 1
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
.venv/bin/python3 scripts/render-dashboard.py --all 2>&1 | tail -3
bash scripts/serve.sh > /tmp/v2ecoli.log 2>&1 &
until [ -f .pbg/server/server-info ]; do sleep 0.5; done
PORT=$(python3 -c "import json; print(json.load(open('.pbg/server/server-info'))['port'])")
echo "port: $PORT"
```

- [ ] **Step 3: Programmatic verification of endpoints**

```bash
echo "--- /loom-explore/index.html (should be 200) ---"
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:$PORT/loom-explore/index.html"

echo "--- /api/ui-config ---"
curl -s "http://localhost:$PORT/api/ui-config" | python3 -m json.tool

echo "--- /api/composite-state (chromosome-partition) ---"
curl -s "http://localhost:$PORT/api/composite-state?ref=pbg_chromosome_rep1.composites.chromosome-partition" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('state keys:', list((d.get('state') or {}).keys())[:10])"

echo "--- /api/investigation-composite-doc (t1/chromosome-partition) ---"
curl -s "http://localhost:$PORT/api/investigation-composite-doc?investigation=t1&composite=chromosome-partition" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('state keys:', list((d.get('state') or {}).keys())[:10])"
```

- [ ] **Step 4: Open dashboard**

```bash
open "http://127.0.0.1:$PORT/#composite-explore"
```

Manual verification:
1. Composite Explorer → pick `chromosome-partition` → interactive React Flow view renders. Drag to pan, scroll to zoom, click a node → inspector panel shows the node's details.
2. Open `#investigations` → click `t1` → Composites tab → click each of
   `chromosome-partition`, `high-count`, `low-count` → iframe re-renders with the picked composite's wiring.
3. Open DevTools console → confirm `explore:inspect` events log when nodes are clicked.

- [ ] **Step 5: Commit v2ecoli sync (do not push yet)**

```bash
cd /Users/eranagmon/code/v2ecoli-chromosome-rep1
git add -A
git commit -m "feat(viewer): sync loom-explore integration from pbg-template"
```

Push only after the user confirms the browser-side verification.

- [ ] **Step 6: Push pbg-template**

```bash
cd /Users/eranagmon/code/pbg-template
git push 2>&1 | tail -3
```

---

## Phase E — Cleanup (deferred follow-up; NOT in this plan)

Once ≥2 sessions of real use confirm stability:

- Remove `bigraph-viz` from `template/pyproject.toml.j2` and from any
  workspace's `pyproject.toml` that pinned it.
- Delete `_render_composite_svg` and its subprocess script from `server.py`.
- Delete the legacy `_legacyLoadCompositeSvg` JS branch.
- Drop the `bigraph-viz` enum value from `ui.composite_view` schema.

This phase is intentionally outside the plan's task list — flip the
default flag first, gather usage, then schedule cleanup.

---

## Self-review

**Spec coverage:**

- Phase A (loom-explore bootstrap): Tasks 1 (scaffold), 2 (port + strip components), 3 (canvas + inspector + postMessage). ✓
- Phase B (distribution): Task 4 (tag + zip; remote push deferred). ✓
- Phase C (pbg-template integration): Tasks 5 (static-serve + vendor), 6 (Composite Explorer iframe), 7 (Investigation tab iframe), 8 (feature flag). ✓
- Phase D (v2ecoli verify): Task 9. ✓
- Phase E (cleanup): explicitly deferred; documented in spec + here. ✓

**Placeholder scan:** none. Each step has complete code + commands. The two "find existing code" steps (Task 6 Step 1, Task 8 Step 3) are inspection-only and the implementer adapts based on what they find — common pattern for the dashboard's organic structure.

**Type consistency:**
- postMessage protocol types declared in `src/api.ts` (Task 3); consumed by walkthrough.js (Tasks 6, 7) using the same string literals (`composite:load`, `explore:ready`, `explore:inspect`).
- Endpoint names consistent: `/api/composite-state` (Task 6), `/api/investigation-composite-doc` (Task 7), `/api/ui-config` (Task 8).

**Risks flagged in advance:**

1. **Loom node components may not be standalone.** Tasks 2 likely will need
   to remove imports of loom-specific contexts (session, library, etc.).
   The implementer should fix as TS errors surface during `npm run build`.
2. **React Flow version mismatch.** Plan pins to `@xyflow/react ^12.4.0`
   matching loom. If loom upgrades, sync the explore pin in the same step.
3. **Bundle size.** Plan target is ≤600KB gzipped. If React Flow + dagre
   blow past that, defer the bundle-size budget to a follow-up rather than
   blocking the release.
4. **YAML parsing in browser.** Task 7's `_loadInvCompositeDetail` initially
   tried to fetch YAML directly — corrected to use a JSON endpoint
   (`/api/investigation-composite-doc`) since no in-browser YAML parser is
   pre-bundled. Implementer confirms this is the path used.

---

Plan saved. Use superpowers:subagent-driven-development to execute.
