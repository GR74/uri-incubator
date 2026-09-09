# Research domain implementation report

## Scope completed

- Added the dependency-free browser-global research tracking domain in `src/workspace-research-domain.jsx`.
- Added behavioral coverage in `tests/research-domain.test.cjs` for the nine required public functions.
- Kept this task isolated from UI integration, generated `index.html`, Git history, and remote state.

## Public API

- `wsResearchEmpty()` returns the version 1 empty state.
- `wsResearchValidate(state)` validates the full record schema and contiguous immutable revision chains.
- `wsResearchRead(storage)` reads `uri.research.v1`; malformed data returns an error without changing storage.
- `wsResearchCurrent(state, projectId)` selects the latest revision of each item in one project.
- `wsResearchCanEdit(item, me, project)` applies project access plus author or PI/PhD demo edit policy, with partners excluded.
- `wsResearchSave(state, input, me, project, people, now)` appends a new revision without mutating prior state.
- `wsResearchSummary(items)` separates tracked work status counts from measurement count and groups work by owner.
- `wsResearchCsv(items, people)` emits BOM-prefixed, CRLF-delimited, fully quoted CSV with formula-safe string cells.
- `wsResearchJson(state, projectId)` emits project-only revision history and the tracking disclaimer.

Both exports label records as `Team-entered operational tracking; not reviewed scientific findings`. CSV includes evidence IDs and author/update audit fields. JSON preserves every revision for only the requested project.

## Validation and policy coverage

- Rejects unsupported state versions, malformed records, duplicate or noncontiguous revisions, and chains that change project, kind, or original author.
- Rejects stale updates, inaccessible projects, unauthorized edits, partners, and owners outside the internal project membership.
- Accepts internal alumni owners and internal identities with global scope.
- Rejects invalid calendar dates, invalid timestamps, invalid enums, and unreadable hostile values without throwing from validation.
- Requires measurement metric, numeric value, unit, condition, and an existing project evidence entry whose `ack` is not `false`.
- Rejects blank, numeric-string, `NaN`, and infinite measurement values before coercion; accepts numeric zero and negative values.
- Allows optional sources only when they reference approved project evidence.
- Allows experiment links only to a current experiment in the same project.
- Neutralizes formula-like CSV strings, including leading whitespace before `=`, `+`, `-`, or `@`; numeric negatives are not prefixed.

## Test evidence

Red run before implementation:

```text
node tests/research-domain.test.cjs
17 tests, 0 pass, 17 fail
Expected failure: required browser-global functions were not implemented.
```

Final targeted run:

```text
node tests/research-domain.test.cjs
18 tests, 18 pass, 0 fail
```

The requested runner form was also attempted:

```text
node --test tests/research-domain.test.cjs
1 file-level failure: spawn EPERM
```

That failure is the known sandbox child-process restriction, not a test assertion failure. Running the same `node:test` file directly executes all subtests in-process and passes.

## Integration notes and concerns

- `wsResearchRead` and `wsResearchSave` deliberately do not write storage. The UI must re-read the global storage state immediately before save, call `wsResearchSave`, persist `result.state` only after `result.ok`, and surface write failures without claiming success.
- `wsResearchCsv` intentionally does not scope its input. The caller must pass only `wsResearchCurrent(state, selectedProjectId)` after confirming access.
- `wsResearchJson` validates the full state and throws for invalid state or project ID so corrupt data cannot be silently exported.
- The root integrator remains responsible for the full build, complete regression suite, browser walkthrough, and generated `index.html` update.
