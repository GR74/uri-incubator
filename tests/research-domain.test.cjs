const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src', 'workspace-research-domain.jsx'), 'utf8');
const context = vm.createContext({
  console,
  crypto: globalThis.crypto,
  Date,
  JSON,
  Math,
});
vm.runInContext(source, context);

const people = [
  { k: 'student', n: 'Student, One', s: 'S. One', tier: 'ug', projects: ['p1'] },
  { k: 'mentor', n: 'Mentor "Two"', s: 'M. Two', tier: 'phd', projects: ['p1'] },
  { k: 'other', n: 'Other Person', s: 'O. Person', tier: 'ug', projects: ['p2'] },
  { k: 'director', n: 'Director', s: 'Director', tier: 'pi', scope: 'all' },
  { k: 'alum', n: 'Former Member', s: 'F. Member', tier: 'alum', projects: ['p1'] },
  { k: 'partner', n: 'Partner', s: 'Partner', tier: 'partner', scope: 'all', projects: ['p1'] },
];
const student = people[0];
const mentor = people[1];
const project = {
  id: 'p1',
  log: [
    { id: 'approved', ack: true },
    { id: 'implicit-approved' },
    { id: 'pending', ack: false },
  ],
};
const now1 = '2026-09-08T12:00:00.000Z';
const now2 = '2026-09-08T13:00:00.000Z';

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function workInput(overrides = {}) {
  return {
    projectId: 'p1',
    kind: 'task',
    title: 'Prepare samples',
    ownerKey: 'student',
    status: 'planned',
    date: '2026-09-08',
    dueDate: '',
    notes: 'Use the written protocol.',
    sourceEntryId: '',
    experimentId: '',
    metric: '',
    value: null,
    unit: '',
    condition: '',
    ...overrides,
  };
}

function measurementInput(overrides = {}) {
  return workInput({
    kind: 'measurement',
    title: 'Buffer pH',
    status: 'completed',
    metric: 'pH',
    value: 7,
    unit: 'dimensionless',
    condition: 'room temperature',
    sourceEntryId: 'approved',
    ...overrides,
  });
}

function save(state, input, me = student, at = now1, selectedProject = project) {
  return context.wsResearchSave(state, input, me, selectedProject, people, at);
}

test('creates an empty versioned research state', () => {
  assert.deepEqual(plain(context.wsResearchEmpty()), { version: 1, revisions: [] });
});

test('appends immutable revisions and rejects a stale optimistic revision', () => {
  const empty = context.wsResearchEmpty();
  const created = save(empty, workInput());
  assert.equal(created.ok, true);
  assert.equal(created.item.revision, 1);
  assert.equal(created.item.authorKey, 'student');
  assert.equal(created.item.updatedBy, 'student');
  assert.equal(created.item.updatedAt, now1);
  assert.equal(empty.revisions.length, 0);

  const update = workInput({
    id: created.item.id,
    revision: 1,
    status: 'in_progress',
  });
  const updated = save(created.state, update, student, now2);
  assert.equal(updated.ok, true);
  assert.equal(updated.item.revision, 2);
  assert.equal(updated.item.status, 'in_progress');
  assert.equal(updated.state.revisions.length, 2);
  assert.equal(updated.state.revisions[0].status, 'planned');
  assert.notEqual(updated.state, created.state);
  assert.notEqual(updated.state.revisions, created.state.revisions);
  assert.equal(created.state.revisions.length, 1);

  const stale = save(updated.state, update, student, now2);
  assert.equal(stale.ok, false);
  assert.match(stale.error, /stale|revision/i);
});

test('validates complete contiguous revision chains and rejects hostile structures', () => {
  const first = save(context.wsResearchEmpty(), workInput()).state;
  const one = first.revisions[0];
  assert.equal(context.wsResearchValidate(first).ok, true);

  const cases = [
    null,
    { version: 1, revisions: {} },
    { version: 2, revisions: [] },
    { version: 1, revisions: [one, { ...one }] },
    { version: 1, revisions: [{ ...one, revision: 2 }] },
    { version: 1, revisions: [one, { ...one, revision: 3 }] },
    { version: 1, revisions: [one, { ...one, revision: 2, projectId: 'p2' }] },
    { version: 1, revisions: [one, { ...one, revision: 2, kind: 'experiment' }] },
    { version: 1, revisions: [one, { ...one, revision: 2, authorKey: 'mentor' }] },
    { version: 1, revisions: [{ ...one, title: { toString() { throw new Error('no coercion'); } } }] },
    { version: 1, revisions: [{ ...one, updatedAt: 'not-an-instant' }] },
  ];

  for (const value of cases) {
    assert.doesNotThrow(() => context.wsResearchValidate(value));
    assert.equal(context.wsResearchValidate(value).ok, false);
  }
});

test('returns only the latest project-scoped revision for each item', () => {
  const first = save(context.wsResearchEmpty(), workInput()).state;
  const item = first.revisions[0];
  const second = save(first, workInput({ id: item.id, revision: 1, status: 'blocked' }), student, now2).state;
  const other = {
    ...item,
    id: 'other-project-item',
    projectId: 'p2',
    title: 'Other project',
  };
  const state = { version: 1, revisions: [...second.revisions, other] };

  const current = context.wsResearchCurrent(state, 'p1');
  assert.equal(current.length, 1);
  assert.equal(current[0].revision, 2);
  assert.equal(current[0].status, 'blocked');
});

test('edit policy requires project access and author or PI/PhD reviewer status', () => {
  const item = save(context.wsResearchEmpty(), workInput()).item;
  assert.equal(context.wsResearchCanEdit(item, student, project), true);
  assert.equal(context.wsResearchCanEdit(item, mentor, project), true);
  assert.equal(context.wsResearchCanEdit(item, people[3], project), true);
  assert.equal(context.wsResearchCanEdit(item, people[4], project), false);
  assert.equal(context.wsResearchCanEdit(item, people[5], project), false);
  assert.equal(context.wsResearchCanEdit(item, people[2], project), false);
  assert.equal(context.wsResearchCanEdit(item, student, { ...project, id: 'p2' }), false);
});

test('assigned owners can update operational work but not another authors measurement', () => {
  const assignedTask = save(
    context.wsResearchEmpty(),
    workInput({ ownerKey: 'student' }),
    mentor
  ).item;
  const assignedMeasurement = save(
    context.wsResearchEmpty(),
    measurementInput({ ownerKey: 'student' }),
    mentor
  ).item;

  assert.equal(context.wsResearchCanEdit(assignedTask, student, project), true);
  assert.equal(context.wsResearchCanEdit(assignedMeasurement, student, project), false);
});

test('save rejects inaccessible projects and unauthorized edits', () => {
  const created = save(context.wsResearchEmpty(), workInput());
  const inaccessible = save(context.wsResearchEmpty(), workInput(), people[2]);
  assert.equal(inaccessible.ok, false);
  assert.match(inaccessible.error, /access/i);

  const update = workInput({ id: created.item.id, revision: 1, status: 'blocked' });
  const alumEdit = save(created.state, update, people[4]);
  assert.equal(alumEdit.ok, false);
  assert.match(alumEdit.error, /edit|author|permission/i);
});

test('date validation rejects calendar-invalid and malformed dates', () => {
  for (const date of ['', '2026-2-03', '2026-02-30', 'not-a-date']) {
    const result = save(context.wsResearchEmpty(), workInput({ date }));
    assert.equal(result.ok, false, date);
    assert.match(result.error, /date/i);
  }
  assert.equal(save(context.wsResearchEmpty(), workInput({ dueDate: '2026-02-30' })).ok, false);
  assert.equal(save(context.wsResearchEmpty(), workInput({ dueDate: '2026-09-30' })).ok, true);
});

test('save normalizes omitted optional references and due date to empty strings', () => {
  const input = workInput();
  delete input.dueDate;
  delete input.sourceEntryId;
  delete input.experimentId;
  const result = save(context.wsResearchEmpty(), input);
  assert.equal(result.ok, true);
  assert.equal(result.item.dueDate, '');
  assert.equal(result.item.sourceEntryId, '');
  assert.equal(result.item.experimentId, '');
});

test('measurement rejects blank or nonfinite values before coercion', () => {
  for (const value of ['', '   ', null, undefined, '0', NaN, Infinity, -Infinity]) {
    const result = save(context.wsResearchEmpty(), measurementInput({ value }));
    assert.equal(result.ok, false, String(value));
    assert.match(result.error, /value|number|finite/i);
  }
});

test('measurement accepts real zero and negative numeric values', () => {
  for (const value of [0, -2.5]) {
    const result = save(context.wsResearchEmpty(), measurementInput({ value }));
    assert.equal(result.ok, true, String(value));
    assert.equal(result.item.value, value);
  }
});

test('owner assignment requires an internal project member and permits alumni', () => {
  assert.equal(save(context.wsResearchEmpty(), workInput({ ownerKey: '' })).ok, true);
  assert.equal(save(context.wsResearchEmpty(), workInput({ ownerKey: 'alum' })).ok, true);
  assert.equal(save(context.wsResearchEmpty(), workInput({ ownerKey: 'director' })).ok, true);
  for (const ownerKey of ['other', 'partner', 'missing']) {
    const result = save(context.wsResearchEmpty(), workInput({ ownerKey }));
    assert.equal(result.ok, false, ownerKey);
    assert.match(result.error, /owner|member/i);
  }
});

test('measurement requires explicit metric, unit, condition, and approved source', () => {
  for (const field of ['metric', 'unit', 'condition', 'sourceEntryId']) {
    const result = save(context.wsResearchEmpty(), measurementInput({ [field]: '   ' }));
    assert.equal(result.ok, false, field);
    assert.match(result.error, new RegExp(field === 'sourceEntryId' ? 'source' : field, 'i'));
  }
  assert.equal(save(context.wsResearchEmpty(), measurementInput({ sourceEntryId: 'implicit-approved' })).ok, true);
  for (const sourceEntryId of ['pending', 'missing']) {
    const result = save(context.wsResearchEmpty(), measurementInput({ sourceEntryId }));
    assert.equal(result.ok, false, sourceEntryId);
    assert.match(result.error, /approved|source/i);
  }
});

test('optional source references also reject pending or missing evidence', () => {
  assert.equal(save(context.wsResearchEmpty(), workInput({ sourceEntryId: 'approved' })).ok, true);
  assert.equal(save(context.wsResearchEmpty(), workInput({ sourceEntryId: 'pending' })).ok, false);
  assert.equal(save(context.wsResearchEmpty(), workInput({ sourceEntryId: 'missing' })).ok, false);
});

test('experiment references require a current same-project experiment', () => {
  const experiment = save(context.wsResearchEmpty(), workInput({ kind: 'experiment', title: 'Run A' }));
  const linked = save(experiment.state, measurementInput({ experimentId: experiment.item.id }), student, now2);
  assert.equal(linked.ok, true);

  const task = save(context.wsResearchEmpty(), workInput());
  assert.equal(save(task.state, measurementInput({ experimentId: task.item.id }), student, now2).ok, false);

  const crossProjectExperiment = {
    ...experiment.item,
    id: 'p2-experiment',
    projectId: 'p2',
  };
  const mixedState = { version: 1, revisions: [crossProjectExperiment] };
  assert.equal(save(mixedState, measurementInput({ experimentId: 'p2-experiment' })).ok, false);
  assert.equal(save(context.wsResearchEmpty(), measurementInput({ experimentId: 'missing' })).ok, false);
});

test('storage read returns an error and never overwrites malformed persisted state', () => {
  let writes = 0;
  const malformedStorage = {
    getItem(key) {
      assert.equal(key, 'uri.research.v1');
      return '{broken json';
    },
    setItem() {
      writes += 1;
    },
  };
  const malformed = context.wsResearchRead(malformedStorage);
  assert.deepEqual(plain(malformed.state), { version: 1, revisions: [] });
  assert.match(malformed.error, /malformed|parse|stored/i);
  assert.equal(writes, 0);

  const absent = context.wsResearchRead({ getItem: () => null });
  assert.deepEqual(plain(absent), { state: { version: 1, revisions: [] }, error: null });

  const invalid = context.wsResearchRead({ getItem: () => '{"version":1,"revisions":[null]}' });
  assert.match(invalid.error, /invalid|revision|stored/i);

  const throwing = context.wsResearchRead({ getItem() { throw new Error('denied'); } });
  assert.match(throwing.error, /denied|storage/i);
});

test('summary separates tracked work from measurements and groups owner counts', () => {
  const items = [
    { ...workInput(), id: 'a', status: 'completed', ownerKey: 'student' },
    { ...workInput(), id: 'b', kind: 'experiment', status: 'blocked', ownerKey: 'student' },
    { ...workInput(), id: 'c', kind: 'milestone', status: 'in_progress', ownerKey: '' },
    { ...workInput(), id: 'd', status: 'planned', ownerKey: 'mentor' },
    { ...measurementInput(), id: 'm', ownerKey: 'mentor' },
  ];
  assert.deepEqual(plain(context.wsResearchSummary(items)), {
    workTotal: 4,
    completed: 1,
    inProgress: 1,
    blocked: 1,
    planned: 1,
    measurementTotal: 1,
    byOwner: [
      { ownerKey: 'student', total: 2, completed: 1, blocked: 1 },
      { ownerKey: '', total: 1, completed: 0, blocked: 0 },
      { ownerKey: 'mentor', total: 1, completed: 0, blocked: 0 },
    ],
  });
});

test('CSV emits BOM/CRLF, quotes punctuation and newlines, and neutralizes formula strings only', () => {
  const items = [{
    ...measurementInput({
      title: '=2+2, "quoted"\nnext line',
      value: -2.5,
      notes: ' \t@SUM(A1:A2)',
    }),
    id: 'm1',
    revision: 2,
    authorKey: 'student',
    updatedBy: 'mentor',
    updatedAt: now2,
  }];
  const csv = context.wsResearchCsv(items, people);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.match(csv, /\r\n/);
  assert.doesNotMatch(csv, /(^|[^\r])\n/);
  assert.match(csv, /"'=2\+2, ""quoted""\r\nnext line"/);
  assert.match(csv, /"' \t@SUM\(A1:A2\)"/);
  assert.match(csv, /"-2\.5"/);
  assert.doesNotMatch(csv, /"'-2\.5"/);
  assert.match(csv, /"sourceEntryId"/);
  assert.match(csv, /"updatedAt"/);
  assert.match(csv, /"trackingStatus"/);
  assert.match(csv, /team-entered operational tracking; not reviewed scientific findings/i);
  assert.ok(csv.endsWith('\r\n'));
});

test('JSON export scopes full revision history to one project and labels tracking', () => {
  const created = save(context.wsResearchEmpty(), workInput());
  const updated = save(created.state, workInput({
    id: created.item.id,
    revision: 1,
    status: 'completed',
  }), mentor, now2);
  const other = { ...created.item, id: 'other', projectId: 'p2' };
  const state = { version: 1, revisions: [...updated.state.revisions, other] };

  const exported = JSON.parse(context.wsResearchJson(state, 'p1'));
  assert.equal(exported.version, 1);
  assert.equal(exported.projectId, 'p1');
  assert.match(exported.trackingStatus, /team-entered/i);
  assert.match(exported.trackingStatus, /not reviewed/i);
  assert.equal(exported.revisions.length, 2);
  assert.deepEqual(exported.revisions.map(item => item.revision), [1, 2]);
  assert.ok(exported.revisions.every(item => item.projectId === 'p1'));
  assert.equal(exported.revisions[1].updatedBy, 'mentor');
});
