const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const Babel = require(path.join(root, 'build', 'vendor', 'babel.js'));
const domainSource = fs.readFileSync(path.join(root, 'src', 'workspace-research-domain.jsx'), 'utf8');
const uiSource = fs.readFileSync(path.join(root, 'src', 'workspace-research.jsx'), 'utf8');
const context = vm.createContext({
  console,
  crypto: globalThis.crypto,
  Date,
  JSON,
  Math,
  Map,
  Set,
  React: { createElement() {}, Fragment: Symbol('Fragment') },
});
vm.runInContext(domainSource, context);
vm.runInContext(Babel.transform(uiSource, {
  presets: [['react', { runtime: 'classic' }]],
  comments: false,
}).code, context);

const people = [
  { k: 'student', n: 'Student One', s: 'S. One', tier: 'ug', projects: ['p1'] },
  { k: 'mentor', n: 'Mentor Two', s: 'M. Two', tier: 'phd', projects: ['p1'] },
];
const me = people[0];
const project = {
  id: 'p1',
  log: [{ id: 'source-1', h: 'Observed result', b: 'The exact reviewed evidence.', ack: true }],
};

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function validMeasurementForm(overrides = {}) {
  return {
    id: '', revision: '', kind: 'measurement', title: 'Buffer pH', ownerKey: 'student',
    status: 'completed', date: '2026-09-08', dueDate: '', notes: '',
    sourceEntryId: 'source-1', experimentId: '', metric: 'pH', value: '0',
    unit: 'dimensionless', condition: 'room temperature',
    ...overrides,
  };
}

test('measurement form rejects a blank string before numeric conversion and preserves zero text', () => {
  const blank = context.wsResearchBuildInput(validMeasurementForm({ value: '   ' }), 'p1');
  assert.equal(blank.ok, false);
  assert.equal(blank.errorField, 'value');
  assert.match(blank.error, /value/i);

  const form = validMeasurementForm({ value: '0' });
  const zero = context.wsResearchBuildInput(form, 'p1');
  assert.equal(zero.ok, true);
  assert.equal(zero.input.value, 0);
  assert.equal(form.value, '0');
});

test('measurement series group only exact metric, unit, condition, and experiment matches', () => {
  const base = {
    kind: 'measurement', metric: 'pH', unit: 'dimensionless', condition: 'room',
    experimentId: 'run-a', date: '2026-09-08', updatedAt: '2026-09-08T12:00:00.000Z',
  };
  const groups = context.wsResearchMeasurementSeries([
    { ...base, id: 'one', value: 7 },
    { ...base, id: 'two', value: 7.2, date: '2026-09-09' },
    { ...base, id: 'unit', value: 7, unit: 'mV' },
    { ...base, id: 'condition', value: 7, condition: 'cold' },
    { ...base, id: 'experiment', value: 7, experimentId: 'run-b' },
    { ...base, id: 'not-numeric', value: Number.NaN },
  ]);

  assert.equal(groups.length, 4);
  const exact = groups.find(group => group.metric === 'pH' && group.unit === 'dimensionless'
    && group.condition === 'room' && group.experimentId === 'run-a');
  assert.deepEqual(plain(exact.items.map(item => item.id)), ['one', 'two']);
  assert.deepEqual(plain(exact.items.map(item => item.value)), [7, 7.2]);
});

test('commit rereads storage and rejects a stale edit without overwriting the latest revision', () => {
  const created = context.wsResearchSave(
    context.wsResearchEmpty(),
    context.wsResearchBuildInput({ ...validMeasurementForm(), value: '7' }, 'p1').input,
    me, project, people, '2026-09-08T12:00:00.000Z'
  );
  const editForm = context.wsResearchFormFromItem(created.item);
  const newer = context.wsResearchSave(
    created.state,
    { ...context.wsResearchBuildInput(editForm, 'p1').input, status: 'blocked' },
    me, project, people, '2026-09-08T13:00:00.000Z'
  );
  let stored = JSON.stringify(newer.state);
  let writes = 0;
  const storage = {
    getItem: () => stored,
    setItem(key, value) { writes += 1; stored = value; },
  };

  const result = context.wsResearchCommit(
    storage, editForm, me, project, people, '2026-09-08T14:00:00.000Z'
  );

  assert.equal(result.ok, false);
  assert.match(result.error, /stale|revision/i);
  assert.equal(writes, 0);
  assert.equal(JSON.parse(stored).revisions.length, 2);
  assert.equal(editForm.value, '7');
});

test('commit reports a storage failure only after attempting the durable write', () => {
  let writes = 0;
  const storage = {
    getItem: () => null,
    setItem() { writes += 1; throw new Error('quota denied'); },
  };
  const form = validMeasurementForm();

  const result = context.wsResearchCommit(
    storage, form, me, project, people, '2026-09-08T12:00:00.000Z'
  );

  assert.equal(result.ok, false);
  assert.match(result.error, /quota denied|save.*locally/i);
  assert.equal(writes, 1);
  assert.equal(form.value, '0');
});

test('export payload rereads current storage and scopes each format to the selected project', () => {
  const first = context.wsResearchSave(
    context.wsResearchEmpty(),
    context.wsResearchBuildInput({ ...validMeasurementForm(), value: '7' }, 'p1').input,
    me, project, people, '2026-09-08T12:00:00.000Z'
  );
  const otherProjectItem = {
    ...first.item,
    id: 'other-project-item',
    projectId: 'p2',
    title: 'Other project secret',
  };
  let stored = JSON.stringify({ version: 1, revisions: [...first.state.revisions, otherProjectItem] });
  let reads = 0;
  const storage = { getItem() { reads += 1; return stored; } };
  const csv = context.wsResearchExportPayload(storage, 'p1', people, 'csv');
  assert.equal(csv.ok, true);
  assert.match(csv.content, /Buffer pH/);
  assert.doesNotMatch(csv.content, /Other project secret/);

  const updated = context.wsResearchSave(
    first.state,
    { ...context.wsResearchBuildInput(context.wsResearchFormFromItem(first.item), 'p1').input, title: 'Fresh title' },
    me, project, people, '2026-09-08T13:00:00.000Z'
  );
  stored = JSON.stringify({ version: 1, revisions: [...updated.state.revisions, otherProjectItem] });
  const json = context.wsResearchExportPayload(storage, 'p1', people, 'json');
  assert.equal(json.ok, true);
  assert.equal(JSON.parse(json.content).revisions.at(-1).title, 'Fresh title');
  assert.doesNotMatch(json.content, /Other project secret/);
  assert.equal(reads, 2);
});

test('browser storage lookup contains a throwing localStorage accessor', () => {
  const browserWindow = {};
  Object.defineProperty(browserWindow, 'localStorage', {
    get() { throw new Error('blocked'); },
  });
  const result = context.wsResearchBrowserStorage(browserWindow);
  assert.equal(result.ok, false);
  assert.match(result.error, /blocked|unavailable/i);
});

test('history snapshot retains every field needed to understand an older measurement revision', () => {
  const snapshot = context.wsResearchHistorySnapshot({
    id: 'm1', revision: 1, kind: 'measurement', title: 'Earlier pH', ownerKey: 'mentor',
    status: 'completed', date: '2026-09-07', dueDate: '2026-09-08', notes: 'Old note',
    metric: 'pH', value: 6.8, unit: 'dimensionless', condition: 'cold',
    sourceEntryId: 'source-1', experimentId: 'run-a', updatedBy: 'student',
    updatedAt: '2026-09-08T12:00:00.000Z',
  }, people);

  assert.deepEqual(plain(snapshot), {
    revision: 1,
    title: 'Earlier pH',
    kind: 'Measurement',
    owner: 'Mentor Two',
    status: 'Completed',
    date: '2026-09-07',
    dueDate: '2026-09-08',
    notes: 'Old note',
    measurement: 'pH: 6.8 dimensionless',
    condition: 'cold',
    sourceEntryId: 'source-1',
    experimentId: 'run-a',
    updatedBy: 'Student One',
    updatedAt: '2026-09-08T12:00:00.000Z',
  });
});

test('source snapshot preserves reviewed evidence text exactly for read-only inspection', () => {
  const source = project.log[0];
  const snapshot = context.wsResearchSourceSnapshot(source);
  assert.equal(snapshot.title, 'Observed result');
  assert.equal(snapshot.body, 'The exact reviewed evidence.');
  assert.equal(snapshot.body, source.b);
});

test('constant raw series uses one centered value tick and one date label', () => {
  const model = context.wsResearchPlotModel({ items: [
    { id: 'one', value: 7, date: '2026-09-08' },
    { id: 'two', value: 7, date: '2026-09-08' },
  ] });
  assert.deepEqual(plain(model.valueTicks), [{ value: 7, y: 100 }]);
  assert.deepEqual(plain(model.dateTicks), [{ value: '2026-09-08', x: 34, anchor: 'start' }]);
  assert.deepEqual(plain(model.points), [
    { id: 'one', x: 300, y: 100 },
    { id: 'two', x: 300, y: 100 },
  ]);
});
