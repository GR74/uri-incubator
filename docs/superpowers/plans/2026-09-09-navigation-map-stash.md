# Unified Navigation, Research Map, and Project Stashing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the competing workspace navigation patterns with one persistent tab system, add an explainable two-dimensional lab source map, and implement a reversible project stash/continue lifecycle.

**Architecture:** Add one pure browser-loadable domain module for project lifecycle and normalized graph operations. Keep `App` in `src/uri.html` as the durable owner of project state, keep research revisions in their existing store, and let the workspace shell render the new navigation, map, and lifecycle controls through explicit callbacks.

**Tech Stack:** Static HTML, React 18 browser globals, Babel JSX compilation, CSS, SVG, browser `localStorage`, Node.js built-in test runner; no new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-09-navigation-map-stash-design.md`

## Global Constraints

- Preserve two-space indentation, semicolons, PascalCase components, camelCase helpers, uppercase registries, and `ws-` CSS prefixes.
- Edit `src/` files only; regenerate `index.html` with `node build/build.js` and commit it with its source changes.
- Keep the production artifact pure ASCII, offline-capable, and free of external resource requests.
- Use the established scarlet `#BA0C2F`, gray `#A7B1B7`, charcoal, and white palette without university marks.
- Draw only explicit provenance edges; do not infer semantic relationships from matching words.
- Treat `archived` seed projects as stashed for display while preserving their original fields.
- Keep stashed projects readable and exportable but disable evidence publication and research editing.
- Label browser-local sharing as a prototype; do not imply real multi-user authorization.
- Write and observe each behavior-changing test failing before adding its production implementation.
- Preserve the user's untracked `URI_Executive_Summary.pdf`; never stage or modify it.

---

### Task 1: Project lifecycle domain

**Files:**

- Create: `src/workspace-domain.jsx`
- Create: `tests/workspace-lifecycle-graph.test.cjs`
- Modify: `src/uri.html:183-186`

**Interfaces:**

- Consumes: project records from `SEED`, demo people with `{ k, n, tier, projects }`, and injected ISO timestamps/IDs.
- Produces: `wsIsStashed(project)`, `wsProjectBuckets(projects)`, `wsCanManageProject(project, person)`, `wsValidateStash(input)`, `wsStashProject(project, input)`, `wsResumeProject(project, input)`, `wsSetStashVisibility(project, input)`, and `wsContinueProject(project, input)`.
- Transition results use `{ ok: true, project }`, `{ ok: true, sourceProject, project }`, or `{ ok: false, error, errorField }`.

- [ ] **Step 1: Write the lifecycle test harness and first failing validation test**

Create a VM test harness that intentionally evaluates an empty string until the domain file exists, then request the desired API:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const domainPath = path.join(__dirname, '../src/workspace-domain.jsx');
const context = vm.createContext({ Date, JSON, Math, Set, Map });
vm.runInContext(fs.existsSync(domainPath) ? fs.readFileSync(domainPath, 'utf8') : '', context);
const plain = value => JSON.parse(JSON.stringify(value));

test('stash validation requires a reason and a next step', () => {
  assert.deepEqual(plain(context.wsValidateStash({ reason: '', nextStep: '' })), {
    ok: false,
    error: 'Record why this project stopped.',
    errorField: 'reason',
  });
  assert.equal(context.wsValidateStash({ reason: 'Paused', nextStep: '  ' }).errorField, 'nextStep');
});
```

- [ ] **Step 2: Run the validation test and verify RED**

Run: `node --test --test-name-pattern="stash validation" tests/workspace-lifecycle-graph.test.cjs`

Expected: FAIL because `context.wsValidateStash` is not a function.

- [ ] **Step 3: Implement validation and lifecycle predicates**

Create `src/workspace-domain.jsx` with constants and pure helpers:

```js
const WS_STASHED_STATUSES = new Set(['stashed', 'archived']);

function wsIsStashed(project){
  return !!project && WS_STASHED_STATUSES.has(project.status);
}

function wsValidateStash(input){
  const reason = String(input && input.reason || '').trim();
  const nextStep = String(input && input.nextStep || '').trim();
  if (!reason) return { ok:false, error:'Record why this project stopped.', errorField:'reason' };
  if (!nextStep) return { ok:false, error:'Record the recommended next step.', errorField:'nextStep' };
  return { ok:true, value:{ reason, nextStep, visibility:input.visibility === 'lab' ? 'lab' : 'private' } };
}

function wsProjectBuckets(projects){
  const all = Array.isArray(projects) ? projects.filter(Boolean) : [];
  return { active:all.filter(project => !wsIsStashed(project)), stashed:all.filter(wsIsStashed) };
}

function wsCanManageProject(project, person){
  if (!project || !person || !['pi', 'phd'].includes(person.tier)) return false;
  return person.scope === 'all' || (person.projects || []).includes(project.id);
}
```

- [ ] **Step 4: Run the validation test and verify GREEN**

Run: `node --test --test-name-pattern="stash validation" tests/workspace-lifecycle-graph.test.cjs`

Expected: PASS.

- [ ] **Step 5: Write failing stash, resume, bucket, and continuation tests**

Append tests that prove immutability and legacy compatibility:

```js
test('stash and resume append lifecycle events without mutating the source', () => {
  const original = { id:'p1', code:'URI-1', name:'Project', status:'active', log:[] };
  const stashed = context.wsStashProject(original, {
    reason:'Instrument unavailable', nextStep:'Book the replacement rig', visibility:'lab',
    actorKey:'mentor', now:'2026-09-09T12:00:00.000Z',
  });
  assert.equal(stashed.ok, true);
  assert.equal(original.status, 'active');
  assert.equal(stashed.project.status, 'stashed');
  assert.equal(stashed.project.lifecycle[0].action, 'stashed');
  const resumed = context.wsResumeProject(stashed.project, {
    actorKey:'mentor', now:'2026-09-10T12:00:00.000Z',
  });
  assert.equal(resumed.project.status, 'active');
  assert.equal(resumed.project.stashReason, 'Instrument unavailable');
  assert.deepEqual(plain(resumed.project.lifecycle.map(item => item.action)), ['stashed', 'resumed']);
  const shared = context.wsSetStashVisibility(stashed.project, {
    visibility:'lab', actorKey:'mentor', now:'2026-09-10T13:00:00.000Z',
  });
  assert.equal(shared.project.stashVisibility, 'lab');
  assert.equal(shared.project.lifecycle.at(-1).action, 'shared');
});

test('project buckets treat archived seed records as stashed', () => {
  const buckets = context.wsProjectBuckets([{ id:'a', status:'active' }, { id:'b', status:'archived' }]);
  assert.deepEqual(plain(buckets.active.map(item => item.id)), ['a']);
  assert.deepEqual(plain(buckets.stashed.map(item => item.id)), ['b']);
});

test('continue creates a linked active project and leaves the stashed source unchanged', () => {
  const source = { id:'p1', code:'URI-1', name:'Project', oneLine:'Aim', status:'stashed', log:[{ id:'old' }] };
  const result = context.wsContinueProject(source, {
    newId:'p2', newCode:'URI-1-C1', actor:{ k:'student', n:'Student', i:'ST', line:'Researcher' },
    now:'2026-09-09T12:00:00.000Z',
  });
  assert.equal(result.ok, true);
  assert.equal(source.status, 'stashed');
  assert.equal(result.project.status, 'active');
  assert.equal(result.project.continuedFrom, 'p1');
  assert.notEqual(result.project.log, source.log);
  assert.match(result.project.log[0].b, /URI-1/);
});
```

- [ ] **Step 6: Run the new lifecycle tests and verify RED**

Run: `node --test tests/workspace-lifecycle-graph.test.cjs`

Expected: validation passes; stash/resume/continue tests FAIL because transition helpers are missing.

- [ ] **Step 7: Implement immutable lifecycle transitions**

Add a lifecycle event helper and the three transitions. Preserve stash metadata on resume, map legacy `archiveNote` into the read-only banner at render time, and create a single provenance entry for a continuation instead of copying the old log:

```js
function wsLifecycleEvent(action, actorKey, now, extra){
  return { action, actorKey, at:now, ...(extra || {}) };
}

function wsStashProject(project, input){
  const validated = wsValidateStash(input);
  if (!validated.ok) return validated;
  if (wsIsStashed(project)) return { ok:false, error:'This project is already stashed.' };
  const event = wsLifecycleEvent('stashed', input.actorKey, input.now);
  return { ok:true, project:{ ...project, status:'stashed', stashedOn:input.now, stashedBy:input.actorKey,
    stashReason:validated.value.reason, stashNextStep:validated.value.nextStep,
    stashVisibility:validated.value.visibility, lifecycle:[...(project.lifecycle || []), event] } };
}

function wsResumeProject(project, input){
  if (!wsIsStashed(project)) return { ok:false, error:'Only a stashed project can be resumed.' };
  const event = wsLifecycleEvent('resumed', input.actorKey, input.now);
  return { ok:true, project:{ ...project, status:'active', resumedOn:input.now,
    lifecycle:[...(project.lifecycle || []), event] } };
}

function wsSetStashVisibility(project, input){
  if (!wsIsStashed(project)) return { ok:false, error:'Only a stashed project can change archive visibility.' };
  const visibility = input.visibility === 'lab' ? 'lab' : 'private';
  const action = visibility === 'lab' ? 'shared' : 'made-private';
  return { ok:true, project:{ ...project, stashVisibility:visibility,
    lifecycle:[...(project.lifecycle || []), wsLifecycleEvent(action, input.actorKey, input.now)] } };
}

function wsContinueProject(source, input){
  if (!wsIsStashed(source)) return { ok:false, error:'Only a stashed project can be continued.' };
  const actor = input.actor;
  const entry = { id:input.newId + '-origin', d:input.now.slice(0, 10), t:'method', au:actor.n,
    h:'Continued from ' + source.code,
    b:'This project continues the stashed record in ' + source.code + '. Read that immutable record before changing the next step.',
    ack:true, sourceProjectId:source.id };
  const project = { ...source, id:input.newId, code:input.newCode, name:source.name + ' - continuation',
    status:'active', continuedFrom:source.id, started:input.now.slice(0, 10), current:[{ n:actor.n, i:actor.i, r:actor.line }],
    contacts:(source.contacts || []).map(item => ({ ...item })),
    artifacts:(source.artifacts || []).map(item => ({ ...item })),
    reading:(source.reading || []).map(item => ({ ...item })),
    log:[entry], lifecycle:[wsLifecycleEvent('continued', actor.k, input.now, { sourceProjectId:source.id })] };
  delete project.stashedOn;
  delete project.stashedBy;
  delete project.stashReason;
  delete project.stashNextStep;
  delete project.stashVisibility;
  delete project.archivedOn;
  delete project.archiveNote;
  return { ok:true, sourceProject:source, project };
}
```

- [ ] **Step 8: Run lifecycle tests and verify GREEN**

Run: `node --test tests/workspace-lifecycle-graph.test.cjs`

Expected: all lifecycle tests PASS.

- [ ] **Step 9: Load the new domain file before existing workspace modules**

Insert this tag before `workspace-research-domain.jsx`:

```html
<script type="text/babel" data-presets="react-classic" src="workspace-domain.jsx"></script>
```

- [ ] **Step 10: Build and commit the lifecycle domain**

Run: `node build/build.js`

Expected: `built index.html`, pure ASCII, zero external requests.

Commit:

```powershell
git add src/workspace-domain.jsx src/uri.html tests/workspace-lifecycle-graph.test.cjs index.html
git commit -m "Add the project stash lifecycle"
```

---

### Task 2: Normalized research graph domain

**Files:**

- Modify: `src/workspace-domain.jsx`
- Modify: `tests/workspace-lifecycle-graph.test.cjs`

**Interfaces:**

- Consumes: `wsBuildResearchGraph(projects, researchItems, options)` where accessible projects are already scoped, research items are current revisions, and `options.includePending` defaults to false.
- Produces: `{ nodes, edges, counts, warnings }`, `wsFilterResearchGraph(graph, filters)`, and `wsLayoutResearchGraph(graph, width, height)`.
- Node targets use `{ section:'project', projectId, projectTab }`; map UI decides how to navigate.

- [ ] **Step 1: Write a failing graph construction test**

```js
test('graph uses approved records and explicit source IDs without inventing pending nodes', () => {
  const projects = [{
    id:'p1', code:'URI-1', name:'Project', status:'active',
    artifacts:[{ n:'Protocol A', d:'SOP-12' }],
    log:[
      { id:'e1', t:'result', h:'Approved result', b:'Observed', ack:true, source:'dataset.csv' },
      { id:'e2', t:'method', h:'Pending method', b:'Draft', ack:false },
    ],
  }];
  const research = [{ id:'m1', projectId:'p1', kind:'measurement', title:'Yield', sourceEntryId:'e1' }];
  const graph = context.wsBuildResearchGraph(projects, research, {});
  assert.equal(graph.nodes.some(node => node.id === 'entry:p1:e1'), true);
  assert.equal(graph.nodes.some(node => node.id === 'entry:p1:e2'), false);
  assert.equal(graph.nodes.some(node => node.type === 'source' && node.label === 'dataset.csv'), true);
  assert.equal(graph.edges.some(edge => edge.type === 'supported-by' && edge.source === 'research:p1:m1'), true);
});
```

- [ ] **Step 2: Run graph construction test and verify RED**

Run: `node --test --test-name-pattern="graph uses approved" tests/workspace-lifecycle-graph.test.cjs`

Expected: FAIL because `wsBuildResearchGraph` is not defined.

- [ ] **Step 3: Implement graph construction with stable IDs and explainable edges**

Use prefixed IDs (`project:`, `entry:`, `research:`, `source:`, `artifact:`), a `Map` to de-duplicate shared named sources, and an `addEdge` helper that refuses unresolved endpoints. Build project and approved-entry nodes first, explicit source/artifact nodes second, then research nodes so `sourceEntryId` and `experimentId` can resolve. Return warning strings for unresolved explicit IDs.

The public shape must be exact:

```js
function wsGraphSourceValues(entry){
  const values = [];
  const add = value => {
    if (!value) return;
    if (Array.isArray(value)) { value.forEach(add); return; }
    if (typeof value === 'string') { values.push(value.trim()); return; }
    if (typeof value === 'object') add(value.label || value.name || value.filename || value.title || value.ref || value.id);
  };
  ['sources', 'sourceRefs', 'citations', 'source', 'attachments', 'files'].forEach(key => add(entry[key]));
  return [...new Set(values.filter(Boolean))];
}

function wsGraphStableId(prefix, value){
  let hash = 2166136261;
  const text = String(value).trim().toLowerCase();
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return prefix + ':' + (hash >>> 0).toString(36);
}

function wsBuildResearchGraph(projects, researchItems, options){
  const includePending = !!(options && options.includePending);
  const nodes = [];
  const edges = [];
  const warnings = [];
  const nodeIds = new Set();
  const addNode = node => { if (!nodeIds.has(node.id)) { nodeIds.add(node.id); nodes.push(node); } return node.id; };
  const addEdge = edge => {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) { warnings.push('Skipped unresolved connection: ' + edge.id); return; }
    edges.push(edge);
  };
  const sourceNodes = new Map();
  const visibleProjects = (projects || []).filter(Boolean);
  visibleProjects.forEach(project => {
    addNode({ id:'project:' + project.id, label:project.name, type:'project', projectId:project.id,
      projectIds:[project.id], status:wsIsStashed(project) ? 'stashed' : 'active', detail:project.oneLine || '',
      target:{ section:'project', projectId:project.id, projectTab:'overview' } });
    (project.log || []).filter(entry => includePending || entry.ack !== false).forEach(entry => {
      const entryId = 'entry:' + project.id + ':' + entry.id;
      const type = entry.t === 'decision' ? 'decision' : 'record';
      addNode({ id:entryId, label:entry.h || 'Untitled record', type, projectId:project.id,
        projectIds:[project.id], status:entry.ack === false ? 'pending' : 'approved', detail:entry.b || '',
        target:{ section:'project', projectId:project.id, projectTab:'record', entryId:entry.id } });
      addEdge({ id:entryId + '>project:' + project.id, source:entryId, target:'project:' + project.id,
        type:'belongs-to', label:'Belongs to ' + project.code });
      wsGraphSourceValues(entry).forEach(label => {
        const sourceId = wsGraphStableId('source', label);
        if (!sourceNodes.has(sourceId)) {
          const node = { id:sourceId, label, type:'source', projectId:null, projectIds:[], status:'recorded', detail:'Explicitly named source' };
          sourceNodes.set(sourceId, node);
          addNode(node);
        }
        const sourceNode = sourceNodes.get(sourceId);
        if (!sourceNode.projectIds.includes(project.id)) sourceNode.projectIds.push(project.id);
        addEdge({ id:entryId + '>' + sourceId, source:entryId, target:sourceId,
          type:'uses', label:(type === 'decision' ? 'Decision supported by ' : 'Uses ') + label });
      });
    });
    (project.artifacts || []).forEach((artifact, index) => {
      const artifactId = 'artifact:' + project.id + ':' + index;
      addNode({ id:artifactId, label:artifact.n || 'Unnamed artifact', type:'artifact', projectId:project.id,
        projectIds:[project.id], status:'recorded', detail:artifact.d || '',
        target:{ section:'project', projectId:project.id, projectTab:'overview' } });
      addEdge({ id:artifactId + '>project:' + project.id, source:artifactId, target:'project:' + project.id,
        type:'belongs-to', label:'Artifact of ' + project.code });
    });
  });
  const projectIds = new Set(visibleProjects.map(project => project.id));
  const visibleResearch = (researchItems || []).filter(item => projectIds.has(item.projectId));
  visibleResearch.forEach(item => addNode({ id:'research:' + item.projectId + ':' + item.id,
    label:item.title || item.metric || 'Untitled research item', type:'research', projectId:item.projectId,
    projectIds:[item.projectId], status:item.status || 'recorded', detail:item.notes || '',
    target:{ section:'project', projectId:item.projectId, projectTab:'research', researchId:item.id } }));
  visibleResearch.forEach(item => {
    const researchId = 'research:' + item.projectId + ':' + item.id;
    addEdge({ id:researchId + '>project:' + item.projectId, source:researchId, target:'project:' + item.projectId,
      type:'belongs-to', label:'Tracked in project' });
    if (item.sourceEntryId) addEdge({ id:researchId + '>entry:' + item.projectId + ':' + item.sourceEntryId,
      source:researchId, target:'entry:' + item.projectId + ':' + item.sourceEntryId,
      type:'supported-by', label:'Supported by approved evidence' });
    if (item.experimentId) addEdge({ id:researchId + '>research:' + item.projectId + ':' + item.experimentId,
      source:researchId, target:'research:' + item.projectId + ':' + item.experimentId,
      type:'linked-experiment', label:'Linked to experiment' });
  });
  visibleProjects.filter(project => project.continuedFrom && projectIds.has(project.continuedFrom)).forEach(project => {
    addEdge({ id:'project:' + project.id + '>project:' + project.continuedFrom,
      source:'project:' + project.id, target:'project:' + project.continuedFrom,
      type:'continued-from', label:'Continued from stashed project' });
  });
  const sourceCount = nodes.filter(node => ['source', 'artifact'].includes(node.type)).length;
  return { nodes, edges, warnings, counts:{ nodes:nodes.length, edges:edges.length,
    projects:nodes.filter(node => node.type === 'project').length, sources:sourceCount } };
}
```

For each connection set a human-readable `label`, such as `Belongs to URI-1`, `Uses dataset.csv`, or `Supported by Approved result`. Do not connect two nodes only because their labels contain similar text.

- [ ] **Step 4: Run graph construction test and verify GREEN**

Run: `node --test --test-name-pattern="graph uses approved" tests/workspace-lifecycle-graph.test.cjs`

Expected: PASS.

- [ ] **Step 5: Write failing scope, search, invalid-edge, stashed, and layout tests**

```js
test('graph filters one project while retaining connected shared sources', () => {
  const graph = context.wsBuildResearchGraph([
    { id:'p1', code:'P1', name:'One', status:'active', log:[{ id:'a', t:'result', h:'A', ack:true, source:'shared.csv' }] },
    { id:'p2', code:'P2', name:'Two', status:'stashed', log:[{ id:'b', t:'decision', h:'B', ack:true, source:'shared.csv' }] },
  ], [], {});
  const filtered = context.wsFilterResearchGraph(graph, { scope:'p2', query:'', types:[] });
  assert.equal(filtered.nodes.some(node => node.id === 'project:p1'), false);
  assert.equal(filtered.nodes.some(node => node.label === 'shared.csv'), true);
  assert.equal(filtered.nodes.find(node => node.id === 'project:p2').status, 'stashed');
});

test('graph layout is deterministic and keeps nodes inside the viewport', () => {
  const graph = { nodes:[{ id:'a', type:'project' }, { id:'b', type:'source' }],
    edges:[{ id:'a-b', source:'a', target:'b', type:'uses', label:'Uses' }] };
  const first = context.wsLayoutResearchGraph(graph, 960, 560);
  const second = context.wsLayoutResearchGraph(graph, 960, 560);
  assert.deepEqual(plain(first), plain(second));
  assert.equal(first.every(node => node.x >= 28 && node.x <= 932 && node.y >= 28 && node.y <= 532), true);
});
```

- [ ] **Step 6: Run filter and layout tests and verify RED**

Run: `node --test tests/workspace-lifecycle-graph.test.cjs`

Expected: new tests FAIL because filter/layout helpers are missing or incomplete.

- [ ] **Step 7: Implement visible-subgraph filtering and deterministic 2D layout**

`wsFilterResearchGraph` first keeps nodes in the requested project plus shared sources attached to them, then applies query/type filters, then retains only edges whose endpoints both remain. Search checks `label`, `detail`, `type`, and `projectId` case-insensitively. Empty `types` means all types.

`wsLayoutResearchGraph` clones nodes in stable ID order, seeds them around a fixed circle, then runs 220 deterministic repulsion/link-attraction iterations. Explicit edges draw project clusters together. Clamp coordinates to 28-pixel viewport padding. Never call `Math.random()`.

```js
function wsFilterResearchGraph(graph, filters){
  const scope = filters && filters.scope || 'all';
  const query = String(filters && filters.query || '').trim().toLowerCase();
  const types = new Set(filters && Array.isArray(filters.types) ? filters.types : []);
  const scoped = (graph.nodes || []).filter(node => scope === 'all'
    || node.projectId === scope || (node.projectIds || []).includes(scope));
  const scopedIds = new Set(scoped.map(node => node.id));
  const scopedEdges = (graph.edges || []).filter(edge => scopedIds.has(edge.source) && scopedIds.has(edge.target));
  const matches = scoped.filter(node => {
    const typeMatch = !types.size || types.has(node.type) || node.type === 'project';
    const text = [node.label, node.detail, node.type, node.projectId].filter(Boolean).join(' ').toLowerCase();
    return typeMatch && (!query || text.includes(query));
  });
  const keep = new Set(matches.map(node => node.id));
  if (query || types.size) scopedEdges.forEach(edge => {
    if (keep.has(edge.source) || keep.has(edge.target)) { keep.add(edge.source); keep.add(edge.target); }
  });
  else scoped.forEach(node => keep.add(node.id));
  const nodes = scoped.filter(node => keep.has(node.id));
  const ids = new Set(nodes.map(node => node.id));
  const edges = scopedEdges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
  return { ...graph, nodes, edges, counts:{ nodes:nodes.length, edges:edges.length,
    projects:nodes.filter(node => node.type === 'project').length,
    sources:nodes.filter(node => ['source', 'artifact'].includes(node.type)).length } };
}

function wsLayoutResearchGraph(graph, width, height){
  const ordered = [...(graph.nodes || [])].sort((left, right) => left.id.localeCompare(right.id));
  const nodes = ordered.map((node, index) => {
    const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2;
    return { ...node, x:width / 2 + Math.cos(angle) * width * 0.32,
      y:height / 2 + Math.sin(angle) * height * 0.32 };
  });
  const byId = new Map(nodes.map(node => [node.id, node]));
  for (let step = 0; step < 220; step += 1) {
    const cooling = 1 - step / 220;
    for (let left = 0; left < nodes.length; left += 1) {
      for (let right = left + 1; right < nodes.length; right += 1) {
        const a = nodes[left];
        const b = nodes[right];
        const dx = b.x - a.x || 0.01;
        const dy = b.y - a.y || 0.01;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const push = Math.max(0, 74 - distance) * 0.18 * cooling;
        a.x -= dx / distance * push;
        a.y -= dy / distance * push;
        b.x += dx / distance * push;
        b.y += dy / distance * push;
      }
    }
    (graph.edges || []).forEach(edge => {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b) return;
      const dx = b.x - a.x || 0.01;
      const dy = b.y - a.y || 0.01;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const pull = (distance - 128) * 0.025 * cooling;
      a.x += dx / distance * pull;
      a.y += dy / distance * pull;
      b.x -= dx / distance * pull;
      b.y -= dy / distance * pull;
    });
    nodes.forEach(node => {
      node.x += (width / 2 - node.x) * 0.003 * cooling;
      node.y += (height / 2 - node.y) * 0.003 * cooling;
      node.x = Math.max(28, Math.min(width - 28, node.x));
      node.y = Math.max(28, Math.min(height - 28, node.y));
    });
  }
  return nodes;
}
```

- [ ] **Step 8: Run all domain tests and commit the graph model**

Run: `node --test tests/workspace-lifecycle-graph.test.cjs`

Expected: all tests PASS.

Commit:

```powershell
git add src/workspace-domain.jsx tests/workspace-lifecycle-graph.test.cjs
git commit -m "Build the research source graph model"
```

---

### Task 3: Durable lifecycle transitions in the application owner

**Files:**

- Modify: `src/workspace-domain.jsx`
- Modify: `tests/workspace-lifecycle-graph.test.cjs`
- Modify: `src/uri.html:2271-2289,4612-4825`

**Interfaces:**

- Consumes: a successful transition plus the complete current App snapshot.
- Produces: `wsPersistProjectTransition(storage, key, appState, transition)` and App callbacks `stashProject`, `resumeProject`, `setStashVisibility`, and `continueProject` returning result objects to `ResearchWorkspace`.

- [ ] **Step 1: Write a failing durable-write test**

```js
test('a failed durable transition write does not return replacement projects', () => {
  const storage = { setItem(){ throw new Error('quota denied'); } };
  const transition = { ok:true, project:{ id:'p1', status:'stashed' } };
  const result = context.wsPersistProjectTransition(storage, 'uri.demo', {
    projects:[{ id:'p1', status:'active' }], shelf:[],
  }, transition);
  assert.equal(result.ok, false);
  assert.match(result.error, /quota denied|save/i);
  assert.equal(result.projects, undefined);
});
```

- [ ] **Step 2: Run the durable-write test and verify RED**

Run: `node --test --test-name-pattern="failed durable" tests/workspace-lifecycle-graph.test.cjs`

Expected: FAIL because the persistence helper is missing.

- [ ] **Step 3: Implement an atomic browser-storage boundary**

```js
function wsPersistProjectTransition(storage, key, appState, transition){
  if (!transition || !transition.ok) return transition || { ok:false, error:'Project transition failed.' };
  const current = appState.projects || [];
  let projects;
  if (transition.sourceProject) projects = [...current, transition.project];
  else projects = current.map(project => project.id === transition.project.id ? transition.project : project);
  try {
    storage.setItem(key, JSON.stringify({ ...appState, projects }));
    return { ...transition, projects };
  } catch (error) {
    return { ok:false, error:'Could not save this project change locally: ' + error.message };
  }
}
```

- [ ] **Step 4: Run the durable-write test and verify GREEN**

Run: `node --test --test-name-pattern="failed durable" tests/workspace-lifecycle-graph.test.cjs`

Expected: PASS.

- [ ] **Step 5: Wire explicit callbacks through `App`**

Change `saveState` to return `{ ok:true }` or `{ ok:false, error }` while existing effect callers may ignore the result. Add `appSnapshot(peopleProjects)` and `commitTransition(transition, assignmentKey)` closures using the current `projects`, `shelf`, `nudged`, `checked`, `briefsMade`, `shared`, `profiles`, `tourDone`, `me`, and `view` values. When continuing, place the prospective assignment in the persisted snapshot but mutate the global demo person only after the write succeeds.

Add:

```js
function currentPeopleProjects(){
  const value = {};
  PEOPLE.forEach(person => { if (person.projects) value[person.k] = [...person.projects]; });
  return value;
}

function appSnapshot(peopleProjects){
  return { projects, shelf, nudged, checked, briefsMade, shared, profiles, tourDone,
    meKey:me.k, view, peopleProjects };
}

function commitTransition(transition, assignmentKey){
  if (!transition.ok) return transition;
  const peopleProjects = currentPeopleProjects();
  if (assignmentKey) peopleProjects[assignmentKey] = [...new Set([...(peopleProjects[assignmentKey] || []), transition.project.id])];
  const persisted = wsPersistProjectTransition(localStorage, STORE, appSnapshot(peopleProjects), transition);
  if (!persisted.ok) return persisted;
  if (assignmentKey) {
    const person = byKey(assignmentKey);
    if (person) person.projects = peopleProjects[assignmentKey];
  }
  setProjects(persisted.projects);
  return persisted;
}

const stashProject = (project, form) => commitTransition(wsStashProject(project, {
  ...form, actorKey:me.k, now:new Date().toISOString(),
}));
const resumeProject = project => commitTransition(wsResumeProject(project, {
  actorKey:me.k, now:new Date().toISOString(),
}));
const setStashVisibility = (project, visibility) => commitTransition(wsSetStashVisibility(project, {
  visibility, actorKey:me.k, now:new Date().toISOString(),
}));
const continueProject = project => {
  const transition = wsContinueProject(project, {
    newId:'continued-' + Date.now().toString(36),
    newCode:project.code + '-C' + (projects.filter(item => item.continuedFrom === project.id).length + 1),
    actor:me, now:new Date().toISOString(),
  });
  return commitTransition(transition, me.k);
};
```

Pass these as `onStash`, `onResume`, `onSetStashVisibility`, and `onContinue` props to `ResearchWorkspace`. Select the new project only after `continueProject` returns `{ ok:true }`.

- [ ] **Step 6: Run the focused domain tests, build, and commit**

Run:

```powershell
node --test tests/workspace-lifecycle-graph.test.cjs
node build/build.js
```

Expected: tests PASS; build exits 0.

Commit:

```powershell
git add src/workspace-domain.jsx src/uri.html tests/workspace-lifecycle-graph.test.cjs index.html
git commit -m "Persist project lifecycle changes safely"
```

---

### Task 4: Unified workspace and project navigation

**Files:**

- Modify: `src/workspace.jsx:3-18,309-321,618-735`
- Modify: `src/workspace.css:96-280,650-780,2110-2430`
- Modify: `tests/workspace-domain.test.cjs`

**Interfaces:**

- Consumes: `WS_NAV`, `WS_PROJECT_TABS`, accessible active/stashed project buckets, and existing `navigate`/`openProject` state setters.
- Produces: `WsHeader`, `WsWorkspaceTabs`, and `WsProjectContext`; workspace section `map`; stable project selection across workspace tools.

- [ ] **Step 1: Write a failing navigation-state test**

Extend the existing test to prove Map is restorable and the new registries expose consistent labels:

```js
test('map is a supported workspace destination', () => {
  memory.set('uri.workspace.test', JSON.stringify({ section:'map', selectedProjectId:'p1', projectTab:'record' }));
  const state = context.wsReadState('test');
  assert.equal(state.section, 'map');
  assert.equal(state.selectedProjectId, 'p1');
  assert.equal(vm.runInContext("WS_NAV.some(item => item[0] === 'map')", context), true);
  assert.equal(context.wsWorkspaceNavKey('project'), 'projects');
});
```

- [ ] **Step 2: Run the navigation test and verify RED**

Run: `node --test --test-name-pattern="map is a supported" tests/workspace-domain.test.cjs`

Expected: FAIL because `map` is not in `WS_NAV`.

- [ ] **Step 3: Add Map and extract navigation components**

Add `['map', 'Map']` before Discover. Implement components with native buttons:

```jsx
function wsWorkspaceNavKey(section){
  return section === 'project' ? 'projects' : section;
}

function WsWorkspaceTabs({ section, onNavigate }){
  const activeKey = wsWorkspaceNavKey(section);
  return <nav className="ws-workspace-tabs" aria-label="Workspace sections">
    {WS_NAV.map(([key, label]) => <button type="button" key={key}
      className={'ws-tab' + (activeKey === key ? ' is-active' : '')}
      aria-current={activeKey === key ? 'page' : undefined}
      onClick={() => onNavigate(key)}>{label}</button>)}
  </nav>;
}

function WsProjectContext({ project, projectTab, onTab, onProjects }){
  if (!project) return null;
  return <div className="ws-project-context">
    <div className="ws-breadcrumb"><button type="button" className="ws-link" onClick={onProjects}>Projects</button><span aria-hidden="true">/</span><strong>{project.name}</strong></div>
    <div className="ws-tabs" role="tablist" aria-label="Project sections">
      {WS_PROJECT_TABS.map(([key, label]) => <button type="button" role="tab"
        aria-selected={projectTab === key} className={'ws-tab' + (projectTab === key ? ' is-active' : '')}
        key={key} onClick={() => onTab(key)}>{label}</button>)}
    </div>
  </div>;
}

function WsProjectPicker({ projects, selectedId, onSelect, label }){
  if (!projects.length) return null;
  const buckets = wsProjectBuckets(projects);
  return <label className="ws-field ws-project-picker">
    <span>{label || 'Current project'}</span>
    <select className="ws-select" value={selectedId || ''} onChange={event => onSelect(event.target.value)}>
      {!!buckets.active.length && <optgroup label="Active projects">
        {buckets.active.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </optgroup>}
      {!!buckets.stashed.length && <optgroup label="Stashed projects">
        {buckets.stashed.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </optgroup>}
    </select>
  </label>;
}
```

`WsHeader` contains the brand, grouped project picker, and identity picker. Remove the desktop project list and workspace sidebar. Render `WsWorkspaceTabs` persistently above `<main>` and `WsProjectContext` only for `section === 'project'`.

- [ ] **Step 4: Replace smooth global scrolling with immediate content focus**

Change workspace navigation to call `window.scrollTo(0, 0)` after section changes. Do not use `behavior:'smooth'`. Preserve `projectTab` when switching projects and keep the selected project as the initial scope for Evidence, Reviews, Handoffs, and Map.

- [ ] **Step 5: Implement the responsive tab rails**

Use a sticky white header, one-pixel gray rules, 44-pixel tab targets, scarlet selected underline, visible `:focus-visible`, `overflow-x:auto`, and right-edge fade cue. Remove obsolete sidebar spacing and menu-drawer CSS. Add a 390-pixel rule that wraps header controls without hiding labels.

- [ ] **Step 6: Run navigation tests and the build**

Run:

```powershell
node --test tests/workspace-domain.test.cjs
node build/build.js
```

Expected: navigation tests PASS and build exits 0.

- [ ] **Step 7: Commit the unified shell**

```powershell
git add src/workspace.jsx src/workspace.css tests/workspace-domain.test.cjs index.html
git commit -m "Unify workspace and project navigation"
```

---

### Task 5: Two-dimensional research source map UI

**Files:**

- Modify: `src/workspace.jsx:194-321,583-617,618-735`
- Modify: `src/workspace.css`
- Modify: `tests/workspace-lifecycle-graph.test.cjs`
- Create: `tests/workspace-ui.test.cjs`

**Interfaces:**

- Consumes: `wsBuildResearchGraph`, `wsFilterResearchGraph`, `wsLayoutResearchGraph`, current accessible projects, and current research revisions read through `wsResearchRead`.
- Produces: `WsResearchMap({ projects, me, selectedProjectId, onScopeChange, onOpenProject })` plus an SVG view and equivalent relationship list.

- [ ] **Step 1: Write a failing map-accessibility source contract test**

The app has no DOM test dependency, so compile the JSX and assert the component contract plus accessible alternative explicitly:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Babel = require('../build/vendor/babel.js');

const source = fs.readFileSync(path.join(__dirname, '../src/workspace.jsx'), 'utf8');
const compiled = Babel.transform(source, { presets:[['react', { runtime:'classic' }]] }).code;

test('map view includes an SVG description and equivalent relationship list', () => {
  assert.match(compiled, /function WsResearchMap/);
  assert.match(compiled, /aria-label.*research source map/i);
  assert.match(compiled, /Map relationships/);
});
```

- [ ] **Step 2: Run the map UI contract and verify RED**

Run: `node --test tests/workspace-ui.test.cjs`

Expected: FAIL because `WsResearchMap` does not exist.

- [ ] **Step 3: Implement map state, graph reading, and filters**

`WsResearchMap` initializes scope to `selectedProjectId || 'all'`, reads `uri.research.v1` with `wsResearchRead`, obtains current items for every accessible project with `wsResearchCurrent`, and falls back to project records plus a visible warning when research storage is unavailable.

Use state for `scope`, `query`, `types`, `selectedNodeId`, and `showPending`. The Show pending control renders only for PI/PhD identities and defaults off. Type filter buttons use `aria-pressed`.

```jsx
function WsResearchMap({ projects, me, selectedProjectId, onScopeChange, onOpenProject }){
  const [scope, setScope] = useState(selectedProjectId || 'all');
  const [query, setQuery] = useState('');
  const [types, setTypes] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [showPending, setShowPending] = useState(false);
  const researchRead = useMemo(() => {
    const storage = wsResearchBrowserStorage(window);
    return storage.ok ? wsResearchRead(storage.storage) : { state:wsResearchEmpty(), error:storage.error };
  }, [projects]);
  const researchItems = useMemo(() => projects.flatMap(project =>
    wsResearchCurrent(researchRead.state, project.id)), [projects, researchRead.state]);
  const graph = useMemo(() => wsBuildResearchGraph(projects, researchItems, {
    includePending:showPending && ['pi', 'phd'].includes(me.tier),
  }), [projects, researchItems, showPending, me.tier]);
  const visible = useMemo(() => wsFilterResearchGraph(graph, { scope, query, types }),
    [graph, scope, query, types]);
  const positioned = useMemo(() => wsLayoutResearchGraph(visible, 960, 560), [visible]);
  const changeScope = value => {
    setScope(value);
    setSelectedNodeId('');
    onScopeChange(value);
  };
  return <section className="ws-map-view">
    <WsPageHead eyebrow="Recorded provenance" title="Research source map"
      subtitle="Projects and the explicit sources, records, and research items connected to them." />
    <div className="ws-map-controls">
      <label className="ws-field"><span>Scope</span><select className="ws-select" value={scope}
        onChange={event => changeScope(event.target.value)}><option value="all">All lab</option>
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      <label className="ws-field"><span>Search map</span><input className="ws-input" value={query}
        onChange={event => setQuery(event.target.value)} /></label>
    </div>
    {researchRead.error && <div className="ws-alert" role="status">{researchRead.error} Project record nodes remain available.</div>}
  </section>;
}
```

- [ ] **Step 4: Implement SVG and accessible list**

Render edges first and nodes second. Each node is a focusable `<button>` outside SVG only if browser SVG button semantics are unreliable; otherwise use `<g role="button" tabIndex="0">` with Enter/Space handlers. Keep labels short on the canvas and put the full label in `<title>`.

```jsx
function wsMapShortLabel(label){
  const value = String(label || 'Untitled');
  return value.length > 24 ? value.slice(0, 23) + '...' : value;
}

function wsEdgeSentence(edge, nodes){
  const byId = new Map(nodes.map(node => [node.id, node]));
  const source = byId.get(edge.source);
  const target = byId.get(edge.target);
  return (source ? source.label : edge.source) + ': ' + edge.label + ' -> ' + (target ? target.label : edge.target);
}

const pointById = new Map(positioned.map(node => [node.id, node]));
const edgeCoordinates = edge => {
  const source = pointById.get(edge.source);
  const target = pointById.get(edge.target);
  return { x1:source.x, y1:source.y, x2:target.x, y2:target.y };
};
const activateNode = (event, nodeId) => {
  if (event.type === 'click' || event.key === 'Enter' || event.key === ' ') {
    if (event.key === ' ') event.preventDefault();
    setSelectedNodeId(nodeId);
  }
};

<svg viewBox="0 0 960 560" role="img" aria-label="Two-dimensional research source map">
  <desc>Projects and their explicitly recorded evidence, research, artifact, and source connections.</desc>
  {visible.edges.map(edge => <line key={edge.id} {...edgeCoordinates(edge)} />)}
  {positioned.map(node => <g key={node.id} role="button" tabIndex="0" aria-label={node.label}
    transform={'translate(' + node.x + ',' + node.y + ')'}
    onClick={event => activateNode(event, node.id)} onKeyDown={event => activateNode(event, node.id)}>
    <title>{node.label}</title>
    <circle r={node.type === 'project' ? 15 : 9} />
    <text y="24" textAnchor="middle">{wsMapShortLabel(node.label)}</text>
  </g>)}
</svg>
<details className="ws-map-list">
  <summary>Map relationships</summary>
  <ul>{visible.edges.map(edge => <li key={edge.id}>{wsEdgeSentence(edge, visible.nodes)}</li>)}</ul>
</details>
```

The selected-node panel lists every incident edge label and provides `Open project`, `Open record`, or `Open research` based on `node.target`.

- [ ] **Step 5: Add map styling and dense/mobile behavior**

Use the pale grid field already present in the workspace, charcoal project hubs, gray source nodes, blue research nodes, and scarlet selected paths. Avoid animated layout. At 390 pixels, keep the SVG horizontally scrollable with a 720-pixel minimum width and place the detail panel below it. Respect `prefers-reduced-motion`.

- [ ] **Step 6: Render Map from the workspace route and project deep links**

For `section === 'map'`, render `WsResearchMap`. Add an `Open source map` action to project Overview that calls a new `openMap(project.id)` helper, sets `selectedProjectId`, and navigates to Map. Map scope changes update `selectedProjectId` only when the scope is a project.

- [ ] **Step 7: Run map domain/UI tests and build**

Run:

```powershell
node --test tests/workspace-lifecycle-graph.test.cjs tests/workspace-ui.test.cjs
node build/build.js
```

Expected: tests PASS; build exits 0.

- [ ] **Step 8: Commit the map interface**

```powershell
git add src/workspace.jsx src/workspace.css tests/workspace-lifecycle-graph.test.cjs tests/workspace-ui.test.cjs index.html
git commit -m "Add the research source map"
```

---

### Task 6: Stash, resume, share, continue, and read-only UI

**Files:**

- Modify: `src/workspace.jsx:321-489,548-617,618-735`
- Modify: `src/workspace-evidence.jsx`
- Modify: `src/workspace-research-domain.jsx`
- Modify: `src/workspace-research.jsx:270-540`
- Modify: `src/workspace.css`
- Modify: `tests/evidence-domain.test.cjs`
- Modify: `tests/research-domain.test.cjs`
- Modify: `tests/workspace-ui.test.cjs`

**Interfaces:**

- Consumes: `onStash`, `onResume`, `onSetStashVisibility`, `onContinue`, `wsIsStashed`, `wsCanManageProject`, and current project lifecycle metadata.
- Produces: `WsStashProject`, `WsStashedBanner`, Projects Active/Stashed filters, Discover continuation cards, and enforced research/evidence read-only behavior.

- [ ] **Step 1: Write a failing research permission test for stashed projects**

Add to `tests/research-domain.test.cjs` using the existing `me`, `project`, and valid item fixtures:

```js
test('stashed and archived projects are read only for every role', () => {
  const item = { authorKey:me.k, projectId:project.id };
  assert.equal(context.wsResearchCanEdit(item, { ...me, tier:'pi' }, { ...project, status:'stashed' }), false);
  assert.equal(context.wsResearchCanEdit(item, { ...me, tier:'pi' }, { ...project, status:'archived' }), false);
});
```

- [ ] **Step 2: Run the permission test and verify RED**

Run: `node --test --test-name-pattern="projects are read only" tests/research-domain.test.cjs`

Expected: FAIL because project status is not checked.

- [ ] **Step 3: Enforce read-only status in research domain and UI**

Make `wsResearchCanEdit` return false before other permission checks when project status is `stashed` or `archived`. Add `readOnly` to `ResearchProjectWorkspace`; when true, render exports and existing data but do not render create buttons/forms or Edit actions. Show a `WsBadge` reading `Read only`.

- [ ] **Step 4: Run the permission test and verify GREEN**

Run: `node --test --test-name-pattern="projects are read only" tests/research-domain.test.cjs`

Expected: PASS.

- [ ] **Step 5: Write a failing evidence read-only test**

Add to `tests/evidence-domain.test.cjs`:

```js
test('evidence writes are blocked for project IDs marked read only', () => {
  assert.equal(context.wsEvidenceCanWriteProject('p1', ['p1']), false);
  assert.equal(context.wsEvidenceCanWriteProject('p1', ['p2']), true);
});
```

- [ ] **Step 6: Run the evidence read-only test and verify RED**

Run: `node --test --test-name-pattern="evidence writes are blocked" tests/evidence-domain.test.cjs`

Expected: FAIL because `wsEvidenceCanWriteProject` is missing.

- [ ] **Step 7: Enforce read-only evidence behavior**

Add the helper and use it in every mutation predicate:

```jsx
function wsEvidenceCanWriteProject(projectId, readOnlyProjectIds){
  return !new Set(readOnlyProjectIds || []).has(projectId);
}

const activeProjectReadOnly = !wsEvidenceCanWriteProject(activeProject.id, readOnlyProjectIds);
const editable = !activeProjectReadOnly && record.authorKey === me.k && record.status !== 'published';
const canActAsReviewer = !activeProjectReadOnly && reviewer && record.authorKey !== me.k && record.status === 'pending';
```

Add `readOnlyProjectIds` to `EvidenceWorkspace`. Guard `startManualRecord`, upload analysis, authored-record updates, review requests, reviewer actions, and publication with an early read-only error even when no control currently exposes the function. For a stashed project, hide Write and Upload tabs but keep Drafts, published records, sources, and review history inspectable. Label the view `Read-only project archive`.

In `ResearchWorkspace`, pass every accessible project to workspace-level Evidence and Reviews together with `readOnlyProjectIds={accessibleProjects.filter(wsIsStashed).map(project => project.id)}`. In the project Evidence tab, hide Add evidence for stashed projects. In Overview, replace Add evidence with Export archive and Open map. This removes write entry points without hiding existing draft or source history.

- [ ] **Step 8: Run the evidence read-only test and verify GREEN**

Run: `node --test --test-name-pattern="evidence writes are blocked" tests/evidence-domain.test.cjs`

Expected: PASS.

- [ ] **Step 9: Write a failing stash UI contract test**

Append to `tests/workspace-ui.test.cjs`:

```js
test('workspace exposes stash confirmation and reversible lifecycle actions', () => {
  assert.match(compiled, /function WsStashProject/);
  assert.match(compiled, /Why did this project stop/);
  assert.match(compiled, /Resume project/);
  assert.match(compiled, /Continue project/);
  assert.match(compiled, /Browser-local sharing prototype/);
});
```

- [ ] **Step 10: Run the stash UI contract and verify RED**

Run: `node --test --test-name-pattern="stash confirmation" tests/workspace-ui.test.cjs`

Expected: FAIL because lifecycle UI is not rendered.

- [ ] **Step 11: Implement stash confirmation and read-only banner**

`WsStashProject` owns reason, next step, visibility, error text, and focus refs. It calls `onStash(project, form)`, keeps the form open on `{ ok:false }`, and closes only on success. Use an inline confirmation panel rather than `window.confirm` so consequences and validation are accessible.

```jsx
function WsStashProject({ project, onStash, onCancel }){
  const [form, setForm] = useState({ reason:'', nextStep:'', visibility:'private' });
  const [error, setError] = useState('');
  const reasonRef = useRef(null);
  const nextStepRef = useRef(null);
  const submit = event => {
    event.preventDefault();
    const result = onStash(project, form);
    if (!result.ok) {
      setError(result.error);
      const target = result.errorField === 'nextStep' ? nextStepRef.current : reasonRef.current;
      requestAnimationFrame(() => target && target.focus());
      return;
    }
    onCancel();
  };
  return <form className="ws-panel ws-stash-form" onSubmit={submit} noValidate>
    <h2>Stash this project</h2>
    <p>The project becomes read only. Its records, evidence, research history, and exports remain available.</p>
    {error && <div className="ws-alert ws-alert-danger" role="alert">{error}</div>}
    <label className="ws-field"><span>Why did this project stop?</span><textarea ref={reasonRef} className="ws-textarea"
      value={form.reason} onChange={event => setForm({ ...form, reason:event.target.value })} /></label>
    <label className="ws-field"><span>Recommended next step</span><textarea ref={nextStepRef} className="ws-textarea"
      value={form.nextStep} onChange={event => setForm({ ...form, nextStep:event.target.value })} /></label>
    <label className="ws-field"><span>Visibility</span><select className="ws-select" value={form.visibility}
      onChange={event => setForm({ ...form, visibility:event.target.value })}>
      <option value="private">Private to assigned researchers</option><option value="lab">Discoverable in this lab demo</option>
    </select></label>
    <div className="ws-actions"><button type="button" className="ws-button ws-button-quiet" onClick={onCancel}>Cancel</button>
      <button type="submit" className="ws-button ws-button-danger">Stash project</button></div>
  </form>;
}
```

`WsStashedBanner` displays:

- `stashReason || archiveNote || 'This project is paused.'`;
- `stashNextStep` or the latest approved next-step entry;
- stashed/archived date and actor when available;
- Export archive and Open map for all authorized readers;
- Resume only when `wsCanManageProject` is true;
- Browser-local sharing control only when manageable.

The sharing control calls `onSetStashVisibility(project, nextVisibility)` and updates its label only after `{ ok:true }`. Storage errors remain visible in the banner.

- [ ] **Step 12: Add Active/Stashed project filters and Discover continuation**

`WsProjects` defaults to Active and offers an accessible two-button segmented filter. Preserve the existing search within the chosen bucket. Stashed rows show the reason and next step.

Build `const projectBuckets = wsProjectBuckets(accessibleProjects)` once in `ResearchWorkspace`. Pass `projectBuckets.active` to Home and use its first item as the default project; keep all accessible projects in the grouped project selector, Map, Projects, and read-only archive views. If an identity has only stashed work, default to Projects > Stashed instead of selecting an inaccessible or editable project.

`WsDiscover` combines existing shelf items with stashed projects whose `stashVisibility === 'lab'`. Label card types clearly. A shared stashed project exposes Read archive and Continue project. On successful continuation, call `openProject(result.project.id)`; on failure, show the returned storage error in an alert.

Render `WsStashedBanner` directly below `WsProjectContext` so the read-only state and archive actions remain visible on every project tab. Render `WsStashProject` only from Settings and only when `wsCanManageProject(project, me)` is true.

- [ ] **Step 13: Add lifecycle styles**

Style the read-only banner with a gray left rule, the stash form with restrained scarlet danger emphasis, and the Active/Stashed control using the same underline/tab grammar. Stashed badges and map nodes must remain readable at WCAG AA contrast. Keep controls usable at 390 pixels.

- [ ] **Step 14: Run focused tests, full tests, and build**

Run:

```powershell
node --test tests/research-domain.test.cjs tests/evidence-domain.test.cjs tests/workspace-ui.test.cjs
node --test tests/*.test.cjs
node build/build.js
```

Expected: focused tests PASS; full suite has zero failures; build exits 0.

- [ ] **Step 15: Commit the complete lifecycle UI**

```powershell
git add src/workspace.jsx src/workspace-evidence.jsx src/workspace-research-domain.jsx src/workspace-research.jsx src/workspace.css tests/evidence-domain.test.cjs tests/research-domain.test.cjs tests/workspace-ui.test.cjs index.html
git commit -m "Add reversible project stashing"
```

---

### Task 7: Documentation and end-to-end offline verification

**Files:**

- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/PRODUCT_FLOW.md`
- Modify: `docs/UX_BLUEPRINT.md`
- Create: `docs/screenshots/navigation-unified-desktop.png`
- Create: `docs/screenshots/navigation-unified-mobile.png`
- Create: `docs/screenshots/source-map-desktop.png`
- Create: `docs/screenshots/stashed-project-desktop.png`
- Modify: `index.html`

**Interfaces:**

- Consumes: the completed workspace UI and all automated tests.
- Produces: current documentation, visual evidence, and a verified self-contained build.

- [ ] **Step 1: Update product and implementation documentation**

Document the persistent workspace/project rails, Map scope and provenance limitation, stash/resume/continue lifecycle, browser-local sharing limitation, read-only enforcement, storage keys, exports, and future GraphRAG adapter boundary. Mark live GraphRAG, real sharing, authentication, and server authorization as not implemented.

- [ ] **Step 2: Run fresh complete automated verification**

Run:

```powershell
node --test tests/*.test.cjs
node build/build.js
```

Expected: every test passes with zero failures and build exits 0 with pure ASCII and zero external requests.

- [ ] **Step 3: Start the local production server**

Run: `node build/serve.js`

Expected: server listens at `http://127.0.0.1:4173` and serves rebuilt `index.html`.

- [ ] **Step 4: Verify desktop navigation and map in the browser**

At a 1280-pixel-wide viewport:

1. Open the production URL without `?legacy=1`.
2. Confirm workspace tabs remain present on Home, Projects, Map, and an open project.
3. Open two projects and confirm the current project tab is preserved.
4. Confirm no smooth-scroll delay, horizontal overflow, console error, or external request.
5. Open Map in All lab scope, then select one project.
6. Search for an explicit source, select its node, confirm its edge explanations, open its target, and inspect the list alternative.
7. Capture `navigation-unified-desktop.png` and `source-map-desktop.png`.

- [ ] **Step 5: Verify the stash lifecycle in the browser**

Using an authorized PI/PhD demo identity:

1. Open an active project and Settings.
2. Confirm blank reason and blank next step are rejected with focused error fields.
3. Stash the project with a reason, next step, and lab visibility.
4. Refresh and confirm it remains stashed and read-only.
5. Confirm it is absent from Home's active list, present under Projects > Stashed, muted but connected on Map, and listed in Discover.
6. Confirm archive Markdown and research exports remain available.
7. Continue the project as another internal researcher and confirm the new active project links to the unchanged source project.
8. Resume the source project and confirm its prior stash metadata remains visible in lifecycle history.
9. Capture `stashed-project-desktop.png`.

- [ ] **Step 6: Verify keyboard, reduced motion, and 390-pixel layout**

At 390 pixels:

1. Traverse both tab rails, project selector, map filters, SVG/list alternative, stash form, and lifecycle actions using only the keyboard.
2. Confirm visible focus and 44-pixel targets.
3. Confirm horizontal tab/map scrolling is discoverable and page content does not overflow.
4. Enable reduced motion and confirm no nonessential animation remains.
5. Capture `navigation-unified-mobile.png`.

- [ ] **Step 7: Reset browser-local demo data and repeat the smoke path**

Use the existing prototype reset action or clear only the URI prototype storage keys, reload, and confirm seeded projects, navigation, Map, Evidence, Reviews, Handoffs, Research, and legacy `?legacy=1` still open without errors.

- [ ] **Step 8: Review the final diff and commit verification artifacts**

Run:

```powershell
git diff --check
git status --short
git diff --stat HEAD~4..HEAD
```

Confirm `URI_Executive_Summary.pdf` is still untracked and excluded.

Commit:

```powershell
git add docs/IMPLEMENTATION_STATUS.md docs/PRODUCT_FLOW.md docs/UX_BLUEPRINT.md docs/screenshots/navigation-unified-desktop.png docs/screenshots/navigation-unified-mobile.png docs/screenshots/source-map-desktop.png docs/screenshots/stashed-project-desktop.png index.html
git commit -m "Document the unified research workspace"
```

- [ ] **Step 9: Run the final completion gate after the last commit**

Run:

```powershell
node --test tests/*.test.cjs
node build/build.js
git status --short
```

Expected: all tests pass, build exits 0, and the only unrelated path shown by status is the user's untracked `URI_Executive_Summary.pdf`.
