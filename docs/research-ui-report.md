# Research UI implementation report

## Delivered

- Added a project Research tab and an operational summary below the Project Overview hero.
- Added accessible create/edit forms for tasks, experiments, milestones, and measurements.
- Kept measurement input as text until blank validation, then passed a finite number to the domain.
- Added current work status, explicit owner/unassigned rows, a measurement table, exact-group raw scatter plots, and full revision details.
- Added exact approved-source previews in the form and inspectable source details in the read-only measurement table.
- Added project-scoped current-record CSV and full-history JSON downloads labeled as browser-local team tracking.
- Added fresh-read optimistic saves and exports. A stale edit, corrupt store, unavailable store, or failed write never overwrites saved data or reports success.
- Added assigned-owner editing for tasks, experiments, and milestones. Another author's measurement remains restricted to its author or a PI/PhD reviewer.
- Added source-preview routes and source-order integration for the domain, research UI, evidence UI, and workspace shell.

## Automated checks

- `node tests/research-ui.test.cjs`: 9 tests passed.
- `node tests/research-domain.test.cjs`: 19 tests passed.
- An in-memory Babel compilation of `workspace-research-domain.jsx`, `workspace-research.jsx`, `workspace-evidence.jsx`, and `workspace.jsx` passed in source order.

The primary integration pass also built the production page and exercised creating a
task and experiment, entering a zero-valued sourced measurement, blank-value feedback,
refresh persistence, stale edit rejection, project isolation, corrupt-state blocking,
failed-write form retention, downloads, and the 390px layout. The measurement table is
a keyboard-focusable named region, field errors reference the inline alert, and storage
alerts receive focus after rendering.

## Prototype limits

- Storage and permissions are browser-local demonstrations, not authentication or multiuser synchronization.
- No task, experiment, milestone, measurement, completion, or ownership is seeded or inferred.
- Measurements are entered explicitly and do not bypass the existing evidence review workflow.
- Plot points are raw values. The UI does not average records or combine different units, conditions, or experiments.
- After a stale edit fails, the retained form must be canceled and reopened from the newest revision before saving again.
