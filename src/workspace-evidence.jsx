const WS_STORAGE_KEY = 'uri.evidence.v1';
const WS_STATE_VERSION = 1;
const WS_MAX_FILE_BYTES = 1024 * 1024;
const WS_ENTRY_TYPES = [
  ['decision', 'Decision'],
  ['method', 'Method'],
  ['result', 'Result'],
  ['deadend', 'Dead end'],
  ['blocker', 'Blocker'],
  ['next', 'Next step'],
];
const WS_MANUAL_FIELDS = [
  ['objective', 'Objective', 'next'],
  ['work', 'Work performed', 'method'],
  ['observations', 'Observations', 'result'],
  ['deviations', 'Deviations', 'deadend'],
  ['outcome', 'Outcome', 'result'],
  ['next', 'Next step', 'next'],
];

function wsNewId(prefix) {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return prefix + '-' + crypto.randomUUID();
  }
  return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
}

function wsEmptyState() {
  return { version: WS_STATE_VERSION, records: [] };
}

function wsValidateEvidenceState(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'The saved evidence workspace is not an object.' };
  }
  if (value.version !== WS_STATE_VERSION || !Array.isArray(value.records)) {
    return { ok: false, error: 'The saved evidence workspace has an unsupported format.' };
  }
  const validStatuses = new Set(['draft', 'pending', 'changes_requested', 'published']);
  for (let i = 0; i < value.records.length; i += 1) {
    const record = value.records[i];
    const validRecord = record && typeof record === 'object' &&
      typeof record.id === 'string' && typeof record.projectId === 'string' &&
      typeof record.authorKey === 'string' && typeof record.authorName === 'string' && typeof record.authorShort === 'string' &&
      (record.kind === 'manual' || record.kind === 'upload') &&
      typeof record.title === 'string' && Number.isInteger(record.revision) && record.revision > 0 &&
      validStatuses.has(record.status) && Array.isArray(record.entries) && Array.isArray(record.files) &&
      record.form && typeof record.form === 'object' && !Array.isArray(record.form);
    if (!validRecord) {
      return { ok: false, error: 'Saved evidence record ' + (i + 1) + ' is malformed.' };
    }
    for (let j = 0; j < record.entries.length; j += 1) {
      const entry = record.entries[j];
      if (!entry || typeof entry.id !== 'string' || typeof entry.type !== 'string' ||
          typeof entry.title !== 'string' || typeof entry.body !== 'string' ||
          typeof entry.included !== 'boolean' ||
          (entry.why !== undefined && typeof entry.why !== 'string') ||
          (entry.citation !== undefined && typeof entry.citation !== 'string') ||
          (entry.excerpt !== undefined && typeof entry.excerpt !== 'string') ||
          (entry.sourceId !== undefined && typeof entry.sourceId !== 'string') ||
          (entry.uncertain !== undefined && typeof entry.uncertain !== 'boolean') ||
          (entry.uncertaintyReason !== undefined && typeof entry.uncertaintyReason !== 'string')) {
        return { ok: false, error: 'Saved evidence record ' + (i + 1) + ' has a malformed draft entry.' };
      }
    }
    for (let j = 0; j < record.files.length; j += 1) {
      const file = record.files[j];
      if (!file || typeof file !== 'object' || typeof file.id !== 'string' ||
          typeof file.name !== 'string' || typeof file.fingerprint !== 'string' ||
          typeof file.status !== 'string' || (file.content !== undefined && typeof file.content !== 'string')) {
        return { ok: false, error: 'Saved evidence record ' + (i + 1) + ' has malformed file metadata.' };
      }
    }
    for (let j = 0; j < WS_MANUAL_FIELDS.length; j += 1) {
      if (typeof record.form[WS_MANUAL_FIELDS[j][0]] !== 'string') {
        return { ok: false, error: 'Saved evidence record ' + (i + 1) + ' has malformed manual fields.' };
      }
    }
    if (record.review !== null && record.review !== undefined) {
      if (!record.review || typeof record.review !== 'object' ||
          !Number.isInteger(record.review.submittedRevision) || record.review.submittedRevision < 1 ||
          typeof record.review.requestedAt !== 'string' ||
          (record.review.comment !== undefined && typeof record.review.comment !== 'string')) {
        return { ok: false, error: 'Saved evidence record ' + (i + 1) + ' has malformed review metadata.' };
      }
    }
  }
  return { ok: true, value };
}

function wsReadEvidenceState() {
  if (typeof window === 'undefined' || !window.localStorage) {
    return { value: wsEmptyState(), error: 'Local browser storage is unavailable. Changes will last only for this page.' };
  }
  let raw;
  try {
    raw = window.localStorage.getItem(WS_STORAGE_KEY);
    if (raw === null) return { value: wsEmptyState(), error: '' };
    const checked = wsValidateEvidenceState(JSON.parse(raw));
    if (!checked.ok) return { value: wsEmptyState(), error: checked.error, raw };
    return { value: checked.value, error: '' };
  } catch (error) {
    return { value: wsEmptyState(), error: 'Saved evidence could not be read: ' + error.message, raw };
  }
}

function wsSaveEvidenceState(value) {
  if (typeof window === 'undefined' || !window.localStorage) {
    return { ok: false, error: 'Local browser storage is unavailable.' };
  }
  try {
    window.localStorage.setItem(WS_STORAGE_KEY, JSON.stringify(value));
    return { ok: true };
  } catch (error) {
    return { ok: false, error: 'Evidence could not be saved locally: ' + error.message };
  }
}

function wsParseTextSections(text, fileName) {
  const normalized = String(text || '').replace(/\r\n?/g, '\n');
  const lines = normalized.split('\n');
  while (lines.length > 1 && !lines[lines.length - 1].trim()) lines.pop();
  const headings = [];
  lines.forEach((line, index) => {
    const match = line.match(/^#{1,6}\s+(.+?)\s*#*\s*$/);
    if (match) headings.push({ index, title: match[1].trim() });
  });
  if (!headings.length) {
    const body = lines.join('\n').trim();
    if (!body) return [];
    return [{
      title: fileName && fileName.toLowerCase().endsWith('.md') ? 'Document' : 'Notes',
      body,
      citation: fileName + ', lines 1-' + lines.length,
      lineStart: 1,
      lineEnd: lines.length,
    }];
  }
  const sections = [];
  if (headings[0].index > 0) {
    const intro = lines.slice(0, headings[0].index).join('\n').trim();
    if (intro) {
      sections.push({
        title: 'Introduction', body: intro,
        citation: fileName + ', lines 1-' + headings[0].index,
        lineStart: 1, lineEnd: headings[0].index,
      });
    }
  }
  headings.forEach((heading, index) => {
    const nextIndex = index + 1 < headings.length ? headings[index + 1].index : lines.length;
    let endIndex = nextIndex;
    while (endIndex > heading.index + 1 && !lines[endIndex - 1].trim()) endIndex -= 1;
    const body = lines.slice(heading.index + 1, endIndex).join('\n').trim();
    if (!body) return;
    sections.push({
      title: heading.title,
      body,
      citation: fileName + ', lines ' + (heading.index + 1) + '-' + endIndex,
      lineStart: heading.index + 1,
      lineEnd: endIndex,
    });
  });
  return sections;
}

function wsGuessEntryType(title) {
  const value = String(title || '').toLowerCase();
  if (/decision|rationale|chose|choice/.test(value)) return { type: 'decision', uncertain: false };
  if (/method|procedure|protocol|setup|work|process/.test(value)) return { type: 'method', uncertain: false };
  if (/dead.?end|fail|deviation|did not work/.test(value)) return { type: 'deadend', uncertain: false };
  if (/block|constraint|limitation/.test(value)) return { type: 'blocker', uncertain: false };
  if (/next|future|follow.?up|todo|open question/.test(value)) return { type: 'next', uncertain: false };
  if (/result|outcome|observation|finding/.test(value)) return { type: 'result', uncertain: false };
  return {
    type: 'result',
    uncertain: true,
    reason: 'The heading did not name an entry type. Result is a placeholder until you choose one.',
  };
}

function wsEntriesForPublish(record, today) {
  return record.entries.filter(entry => entry.included && entry.title.trim() && entry.body.trim()).map(entry => {
    const published = {
      id: 'ws-' + record.id + '-r' + record.revision + '-' + entry.id,
      d: today,
      t: entry.type,
      au: record.authorShort,
      h: entry.title.trim(),
      b: entry.body.trim(),
    };
    if (entry.why && entry.why.trim()) published.why = entry.why.trim();
    if (entry.citation) published.source = entry.citation;
    return published;
  });
}

function wsBlankForm() {
  return { objective: '', work: '', observations: '', deviations: '', outcome: '', next: '' };
}

function wsCreateRecord(projectId, me, kind, title) {
  const now = new Date().toISOString();
  return {
    id: wsNewId('record'),
    projectId,
    authorKey: me.k,
    authorName: me.n,
    authorShort: me.s,
    kind,
    title: title || '',
    status: 'draft',
    revision: 1,
    publishedRevision: null,
    form: wsBlankForm(),
    files: [],
    entries: [],
    review: null,
    createdAt: now,
    updatedAt: now,
  };
}

function wsPrepareRecordForAuthorEdit(record) {
  if (record.status !== 'pending' && record.status !== 'changes_requested') return record;
  return {
    ...record,
    status: 'draft',
    revision: record.revision + 1,
    review: null,
  };
}

function wsManualEntries(record) {
  return WS_MANUAL_FIELDS.filter(field => String(record.form[field[0]] || '').trim()).map(field => ({
    id: 'manual-' + field[0],
    type: field[2],
    title: record.title.trim() + ': ' + field[1],
    body: String(record.form[field[0]]).trim(),
    why: '',
    sourceId: 'manual',
    citation: 'Manual lab entry, ' + field[1],
    excerpt: String(record.form[field[0]]).trim(),
    included: true,
    origin: 'manual',
    uncertain: false,
    uncertaintyReason: '',
  }));
}

function wsStatusLabel(status) {
  return ({
    draft: 'Draft', pending: 'Review requested', changes_requested: 'Changes requested', published: 'Published',
  })[status] || status;
}

function wsCanReview(me) {
  return !!me && (me.tier === 'pi' || me.tier === 'phd');
}

function wsFormatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  return Math.round(bytes / 1024) + ' KB';
}

function wsFileFingerprint(file) {
  return String(file.name || '').toLowerCase() + ':' + file.size + ':' + (file.lastModified || 0);
}

function WSEvidenceProjectPicker({ projects, projectId, onChange }) {
  return (
    <label className="ws-field">
      <span>Project</span>
      <select className="ws-select" value={projectId} onChange={event => onChange(event.target.value)}>
        {projects.map(project => <option key={project.id} value={project.id}>{project.code} - {project.name}</option>)}
      </select>
    </label>
  );
}

function WSEvidenceStages({ files, linking, ready }) {
  const hasFiles = files.length > 0;
  const isReading = files.some(file => file.status === 'reading');
  const isExtracting = files.some(file => file.status === 'extracting');
  const hasFailure = files.some(file => file.status === 'failed');
  const stages = [
    ['Uploaded', hasFiles ? 'complete' : '', 'Files selected for this local workspace.'],
    ['Reading', isReading ? 'current' : hasFiles && !files.some(file => file.status === 'queued') ? 'complete' : '', 'Reading file contents with your browser.'],
    ['Extracting', isExtracting ? 'current' : ready ? 'complete' : '', 'Splitting Markdown headings into cited excerpts.'],
    ['Linking evidence', linking ? 'current' : ready ? 'complete' : '', 'Attaching each draft to its local source lines.'],
    ['Ready for review', ready ? 'complete' : hasFailure && !linking ? 'failed' : '', 'No entry is published at this stage.'],
  ];
  return (
    <ol className="ws-stage-list" aria-label="Analysis progress">
      {stages.map((stage, index) => (
        <li key={stage[0]} className={'ws-stage ' + stage[1]}>
          <span className="ws-stage-mark" aria-hidden="true">{stage[1] === 'complete' ? '✓' : stage[1] === 'failed' ? '!' : index + 1}</span>
          <span><strong>{stage[0]}</strong><small>{stage[2]}</small></span>
        </li>
      ))}
    </ol>
  );
}

function EvidenceWorkspace({ projects, me, initialProjectId, mode, onPublished, onOpenProject }) {
  const initialLoad = React.useRef(null);
  if (initialLoad.current === null) initialLoad.current = wsReadEvidenceState();
  const [evidenceState, setEvidenceState] = React.useState(initialLoad.current.value);
  const [storageBlocked, setStorageBlocked] = React.useState(!!initialLoad.current.raw && !!initialLoad.current.error);
  const [storageError, setStorageError] = React.useState(initialLoad.current.error || '');
  const firstProjectId = projects && projects.length ? projects[0].id : '';
  const initialAllowed = (projects || []).some(project => project.id === initialProjectId) ? initialProjectId : firstProjectId;
  const [projectId, setProjectId] = React.useState(initialAllowed);
  const [section, setSection] = React.useState(mode === 'reviews' ? 'reviews' : 'write');
  const [activeRecordId, setActiveRecordId] = React.useState(null);
  const [selectedEntryId, setSelectedEntryId] = React.useState(null);
  const [mobilePane, setMobilePane] = React.useState('draft');
  const [uploadFiles, setUploadFiles] = React.useState([]);
  const [analysisRecordId, setAnalysisRecordId] = React.useState(null);
  const [linking, setLinking] = React.useState(false);
  const [feedback, setFeedback] = React.useState('');
  const [reviewComment, setReviewComment] = React.useState('');
  const publishing = React.useRef(new Set());
  const evidenceRef = React.useRef(evidenceState);
  evidenceRef.current = evidenceState;

  const authorizedIds = React.useMemo(() => new Set((projects || []).map(project => project.id)), [projects]);
  const authorizedKey = (projects || []).map(project => project.id).join('|');
  const reviewer = wsCanReview(me);
  const activeProject = (projects || []).find(project => project.id === projectId) || null;
  const activeProjectReadOnly = !!activeProject && (activeProject.status === 'stashed' || activeProject.status === 'archived');
  const activeRecord = evidenceState.records.find(record => record.id === activeRecordId) || null;
  const visibleRecords = evidenceState.records.filter(record => canReadRecord(record));
  const projectRecords = visibleRecords.filter(record => record.projectId === projectId);

  React.useEffect(() => {
    if (mode === 'reviews') setSection('reviews');
    else if (section === 'reviews') setSection('write');
  }, [mode]);

  React.useEffect(() => {
    if ((projects || []).some(project => project.id === initialProjectId)) setProjectId(initialProjectId);
  }, [initialProjectId]);

  React.useEffect(() => {
    if (!authorizedIds.has(projectId)) setProjectId(firstProjectId);
  }, [authorizedKey, projectId, firstProjectId]);

  React.useEffect(() => {
    if (activeProjectReadOnly && !['drafts', 'reviews', 'review'].includes(section)) setSection(mode === 'reviews' ? 'reviews' : 'drafts');
  }, [activeProjectReadOnly, mode, section]);

  React.useEffect(() => {
    if (storageBlocked) return;
    const result = wsSaveEvidenceState(evidenceState);
    setStorageError(result.ok ? '' : result.error);
  }, [evidenceState, storageBlocked]);

  React.useEffect(() => {
    setActiveRecordId(null);
    setSelectedEntryId(null);
    setFeedback('');
    setReviewComment('');
  }, [me.k]);

  function assertAuthorized(targetProjectId) {
    if (!authorizedIds.has(targetProjectId)) {
      setFeedback('This project is not in your current authorized workspace. No change was made.');
      return false;
    }
    return true;
  }

  function assertWritable(targetProjectId) {
    const target = (projects || []).find(project => project.id === targetProjectId);
    if (target && (target.status === 'stashed' || target.status === 'archived')) {
      setFeedback('This project is stashed. Its evidence remains readable, but changes require resuming the project.');
      return false;
    }
    return assertAuthorized(targetProjectId);
  }

  function canReadRecord(record) {
    if (!record || !authorizedIds.has(record.projectId)) return false;
    if (record.authorKey === me.k || record.status === 'published') return true;
    return reviewer && (record.status === 'pending' || record.status === 'changes_requested');
  }

  function explicitFreshStart() {
    const fresh = wsEmptyState();
    const result = wsSaveEvidenceState(fresh);
    if (!result.ok) {
      setStorageError(result.error);
      return;
    }
    setEvidenceState(fresh);
    setStorageBlocked(false);
    setStorageError('');
    setFeedback('The unreadable local evidence workspace was replaced after your confirmation.');
  }

  function updateAuthoredRecord(recordId, updater) {
    setEvidenceState(current => {
      const record = current.records.find(item => item.id === recordId);
      if (!record || !assertWritable(record.projectId) || record.authorKey !== me.k || record.status === 'published') {
        setFeedback('You cannot edit this draft. No change was made.');
        return current;
      }
      const returningToDraft = record.status === 'pending' || record.status === 'changes_requested';
      const editable = wsPrepareRecordForAuthorEdit(record);
      const updated = {
        ...updater(editable),
        updatedAt: new Date().toISOString(),
      };
      if (returningToDraft) setFeedback('Editing opened revision ' + updated.revision + '. A new review is required.');
      return { ...current, records: current.records.map(item => item.id === recordId ? updated : item) };
    });
  }

  function startManualRecord() {
    if (!activeProject || !assertWritable(activeProject.id)) return;
    const record = wsCreateRecord(activeProject.id, me, 'manual', '');
    setEvidenceState(current => ({ ...current, records: [record, ...current.records] }));
    setActiveRecordId(record.id);
    setSection('manual');
    setFeedback('Draft started and saved locally.');
  }

  function openRecord(record) {
    if (!record || !assertAuthorized(record.projectId) || !canReadRecord(record)) {
      setFeedback('This evidence group is not available to your current demo identity.');
      return;
    }
    setProjectId(record.projectId);
    setActiveRecordId(record.id);
    setSelectedEntryId(record.entries[0] ? record.entries[0].id : null);
    setSection(record.kind === 'manual' && !record.entries.length ? 'manual' : 'review');
    setFeedback('');
    setReviewComment(record.review && record.review.comment ? record.review.comment : '');
  }

  function prepareManualReview(record) {
    if (!record.title.trim() || !WS_MANUAL_FIELDS.some(field => String(record.form[field[0]] || '').trim())) {
      setFeedback('Add a title and at least one meaningful lab-work field before review.');
      return;
    }
    const entries = wsManualEntries(record);
    updateAuthoredRecord(record.id, current => ({ ...current, entries }));
    setSelectedEntryId(entries[0].id);
    setSection('review');
    setFeedback('Review every included entry before you submit it.');
  }

  function addFiles(fileList) {
    if (!activeProject || !assertWritable(activeProject.id)) return;
    const existingFiles = visibleRecords.flatMap(record => record.files.map(file => ({ record, file })));
    const additions = Array.from(fileList || []).map(file => {
      const name = file.name || 'unnamed file';
      const extension = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
      const duplicate = existingFiles.find(item => item.file.fingerprint === wsFileFingerprint(file));
      let error = '';
      let recoverable = true;
      if (extension === 'pdf' || extension === 'docx') {
        error = extension.toUpperCase() + ' parsing is not yet supported. Convert it to Markdown or plain text, then add that file.';
        recoverable = false;
      } else if (extension !== 'md' && extension !== 'txt') {
        error = 'Only .md and .txt files can be read in this local preview.';
        recoverable = false;
      } else if (file.size > WS_MAX_FILE_BYTES) {
        error = 'This file is larger than 1 MB. Split it into smaller Markdown or text files.';
        recoverable = false;
      }
      return {
        id: wsNewId('file'), file, name, size: file.size, lastModified: file.lastModified || 0,
        fingerprint: wsFileFingerprint(file), extension,
        status: error ? 'failed' : 'queued', error, recoverable,
        duplicateRecordId: duplicate ? duplicate.record.id : null,
        duplicateName: duplicate ? duplicate.record.title : '',
      };
    });
    setUploadFiles(current => [...current, ...additions]);
    setFeedback(additions.length ? additions.length + ' file' + (additions.length === 1 ? '' : 's') + ' added.' : '');
  }

  function removeUploadFile(fileId) {
    setUploadFiles(current => current.filter(file => file.id !== fileId));
  }

  async function analyzeFiles(onlyIds) {
    if (!activeProject || !assertWritable(projectId)) return;
    const existingGroup = analysisRecordId ? evidenceRef.current.records.find(record => record.id === analysisRecordId) : null;
    if (existingGroup && (existingGroup.authorKey !== me.k || !authorizedIds.has(existingGroup.projectId) || existingGroup.status === 'published')) {
      setFeedback('This analyzed change set can no longer be edited. Start a new upload group.');
      return;
    }
    const target = uploadFiles.filter(file => (!onlyIds || onlyIds.includes(file.id)) && file.status !== 'ready' && file.recoverable);
    if (!target.length) {
      setFeedback('Add a readable Markdown or text file first.');
      return;
    }
    let collected = [];
    let processedFiles = [];
    for (const item of target) {
      setUploadFiles(current => current.map(file => file.id === item.id ? { ...file, status: 'reading', error: '' } : file));
      try {
        if (!item.file || typeof item.file.text !== 'function') throw new Error('Reselect this file so the browser can read it again.');
        const text = await item.file.text();
        setUploadFiles(current => current.map(file => file.id === item.id ? { ...file, status: 'extracting' } : file));
        const sections = wsParseTextSections(text, item.name);
        if (!sections.length) throw new Error('No readable text was found. Replace the file with a non-empty transcript.');
        const entries = sections.map(section => {
          const guess = wsGuessEntryType(section.title);
          return {
            id: wsNewId('entry'),
            type: guess.type,
            title: section.title,
            body: section.body || section.title,
            why: '',
            sourceId: item.id,
            citation: section.citation,
            excerpt: section.body || section.title,
            included: true,
            origin: 'local-preview',
            uncertain: !!guess.uncertain,
            uncertaintyReason: guess.reason || '',
          };
        });
        collected = collected.concat(entries);
        processedFiles.push({
          id: item.id, name: item.name, size: item.size, lastModified: item.lastModified,
          fingerprint: item.fingerprint, status: 'ready', content: text,
          sectionCount: entries.length,
        });
        setUploadFiles(current => current.map(file => file.id === item.id ? { ...file, status: 'ready', error: '', sectionCount: entries.length } : file));
      } catch (error) {
        setUploadFiles(current => current.map(file => file.id === item.id ? {
          ...file, status: 'failed', error: error.message || 'The browser could not read this file.', recoverable: true,
        } : file));
      }
    }
    if (!collected.length) {
      setFeedback('No new excerpts are ready. Successful files from earlier attempts are still preserved.');
      return;
    }
    setLinking(true);
    const currentRecord = existingGroup;
    const record = currentRecord ? wsPrepareRecordForAuthorEdit(currentRecord) : wsCreateRecord(
      projectId,
      me,
      'upload',
      'Evidence from ' + processedFiles[0].name + (processedFiles.length > 1 ? ' and ' + (processedFiles.length - 1) + ' more' : '')
    );
    const updatedRecord = {
      ...record,
      files: [
        ...record.files.filter(file => !processedFiles.some(next => next.id === file.id)),
        ...processedFiles,
      ],
      entries: [...record.entries, ...collected],
      updatedAt: new Date().toISOString(),
    };
    setEvidenceState(current => ({
      ...current,
      records: current.records.some(item => item.id === updatedRecord.id)
        ? current.records.map(item => item.id === updatedRecord.id ? updatedRecord : item)
        : [updatedRecord, ...current.records],
    }));
    setAnalysisRecordId(updatedRecord.id);
    setActiveRecordId(updatedRecord.id);
    setSelectedEntryId(collected[0].id);
    setLinking(false);
    setFeedback(collected.length + ' cited excerpt' + (collected.length === 1 ? ' is' : 's are') + ' ready for your review.');
  }

  function updateEntry(recordId, entryId, patch) {
    updateAuthoredRecord(recordId, record => ({
      ...record,
      entries: record.entries.map(entry => entry.id === entryId ? { ...entry, ...patch } : entry),
    }));
  }

  function requestReview(record) {
    if (!assertWritable(record.projectId) || record.authorKey !== me.k || record.status !== 'draft') return;
    const entries = wsEntriesForPublish(record, new Date().toISOString().slice(0, 10));
    if (!entries.length) {
      setFeedback('Include at least one complete entry before requesting review.');
      return;
    }
    setEvidenceState(current => ({
      ...current,
      records: current.records.map(item => item.id === record.id ? {
        ...item,
        status: 'pending',
        review: { submittedRevision: item.revision, requestedAt: new Date().toISOString(), comment: '' },
        updatedAt: new Date().toISOString(),
      } : item),
    }));
    setFeedback('Revision ' + record.revision + ' was submitted for review. Nothing has been published.');
  }

  function requestChanges(record) {
    if (!reviewer || record.authorKey === me.k || !assertWritable(record.projectId) || record.status !== 'pending') return;
    if (!reviewComment.trim()) {
      setFeedback('Add a specific review comment before requesting changes.');
      return;
    }
    if (!record.review || record.review.submittedRevision !== record.revision) {
      setFeedback('This review is stale. Reopen the newest revision before acting.');
      return;
    }
    setEvidenceState(current => ({
      ...current,
      records: current.records.map(item => item.id === record.id ? {
        ...item,
        status: 'changes_requested',
        review: {
          ...item.review,
          comment: reviewComment.trim(),
          reviewedBy: me.k,
          reviewerName: me.n,
          reviewedAt: new Date().toISOString(),
        },
        updatedAt: new Date().toISOString(),
      } : item),
    }));
    setFeedback('Changes were requested. The author must submit a new revision.');
  }

  function publishRecord(record, approval) {
    if (!record || publishing.current.has(record.id) || !assertWritable(record.projectId)) return;
    if (typeof onPublished !== 'function') {
      setFeedback('Publishing is unavailable because the project update handler is not connected.');
      return;
    }
    const latest = evidenceRef.current.records.find(item => item.id === record.id);
    if (!latest || latest.revision !== record.revision || latest.publishedRevision === latest.revision) {
      setFeedback('This revision is stale or already published. No duplicate was created.');
      return;
    }
    if (approval) {
      if (!reviewer || latest.authorKey === me.k || latest.status !== 'pending' ||
          !latest.review || latest.review.submittedRevision !== latest.revision) {
        setFeedback('Only a PI or PhD mentor can approve another author\'s exact submitted revision.');
        return;
      }
    } else if (!reviewer || latest.authorKey !== me.k || latest.status !== 'draft') {
      setFeedback('Your current demo capability does not allow direct publishing of this draft.');
      return;
    }
    const entries = wsEntriesForPublish(latest, new Date().toISOString().slice(0, 10));
    if (!entries.length) {
      setFeedback('Include at least one complete entry before publishing.');
      return;
    }
    const publishedRecord = {
      ...latest,
      status: 'published',
      publishedRevision: latest.revision,
      review: approval ? {
        ...latest.review,
        approvedRevision: latest.revision,
        reviewedBy: me.k,
        reviewerName: me.n,
        reviewedAt: new Date().toISOString(),
      } : latest.review,
      updatedAt: new Date().toISOString(),
    };
    const nextState = {
      ...evidenceRef.current,
      records: evidenceRef.current.records.map(item => item.id === latest.id ? publishedRecord : item),
    };
    if (storageBlocked) {
      setFeedback('Resolve the unreadable saved workspace before publishing.');
      return;
    }
    publishing.current.add(latest.id);
    try {
      onPublished(latest.projectId, entries);
    } catch (error) {
      publishing.current.delete(latest.id);
      setFeedback('The project record rejected this publish, so the draft remains unpublished: ' + error.message);
      return;
    }
    const saved = wsSaveEvidenceState(nextState);
    setEvidenceState(nextState);
    if (!saved.ok) {
      setStorageError(saved.error);
      setFeedback('The project record was updated, but its local evidence marker could not be saved. Entry IDs prevent duplicate project updates.');
    } else {
      setFeedback(entries.length + ' update' + (entries.length === 1 ? '' : 's') + ' published from revision ' + latest.revision + '.');
    }
  }

  if (!projects || !projects.length || !activeProject) {
    return (
      <div className="ws-content">
        <div className="ws-callout ws-alert-danger" role="alert">
          No authorized project is available. Evidence actions are disabled.
        </div>
      </div>
    );
  }

  function renderStorageAlert() {
    if (!storageError) return null;
    return (
      <div className={'ws-alert ' + (storageBlocked ? 'ws-alert-danger' : '')} role="alert">
        <strong>Local evidence storage needs attention.</strong>
        <span>{storageError}</span>
        {storageBlocked && (
          <button type="button" className="ws-button ws-button-quiet" onClick={explicitFreshStart}>
            Replace unreadable saved data
          </button>
        )}
      </div>
    );
  }

  function renderManual(record) {
    const editable = !activeProjectReadOnly && record.authorKey === me.k && record.status !== 'published';
    return (
      <div className="ws-panel">
        <div className="ws-page-head">
          <div>
            <p className="ws-subtitle">Manual lab entry · saved locally as you type</p>
            <h2 className="ws-title">Record what happened at the bench</h2>
          </div>
          <span className="ws-badge">{wsStatusLabel(record.status)} · revision {record.revision}</span>
        </div>
        {record.review && record.review.comment && (
          <div className="ws-callout"><strong>Reviewer comment</strong><p>{record.review.comment}</p></div>
        )}
        <label className="ws-field">
          <span>Title <em>required</em></span>
          <input className="ws-input" value={record.title} disabled={!editable}
            onChange={event => updateAuthoredRecord(record.id, current => ({ ...current, title: event.target.value }))}
            placeholder="Round 3 sort-day update" />
        </label>
        <div className="ws-list">
          {WS_MANUAL_FIELDS.map(field => (
            <label key={field[0]} className="ws-field">
              <span>{field[1]}</span>
              <textarea className="ws-textarea" rows="3" value={record.form[field[0]] || ''} disabled={!editable}
                onChange={event => updateAuthoredRecord(record.id, current => ({
                  ...current, form: { ...current.form, [field[0]]: event.target.value },
                }))}
                placeholder={'Describe the ' + field[1].toLowerCase() + ' in enough detail for the next researcher.'} />
            </label>
          ))}
        </div>
        <div className="ws-actions">
          <button className="ws-button ws-button-quiet" type="button" onClick={() => { setSection('write'); setActiveRecordId(null); }}>Back to evidence</button>
          {editable && <button className="ws-button ws-button-primary" type="button" onClick={() => prepareManualReview(record)}>Review entry</button>}
        </div>
      </div>
    );
  }

  function renderSource(record, selected) {
    if (record.kind === 'manual') {
      return (
        <div className="ws-source">
          <div className="ws-source-head"><strong>Manual lab entry</strong><span>Source authored by {record.authorName}</span></div>
          <div className="ws-source-body">
            {WS_MANUAL_FIELDS.filter(field => record.form[field[0]]).map(field => (
              <section key={field[0]}>
                <h4>{field[1]}</h4>
                <p>{record.form[field[0]]}</p>
              </section>
            ))}
          </div>
        </div>
      );
    }
    const file = selected ? record.files.find(item => item.id === selected.sourceId) : record.files[0];
    return (
      <div className="ws-source">
        <div className="ws-source-head">
          <strong className="ws-file-name">{file ? file.name : 'Source excerpt'}</strong>
          <span>{selected ? selected.citation : 'Choose a citation to inspect its passage.'}</span>
        </div>
        <div className="ws-source-body">
          <pre>{selected ? selected.excerpt : 'Select a draft entry to inspect the source text.'}</pre>
        </div>
      </div>
    );
  }

  function renderReview(record) {
    const selected = record.entries.find(entry => entry.id === selectedEntryId) || record.entries[0] || null;
    const canEdit = !activeProjectReadOnly && record.authorKey === me.k && record.status !== 'published';
    const included = record.entries.filter(entry => entry.included && entry.title.trim() && entry.body.trim()).length;
    const canActAsReviewer = !activeProjectReadOnly && reviewer && record.authorKey !== me.k && record.status === 'pending';
    return (
      <div className="ws-panel">
        <div className="ws-page-head">
          <div>
            <p className="ws-subtitle">Grouped change set · {activeProject.code}</p>
            <h2 className="ws-title">{record.title || 'Untitled evidence draft'}</h2>
            <p className="ws-muted">By {record.authorName} · revision {record.revision}</p>
          </div>
          <span className="ws-badge">{wsStatusLabel(record.status)}</span>
        </div>
        <div className="ws-callout">
          <strong>Local preview: organizes text by headings; AI analysis not connected.</strong>
          <p>{record.status === 'published' ? 'This published revision is read only. Its original sources remain available for inspection.' : canEdit ? 'Review and edit each proposed statement. Nothing is published until an explicit approval or publishing action.' : 'Review this exact submitted revision. Request changes if the author needs to revise a statement.'}</p>
        </div>
        {record.review && record.review.comment && (
          <div className="ws-alert"><strong>Changes requested</strong><span>{record.review.comment}</span></div>
        )}
        <div className="ws-switcher" role="group" aria-label="Review pane">
          <button type="button" className={mobilePane === 'source' ? 'active' : ''} onClick={() => setMobilePane('source')}>Source</button>
          <button type="button" className={mobilePane === 'draft' ? 'active' : ''} onClick={() => setMobilePane('draft')}>Draft</button>
        </div>
        <div className="ws-review-grid" data-mobile-view={mobilePane}>
          <section className={'ws-review-source ws-mobile-source ' + (mobilePane === 'source' ? 'active' : '')} aria-label="Original source">
            {renderSource(record, selected)}
          </section>
          <section className={'ws-review-draft ws-mobile-draft ' + (mobilePane === 'draft' ? 'active' : '')} aria-label="Draft entries">
            <div className="ws-list">
              {record.entries.map((entry, index) => (
                <article key={entry.id} className={'ws-draft-card ' + (!entry.included ? 'excluded ' : '') + (entry.uncertain ? 'uncertain' : '')}>
                  <div className="ws-draft-meta">
                    <label className="ws-check">
                      <input type="checkbox" checked={entry.included} disabled={!canEdit}
                        onChange={event => updateEntry(record.id, entry.id, { included: event.target.checked })} />
                      Include entry {index + 1}
                    </label>
                    <button type="button" className="ws-citation" onClick={() => { setSelectedEntryId(entry.id); setMobilePane('source'); }}>
                      {entry.citation || 'Manual source'}
                    </button>
                  </div>
                  {entry.uncertain && <div className="ws-callout"><strong>Type needs review.</strong><p>{entry.uncertaintyReason}</p></div>}
                  <label className="ws-field">
                    <span>Entry type</span>
                    <select className="ws-select" value={entry.type} disabled={!canEdit}
                      onChange={event => updateEntry(record.id, entry.id, { type: event.target.value, uncertain: false, uncertaintyReason: '' })}>
                      {WS_ENTRY_TYPES.map(type => <option key={type[0]} value={type[0]}>{type[1]}</option>)}
                    </select>
                  </label>
                  <label className="ws-field">
                    <span>Proposed statement</span>
                    <input className="ws-input" value={entry.title} disabled={!canEdit}
                      onFocus={() => setSelectedEntryId(entry.id)}
                      onChange={event => updateEntry(record.id, entry.id, { title: event.target.value })} />
                  </label>
                  <label className="ws-field">
                    <span>Supporting detail</span>
                    <textarea className="ws-textarea" rows="4" value={entry.body} disabled={!canEdit}
                      onFocus={() => setSelectedEntryId(entry.id)}
                      onChange={event => updateEntry(record.id, entry.id, { body: event.target.value })} />
                  </label>
                  {(entry.type === 'decision' || entry.type === 'deadend') && (
                    <label className="ws-field">
                      <span>Why</span>
                      <textarea className="ws-textarea" rows="2" value={entry.why || ''} disabled={!canEdit}
                        onChange={event => updateEntry(record.id, entry.id, { why: event.target.value })}
                        placeholder="Explain the rationale or why this failed." />
                    </label>
                  )}
                </article>
              ))}
            </div>
          </section>
        </div>
        <div className="ws-summary-bar">
          <span><strong>{included}</strong> of {record.entries.length} entries will be submitted.</span>
          <span>Excluded entries stay in this local draft.</span>
        </div>
        {canActAsReviewer && (
          <label className="ws-field">
            <span>Reviewer comment</span>
            <textarea className="ws-textarea" rows="3" value={reviewComment} onChange={event => setReviewComment(event.target.value)}
              placeholder="Required when requesting changes." />
          </label>
        )}
        <div className="ws-actions">
          <button className="ws-button ws-button-quiet" type="button" onClick={() => { setActiveRecordId(null); setSection(mode === 'reviews' ? 'reviews' : 'drafts'); }}>Back</button>
          {record.kind === 'manual' && canEdit && <button className="ws-button ws-button-quiet" type="button" onClick={() => setSection('manual')}>Edit lab fields</button>}
          {canEdit && record.status === 'draft' && !reviewer && (
            <button className="ws-button ws-button-primary" type="button" disabled={!included} onClick={() => requestReview(record)}>Request review</button>
          )}
          {canEdit && record.status === 'draft' && reviewer && (
            <button className="ws-button ws-button-primary" type="button" disabled={!included} onClick={() => publishRecord(record, false)}>Publish updates</button>
          )}
          {canActAsReviewer && (
            <>
              <button className="ws-button ws-button-quiet" type="button" onClick={() => requestChanges(record)}>Request changes</button>
              <button className="ws-button ws-button-primary" type="button" disabled={!included} onClick={() => publishRecord(record, true)}>Approve and publish</button>
            </>
          )}
        </div>
      </div>
    );
  }

  function renderWrite() {
    const myDrafts = projectRecords.filter(record => record.authorKey === me.k && record.kind === 'manual' && record.status !== 'published');
    return (
      <div className="ws-panel">
        <div className="ws-page-head">
          <div><p className="ws-subtitle">Write an update</p><h2 className="ws-title">Record lab work without losing the details</h2></div>
          <span className="ws-badge">Local draft</span>
        </div>
        <p className="ws-muted">Only the title and one meaningful field are required. You can leave and resume before review.</p>
        <div className="ws-actions">
          <button className="ws-button ws-button-primary" type="button" onClick={startManualRecord}>Start a lab update</button>
        </div>
        {myDrafts.length > 0 && (
          <div className="ws-list">
            <h3>Resume a manual draft</h3>
            {myDrafts.map(record => (
              <button key={record.id} type="button" className="ws-row" onClick={() => openRecord(record)}>
                <span><strong>{record.title || 'Untitled lab update'}</strong><small>{wsStatusLabel(record.status)} · revision {record.revision}</small></span>
                <span>Open</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  function renderUpload() {
    const ready = uploadFiles.some(file => file.status === 'ready');
    return (
      <div className="ws-panel">
        <div className="ws-page-head">
          <div><p className="ws-subtitle">Upload material</p><h2 className="ws-title">Turn prepared text into cited draft entries</h2></div>
          <span className="ws-badge">{activeProject.code} · authorized project</span>
        </div>
        <div className="ws-callout">
          <strong>Local preview: organizes text by headings; AI analysis not connected.</strong>
          <p>Markdown and plain-text files up to 1 MB are read in this browser. PDF and DOCX conversion is not connected yet.</p>
        </div>
        <label className="ws-upload">
          <input type="file" multiple accept=".md,.txt,.pdf,.docx,text/markdown,text/plain,application/pdf" onChange={event => { addFiles(event.target.files); event.target.value = ''; }} />
          <strong>Add evidence files</strong>
          <span>.md or .txt · maximum 1 MB each</span>
        </label>
        {uploadFiles.length > 0 && (
          <div className="ws-file-list">
            {uploadFiles.map(file => (
              <div key={file.id} className="ws-file">
                <div>
                  <strong className="ws-file-name">{file.name}</strong>
                  <span className="ws-file-meta">{wsFormatBytes(file.size)} · {file.status}</span>
                  {file.duplicateRecordId && (
                    <div className="ws-alert">
                      <span>Possible duplicate of “{file.duplicateName}”.</span>
                      <button className="ws-button ws-button-quiet" type="button" onClick={() => {
                        const previous = evidenceState.records.find(record => record.id === file.duplicateRecordId);
                        if (previous) openRecord(previous);
                      }}>Open previous source</button>
                    </div>
                  )}
                  {file.error && <div className="ws-alert ws-alert-danger" role="alert">{file.error}</div>}
                </div>
                <div className="ws-actions">
                  {file.status === 'failed' && file.recoverable && <button className="ws-button ws-button-quiet" type="button" onClick={() => analyzeFiles([file.id])}>Retry</button>}
                  <button className="ws-button ws-button-quiet" type="button" onClick={() => removeUploadFile(file.id)}>Remove</button>
                </div>
              </div>
            ))}
          </div>
        )}
        <WSEvidenceStages files={uploadFiles} linking={linking} ready={ready} />
        <div className="ws-actions">
          <button className="ws-button ws-button-primary" type="button" disabled={!uploadFiles.some(file => file.status === 'queued' || (file.status === 'failed' && file.recoverable)) || linking}
            onClick={() => analyzeFiles()}>Analyze evidence</button>
          {analysisRecordId && ready && (
            <button className="ws-button ws-button-quiet" type="button" onClick={() => {
              const record = evidenceState.records.find(item => item.id === analysisRecordId);
              if (record) openRecord(record);
            }}>Review cited drafts</button>
          )}
        </div>
      </div>
    );
  }

  function renderDrafts() {
    const drafts = projectRecords.filter(record => record.authorKey === me.k && record.status !== 'published');
    const published = projectRecords.filter(record => record.status === 'published');
    return (
      <div className="ws-panel">
        <div className="ws-page-head"><div><p className="ws-subtitle">Saved locally</p><h2 className="ws-title">Your evidence drafts</h2></div><span className="ws-badge">{drafts.length}</span></div>
        {drafts.length ? (
          <div className="ws-list">
            {drafts.map(record => (
              <button key={record.id} type="button" className="ws-row" onClick={() => openRecord(record)}>
                <span><strong>{record.title || 'Untitled evidence draft'}</strong><small>{record.kind === 'manual' ? 'Manual lab entry' : record.files.length + ' source file(s)'}</small></span>
                <span>{wsStatusLabel(record.status)} · r{record.revision}</span>
              </button>
            ))}
          </div>
        ) : <div className="ws-empty">No drafts for this project yet.</div>}
        <div className="ws-list">
          <h3>Published evidence</h3>
          <p className="ws-muted">Published groups remain available with their original source citations.</p>
          {published.length ? published.map(record => (
            <button key={record.id} type="button" className="ws-row" onClick={() => openRecord(record)}>
              <span><strong>{record.title || 'Untitled evidence group'}</strong><small>{record.authorName} · revision {record.revision} · read only</small></span>
              <span>Inspect sources</span>
            </button>
          )) : <div className="ws-empty">No evidence groups have been published from this local workflow yet.</div>}
        </div>
      </div>
    );
  }

  function renderReviews() {
    const queue = projectRecords.filter(record => record.status === 'pending' || (record.status === 'changes_requested' && record.authorKey === me.k));
    return (
      <div className="ws-panel">
        <div className="ws-page-head">
          <div><p className="ws-subtitle">Project-scoped queue</p><h2 className="ws-title">Evidence reviews</h2></div>
          <span className="ws-badge">{queue.filter(record => record.status === 'pending').length} pending</span>
        </div>
        <div className="ws-callout">
          <strong>Demo capability mapping</strong>
          <p>Students request review. PIs and PhD mentors can approve another author’s submitted revision or request changes. Review is not a publication event until Approve and publish is chosen.</p>
        </div>
        {queue.length ? (
          <div className="ws-list">
            {queue.map(record => {
              const studentReadOnly = !reviewer && record.authorKey !== me.k;
              return (
                <button key={record.id} type="button" className="ws-row" onClick={() => openRecord(record)}>
                  <span><strong>{record.title || 'Untitled evidence draft'}</strong><small>{record.authorName} · revision {record.revision} · {record.entries.filter(entry => entry.included).length} included</small></span>
                  <span>{studentReadOnly ? 'Read only · ' : ''}{wsStatusLabel(record.status)}</span>
                </button>
              );
            })}
          </div>
        ) : <div className="ws-empty">No review requests for this project.</div>}
      </div>
    );
  }

  return (
    <div className="ws-content">
      <div className="ws-page-head">
        <div>
          <p className="ws-subtitle">{mode === 'reviews' ? 'Reviews' : 'Evidence'} · browser-local prototype</p>
          <h1 className="ws-title">{mode === 'reviews' ? 'Review evidence before it becomes official' : 'Add evidence to the research record'}</h1>
        </div>
        <WSEvidenceProjectPicker projects={projects} projectId={projectId} onChange={value => { setProjectId(value); setActiveRecordId(null); setAnalysisRecordId(null); setUploadFiles([]); setSection(mode === 'reviews' ? 'reviews' : 'write'); }} />
      </div>
      {renderStorageAlert()}
      {activeProjectReadOnly && <div className="ws-alert" role="status"><strong>Archived evidence</strong><span>Published evidence and saved drafts remain inspectable. Resume this project before writing, uploading, reviewing, or publishing.</span></div>}
      {feedback && <div className="ws-alert" role="status">{feedback}</div>}
      {mode !== 'reviews' && !activeProjectReadOnly && !['manual', 'review'].includes(section) && (
        <div className="ws-tabs" role="tablist" aria-label="Evidence workspace">
          {[['write', 'Write an update'], ['upload', 'Upload material'], ['drafts', 'Drafts']].map(tab => (
            <button key={tab[0]} type="button" role="tab" aria-selected={section === tab[0]}
              className={'ws-tab ' + (section === tab[0] ? 'active' : '')} onClick={() => setSection(tab[0])}>{tab[1]}</button>
          ))}
        </div>
      )}
      {activeRecord && !authorizedIds.has(activeRecord.projectId) ? (
        <div className="ws-alert ws-alert-danger" role="alert">This saved draft is outside your current authorized projects. It cannot be opened or changed.</div>
      ) : (
        <>
          {section === 'write' && !activeProjectReadOnly && renderWrite()}
          {section === 'upload' && !activeProjectReadOnly && renderUpload()}
          {section === 'drafts' && renderDrafts()}
          {section === 'reviews' && renderReviews()}
          {section === 'manual' && activeRecord && renderManual(activeRecord)}
          {section === 'review' && activeRecord && renderReview(activeRecord)}
        </>
      )}
      <div className="ws-actions">
        {typeof onOpenProject === 'function' && <button className="ws-button ws-button-quiet" type="button" onClick={() => onOpenProject(activeProject.id)}>Open {activeProject.code}</button>}
      </div>
    </div>
  );
}
