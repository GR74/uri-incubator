# Dashboard and ClearerMind Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing URI interface to the backend, preserve its coherent navigation and review workflow, populate every dashboard area from real projections or explicit user actions, and deliver a privacy-safe ClearerMind pilot walkthrough.

**Architecture:** Keep the vendored, self-contained React build and add a small browser API boundary before migrating one workflow at a time from seed data and localStorage. FastAPI serves the generated page and same-origin APIs for backend mode; the original static prototype remains available as an explicitly labeled offline demo. The ClearerMind pilot is configured from selected local sources only after synthetic end-to-end tests pass.

**Tech Stack:** Existing vendored React/Babel/Tailwind build, browser Fetch API, Node built-in test runner, FastAPI static response, Playwright browser verification, PostgreSQL-backed API from the first two plans

**Spec:** `docs/superpowers/specs/2026-09-11-local-postgres-research-backend-design.md`

## Global Constraints

- Complete both backend plans and their acceptance gates first.
- Do not edit generated `index.html` by hand; rebuild it with `node build/build.js` after source changes.
- Preserve horizontal workspace tabs, contextual project tabs, responsive behavior, keyboard navigation, and legacy access.
- Backend mode must not fall back to fictional seed data or browser-local writes after a server mutation fails.
- Keep AI candidates visibly separate from approved records and team-entered operational tracking.
- Never display a graph edge that lacks an accessible, evidence-backed backend relation.
- Roles, permissions, assignments, review decisions, sharing, and stash state come from explicit server-side state.
- Do not ingest or screenshot raw participant data, unselected conversations, credentials, or restricted source text.
- Include before-and-after desktop and 390-pixel screenshots for visible changes.
- Every behavior-changing task follows red-green-refactor and ends in a focused commit.

---

## Planned file structure

```text
src/
  workspace-api.jsx             Fetch client, typed response normalization and error mapping
  workspace-backend.jsx         Backend bootstrap, identity/project state and loading boundaries
  workspace-ingestion.jsx       Source selection, preview, upload and progress UI
  workspace-retrieval.jsx       Cited question answering and source-opening UI
  workspace.jsx                 Existing shell and backend-projection rendering
  workspace-evidence.jsx        Existing evidence/review UI adapted to server commands
  workspace-research.jsx        Existing research tracking adapted to server commands
  workspace.css                 New backend, progress, citation and error states
tests/
  workspace-api.test.cjs
  workspace-backend-ui.test.cjs
  workspace-ingestion-ui.test.cjs
  workspace-retrieval-ui.test.cjs
backend/uri_backend/web.py       Generated-page serving and backend-mode configuration
backend/tests/test_web_app.py
docs/pilot/
  CLEARERMIND_RUNBOOK.md
  CLEARERMIND_SOURCE_MANIFEST.example.yaml
  PRIVACY_CHECKLIST.md
docs/screenshots/
  backend-*.png
```

### Task 1: Browser API boundary and same-origin application serving

**Files:**
- Create: `src/workspace-api.jsx`
- Create: `tests/workspace-api.test.cjs`
- Create: `backend/uri_backend/web.py`
- Create: `backend/tests/test_web_app.py`
- Modify: `src/uri.html`
- Modify: `backend/uri_backend/api.py`

**Interfaces:**
- Produces: `wsApiRequest(path, options) -> Promise<object>` and `wsApiError(error) -> {code,message,status}`.
- Produces: `wsCreateApiClient({baseUrl,getActorId})` with projects, sources, drafts, reviews, research, graph, answers, lifecycle, handoff, and discover methods.
- Produces: `GET /` serving generated `index.html` and `GET /api/client-config` returning backend mode.

- [ ] **Step 1: Write failing API client and web-serving tests**

```javascript
test('API client sends actor, content type, and idempotency headers', async () => {
  const calls = [];
  const api = context.wsCreateApiClient({
    baseUrl:'http://127.0.0.1:4173',
    getActorId:() => 'user-1',
    fetchImpl:async (url, options) => {
      calls.push({url, options});
      return { ok:true, status:201, json:async () => ({id:'p1'}) };
    },
  });
  await api.createProject({title:'ClearerMind'}, 'create-clearermind');
  assert.equal(calls[0].options.headers['X-URI-User-ID'], 'user-1');
  assert.equal(calls[0].options.headers['Idempotency-Key'], 'create-clearermind');
});
```

```python
def test_root_serves_generated_application(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Undergraduate Research Incubator" in response.text
    assert response.headers["cache-control"] == "no-store"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `node --test tests/workspace-api.test.cjs`

Run: `cd backend; uv run pytest tests/test_web_app.py -q`

Expected: FAIL because the API client and web route do not exist.

- [ ] **Step 3: Implement strict fetch and page-serving boundaries**

`wsApiRequest` parses JSON success and errors, maps network failure to `backend_unavailable`, never retries non-idempotent commands without an idempotency key, and preserves HTTP 401, 403, 409, 413, 415, and 422 codes. File uploads use `FormData` without forcing a JSON content type.

Serve the repository's generated `index.html` only after resolving and verifying the configured path remains beneath the repository root. `/api/client-config` returns `{mode:"backend", apiBase:"/api"}`. Loading `index.html` directly remains an offline prototype and shows its existing sample-data disclosure.

- [ ] **Step 4: Verify both build modes**

Run: `node --test tests/workspace-api.test.cjs; node build/build.js`

Run: `cd backend; uv run pytest tests/test_web_app.py -q`

Expected: all tests pass; the rebuilt page remains pure ASCII with no external resources.

- [ ] **Step 5: Commit the API boundary**

```bash
git add src/workspace-api.jsx src/uri.html tests/workspace-api.test.cjs backend/uri_backend/web.py backend/uri_backend/api.py backend/tests/test_web_app.py index.html
git commit -m "Connect the workspace API boundary"
```

### Task 2: Backend bootstrap for projects, identities, and projections

**Files:**
- Create: `src/workspace-backend.jsx`
- Create: `tests/workspace-backend-ui.test.cjs`
- Modify: `src/uri.html:4600-4900`
- Modify: `src/workspace.jsx:995-1170`
- Modify: `src/workspace.css`

**Interfaces:**
- Produces: `BackendResearchWorkspace({api,initialActorId})`.
- Consumes: project, user, membership, Home, Projects, and Overview API projections.
- Produces: explicit loading, empty, unauthorized, backend-unavailable, and stale-version states.

- [ ] **Step 1: Write failing bootstrap-state tests**

```javascript
test('backend workspace never replaces a failed request with sample projects', async () => {
  const model = await context.wsLoadBackendWorkspace({
    listActors:async () => [{id:'u1', name:'Researcher'}],
    listProjects:async () => { throw Object.assign(new Error('offline'), {code:'backend_unavailable'}); },
  }, 'u1');
  assert.equal(model.status, 'error');
  assert.deepEqual(model.projects, []);
  assert.match(model.message, /backend/i);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/workspace-backend-ui.test.cjs`

Expected: FAIL because backend bootstrap does not exist.

- [ ] **Step 3: Implement backend state without breaking the legacy prototype**

Load client configuration, actors, accessible projects, workspace Home projection, and the current project projection. Store only the selected actor/project/tab navigation hint in localStorage; server data remains authoritative. After each successful command, refetch only invalidated projections. On 409, retain form input and offer Reload current version. On backend failure, show an error with Retry and Offline prototype actions; never silently render `PEOPLE` or seeded projects in backend mode.

Pass backend project/person view models into the existing shell. Keep the legacy top-level application and seed registries for explicit offline/legacy mode until the migration is complete.

- [ ] **Step 4: Verify loading, access, and refresh behavior**

Run: `node --test tests/workspace-backend-ui.test.cjs tests/workspace-domain.test.cjs`

Expected: all tests pass for empty database, actor change, project removal, 401/403, network failure, stale projection, retry, and no sample fallback.

- [ ] **Step 5: Commit backend workspace bootstrap**

```bash
git add src/workspace-backend.jsx src/uri.html src/workspace.jsx src/workspace.css tests/workspace-backend-ui.test.cjs index.html
git commit -m "Load projects from the backend"
```

### Task 3: Six-source ingestion and quality-guidance interface

**Files:**
- Create: `src/workspace-ingestion.jsx`
- Create: `tests/workspace-ingestion-ui.test.cjs`
- Modify: `src/workspace-evidence.jsx`
- Modify: `src/workspace.jsx`
- Modify: `src/workspace.css`

**Interfaces:**
- Produces: `WsSourceChooser`, `WsGitSourceForm`, `WsConversationSelector`, `WsUploadSourceForm`, `WsQualityPreview`, and `WsIngestionProgress`.
- Consumes: source preview/register, conversation inventory/promote/purge, ingestion-run status, and source-version APIs.

- [ ] **Step 1: Write failing source-selection and privacy tests**

```javascript
test('conversation selection submits only checked conversation ids', async () => {
  const calls = [];
  const model = context.wsConversationSelectionModel([
    {id:'clearermind', title:'ClearerMind'},
    {id:'private', title:'Unrelated private chat'},
  ], new Set(['clearermind']));
  await model.promote({promote:async ids => calls.push(ids)});
  assert.deepEqual(calls, [['clearermind']]);
});

test('quality view has dimensions and no overall score', () => {
  const view = context.wsQualityView({dimensions:{provenance:{level:'partial', explanation:'No author'}}, overall_score:null});
  assert.equal(view.rows.length, 1);
  assert.equal(Object.hasOwn(view, 'score'), false);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/workspace-ingestion-ui.test.cjs`

Expected: FAIL because the ingestion interface does not exist.

- [ ] **Step 3: Implement tracked ingestion for all source families**

Present Git, selected conversations, documents, notebook/run, dataset/reference manifest, and lab notebook/protocol as role-oriented choices. Each explains what the source can establish, what it cannot establish, accepted pilot formats, and privacy cautions. Git requires repository root, ref, start/end commits, and path rules. Conversation upload shows metadata inventory before selection and exposes Cancel and purge.

Show provenance, temporal fidelity, decision density, reproducibility support, parse completeness, citation addressability, and extraction confidence separately. Display privacy/licensing warnings outside the quality list. Poll active ingestion status with bounded backoff and stop on terminal state, navigation, or component unmount. Preserve partial successes and make individual failed sources retryable.

- [ ] **Step 4: Verify accessibility and failure recovery**

Run: `node --test tests/workspace-ingestion-ui.test.cjs tests/evidence-domain.test.cjs`

Expected: all tests pass for keyboard selection, supported-format copy, oversize/unsupported errors, OCR-required state, partial failure, retry, cancellation, conversation purge, and stashed read-only behavior.

- [ ] **Step 5: Commit source ingestion UI**

```bash
git add src/workspace-ingestion.jsx src/workspace-evidence.jsx src/workspace.jsx src/workspace.css tests/workspace-ingestion-ui.test.cjs index.html
git commit -m "Add tracked source ingestion"
```

### Task 4: Server-backed drafts, reviews, research, and project record

**Files:**
- Modify: `src/workspace-evidence.jsx`
- Modify: `src/workspace-research.jsx`
- Modify: `src/workspace-research-domain.jsx`
- Modify: `src/workspace.jsx`
- Create: `tests/workspace-server-records.test.cjs`

**Interfaces:**
- Consumes: draft-set, review, publication, research, Record, Evidence, and Overview APIs.
- Produces: the existing Evidence, Reviews, Research, Record, and Overview experiences backed by server versions.

- [ ] **Step 1: Write failing publication-refresh and tracking tests**

```javascript
test('successful publication refreshes record and dashboard projections', async () => {
  const calls = [];
  await context.wsPublishAndRefresh({
    publish:async () => ({publication_id:'pub1'}),
    refresh:async keys => calls.push(keys),
  }, {draftSetId:'d1', expectedVersion:3, idempotencyKey:'publish-d1-v3'});
  assert.deepEqual(calls, [['drafts', 'reviews', 'record', 'overview', 'map', 'people']]);
});

test('AI suggested work stays unassigned until confirmed', () => {
  const item = context.wsResearchFromCandidate({kind:'task', title:'Rerun analysis', status:'draft_suggestion'});
  assert.equal(item.ownerId, null);
  assert.equal(item.status, 'suggested');
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/workspace-server-records.test.cjs`

Expected: FAIL because server-backed workflow helpers do not exist.

- [ ] **Step 3: Replace browser persistence one workflow at a time**

Load source groups and draft sets from the server, retain exact included/excluded state, send expected versions on edits, and map review actions to server commands. After publication, refresh all affected projections. Render citations as source title plus locator; restricted citations show that evidence exists without leaking text.

Load tasks, experiments, milestones, measurements, and revision history from the Research API. Preserve exact grouping by metric, unit, condition, and experiment. Suggested work requires Confirm before assignment or status editing. Overview and Record consume server projections and keep current labels for approved entries, recorded next steps, latest dated update, current state, and next action.

- [ ] **Step 4: Verify workflow parity**

Run: `node --test tests/workspace-server-records.test.cjs tests/evidence-domain.test.cjs tests/research-domain.test.cjs tests/research-ui.test.cjs`

Expected: all tests pass for draft editing, review request, changes requested, stale edit, idempotent publication, citations, research revisions, measurements, explicit suggestion confirmation, and projection refresh.

- [ ] **Step 5: Commit server-backed research workflows**

```bash
git add src/workspace-evidence.jsx src/workspace-research.jsx src/workspace-research-domain.jsx src/workspace.jsx tests/workspace-server-records.test.cjs index.html
git commit -m "Back research workflows with PostgreSQL"
```

### Task 5: Real graph, cited retrieval, and contribution views

**Files:**
- Create: `src/workspace-retrieval.jsx`
- Create: `tests/workspace-retrieval-ui.test.cjs`
- Modify: `src/workspace.jsx:580-625`
- Modify: `src/workspace.jsx:884-963`
- Modify: `src/workspace.css`

**Interfaces:**
- Produces: `WsResearchQuestion`, `WsCitedAnswer`, `WsSourceLocator`, and backend `WsResearchMap` adapter.
- Consumes: graph, search, answer, People, and contribution projections.

- [ ] **Step 1: Write failing evidence-map and citation tests**

```javascript
test('map rejects an edge whose endpoints are absent', () => {
  const model = context.wsNormalizeBackendGraph({
    nodes:[{id:'record:r1', type:'record', label:'Decision'}],
    edges:[{id:'e1', source:'record:r1', target:'source:missing', label:'supported by'}],
    warnings:[],
  });
  assert.deepEqual(model.edges, []);
  assert.match(model.warnings[0], /missing endpoint/i);
});

test('answer sentences expose clickable exact locators', () => {
  const model = context.wsAnswerModel({
    status:'answered',
    sentences:[{text:'The method changed.', citation_ids:['c1']}],
    citations:[{id:'c1', source_title:'methods.md', locator:{line_start:14, line_end:17}}],
  });
  assert.equal(model.sentences[0].citations[0].label, 'methods.md, lines 14-17');
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/workspace-retrieval-ui.test.cjs`

Expected: FAIL because backend graph and answer adapters do not exist.

- [ ] **Step 3: Connect evidence-backed graph, questions, and contributions**

Retain existing map filters, list alternative, deterministic SVG rendering, keyboard selection, and project scoping. Replace browser graph derivation with backend nodes and cited edges. The detail panel shows relation type, review state, readable citations, and Open record/source actions. Unresolved edges become warnings and never render.

Add a question panel that clearly distinguishes approved-only answers from reviewer-enabled pending context. Each answer sentence lists clickable source locators; insufficient evidence and contradictions receive dedicated states. People shows explicit roles/capabilities, reviewed contribution events, unmatched source authorship, and continuity dependencies. Remove commit-count or message-count credit summaries.

- [ ] **Step 4: Verify map, retrieval, and accessibility**

Run: `node --test tests/workspace-retrieval-ui.test.cjs tests/workspace-lifecycle-graph.test.cjs`

Expected: all tests pass for missing endpoints, permission-filtered nodes, stashed styling, pending toggle, exact citations, restricted source text, refusal, contradictions, role labels, and contribution events.

- [ ] **Step 5: Commit research intelligence views**

```bash
git add src/workspace-retrieval.jsx src/workspace.jsx src/workspace.css tests/workspace-retrieval-ui.test.cjs index.html
git commit -m "Show cited research connections"
```

### Task 6: Server-backed stash, handoff, sharing, and continuation

**Files:**
- Modify: `src/workspace-domain.jsx`
- Modify: `src/workspace.jsx:629-710`
- Modify: `src/workspace.jsx:816-990`
- Create: `tests/workspace-server-lifecycle.test.cjs`
- Modify: `src/workspace.css`

**Interfaces:**
- Consumes: lifecycle, archive export, handoff, Discover, and continuation APIs.
- Produces: version-checked Settings commands and projection-driven read-only archive views.

- [ ] **Step 1: Write failing no-optimistic-mutation tests**

```javascript
test('failed stash leaves the active project unchanged', async () => {
  const active = {id:'p1', status:'active', version:4};
  const result = await context.wsRunLifecycleCommand(active, async () => {
    throw Object.assign(new Error('conflict'), {status:409, code:'stale_version'});
  });
  assert.equal(result.project, active);
  assert.equal(result.error.code, 'stale_version');
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/workspace-server-lifecycle.test.cjs`

Expected: FAIL because lifecycle commands still use browser mutation.

- [ ] **Step 3: Connect lifecycle commands and immutable archive projections**

Send reason, next step, visibility, expected version, and idempotency key to stash. Update UI state only from the successful server response. A stashed project hides all write controls, stops active polling, retains readable sources/drafts/history, and exposes permitted export, visibility, resume, and continuation actions.

Handoff loads approved current state, methods, results, failed approaches, contributors, omissions, artifacts, and next steps. Restricted or unavailable material is listed as omitted without content. Discover shows only lab-shared stashed projects. Continue opens the new project returned by the server and preserves the source archive.

- [ ] **Step 4: Verify lifecycle and handoff parity**

Run: `node --test tests/workspace-server-lifecycle.test.cjs tests/workspace-lifecycle-graph.test.cjs`

Expected: all tests pass for validation, 409 conflict, failed network write, read-only state, visibility, scoped export, resume, discover access, and linked continuation.

- [ ] **Step 5: Commit server-backed project lifecycle**

```bash
git add src/workspace-domain.jsx src/workspace.jsx src/workspace.css tests/workspace-server-lifecycle.test.cjs index.html
git commit -m "Persist project archive lifecycles"
```

### Task 7: Synthetic end-to-end gate and ClearerMind pilot runbook

**Files:**
- Create: `docs/pilot/CLEARERMIND_RUNBOOK.md`
- Create: `docs/pilot/CLEARERMIND_SOURCE_MANIFEST.example.yaml`
- Create: `docs/pilot/PRIVACY_CHECKLIST.md`
- Create: `backend/tests/e2e/test_synthetic_pilot.py`
- Modify: `README.md`
- Modify: `docs/PRODUCT_FLOW.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Create: `docs/screenshots/backend-ingestion-desktop.png`
- Create: `docs/screenshots/backend-review-desktop.png`
- Create: `docs/screenshots/backend-dashboard-desktop.png`
- Create: `docs/screenshots/backend-map-desktop.png`
- Create: `docs/screenshots/backend-dashboard-mobile.png`

**Interfaces:**
- Produces: one reproducible synthetic end-to-end test and one human-controlled ClearerMind setup/runbook.
- Consumes: every backend and frontend interface from all three plans.

- [ ] **Step 1: Write the failing synthetic pilot test**

```python
async def test_synthetic_project_reaches_stashed_continuable_archive(pilot) -> None:
    project = await pilot.create_project("Synthetic pilot")
    await pilot.ingest_all_six_source_families(project)
    draft = await pilot.run_extraction(project)
    publication = await pilot.review_and_publish(draft)
    dashboard = await pilot.dashboard(project)
    assert dashboard.approved_entries == publication.record_count
    assert dashboard.map.nodes > 0
    answer = await pilot.ask(project, "Why did the method change?")
    assert answer.status == "answered"
    assert all(sentence.citation_ids for sentence in answer.sentences)
    archive = await pilot.stash_and_export(project)
    continuation = await pilot.continue_project(archive)
    assert continuation.continued_from == project.id
```

- [ ] **Step 2: Run the synthetic pilot and verify RED**

Run: `cd backend; uv run pytest tests/e2e/test_synthetic_pilot.py -q`

Expected: FAIL until all frontend-serving and end-to-end orchestration paths are connected.

- [ ] **Step 3: Complete the runbook and manifest contract**

The source manifest requires project ID, repository root, named ref, start/end commits, include paths, explicitly selected conversation IDs, document paths, notebook/run paths, dataset manifest paths, and lab-notebook/protocol paths. It stores no credentials or participant data. The runbook begins with a clean database backup, source-owner confirmation, privacy checklist, dry-run inventory, explicit selection confirmation, and expected artifact hashes.

The runbook then covers ingestion, quality warnings, extraction, review, publication, dashboard inspection, four cited questions, contribution inspection, stash, export, sharing, and continuation. It ends with database backup, artifact checksum verification, supported-format report, model/runtime metrics, and an explicit list of omitted or unavailable sources.

- [ ] **Step 4: Run complete automated verification**

Run: `cd backend; uv run pytest -q; uv run ruff check uri_backend tests scripts; uv run alembic upgrade head`

Run: `node --test tests/*.test.cjs; node build/build.js; git diff --check`

Expected: every backend and Node test passes, the migration is at head, the generated page is pure ASCII and self-contained, and the unrelated executive-summary PDF remains untouched.

- [ ] **Step 5: Verify the interface manually with synthetic data**

Serve FastAPI and the worker, then exercise desktop and 390-pixel flows for project creation, all six source types, privacy preview, progress, draft review, publication, Overview, Research, Record, Evidence, People, Map, cited questions, Handoffs, Settings, stash, Discover, and continuation. Test keyboard-only navigation, visible focus, reduced motion, refresh, worker restart, backend outage, and malformed upload.

Expected: no browser errors or cross-project leaks; every displayed metric matches its projection; every graph relation and answer citation opens a readable source location; screenshots contain synthetic data only.

- [ ] **Step 6: Execute the ClearerMind pilot only after source-owner confirmation**

Run the manifest dry-run and present its selected refs, commit IDs, paths, conversation titles/IDs, file sizes, exclusions, privacy warnings, and artifact hashes for confirmation. After confirmation, execute ingestion without changing the ClearerMind Git checkout and without persisting unselected conversations or raw participant data.

Expected: the dashboard is populated from approved ClearerMind evidence and explicit project actions. Missing categories remain honest empty states. Record extraction accuracy, corrections, unsupported sources, latency, and citation fidelity without publishing sensitive source text.

- [ ] **Step 7: Commit the verified pilot delivery**

```bash
git add docs/pilot README.md docs/PRODUCT_FLOW.md docs/IMPLEMENTATION_STATUS.md docs/screenshots backend/tests/e2e index.html
git commit -m "Document the ClearerMind pilot"
```

## Final acceptance gate

- All current workspace and project tabs load from backend projections in backend mode.
- The same source never creates duplicate artifacts, parts, drafts, records, or graph edges after retries.
- Users can trace every approved statement, graph edge, and generated answer to an authorized source location.
- Roles, assignments, reviews, contributions, sharing, and lifecycle state are explicit and server-enforced.
- A stashed project remains searchable, exportable, shareable, resumable, and continuable while read-only.
- The ClearerMind pilot uses only confirmed sources and selected conversations and never ingests raw participant data.
- Synthetic tests, backend tests, Node tests, build, migrations, browser checks, and checksum verification all pass.
