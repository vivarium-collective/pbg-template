# Vivarium chrome — left rail + topbar redesign

**Date:** 2026-05-13
**Status:** Approved for implementation
**Owner:** Eran (process-bigraph workspaces)
**Builds on:** [`2026-05-12-study-model-design.md`](./2026-05-12-study-model-design.md) — the Study model + 8-tab workbench stay as-is.

## Goals

Reshape the dashboard's primary navigation to match the Vivarium mockup:

- Left rail with primary nav (collapsible), workspace identity at top, user avatar at bottom.
- Slim top bar showing breadcrumbs + branch chip + GitHub icon + workspace controls (Up-to-date / Share / kebab menu).
- INVESTIGATIONS section in the rail listing studies, grouped by `topic`.
- One label rename on the workbench tab strip: "Composites" → **"Baseline Composite"**.
- One label rename on the primary nav: "Branches" → **"GitHub Branches"**.

The Study model, endpoints, and tab functionality from the previous spec are unchanged. This is a chrome-only restructure plus a single new spec field (`topic`).

## Non-goals

- **Multi-workspace switching.** The workspace dropdown is decoration. The string it shows comes from `workspace.yaml.name` (read-only). The dropdown has one entry plus a hint row ("Other workspaces — coming soon"). API stays single-workspace per server.
- **Real avatar identity.** Bottom-of-rail avatar shows `workspace.yaml.owner.email` (or "—" if absent) + initials. No auth, no per-user identity.
- **Topic management UI.** Topics are a free-text string on each study (`spec.yaml.topic`). Users set it by editing the study (the Overview tab gains a Topic field) — no separate Topics CRUD page.
- **Reskinning the workbench tab content.** Inside each Study tab, the existing content stays. Mockup's 3-column Overview dashboard is a follow-up.
- **Replacing the dirty-files pill landing in parallel.** The pill (in-flight from the prior session) moves from the old workstream-strip into the new topbar's branch chip area unchanged.

## Architecture

### Chrome layout (replaces current top-banner nav)

```
┌────────────────────────────────────────────────────────────────┐
│  LEFT RAIL              │   TOP BAR (slim)                       │
│  ┌─────────────────┐    │   Breadcrumbs · [branch ▼] [↗GH] [Up-to-date] [Share] [⋯] [avatar] │
│  │ Vivarium        │    ├────────────────────────────────────────│
│  │ Workspace       │    │                                         │
│  │                 │    │   PAGE CONTENT                          │
│  │ Workspace ▼     │    │                                         │
│  │ v2ecoli         │    │                                         │
│  │                 │    │                                         │
│  │ ─ Primary ──    │    │                                         │
│  │ • Dashboard     │    │                                         │
│  │ • Registry      │    │                                         │
│  │ • Sim Setup     │    │                                         │
│  │ • Investigations│    │                                         │
│  │ • Visualizations│    │                                         │
│  │ • GitHub Branches│   │                                         │
│  │                 │    │                                         │
│  │ ─ Investigations│    │                                         │
│  │ ▸ Antibiotic    │    │                                         │
│  │   response  3   │    │                                         │
│  │ ▸ Nutrient      │    │                                         │
│  │   limitation 2  │    │                                         │
│  │ ▸ Ungrouped 4   │    │                                         │
│  │                 │    │                                         │
│  │ ─────────       │    │                                         │
│  │ AK Alex Kim     │    │                                         │
│  │ alex@example.org│    │                                         │
│  └─────────────────┘    │                                         │
│  [«]                    │                                         │
└────────────────────────────────────────────────────────────────┘
```

**Collapsed state**: rail narrows to a 56px strip showing icon-only nav items + workspace logo + collapse-toggle. Clicking any item still routes; investigations sublist collapses too.

**Toggle**: a `«` / `»` button at the bottom-left of the rail. State persists in `localStorage` (`vivarium.rail-collapsed`).

### Top bar contents

| Element | Source / behavior |
|---|---|
| Breadcrumbs | `Investigations › <topic> › <study name>` when on a Study; falls back to `<page-title>` for other pages. |
| Branch chip | `git rev-parse --abbrev-ref HEAD` via existing `/api/work-status`. Includes the dirty-pill (when count > 0). Click → dropdown with Push / Create PR / End workstream actions (carry over from existing workstream-strip buttons). |
| GitHub icon | If `workspace.yaml.github.repo` set, links to the repo. Else hidden. |
| Up-to-date / Push (N) | Existing button from work-status payload — reuse current logic. |
| Share | Decoration only. Tooltip: "Coming soon — share a workspace link." |
| ⋯ kebab | Decoration: tooltip "Workspace settings — coming soon." |
| Avatar circle (top-right) | `workspace.yaml.owner.email` → initials (e.g., "alex@example.org" → "AK"). Decoration; click does nothing or shows a tiny popover with email. |

### Data model changes

**One new field** on study spec:

```yaml
# investigations/<study>/spec.yaml
topic: "Antibiotic response"     # NEW (optional). Free-text grouping label.
```

Migration: `migrate_study_to_v2_vocabulary` initializes `topic: ""` on legacy migrations (mirroring `question`/`hypothesis`/`status`).

The Overview tab gains a 4th editable field above the existing question/hypothesis/status row:

```
┌──────────────────────────────────────────────┐
│ Topic (optional)                              │
│ [ Antibiotic response                       ] │
│                                                │
│ Question                                       │
│ [ ... existing ... ]                           │
└──────────────────────────────────────────────┘
```

Backed by extending the existing `POST /api/investigation-set-overview` to also accept `topic` in `fields_to_update` (A3.5 endpoint; one-line schema addition).

### Sidebar Investigations grouping

`GET /api/investigations` already returns each study's `description`/`tags`/etc. Extend to include `topic` (post-A2 the field exists; just surface it).

In the frontend, group the studies by `topic`:

- Strip-only collapse arrow per topic header
- Per-topic count
- Ungrouped studies (topic empty/missing) land in a "Ungrouped" section at the bottom
- Clicking a study navigates to that study's workbench (existing `_openInvestigation(name)`)
- Current investigation highlighted

Each section item:
```
[icon] <study name>
       <baseline name>  <run count>
```

### Tab strip renames

- Workbench: `data-tab="composites"` button text changes from "Composites" to "Baseline Composite". Other tab names stay. The `data-tab` attribute stays `composites` so JS handlers don't churn.
- Primary nav: "Branches" → "GitHub Branches" (HTML text only; `data-page` stays `branches`).

### Chrome wiring map

| Existing element | Disposition |
|---|---|
| `#side-menu` (left vertical nav, already exists) | KEEP — but heavily restyle as the rail. Add workspace-header at top, INVESTIGATIONS section at bottom, collapse-toggle. |
| `#workstream-strip` (top horizontal strip) | RELOCATE — the branch + push + PR controls move into the new top bar. The dirty-files pill (in-flight) keeps its hook into the strip API but lands in the topbar's branch chip. |
| Old top banner (logo + page-title bar) | REMOVE — Vivarium logo moves to the rail header; page title goes into the topbar breadcrumb path. |
| Pages container | Unchanged — same routing via `_switchPage`. |

## Endpoints

**New / extended:**

- `POST /api/investigation-set-overview` — extend `_VALID_OVERVIEW_STATUSES` block to also accept a `topic` string field in `fields_to_update`. (Trivial; one line in the handler's field loop.)
- `GET /api/investigations` — already returns per-study metadata; add `topic` to the projection. (One line.)

**No new endpoints** for chrome behavior — collapse state is browser-local, workspace identity comes from existing `/api/work-status` + `workspace.yaml` (read at boot).

## Testing

- `test_migrate_initializes_topic_blank` — new top-level field initialized to `""`.
- `test_post_set_overview_accepts_topic` — endpoint extension.
- `test_get_investigations_includes_topic` — projection.
- Frontend: manual verify in v2ecoli (left rail collapses, study links route correctly, topic edits persist).

## Rollout

**Phase V (chrome only — no Study-model touches):**

1. Backend: add `topic` to migration + `set-overview` + `/api/investigations` projection (1 commit, 3 tests).
2. CSS: rail + top-bar styles (1 commit, no JS).
3. Template (`index.html.j2`): restructure `<body>` to rail + topbar + content (1 commit; no JS contracts change).
4. JS: collapse toggle + workspace-name header + Investigations grouping renderer + topic field on Overview tab + workbench tab rename ("Composites" → "Baseline Composite") + primary nav rename ("Branches" → "GitHub Branches"). (1 commit.)
5. Sync to v2ecoli; manual verify in browser; commit synced scripts in v2ecoli.

Each step is independently revertable. The Study-model code paths (`spec.yaml.variants/groups/comparisons/etc.`) stay completely unchanged.

## Out of scope (follow-ups)

- Real multi-workspace switching (cross-workspace dashboard, workspace-discovery API).
- Auth + per-user avatars.
- Mockup's 3-column Overview tab layout (research-question card / design-diagram card / key-results card with charts).
- Status column on Groups + Interventions tables.
- "Up-to-date" button as a rebase / pull control (currently passthrough to existing work-status state).
- Share menu functionality.
- Per-study breadcrumb auto-population from URL (the topbar gets it from in-memory state).
- Auto-creation of a default "control" group on `investigation-create-from-composite`.
