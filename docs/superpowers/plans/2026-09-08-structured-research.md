# Structured Research Tracking Implementation Plan

> **For agentic workers:** Use subagent-driven development with GPT-5.6 Sol implementation and independent review. Do not commit, push, deploy, install packages, or discard existing workspace changes.

**Goal:** Make project work, responsibility, and measurements inspectable and exportable without confusing documentation volume with research progress.

**Architecture:** Add a local operational tracking store alongside the existing reviewed evidence store. Tasks, experiments, milestones, and measurements are explicitly team-entered tracking, not approved scientific findings. The existing evidence approval path is unchanged. One project-scoped Research view edits and visualizes tracking; Project Overview exposes a compact summary and expandable narrative.

**Tech Stack:** Existing browser-global React JSX, plain CSS, built-in Node tests, offline build. No new dependencies or cloud services.

**Spec:** Approved conversation direction: project progress, team activity, measurement values with units/conditions/dates/source links, portable tabular exports, and handoff continuity. This document defines the bounded first implementation of that direction.

## Global constraints

- Preserve scarlet/gray styling and existing navigation/evidence/review behavior.
- Use `apply_patch` for source edits. No generated `index.html` edits; root runs build.
- Browser-local data is a prototype, never real authorization or multiuser synchronization.
- No invented seed measurements, task completion, readiness scores, or inferred ownership.
- Keep tracking separate from approved findings. The UI and every export identify team-entered status.
- Never infer quantitative values from prose. Users enter values explicitly and select source evidence.
- Retain earlier snapshots when a tracking item changes. No delete operation in this increment.
- New localStorage key `uri.research.v1`; malformed state must show an error and remain untouched. Failed writes cannot report success or silently keep unsaved changes.
- Project access is `me.scope === 'all' || me.projects.includes(project.id)`, excluding partners. Authors edit their own items; assigned owners can also edit tasks/experiments/milestones, not others' measurements. PI/PhD identities can edit in accessible projects as a labeled demo policy. All accessible members can read project tracking.
- Exports contain only the selected accessible project. CSV quotes cells, uses CRLF and UTF-8 BOM, and neutralizes spreadsheet formula injection for user strings; real numeric negatives stay numeric. JSON preserves revision history.

## Task 1: Tracking domain and tabular exports

**Files:** Create `src/workspace-research-domain.jsx`, `tests/research-domain.test.cjs`.

**Data contract:** `{version:1, revisions:[]}`. Every immutable revision has `id` (stable item ID), `revision` (positive integer), `projectId`, `kind` (`task|experiment|milestone|measurement`), `title`, `ownerKey` (empty means unassigned), `status` (`planned|in_progress|blocked|completed`), `date` (YYYY-MM-DD, required; work date / observation date), `dueDate` (optional), `notes`, `sourceEntryId` (optional except measurement), `experimentId` (optional), `metric`, `value` (number for measurement, otherwise null), `unit`, `condition`, `authorKey` (original author), `updatedBy`, `updatedAt` (ISO timestamp). Nonmeasurement metric/unit/condition can be empty strings. Measurement status is recorded operationally, not approval.

**Interfaces:** Browser-global functions, no imports or top-level dependencies on later scripts:

```js
wsResearchEmpty() // {version:1,revisions:[]}
wsResearchValidate(state) // {ok,error?}; structural and revision-chain validation
wsResearchRead(storage) // {state,error}; malformed storage preserved
wsResearchCurrent(state, projectId) // latest revision per id, scoped
wsResearchCanEdit(item, me, project) // boolean, access + author/reviewer policy
wsResearchSave(state, input, me, project, people, now) // {ok,state?,item?,error?}; append, never mutate
wsResearchSummary(items) // {workTotal,completed,inProgress,blocked,planned,measurementTotal,byOwner:[{ownerKey,total,completed,blocked}]}
wsResearchCsv(items, people) // string, BOM + escaped CRLF rows, no cross-project selection inside helper
wsResearchJson(state, projectId) // JSON string; project-only revisions + tracking disclaimer
```

`input` supplies the editable fields above and optional `id` plus `revision` for optimistic revision check. Domain fills author/audit/revision identifiers (use crypto.randomUUID where available, fallback if needed). Reject stale updates, inaccessible projects, invalid enums/dates/nonfinite values, invalid owner assignment (must be an internal project member), missing measurement metric/unit/condition/source, references to unapproved or missing source entries, and cross-project/nonexperiment experiment references. Existing approved entry IDs live at `project.log[].id` with `ack !== false`. Source links are identifiers, not executable URLs. Blank unit is not allowed; dimensionless is acceptable explicitly.

- [ ] Write red tests before implementing: revision retention, stale version rejection, access/edit policy, date validation, blank/NaN values rejected and zero/negative allowed, owner membership, measurement provenance, same-project experiment refs, corrupt storage, summary counts, CSV punctuation/newlines/formula escaping, JSON scoping.
- [ ] Implement pure helpers and validation. Test example: saving value `0` with valid metric/unit/condition/date/source succeeds; blank value must not be coerced to zero.
- [ ] Run `node --test tests/research-domain.test.cjs`; report exact results and files. Do not wire UI yet.

## Task 2: Research view, overview, and integration

**Files:** Create `src/workspace-research.jsx`; modify `src/workspace.jsx`, `src/workspace.css`, `src/uri.html`, `build/serve.js`, and scoped tests/docs.

**Consumes:** Task 1 interfaces. Component `ResearchProjectWorkspace({project,me,people})`; component `ResearchProjectSummary({project,me,onOpen})`. Load domain and research scripts before workspace.jsx. Components use React hooks through React itself. Scope instance keys by identity/project.

- [ ] Add a Research project tab, preserving existing tabs. Add a compact operational summary before narrative panels in Project Overview, linking to Research. Show completed/total tracked work, in progress, blocked, measurements. Do not call this percent research complete. Empty state invites the first record.
- [ ] Research view: work status distribution with counts and list, team responsibility rows with explicit unassigned state, measurement table, and a simple selected-series plot only when numeric records match metric/unit/condition (never aggregate incompatible units or unrelated experiments). Visible table remains the accessible equivalent. Missing measurements show an honest empty state.
- [ ] Add accessible create/edit forms for four record kinds. Fields: title, owner, status, work/observation date, due date, notes, approved source picker, related experiment picker; measurement metric/value/unit/condition required. Source picker previews referenced evidence text. Use inline error feedback and focus. Preserve entered fields after validation/storage errors. Editing creates a new revision; show history using details disclosure, author/date.
- [ ] Keep measurement labels explicit: team-entered, not reviewed findings. No automatic data extraction and no review bypass. Existing Add evidence CTA stays available for publishing actual research knowledge.
- [ ] Export buttons: `Export CSV` for current selected-project records; `Export history JSON` for project-only full revisions. Use Blob, createObjectURL and cleanup as existing download does. Prevent unauthorized export and clearly identify browser-local tracking in the file.
- [ ] Reduce Overview text density using short existing titles and `<details><summary>` for full current-state/next-action explanations; do not truncate away provenance or change scientific wording.
- [ ] Preserve existing serif/sans type and palette; use `ws-research-*` CSS for new styles, mobile stacking, visible focus, readable tables without document overflow, and text labels accompanying visuals.
- [ ] Run build/full tests and browser walkthrough: create task, assign owner, update status, create experiment, enter zero-valued measurement with source, refresh persistence, stale revision guard, CSV download, history export, identity access, 390px layout. Root independently verifies.

## Review and delivery

- [ ] Independent review checks spec compliance, permission/scoping, formula injection, immutable revisions, source integrity, no invented metrics, storage recovery, and responsive UI.
- [ ] Correct important findings and re-run targeted tests.
- [ ] Update implementation status and contributor structure notes, retain before/after screenshots.
- [ ] No Git commit/push or deployment in this increment.

## Execution ledger

Existing changes are the user's active prototype on a feature branch. Work in place to retain the live preview and uncommitted implementation; no new worktree or Git mutation is needed.

| Interface / task | Check |
| --- | --- |
| Domain to UI | Exact helpers and record schema above; domain has no React dependency |
| UI to shell | Research tab and source scripts integrate without replacing evidence store |
| Task 1 internal | Numeric zero supported; blank rejected; source/owner validation enforced |
| Task 2 internal | Team-entered metrics distinguished from reviewed official knowledge |

Status: Task 1 implemented; root independently verified 17/17 initial domain tests, implementer subsequently added a passing formula-prefix test (18 total). Independent domain review passed with no blocking findings. Report is present at `docs/research-domain-report.md` (created after reviewer inspection). Task 2 implementation delegated to `research_ui` (Sol). Baseline 17 tests also pass. Read-only UX review completed: preserve identity/project component keys, keep operational counts separate, retain numeric form values as strings until validation, group series by metric/unit/condition/experiment, and scope exports at click time.

Domain review notes: UI must block writes while storage has a corruption error; domain validation intentionally accepts extra persisted fields but domain-created records have the specified fields only. Ancient calendar years below 0100 are not supported. Neither minor affects current fictional project dates; no migration or destructive recovery action is added.

Integration refinement: allow assigned owners to update operational work created by a mentor, while retaining author/reviewer-only edits for measurements. This avoids tasks that assignees cannot update; assignment acts as a demo edit capability for that work item. Task 2 implementer owns the small domain/test adjustment and must test both allowed work editing and denied nonauthor measurement editing.

### Root browser verification in progress

Initial integrated production build passes; source preview and both new asset routes load without page errors. Six UI helper tests pass. An isolated browser context (not the user's preview storage) verified task/experiment creation, blank measurement rejection, numeric zero retained after refresh and in edit forms, negative measurement revision retaining old zero, CSV and history JSON downloads, stale-edit rejection without overwriting latest data, and switching to another project's identity without leaking tracking records. Corrupt storage remained byte-for-byte unchanged and disabled creation; simulated quota failure retained form text and did not append a revision. A second compatible observation produces a second plot point. Mobile 390px has no document overflow. Final screenshot/verification pass follows pending polish.

UI polish completed: detailed historical measurement/owner/source snapshots, read-only source inspection, accessible error association/focus and table scrolling, nonduplicated constant-series axes, compact mobile add buttons, date nowrap, and assigned-owner work editing. Independent UI review passed without important findings.

### Final verification

Both implementation tasks and independent reviews are complete. The final production build passes; the full suite passes 45/45 tests (19 research domain, 9 research UI, and 17 existing regressions). Root verified assigned-owner editing, read-only source inspection, historical values, project scoping, actual CSV/JSON downloads, refresh persistence, stale-edit rejection, corrupt-storage preservation, and failed-write form retention. Desktop and 390px mobile screenshots are retained under `docs/screenshots/research-*.png`. The generated `index.html` loads its Research tab from disk with HTTP(S) blocked, zero external requests, and zero page errors. Isolated synthetic test contexts were closed; the user's stored data was not changed. Contributor structure and implementation status are updated. No commit, push, or deployment was performed.
