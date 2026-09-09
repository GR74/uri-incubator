const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const Babel = require('../build/vendor/babel.js');
const memory = new Map();
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/workspace.jsx'), 'utf8');
const context = vm.createContext({
  React: { createElement() {} },
  localStorage: { getItem: key => memory.get(key) ?? null },
  TYPES: Object.fromEntries(['decision', 'method', 'result', 'deadend', 'blocker', 'next'].map(type => [type, { label: type[0].toUpperCase() + type.slice(1) }])),
  TYPE_ORDER: ['decision', 'method', 'result', 'deadend', 'blocker', 'next'],
});

test('record summary counts approved evidence and anchors six months to the latest valid date', () => {
  const summary = context.wsRecordSummary([{ log: [
    { t: 'decision', d: '2026-08-12', ack: true },
    { t: 'method', d: '2026-03-01' },
    { t: 'result', d: '2025-12-31', ack: true },
    { t: 'decision', d: '2026-02-30', ack: true },
    { t: 'blocker', d: '2027-01-01', ack: false },
  ] }]);
  assert.equal(summary.approvedTotal, 4);
  assert.equal(summary.typeCounts.length, 6);
  assert.equal(summary.typeCounts.find(item => item.type === 'decision').count, 2);
  assert.equal(summary.typeCounts.find(item => item.type === 'blocker').count, 0);
  assert.equal(summary.latestDate, '2026-08-12');
  assert.equal(summary.periodLabel, 'March-August 2026');
  assert.equal(summary.activity.length, 6);
  assert.equal(summary.activity[0].key, '2026-03');
  assert.equal(summary.activity[5].key, '2026-08');
  assert.equal(summary.activity.reduce((sum, item) => sum + item.count, 0), 2);
});

test('record summary handles missing logs and undated records without inventing activity', () => {
  const empty = context.wsRecordSummary([{}, { log: [] }]);
  assert.equal(empty.approvedTotal, 0);
  assert.equal(empty.activity.length, 0);
  assert.equal(empty.latestDate, '');
  const undated = context.wsRecordSummary([{ log: [{ t: 'method', d: 'invalid', ack: true }] }]);
  assert.equal(undated.approvedTotal, 1);
  assert.equal(undated.activity.length, 0);
  assert.equal(undated.periodLabel, 'No dated approved entries');
});
vm.runInContext(Babel.transform(source, { presets: [['react', { runtime: 'classic' }]] }).code, context);

test('malformed navigation preferences recover to a supported screen', () => {
  memory.set('uri.workspace.test', JSON.stringify({ section: 'missing', projectTab: {}, selectedProjectId: 23 }));
  const state = context.wsReadState('test');
  assert.equal(state.section, undefined);
  assert.equal(state.projectTab, undefined);
  assert.equal(state.selectedProjectId, undefined);
  memory.set('uri.workspace.test', '{bad json');
  assert.deepEqual(Object.keys(context.wsReadState('test')), []);
});

test('project pages keep Projects active and Map is restorable', () => {
  memory.set('uri.workspace.test', JSON.stringify({ section:'map', projectTab:'record', selectedProjectId:'p1' }));
  const state = context.wsReadState('test');
  assert.equal(state.section, 'map');
  assert.equal(state.projectTab, 'record');
  assert.equal(state.selectedProjectId, 'p1');
  assert.equal(context.wsWorkspaceNavKey('project'), 'projects');
});

test('export retains historical rationale, citations, and supersession links', () => {
  const exported = context.wsMarkdown({ name: 'Sample project', oneLine: 'Project objective', log: [
    { id: 'old', t: 'decision', d: '2026-08-01', au: 'A', h: 'Original approach', b: 'Original detail', why: 'Original rationale', ack: true },
    { id: 'new', t: 'decision', d: '2026-09-01', au: 'B', h: 'Updated approach', b: 'Updated detail', why: 'Updated rationale', ack: true, supersedes: 'old', source: 'notes.md, lines 4-6' },
  ] });
  assert.match(exported, /Original rationale/);
  assert.match(exported, /Updated rationale/);
  assert.match(exported, /Supersedes: old/);
  assert.match(exported, /notes.md, lines 4-6/);
  assert.ok(exported.indexOf('2026-08-01 - Decision') < exported.indexOf('2026-09-01 - Decision'));
});

test('pending knowledge is excluded from the opening brief and labeled in the history', () => {
  const exported = context.wsMarkdown({ name: 'Sample', oneLine: 'Objective', log: [
    { id: 'pending', t: 'method', d: '2026-09-01', au: 'A', h: 'Unreviewed method', b: 'Unverified detail', ack: false },
  ] });
  const [brief, history] = exported.split('## Full authorized history');
  assert.doesNotMatch(brief, /Unreviewed method/);
  assert.match(history, /Unreviewed method/);
  assert.match(history, /Pending review - not part of the official record/);
});
