const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Babel = require('../build/vendor/babel.js');

const html = fs.readFileSync(path.join(__dirname, '../src/uri.html'), 'utf8');
const main = [...html.matchAll(/<script\b([^>]*\btype="text\/babel"[^>]*)>([\s\S]*?)<\/script>/g)]
  .filter(([, attrs]) => !/\bsrc=/.test(attrs)).map(([, , body]) => body).join('\n');
const code = Babel.transform(main + '\nglobalThis.testApi = { buildIndex, debts, SEED, SHELF_SEED, byKey };', {
  presets: [['react', { runtime: 'classic' }]],
}).code;
const context = vm.createContext({
  React: { createContext: () => ({}), createElement: () => ({}) },
  ReactDOM: { createRoot: () => ({ render() {} }) },
  document: { getElementById: () => ({}) },
});
vm.runInContext(code, context);
const api = context.testApi;

test('partner search cannot expose internal projects, entries, or unshared people', () => {
  const results = api.buildIndex({ projects: api.SEED, shelf: api.SHELF_SEED,
    me: api.byKey('dana'), lens: 'partner', shared: ['amara'] });
  assert.ok(results.length > 0);
  assert.equal(results.some(item => ['project', 'me'].includes(item.act.t)), false);
  assert.deepEqual(Array.from(results.filter(item => item.act.t === 'record'), item => item.act.k), ['amara']);
  const listedIds = api.SHELF_SEED.filter(s => s.visibility === 'partner' && !s.claimedBy).map(s => s.id);
  for (const item of results.filter(item => item.act.t === 'shelf')) assert.ok(listedIds.includes(item.act.k));
});

test('removing record sharing removes it from partner search', () => {
  const results = api.buildIndex({ projects: api.SEED, shelf: api.SHELF_SEED,
    me: api.byKey('dana'), lens: 'partner', shared: [] });
  assert.equal(results.some(item => item.act.t === 'record'), false);
});

test('internal search still finds project knowledge', () => {
  const results = api.buildIndex({ projects: api.SEED, shelf: api.SHELF_SEED,
    me: api.byKey('okonkwo'), lens: 'sup' });
  assert.ok(results.some(item => item.act.t === 'project' && /FACS/.test(item.label)));
});

test('an empty project has an actionable gap instead of crashing continuity analysis', () => {
  const gaps = api.debts({ ...api.SEED[0], log: [] });
  assert.equal(gaps.length, 1);
  assert.equal(gaps[0].k, 'empty');
  assert.match(gaps[0].faculty, /first project update/);
});
