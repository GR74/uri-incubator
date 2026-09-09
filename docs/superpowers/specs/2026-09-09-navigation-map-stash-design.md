# Unified navigation, research map, and project stashing

Date: 2026-09-09

## Goal

Make the URI research workspace easier to navigate, expose how recorded lab knowledge connects, and let researchers pause work without losing or obscuring its history.

The change has three coordinated outcomes:

1. Workspace and project navigation use the same horizontal-tab language.
2. A two-dimensional map shows recorded relationships among projects and their data sources.
3. A reversible stash lifecycle preserves paused projects and supports export, sharing, and continuation.

The prototype remains static, offline-capable, and browser-local. It does not claim to provide real multi-user authorization, server persistence, document extraction, or GraphRAG retrieval.

## Navigation model

### Workspace frame

Replace the desktop sidebar with a compact application header and a persistent horizontal workspace tab rail. The header contains the URI identity, a project selector when projects are available, and the existing demo-identity control.

The workspace rail contains:

- Home
- Projects
- Evidence
- Reviews
- Handoffs
- Map
- Discover

All tabs use the existing project-tab visual language: sentence-case labels, a quiet neutral resting state, and a scarlet underline for the selected tab. Workspace navigation stays visible while a project is open so users never lose the route back to workspace-level tools.

### Project context

Opening a project adds a contextual row below the workspace rail:

`Projects / [project name]`

The project tabs follow immediately below it:

- Overview
- Research
- Record
- Evidence
- People
- Settings

The project selector changes the current project without leaving the current project tab when that tab is valid. It groups active projects first and stashed projects second so a directly opened stashed project always has a visible selector value. Workspace-level Evidence, Reviews, Handoffs, and Map retain the current project as their initial scope rather than making the user choose again.

The browser-local workspace state continues to remember the current workspace section, project, and project tab for each demo identity. Navigation changes scroll immediately to the beginning of the new content; the current smooth page motion is removed because it makes state changes feel delayed and choppy.

### Responsive and keyboard behavior

On narrow screens, the header wraps and both tab rails become independently horizontally scrollable. A visible fade or edge cue indicates additional tabs. Tabs use native buttons with `aria-current` or tab semantics as appropriate, preserve visible focus, and keep a minimum touch target of 44 pixels.

## Research source map

### Scope and purpose

Map is a workspace-level destination. It opens in All lab scope and offers a scope control for each accessible project. A project can also deep-link to Map with that project preselected.

The map answers three questions:

1. What recorded sources support this lab or project?
2. How are sources connected to evidence, research work, decisions, and projects?
3. Which source or project should the researcher open next?

It is not a claim that semantic similarity or causal relationships have been inferred. Every displayed edge must be explainable from explicit prototype data.

### Normalized graph model

The interface consumes a normalized model so the browser-local implementation can later be replaced by a GraphRAG endpoint:

```js
{
  nodes: [{ id, label, type, projectId, status, detail, target }],
  edges: [{ id, source, target, type, label }],
  counts: { nodes, edges, projects, sources }
}
```

Initial node types are:

- project
- approved evidence or record entry
- research item or measurement
- artifact, protocol, dataset, file, citation, or other named source
- decision

Initial edge types are:

- belongs to project
- cites or uses source
- measurement supported by evidence
- research item linked to experiment
- decision supported by record
- continued from stashed project

The browser adapter derives only relationships supported by existing IDs or explicit source references. It does not infer a connection from matching words alone. Unapproved evidence is excluded from the all-lab map; a reviewer who can access a project may reveal pending material through an explicit filter, clearly labeled as pending.

### Layout and interaction

The first implementation uses deterministic SVG coordinates and a lightweight relaxation pass based on the existing legacy map. It does not introduce a runtime dependency or copy Exo's three-dimensional renderer. The normalized node-and-edge boundary is inspired by Exo's graph data contract and preserves a clean migration path to a real API.

Projects act as stable hubs. Their connected records and sources form nearby clusters. Shared source identifiers can connect more than one project in All lab scope. Stashed projects use a muted outline but remain searchable and connected.

The map includes:

- a scope selector;
- text search;
- type filters;
- a compact legend;
- counts for visible nodes, connections, projects, and sources;
- hover or keyboard focus to isolate immediate neighbors;
- selection to open a detail panel;
- an Open record or Open project action when the node has a valid target;
- a list-based alternative containing the same visible nodes and relationships.

The detail panel states why each edge exists. Empty scopes explain which approved record or source action will populate the map. Dense scopes may limit labels until focus or selection, but must not silently omit nodes from the accessible list.

## Project stash lifecycle

### Stashing

Project Settings contains a Stash project action for users who can manage the project in the demo permission model. Stashing requires:

- a reason the work stopped;
- a recommended next step.

Confirmation explains that the project becomes read-only and leaves active project lists, while its content remains available. On confirmation, the project records:

```js
{
  status: 'stashed',
  stashedOn,
  stashedBy,
  stashReason,
  stashNextStep,
  stashVisibility: 'private' | 'lab'
}
```

Existing archived seed data is treated as stashed for navigation and display, while retaining its original status fields for backward compatibility.

Every transition appends a small immutable item to `lifecycle`, containing the action, actor, timestamp, and source or continuation project ID when applicable. Tests inject timestamps and new-project IDs so transition results are deterministic.

Stashing does not delete, rewrite, or copy project history. Project logs, evidence records, research revisions, people, artifacts, and existing handoff material keep their IDs and storage locations.

### Finding and reading stashed work

The Projects page has Active and Stashed filters. Home and the project selector show active work by default. Stashed projects remain readable from Projects, Map, direct links, and permitted search results. They display a clear read-only banner with the stash reason and next step.

The existing handoff Markdown export remains available for a stashed project and is reframed as an archive or revival brief when opened from the stashed state. Research CSV and JSON exports remain project-scoped and include their existing provenance and revision history. Evidence publication, research editing, and other write controls are disabled while the project is stashed.

### Resuming and sharing

The original owner or authorized project manager can Resume the project. Resume changes the lifecycle status to active and records a lifecycle event; it does not remove the earlier stash metadata.

The owner can make a stashed project discoverable to the lab. In this browser prototype, the control changes only local demo visibility and is labeled accordingly. A discoverable project appears in Discover with its reason, established findings, next step, and available archive material.

Another researcher can choose Continue project. This creates a new active project whose `continuedFrom` field points to the stashed project. The stashed project stays immutable. The continuation begins with a provenance entry explaining where it came from and links back to the original in the map.

## State and component boundaries

### Pure domain helpers

Add a focused browser-loadable domain file for navigation-safe lifecycle and graph operations. It owns:

- filtering active and stashed projects;
- validating stash input;
- applying stash, resume, and continuation transitions without mutating the input project;
- building the normalized graph from projects, evidence, and research state;
- deterministic graph layout inputs and visible-scope filtering.

Pure helpers make lifecycle and graph behavior testable without rendering React.

### UI components

The workspace shell owns navigation state and delegates content to existing Evidence and Research components. New or revised components are:

- `WsHeader` for brand, identity, and project selection;
- `WsWorkspaceTabs` for persistent workspace navigation;
- `WsProjectContext` for breadcrumb and project tabs;
- `WsResearchMap` for filters, SVG, detail panel, and list alternative;
- `WsStashProject` for validated confirmation;
- `WsStashedBanner` for read-only state and lifecycle actions;
- revised `WsProjects`, `WsDiscover`, and `WsProjectSettings` views.

The top-level application remains the owner of project state because it already persists projects through the prototype's existing store. It passes explicit `onStash`, `onResume`, and `onContinue` callbacks into the workspace. Each callback computes the next full prototype state, attempts the browser-storage write, and updates React state only after that write succeeds. Research revisions remain in their current separate browser-local store and are passed to the graph builder as an explicit input rather than read by the domain helper.

## Failure behavior

- Malformed remembered navigation state falls back to Home and the first accessible active project.
- A missing or inaccessible selected project returns to Projects without revealing its data.
- Blank stash reasons or next steps block confirmation and focus the relevant field.
- A failed browser-storage write keeps the form open and does not claim that the project was stashed, resumed, or continued.
- Corrupt research storage does not prevent the map from showing valid project records; the map reports that research nodes are unavailable.
- Invalid graph edges are discarded and reported in a non-blocking map notice rather than crashing the page.
- A stashed direct link remains readable for authorized identities but cannot open editing controls.
- Continuing a project never mutates or claims the stashed source project.

## Visual direction

Retain the existing URI scarlet, charcoal, gray, and white palette and the current expressive project hero. Navigation becomes quieter so the research content and map remain the visual focus. The map is the single new high-attention element: white or pale-gray plotting field, charcoal source nodes, scarlet selected paths, and restrained node-type accents. Connections encode recorded provenance rather than decoration.

The implementation must avoid generic identical cards, gratuitous gradients, continuous motion, and graph animation that makes node positions unstable. Reduced-motion preferences disable nonessential transition effects.

## Verification criteria

### Automated tests

- Workspace state accepts Map and rejects invalid sections or project tabs.
- Active lists omit stashed projects by default; Stashed lists include both new stashed and legacy archived records.
- Stash rejects missing reason or next step and never mutates its input.
- Resume preserves stash metadata and records the new lifecycle state.
- Continue creates a distinct active project linked to the source without modifying it.
- The graph contains only accessible projects and approved evidence by default.
- Explicit evidence and research source IDs create the expected labeled edges.
- Unresolved source IDs and corrupt research state do not crash graph construction.
- All-lab and project scopes return the expected node and edge subsets.
- Generated markup exposes both the map and its list alternative.
- Existing evidence, review, research, export, legacy-access, and malformed-storage tests continue to pass.

Each behavior-changing test is written and observed failing before its production implementation.

### Build and manual checks

- `node --test tests/*.test.cjs`
- `node build/build.js`
- Serve the rebuilt artifact with `node build/serve.js`.
- Verify desktop and 390-pixel layouts for workspace tabs, project tabs, Map, stash confirmation, stashed read-only state, and Discover continuation.
- Verify keyboard navigation, visible focus, map list alternative, and reduced motion.
- Verify refresh persistence for selected navigation, stash, resume, and continuation.
- Verify that a stashed project cannot be edited but can be exported.
- Verify offline loading with no external requests or page errors.
- Capture before-and-after screenshots for the navigation, map, and stash lifecycle.

## Out of scope

- A deployed GraphRAG backend or live Exo integration
- Semantic edge inference, embeddings, or retrieval ranking
- Real authentication or cross-user authorization
- Real-time collaboration or server-enforced read-only state
- Upload parsing, OCR, or automatic metadata extraction
- Public share links or external notifications
- Migration of existing browser data beyond backward-compatible lifecycle interpretation
