const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const Babel = require(path.join(root, 'build', 'vendor', 'babel.js'));
const source = fs.readFileSync(path.join(root, 'src', 'workspace-evidence.jsx'), 'utf8');
const compiled = Babel.transform(source, {
  presets: [['react', { runtime: 'classic' }]],
  comments: false,
}).code;
const context = {
  React: {
    createElement() {},
    Fragment: Symbol('Fragment'),
  },
  console,
  crypto: globalThis.crypto,
  Date,
  JSON,
  Set,
};
vm.createContext(context);
vm.runInContext(compiled, context);

test('markdown parsing keeps heading sections and exact line citations', () => {
  const sections = context.wsParseTextSections(
    '# Setup\nUse cold buffer.\n\n## Result\nYield was 81%.\nSecond line.',
    'run.md'
  );

  assert.deepEqual(JSON.parse(JSON.stringify(sections)), [
    {
      title: 'Setup',
      body: 'Use cold buffer.',
      citation: 'run.md, lines 1-2',
      lineStart: 1,
      lineEnd: 2,
    },
    {
      title: 'Result',
      body: 'Yield was 81%.\nSecond line.',
      citation: 'run.md, lines 4-6',
      lineStart: 4,
      lineEnd: 6,
    },
  ]);
});

test('plain text becomes one reviewable cited excerpt', () => {
  const sections = context.wsParseTextSections('First line\nSecond line', 'notes.txt');

  assert.deepEqual(JSON.parse(JSON.stringify(sections)), [{
    title: 'Notes',
    body: 'First line\nSecond line',
    citation: 'notes.txt, lines 1-2',
    lineStart: 1,
    lineEnd: 2,
  }]);
});

test('markdown parsing skips heading-only sections instead of inventing a body', () => {
  const sections = context.wsParseTextSections(
    '# Handoff packet\n\n## Result\nYield reached 81%.',
    'handoff.md'
  );

  assert.deepEqual(JSON.parse(JSON.stringify(sections)), [{
    title: 'Result',
    body: 'Yield reached 81%.',
    citation: 'handoff.md, lines 3-4',
    lineStart: 3,
    lineEnd: 4,
  }]);
});

test('storage validation rejects malformed records instead of partially accepting them', () => {
  const malformed = {
    version: 1,
    records: [{ id: 'r1', projectId: 'p1', entries: 'not-an-array' }],
  };
  const result = context.wsValidateEvidenceState(malformed);

  assert.equal(result.ok, false);
  assert.match(result.error, /record/i);
});

test('storage validation rejects malformed file and form payloads before rendering', () => {
  const base = {
    version: 1,
    records: [{
      id: 'r1', projectId: 'p1', authorKey: 'priya', authorName: 'Priya',
      authorShort: 'P. Raghunathan', kind: 'manual', title: 'Run', revision: 1,
      status: 'draft', entries: [], files: [],
      form: { objective: '', work: '', observations: '', deviations: '', outcome: '', next: '' },
    }],
  };

  const badFile = JSON.parse(JSON.stringify(base));
  badFile.records[0].files = [null];
  assert.equal(context.wsValidateEvidenceState(badFile).ok, false);

  const badForm = JSON.parse(JSON.stringify(base));
  badForm.records[0].form.outcome = 81;
  assert.equal(context.wsValidateEvidenceState(badForm).ok, false);
});

test('editing a submitted revision creates one new draft revision and clears review state', () => {
  const submitted = {
    id: 'r1', status: 'pending', revision: 3,
    review: { submittedRevision: 3, requestedAt: '2026-09-08T12:00:00.000Z' },
  };

  const reopened = context.wsPrepareRecordForAuthorEdit(submitted);
  assert.equal(reopened.status, 'draft');
  assert.equal(reopened.revision, 4);
  assert.equal(reopened.review, null);

  const typedAgain = context.wsPrepareRecordForAuthorEdit(reopened);
  assert.equal(typedAgain.revision, 4);
});

test('reviewer render can filter a student pending record without initialization errors', () => {
  const pending = {
    id: 'r-pending', projectId: 'p1', authorKey: 'priya', authorName: 'Priya Raghunathan',
    authorShort: 'P. Raghunathan', kind: 'upload', title: 'Sort notes', status: 'pending',
    revision: 1, publishedRevision: null,
    form: { objective: '', work: '', observations: '', deviations: '', outcome: '', next: '' },
    files: [],
    entries: [{
      id: 'entry-1', type: 'result', title: 'Yield improved', body: 'Yield reached 81%.',
      included: true, why: '', citation: 'run.md, lines 1-2', excerpt: 'Yield reached 81%.',
      sourceId: 'file-1', uncertain: false, uncertaintyReason: '',
    }],
    review: { submittedRevision: 1, requestedAt: '2026-09-08T12:00:00.000Z', comment: '' },
    createdAt: '2026-09-08T12:00:00.000Z', updatedAt: '2026-09-08T12:00:00.000Z',
  };
  context.window = {
    localStorage: {
      getItem: () => JSON.stringify({ version: 1, records: [pending] }),
      setItem() {},
    },
  };
  context.React.useRef = initial => ({ current: initial });
  context.React.useState = initial => [typeof initial === 'function' ? initial() : initial, () => {}];
  context.React.useMemo = calculate => calculate();
  context.React.useEffect = () => {};

  assert.doesNotThrow(() => context.EvidenceWorkspace({
    projects: [{ id: 'p1', code: 'URI-1', name: 'Project one' }],
    me: { k: 'okonkwo', n: 'Dr. Marisol Okonkwo', s: 'M. Okonkwo', tier: 'pi' },
    initialProjectId: 'p1',
    mode: 'reviews',
    onPublished() {},
    onOpenProject() {},
  }));
});

test('publish mapping includes only selected entries and gives stable globally scoped ids', () => {
  const record = {
    id: 'rec-123',
    revision: 4,
    authorShort: 'P. Raghunathan',
    entries: [
      { id: 'a', included: true, type: 'method', title: 'Cold buffer', body: 'Use 4 C buffer.', citation: 'run.md, lines 1-2' },
      { id: 'b', included: false, type: 'result', title: 'Excluded', body: 'Do not publish.' },
      { id: 'c', included: true, type: 'decision', title: 'Keep the gate', body: 'It reduced drift.', why: 'Comparable runs.' },
    ],
  };

  assert.deepEqual(JSON.parse(JSON.stringify(context.wsEntriesForPublish(record, '2026-09-08'))), [
    {
      id: 'ws-rec-123-r4-a',
      d: '2026-09-08',
      t: 'method',
      au: 'P. Raghunathan',
      h: 'Cold buffer',
      b: 'Use 4 C buffer.',
      source: 'run.md, lines 1-2',
    },
    {
      id: 'ws-rec-123-r4-c',
      d: '2026-09-08',
      t: 'decision',
      au: 'P. Raghunathan',
      h: 'Keep the gate',
      b: 'It reduced drift.',
      why: 'Comparable runs.',
    },
  ]);
});
