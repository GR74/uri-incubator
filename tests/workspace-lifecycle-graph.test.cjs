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
  assert.deepEqual(plain(context.wsValidateStash({ reason:'', nextStep:'' })), {
    ok:false,
    error:'Record why this project stopped.',
    errorField:'reason',
  });
  assert.equal(context.wsValidateStash({ reason:'Paused', nextStep:'  ' }).errorField, 'nextStep');
  assert.deepEqual(plain(context.wsValidateStash({ reason:' Paused ', nextStep:' Resume assay ', visibility:'lab' })), {
    ok:true,
    value:{ reason:'Paused', nextStep:'Resume assay', visibility:'lab' },
  });
});

test('stash records lifecycle metadata without mutating the active project', () => {
  const original = { id:'p1', code:'URI-1', name:'Project', status:'active', log:[] };
  const result = context.wsStashProject(original, {
    reason:'Instrument unavailable',
    nextStep:'Book the replacement rig',
    visibility:'lab',
    actorKey:'mentor',
    now:'2026-09-09T12:00:00.000Z',
  });
  assert.equal(result.ok, true);
  assert.equal(original.status, 'active');
  assert.equal(result.project.status, 'stashed');
  assert.equal(result.project.stashReason, 'Instrument unavailable');
  assert.deepEqual(plain(result.project.lifecycle), [{
    action:'stashed', actorKey:'mentor', at:'2026-09-09T12:00:00.000Z',
  }]);
});

test('resume and visibility changes preserve the recorded stash history', () => {
  const stashed = {
    id:'p1', status:'stashed', stashReason:'Paused', stashVisibility:'private',
    lifecycle:[{ action:'stashed', actorKey:'mentor', at:'2026-09-09T12:00:00.000Z' }],
  };
  const shared = context.wsSetStashVisibility(stashed, {
    visibility:'lab', actorKey:'mentor', now:'2026-09-09T13:00:00.000Z',
  });
  const resumed = context.wsResumeProject(shared.project, {
    actorKey:'mentor', now:'2026-09-10T12:00:00.000Z',
  });
  assert.equal(stashed.stashVisibility, 'private');
  assert.equal(shared.project.stashVisibility, 'lab');
  assert.equal(resumed.project.status, 'active');
  assert.equal(resumed.project.stashReason, 'Paused');
  assert.deepEqual(plain(resumed.project.lifecycle.map(item => item.action)), ['stashed', 'shared', 'resumed']);
});

test('project buckets treat archived records as stashed', () => {
  const buckets = context.wsProjectBuckets([
    { id:'a', status:'active' },
    { id:'b', status:'archived' },
    { id:'c', status:'stashed' },
  ]);
  assert.deepEqual(plain(buckets.active.map(item => item.id)), ['a']);
  assert.deepEqual(plain(buckets.stashed.map(item => item.id)), ['b', 'c']);
});

test('continue creates a linked active project without changing the stashed source', () => {
  const source = {
    id:'p1', code:'URI-1', name:'Project', oneLine:'Aim', status:'stashed',
    stashReason:'Paused', artifacts:[{ n:'Protocol' }], log:[{ id:'old' }],
  };
  const result = context.wsContinueProject(source, {
    newId:'p2', newCode:'URI-1-C1',
    actor:{ k:'student', n:'Student', s:'S. Student', i:'ST', line:'Researcher' },
    now:'2026-09-09T12:00:00.000Z',
  });
  assert.equal(result.ok, true);
  assert.equal(source.status, 'stashed');
  assert.equal(result.project.status, 'active');
  assert.equal(result.project.continuedFrom, 'p1');
  assert.equal(result.project.stashReason, undefined);
  assert.notEqual(result.project.artifacts, source.artifacts);
  assert.deepEqual(plain(result.project.log.map(entry => entry.id)), ['p2-origin']);
  assert.match(result.project.log[0].b, /URI-1/);
});

test('only project managers can change lifecycle state', () => {
  const project = { id:'p1' };
  assert.equal(context.wsCanManageProject(project, { tier:'pi', scope:'all' }), true);
  assert.equal(context.wsCanManageProject(project, { tier:'phd', projects:['p1'] }), true);
  assert.equal(context.wsCanManageProject(project, { tier:'ug', projects:['p1'] }), false);
  assert.equal(context.wsCanManageProject(project, { tier:'phd', projects:['p2'] }), false);
});

test('graph contains approved records, artifacts, and explicit source relationships', () => {
  const projects = [{
    id:'p1', code:'URI-1', name:'Project', oneLine:'Aim', status:'active',
    artifacts:[{ n:'Protocol A', d:'SOP-12' }],
    log:[
      { id:'e1', t:'result', h:'Approved result', b:'Observed', ack:true, source:'dataset.csv' },
      { id:'e2', t:'method', h:'Pending method', b:'Draft', ack:false },
    ],
  }];
  const research = [{
    id:'m1', projectId:'p1', kind:'measurement', title:'Yield', status:'completed',
    sourceEntryId:'e1', notes:'Recorded measurement',
  }];
  const graph = context.wsBuildResearchGraph(projects, research, {});
  assert.equal(graph.nodes.some(node => node.id === 'entry:p1:e1'), true);
  assert.equal(graph.nodes.some(node => node.id === 'entry:p1:e2'), false);
  assert.equal(graph.nodes.some(node => node.type === 'artifact' && node.label === 'Protocol A'), true);
  assert.equal(graph.nodes.some(node => node.type === 'source' && node.label === 'dataset.csv'), true);
  assert.equal(graph.edges.some(edge => edge.type === 'supported-by' && edge.source === 'research:p1:m1'), true);
  assert.equal(graph.warnings.length, 0);
});

test('graph reports unresolved explicit research references without crashing', () => {
  const graph = context.wsBuildResearchGraph([
    { id:'p1', code:'P1', name:'One', status:'active', log:[] },
  ], [{ id:'m1', projectId:'p1', title:'Yield', sourceEntryId:'missing' }], {});
  assert.equal(graph.nodes.some(node => node.id === 'research:p1:m1'), true);
  assert.equal(graph.edges.some(edge => edge.type === 'supported-by'), false);
  assert.match(graph.warnings[0], /unresolved/i);
});

test('graph filtering keeps the selected project and its shared source neighbors', () => {
  const graph = context.wsBuildResearchGraph([
    { id:'p1', code:'P1', name:'One', status:'active', log:[{ id:'a', t:'result', h:'A', ack:true, source:'shared.csv' }] },
    { id:'p2', code:'P2', name:'Two', status:'stashed', log:[{ id:'b', t:'decision', h:'B', ack:true, source:'shared.csv' }] },
  ], [], {});
  const filtered = context.wsFilterResearchGraph(graph, { scope:'p2', query:'', types:[] });
  assert.equal(filtered.nodes.some(node => node.id === 'project:p1'), false);
  assert.equal(filtered.nodes.some(node => node.label === 'shared.csv'), true);
  assert.equal(filtered.nodes.find(node => node.id === 'project:p2').status, 'stashed');
  const searched = context.wsFilterResearchGraph(graph, { scope:'all', query:'shared.csv', types:['source'] });
  assert.equal(searched.nodes.some(node => node.label === 'shared.csv'), true);
  assert.equal(searched.nodes.some(node => node.type === 'project'), false);
});

test('graph layout is deterministic and stays inside its viewport', () => {
  const graph = {
    nodes:[{ id:'b', type:'source' }, { id:'a', type:'project' }],
    edges:[{ id:'a-b', source:'a', target:'b', type:'uses', label:'Uses' }],
  };
  const first = context.wsLayoutResearchGraph(graph, 960, 560);
  const second = context.wsLayoutResearchGraph(graph, 960, 560);
  assert.deepEqual(plain(first), plain(second));
  assert.deepEqual(plain(first.map(node => node.id)), ['a', 'b']);
  assert.equal(first.every(node => node.x >= 28 && node.x <= 932 && node.y >= 28 && node.y <= 532), true);
});

test('durable project transition returns replacement projects only after storage succeeds', () => {
  let saved = '';
  const storage = { setItem(key, value){ saved = key + ':' + value; } };
  const transition = { ok:true, project:{ id:'p1', status:'stashed' } };
  const result = context.wsPersistProjectTransition(storage, 'uri.demo', {
    projects:[{ id:'p1', status:'active' }], shelf:[],
  }, transition);
  assert.equal(result.ok, true);
  assert.equal(result.projects[0].status, 'stashed');
  assert.match(saved, /^uri\.demo:/);
});

test('failed durable project transition does not expose unsaved projects', () => {
  const storage = { setItem(){ throw new Error('quota denied'); } };
  const transition = { ok:true, project:{ id:'p1', status:'stashed' } };
  const result = context.wsPersistProjectTransition(storage, 'uri.demo', {
    projects:[{ id:'p1', status:'active' }], shelf:[],
  }, transition);
  assert.equal(result.ok, false);
  assert.match(result.error, /quota denied|save/i);
  assert.equal(result.projects, undefined);
});
