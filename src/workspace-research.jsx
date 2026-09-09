/* Project-scoped operational research tracking. Domain helpers load first. */

const WS_RESEARCH_KIND_OPTIONS = [
  ['task', 'Task'],
  ['experiment', 'Experiment'],
  ['milestone', 'Milestone'],
  ['measurement', 'Measurement'],
];
const WS_RESEARCH_STATUS_OPTIONS = [
  ['planned', 'Planned'],
  ['in_progress', 'In progress'],
  ['blocked', 'Blocked'],
  ['completed', 'Completed'],
];

function wsResearchKindLabel(kind) {
  const option = WS_RESEARCH_KIND_OPTIONS.find(item => item[0] === kind);
  return option ? option[1] : kind;
}

function wsResearchStatusLabel(status) {
  const option = WS_RESEARCH_STATUS_OPTIONS.find(item => item[0] === status);
  return option ? option[1] : status;
}

function wsResearchPersonName(people, key) {
  if (!key) return 'Unassigned';
  const person = (people || []).find(candidate => candidate && candidate.k === key);
  return person ? person.n : 'Unknown member';
}

function wsResearchBrowserStorage(browserWindow) {
  try {
    const storage = browserWindow && browserWindow.localStorage;
    if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
      return { ok:false, error:'Local browser research storage is unavailable.' };
    }
    return { ok:true, storage };
  } catch (error) {
    return { ok:false, error:'Local browser research storage is unavailable: ' + (error.message || 'access was blocked') + '.' };
  }
}

function wsResearchLocalDate(now) {
  const date = now || new Date();
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}

function wsResearchNewForm(kind, date) {
  return {
    id:'', revision:'', kind, title:'', ownerKey:'', status:'planned',
    date:date || wsResearchLocalDate(), dueDate:'', notes:'', sourceEntryId:'',
    experimentId:'', metric:'', value:'', unit:'', condition:'',
  };
}

function wsResearchFormFromItem(item) {
  return {
    id:item.id, revision:item.revision, kind:item.kind, title:item.title,
    ownerKey:item.ownerKey, status:item.status, date:item.date, dueDate:item.dueDate,
    notes:item.notes, sourceEntryId:item.sourceEntryId, experimentId:item.experimentId,
    metric:item.metric, value:item.kind === 'measurement' ? String(item.value) : '',
    unit:item.unit, condition:item.condition,
  };
}

function wsResearchBuildInput(form, projectId) {
  if (!form || typeof form !== 'object') return { ok:false, error:'The research form is unavailable.', errorField:'' };
  if (form.kind === 'measurement' && (typeof form.value !== 'string' || form.value.trim() === '')) {
    return { ok:false, error:'Measurement value is required.', errorField:'value' };
  }
  let value = null;
  if (form.kind === 'measurement') {
    value = Number(form.value);
    if (!Number.isFinite(value)) return { ok:false, error:'Measurement value must be a finite number.', errorField:'value' };
  }
  const input = {
    projectId,
    kind:form.kind,
    title:form.title,
    ownerKey:form.ownerKey,
    status:form.status,
    date:form.date,
    dueDate:form.dueDate,
    notes:form.notes,
    sourceEntryId:form.sourceEntryId,
    experimentId:form.experimentId,
    metric:form.metric,
    value,
    unit:form.unit,
    condition:form.condition,
  };
  if (form.id) {
    input.id = form.id;
    input.revision = form.revision;
  }
  return { ok:true, input };
}

function wsResearchErrorField(error) {
  const value = String(error || '').toLowerCase();
  if (value.includes('title')) return 'title';
  if (value.includes('owner')) return 'ownerKey';
  if (value.includes('due date')) return 'dueDate';
  if (value.includes('date')) return 'date';
  if (value.includes('metric')) return 'metric';
  if (value.includes('value') || value.includes('number') || value.includes('finite')) return 'value';
  if (value.includes('unit')) return 'unit';
  if (value.includes('condition')) return 'condition';
  if (value.includes('source')) return 'sourceEntryId';
  if (value.includes('experiment')) return 'experimentId';
  if (value.includes('status')) return 'status';
  return '';
}

function wsResearchCommit(storage, form, me, project, people, now) {
  const fresh = wsResearchRead(storage);
  if (fresh.error) return { ok:false, error:fresh.error, state:fresh.state, blocked:true };
  const built = wsResearchBuildInput(form, project.id);
  if (!built.ok) return { ...built, state:fresh.state, blocked:false };
  const saved = wsResearchSave(fresh.state, built.input, me, project, people, now);
  if (!saved.ok) {
    return { ...saved, state:fresh.state, blocked:false, errorField:wsResearchErrorField(saved.error) };
  }
  try {
    storage.setItem(WS_RESEARCH_STORAGE_KEY, JSON.stringify(saved.state));
  } catch (error) {
    return {
      ok:false,
      error:'Research tracking could not be saved locally: ' + (error.message || 'the write failed') + '.',
      state:fresh.state,
      blocked:false,
    };
  }
  return { ...saved, blocked:false };
}

function wsResearchExportPayload(storage, projectId, people, format) {
  const fresh = wsResearchRead(storage);
  if (fresh.error) return { ok:false, error:fresh.error, blocked:true };
  try {
    if (format === 'csv') {
      return {
        ok:true,
        content:wsResearchCsv(wsResearchCurrent(fresh.state, projectId), people),
        type:'text/csv;charset=utf-8',
        extension:'csv',
      };
    }
    if (format === 'json') {
      return {
        ok:true,
        content:wsResearchJson(fresh.state, projectId),
        type:'application/json;charset=utf-8',
        extension:'json',
      };
    }
    return { ok:false, error:'Choose CSV or JSON research export.', blocked:false };
  } catch (error) {
    return { ok:false, error:error.message || 'Research export failed.', blocked:false };
  }
}

function wsResearchMeasurementSeries(items) {
  const groups = new Map();
  (items || []).forEach(item => {
    if (!item || item.kind !== 'measurement' || typeof item.value !== 'number' || !Number.isFinite(item.value)) return;
    const key = JSON.stringify([item.metric, item.unit, item.condition, item.experimentId]);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        metric:item.metric,
        unit:item.unit,
        condition:item.condition,
        experimentId:item.experimentId,
        items:[],
      });
    }
    groups.get(key).items.push(item);
  });
  const output = Array.from(groups.values());
  output.forEach(group => group.items.sort((a, b) => String(a.date).localeCompare(String(b.date)) || String(a.updatedAt).localeCompare(String(b.updatedAt))));
  return output.sort((a, b) => [a.metric, a.unit, a.condition, a.experimentId].join('\n').localeCompare([b.metric, b.unit, b.condition, b.experimentId].join('\n')));
}

function wsResearchSeriesLabel(series, items) {
  if (!series) return '';
  const experiment = (items || []).find(item => item.id === series.experimentId);
  return series.metric + ' (' + series.unit + ') - ' + series.condition + ' - ' + (experiment ? experiment.title : 'No related experiment');
}

function wsResearchHistorySnapshot(item, people) {
  return {
    revision:item.revision,
    title:item.title,
    kind:wsResearchKindLabel(item.kind),
    owner:wsResearchPersonName(people, item.ownerKey),
    status:wsResearchStatusLabel(item.status),
    date:item.date,
    dueDate:item.dueDate,
    notes:item.notes,
    measurement:item.kind === 'measurement' ? item.metric + ': ' + item.value + ' ' + item.unit : '',
    condition:item.condition,
    sourceEntryId:item.sourceEntryId,
    experimentId:item.experimentId,
    updatedBy:wsResearchPersonName(people, item.updatedBy),
    updatedAt:item.updatedAt,
  };
}

function wsResearchSourceSnapshot(entry) {
  return {
    title:entry && entry.h ? entry.h : '',
    body:entry && entry.b ? entry.b : '',
    rationale:entry && entry.why ? entry.why : '',
    date:entry && entry.d ? entry.d : '',
    author:entry && entry.au ? entry.au : '',
  };
}

function wsResearchPlotModel(series) {
  const items = series && Array.isArray(series.items) ? series.items : [];
  if (!items.length) return { points:[], valueTicks:[], dateTicks:[] };
  const values = items.map(item => item.value);
  const stamps = items.map(item => Date.parse(item.date + 'T00:00:00Z'));
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const minStamp = Math.min(...stamps);
  const maxStamp = Math.max(...stamps);
  const xFor = stamp => minStamp === maxStamp ? 300 : 34 + ((stamp - minStamp) / (maxStamp - minStamp)) * 532;
  const yFor = value => minValue === maxValue ? 100 : 178 - ((value - minValue) / (maxValue - minValue)) * 142;
  return {
    points:items.map(item => ({ id:item.id, x:xFor(Date.parse(item.date + 'T00:00:00Z')), y:yFor(item.value) })),
    valueTicks:minValue === maxValue
      ? [{ value:minValue, y:100 }]
      : [{ value:maxValue, y:36 }, { value:minValue, y:178 }],
    dateTicks:minStamp === maxStamp
      ? [{ value:items[0].date, x:34, anchor:'start' }]
      : [{ value:items[0].date, x:34, anchor:'start' }, { value:items[items.length - 1].date, x:576, anchor:'end' }],
  };
}

function wsResearchDownload(content, type, fileName) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function WsResearchPlot({ series }) {
  if (!series || !series.items.length) return null;
  const model = wsResearchPlotModel(series);
  return (
    <div className="ws-research-plot">
      <svg viewBox="0 0 600 220" role="img" aria-label={'Raw scatter plot of ' + series.metric + ' in ' + series.unit + ' under ' + series.condition}>
        <path className="ws-research-axis" d="M34 18V178H576" />
        {model.valueTicks.map(tick => <text key={'value-' + tick.value + '-' + tick.y} x="30" y={tick.y + 4}>{tick.value}</text>)}
        {model.dateTicks.map(tick => <text key={'date-' + tick.value + '-' + tick.x} x={tick.x} y="214" textAnchor={tick.anchor}>{tick.value}</text>)}
        {series.items.map((item, index) => (
          <circle key={item.id} cx={model.points[index].x} cy={model.points[index].y} r="6">
            <title>{item.date + ': ' + item.value + ' ' + item.unit + ', ' + item.condition}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

function ResearchProjectSummary({ project, me, onOpen }) {
  if (!wsResearchHasProjectAccess(me, project)) return null;
  const readOnly = project.status === 'stashed' || project.status === 'archived';
  const storageResult = wsResearchBrowserStorage(typeof window === 'undefined' ? null : window);
  const read = storageResult.ok ? wsResearchRead(storageResult.storage) : { state:wsResearchEmpty(), error:storageResult.error };
  if (read.error) {
    return (
      <section className="ws-research-summary ws-alert-danger" aria-label="Research tracking summary">
        <div><h2>Team-entered research tracking</h2><p>{read.error} Tracking actions are blocked; saved data was not changed.</p></div>
        <button type="button" className="ws-button ws-button-quiet" onClick={onOpen}>Open Research</button>
      </section>
    );
  }
  const summary = wsResearchSummary(wsResearchCurrent(read.state, project.id));
  return (
    <section className="ws-research-summary" aria-label="Research tracking summary">
      <div className="ws-research-summary-copy">
        <div className="ws-kicker">Team-entered operational tracking</div>
        <h2>Research activity</h2>
        <p>Work and measurements recorded by the team are separate from reviewed scientific findings.</p>
      </div>
      {summary.workTotal || summary.measurementTotal ? (
        <div className="ws-research-summary-stats">
          <div><strong>{summary.completed}/{summary.workTotal}</strong><span>Tracked work completed</span></div>
          <div><strong>{summary.inProgress}</strong><span>In progress</span></div>
          <div><strong>{summary.blocked}</strong><span>Blocked</span></div>
          <div><strong>{summary.measurementTotal}</strong><span>Measurements</span></div>
        </div>
      ) : <p className="ws-research-summary-empty">{readOnly ? 'No operational tracking records were archived for this project.' : 'No operational tracking records yet. Add the first task, experiment, milestone, or measurement.'}</p>}
      <button type="button" className="ws-button ws-button-quiet" onClick={onOpen}>{readOnly || summary.workTotal || summary.measurementTotal ? 'Open Research' : 'Add first record'}</button>
    </section>
  );
}

function ResearchProjectWorkspace({ project, me, people }) {
  const readOnly = project.status === 'stashed' || project.status === 'archived';
  const initialRef = React.useRef(null);
  if (initialRef.current === null) {
    const storageResult = wsResearchBrowserStorage(typeof window === 'undefined' ? null : window);
    initialRef.current = storageResult.ok
      ? { ...wsResearchRead(storageResult.storage), storage:storageResult.storage }
      : { state:wsResearchEmpty(), error:storageResult.error, storage:null };
  }
  const [researchState, setResearchState] = React.useState(initialRef.current.state);
  const [storageError, setStorageError] = React.useState(initialRef.current.error || '');
  const [storageBlocked, setStorageBlocked] = React.useState(!!initialRef.current.error);
  const [form, setForm] = React.useState(null);
  const [formError, setFormError] = React.useState('');
  const [errorField, setErrorField] = React.useState('');
  const [feedback, setFeedback] = React.useState('');
  const [selectedSeriesKey, setSelectedSeriesKey] = React.useState('');
  const fieldRefs = React.useRef({});
  const formErrorRef = React.useRef(null);
  const storageAlertRef = React.useRef(null);
  const items = React.useMemo(() => wsResearchCurrent(researchState, project.id), [researchState, project.id]);
  const summary = React.useMemo(() => wsResearchSummary(items), [items]);
  const workItems = React.useMemo(() => items.filter(item => item.kind !== 'measurement').sort((a, b) => String(b.date).localeCompare(String(a.date))), [items]);
  const measurements = React.useMemo(() => items.filter(item => item.kind === 'measurement').sort((a, b) => String(b.date).localeCompare(String(a.date))), [items]);
  const seriesGroups = React.useMemo(() => wsResearchMeasurementSeries(measurements), [measurements]);
  const selectedSeries = seriesGroups.find(series => series.key === selectedSeriesKey) || seriesGroups[0] || null;
  const approvedSources = (project.log || []).filter(entry => entry && entry.id && entry.ack !== false);
  const experiments = items.filter(item => item.kind === 'experiment' && (!form || item.id !== form.id));
  const members = (people || []).filter(person => person && person.tier !== 'partner' && (person.scope === 'all' || (person.projects || []).includes(project.id)));
  const selectedSource = form ? approvedSources.find(entry => entry.id === form.sourceEntryId) : null;

  React.useEffect(() => {
    if (!seriesGroups.length) {
      if (selectedSeriesKey) setSelectedSeriesKey('');
      return;
    }
    if (!seriesGroups.some(series => series.key === selectedSeriesKey)) setSelectedSeriesKey(seriesGroups[0].key);
  }, [seriesGroups, selectedSeriesKey]);

  React.useEffect(() => {
    if (!formError) return;
    const target = errorField && fieldRefs.current[errorField] ? fieldRefs.current[errorField] : formErrorRef.current;
    if (target && typeof target.focus === 'function') target.focus();
  }, [formError, errorField]);

  React.useEffect(() => {
    if (storageError && storageAlertRef.current && typeof storageAlertRef.current.focus === 'function') storageAlertRef.current.focus();
  }, [storageError]);

  function focusError(field) {
    const target = field && fieldRefs.current[field] ? fieldRefs.current[field] : formErrorRef.current;
    if (target && typeof target.focus === 'function') target.focus();
  }

  function startCreate(kind) {
    if (readOnly) {
      setFeedback('This project is stashed. Its research tracking is read only until the project is resumed.');
      return;
    }
    if (storageBlocked) {
      setFeedback('Research actions are blocked until local storage can be read safely.');
      return;
    }
    setForm(wsResearchNewForm(kind, wsResearchLocalDate()));
    setFormError('');
    setErrorField('');
    setFeedback('');
  }

  function startEdit(item) {
    if (!wsResearchCanEdit(item, me, project)) {
      setFeedback('Only the original author, the assigned operational owner, or a PI/PhD reviewer can edit this item.');
      return;
    }
    setForm(wsResearchFormFromItem(item));
    setFormError('');
    setErrorField('');
    setFeedback('');
  }

  function updateForm(field, value) {
    setForm(current => ({ ...current, [field]:value }));
    if (errorField === field) {
      setErrorField('');
      setFormError('');
    }
  }

  function saveForm(event) {
    event.preventDefault();
    if (readOnly) {
      setFormError('This project is stashed. Resume it before changing research tracking.');
      focusError('');
      return;
    }
    if (!wsResearchHasProjectAccess(me, project)) {
      setFormError('This project is not available to the current identity. No change was made.');
      focusError('');
      return;
    }
    const storageResult = wsResearchBrowserStorage(typeof window === 'undefined' ? null : window);
    if (!storageResult.ok) {
      setStorageError(storageResult.error);
      setStorageBlocked(true);
      setFormError(storageResult.error);
      focusError('');
      return;
    }
    const result = wsResearchCommit(storageResult.storage, form, me, project, people, new Date().toISOString());
    if (!result.ok) {
      if (result.state) setResearchState(result.state);
      setStorageBlocked(!!result.blocked);
      if (result.blocked) setStorageError(result.error);
      setFormError(result.error);
      setErrorField(result.errorField || '');
      focusError(result.errorField || '');
      return;
    }
    setResearchState(result.state);
    setStorageError('');
    setStorageBlocked(false);
    setForm(null);
    setFormError('');
    setErrorField('');
    setFeedback((result.item.revision === 1 ? 'Created ' : 'Saved revision ' + result.item.revision + ' of ') + result.item.title + '.');
  }

  function exportRecords(format) {
    if (!wsResearchHasProjectAccess(me, project)) {
      setFeedback('This project is not available to the current identity. Nothing was exported.');
      return;
    }
    const storageResult = wsResearchBrowserStorage(typeof window === 'undefined' ? null : window);
    if (!storageResult.ok) {
      setStorageError(storageResult.error);
      setStorageBlocked(true);
      return;
    }
    const result = wsResearchExportPayload(storageResult.storage, project.id, people, format);
    if (!result.ok) {
      setStorageError(result.error);
      setStorageBlocked(!!result.blocked);
      return;
    }
    const stem = String(project.code || project.id || 'project').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    try {
      wsResearchDownload(result.content, result.type, stem + '-browser-local-research.' + result.extension);
      setFeedback(format === 'csv' ? 'Exported current project tracking as CSV.' : 'Exported project revision history as JSON.');
    } catch (error) {
      setFeedback('The browser could not create the research download: ' + (error.message || 'download failed') + '.');
    }
  }

  function renderHistory(item) {
    const revisions = researchState.revisions.filter(revision => revision.id === item.id).slice().reverse();
    return (
      <details className="ws-research-history">
        <summary>Revision history ({revisions.length})</summary>
        <ol>
          {revisions.map(revision => (
            <li key={revision.id + ':' + revision.revision}>
              {(() => { const snapshot = wsResearchHistorySnapshot(revision, people); const source = approvedSources.find(entry => entry.id === snapshot.sourceEntryId); const experiment = items.find(candidate => candidate.id === snapshot.experimentId); return <><strong>Revision {snapshot.revision}: {snapshot.title}</strong><span>{snapshot.kind} - {snapshot.status} - owner: {snapshot.owner}</span><span>Work or observation date: {snapshot.date}{snapshot.dueDate ? ' - due ' + snapshot.dueDate : ''}</span>{snapshot.measurement && <span>{snapshot.measurement} - condition: {snapshot.condition}</span>}{snapshot.sourceEntryId && <span>Approved source: {source ? source.h : snapshot.sourceEntryId}</span>}{snapshot.experimentId && <span>Related experiment: {experiment ? experiment.title : snapshot.experimentId}</span>}<span>Updated by {snapshot.updatedBy} on {new Date(snapshot.updatedAt).toLocaleString()}</span>{snapshot.notes && <p>{snapshot.notes}</p>}</>; })()}
            </li>
          ))}
        </ol>
      </details>
    );
  }

  if (!wsResearchHasProjectAccess(me, project)) {
    return <div className="ws-alert ws-alert-danger" role="alert">This project is not available to the current identity. Research tracking is read only and cannot be exported.</div>;
  }

  return (
    <div className="ws-research-workspace">
      <WsPageHead
        eyebrow="Team-entered operational tracking"
        title="Research"
        subtitle="Plan work, record responsibility, and enter measurements explicitly. These records are browser-local and are not reviewed scientific findings."
        actions={<><button type="button" className="ws-button ws-button-quiet" onClick={() => exportRecords('csv')}>Export CSV</button><button type="button" className="ws-button ws-button-quiet" onClick={() => exportRecords('json')}>Export history JSON</button></>}
      />
      {storageError && <div className="ws-alert ws-alert-danger" role="alert" tabIndex="-1" ref={storageAlertRef}><strong>Local research storage needs attention.</strong><span>{storageError}</span><span>Saved data was not replaced. Save and export actions are blocked when the stored state cannot be read.</span></div>}
      {readOnly && <div className="ws-alert" role="status"><strong>Archived research tracking</strong><span>This record remains searchable and exportable, but it cannot be changed while the project is stashed.</span></div>}
      {feedback && <div className="ws-alert" role="status">{feedback}</div>}

      {!readOnly && <section className="ws-research-create" aria-label="Create a research tracking record">
        <div><h2>Add team-entered tracking</h2><p>Enter only work or measurements the team explicitly recorded. Publishing research knowledge still happens through Add evidence.</p></div>
        <div className="ws-actions">
          {WS_RESEARCH_KIND_OPTIONS.map(option => <button type="button" className="ws-button" disabled={storageBlocked} key={option[0]} onClick={() => startCreate(option[0])}>Add {option[1].toLowerCase()}</button>)}
        </div>
      </section>}

      {form && !readOnly && (
        <form className="ws-panel ws-research-form" onSubmit={saveForm} noValidate>
          <div className="ws-panel-head"><div><div className="ws-kicker">{form.id ? 'Edit creates a new immutable revision' : 'New tracking record'}</div><h2>{form.id ? 'Edit ' + wsResearchKindLabel(form.kind).toLowerCase() : 'Add ' + wsResearchKindLabel(form.kind).toLowerCase()}</h2></div>{form.id && <WsBadge>Revision {form.revision}</WsBadge>}</div>
          <div className="ws-panel-body">
            {formError && <div id="ws-research-form-error" className="ws-alert ws-alert-danger" role="alert" tabIndex="-1" ref={formErrorRef}>{formError}</div>}
            <div className="ws-research-form-grid">
              <label className="ws-field"><span>Record type</span><select className="ws-select" value={form.kind} disabled={!!form.id} onChange={event => updateForm('kind', event.target.value)}>{WS_RESEARCH_KIND_OPTIONS.map(option => <option key={option[0]} value={option[0]}>{option[1]}</option>)}</select></label>
              <label className="ws-field ws-research-span-two"><span>Title</span><input ref={node => { fieldRefs.current.title = node; }} aria-invalid={errorField === 'title'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" value={form.title} onChange={event => updateForm('title', event.target.value)} required /></label>
              <label className="ws-field"><span>Owner</span><select ref={node => { fieldRefs.current.ownerKey = node; }} aria-invalid={errorField === 'ownerKey'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-select" value={form.ownerKey} onChange={event => updateForm('ownerKey', event.target.value)}><option value="">Unassigned</option>{members.map(person => <option key={person.k} value={person.k}>{person.n}</option>)}</select></label>
              <label className="ws-field"><span>Status</span><select ref={node => { fieldRefs.current.status = node; }} aria-invalid={errorField === 'status'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-select" value={form.status} onChange={event => updateForm('status', event.target.value)}>{WS_RESEARCH_STATUS_OPTIONS.map(option => <option key={option[0]} value={option[0]}>{option[1]}</option>)}</select></label>
              <label className="ws-field"><span>{form.kind === 'measurement' ? 'Observation date' : 'Work date'}</span><input ref={node => { fieldRefs.current.date = node; }} aria-invalid={errorField === 'date'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" type="date" value={form.date} onChange={event => updateForm('date', event.target.value)} required /></label>
              <label className="ws-field"><span>Due date <small>optional</small></span><input ref={node => { fieldRefs.current.dueDate = node; }} aria-invalid={errorField === 'dueDate'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" type="date" value={form.dueDate} onChange={event => updateForm('dueDate', event.target.value)} /></label>
              {form.kind === 'measurement' && <>
                <label className="ws-field"><span>Metric</span><input ref={node => { fieldRefs.current.metric = node; }} aria-invalid={errorField === 'metric'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" value={form.metric} onChange={event => updateForm('metric', event.target.value)} required /></label>
                <label className="ws-field"><span>Value</span><input ref={node => { fieldRefs.current.value = node; }} aria-invalid={errorField === 'value'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" type="number" step="any" value={form.value} onChange={event => updateForm('value', event.target.value)} required /></label>
                <label className="ws-field"><span>Unit</span><input ref={node => { fieldRefs.current.unit = node; }} aria-invalid={errorField === 'unit'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" value={form.unit} onChange={event => updateForm('unit', event.target.value)} placeholder="Use dimensionless when appropriate" required /></label>
                <label className="ws-field"><span>Condition</span><input ref={node => { fieldRefs.current.condition = node; }} aria-invalid={errorField === 'condition'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-input" value={form.condition} onChange={event => updateForm('condition', event.target.value)} required /></label>
              </>}
              <label className="ws-field"><span>Approved source {form.kind !== 'measurement' && <small>optional</small>}</span><select ref={node => { fieldRefs.current.sourceEntryId = node; }} aria-invalid={errorField === 'sourceEntryId'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-select" value={form.sourceEntryId} onChange={event => updateForm('sourceEntryId', event.target.value)} required={form.kind === 'measurement'}><option value="">{form.kind === 'measurement' ? 'Choose approved evidence' : 'No linked source'}</option>{approvedSources.map(entry => <option key={entry.id} value={entry.id}>{entry.h}</option>)}</select></label>
              <label className="ws-field"><span>Related experiment <small>optional</small></span><select ref={node => { fieldRefs.current.experimentId = node; }} aria-invalid={errorField === 'experimentId'} aria-describedby={formError ? 'ws-research-form-error' : undefined} className="ws-select" value={form.experimentId} onChange={event => updateForm('experimentId', event.target.value)}><option value="">No related experiment</option>{experiments.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
              <label className="ws-field ws-research-span-two"><span>Notes <small>optional</small></span><textarea className="ws-textarea" value={form.notes} onChange={event => updateForm('notes', event.target.value)} rows="4" /></label>
            </div>
            {selectedSource && <details className="ws-research-source-preview"><summary>Preview approved source: {selectedSource.h}</summary><div><p>{selectedSource.b}</p>{selectedSource.why && <p><strong>Rationale:</strong> {selectedSource.why}</p>}<span className="ws-meta">{selectedSource.d} - {selectedSource.au}</span></div></details>}
            <div className="ws-actions"><button type="button" className="ws-button ws-button-quiet" onClick={() => { setForm(null); setFormError(''); setErrorField(''); }}>Cancel</button><button type="submit" className="ws-button ws-button-primary" disabled={storageBlocked}>{form.id ? 'Save new revision' : 'Save tracking record'}</button></div>
          </div>
        </form>
      )}

      <section className="ws-research-status" aria-labelledby="research-status-title">
        <div className="ws-research-section-head"><div><div className="ws-kicker">Operational counts, not a research score</div><h2 id="research-status-title">Work status</h2></div><span className="ws-meta">{summary.completed} of {summary.workTotal} tracked work items completed</span></div>
        {summary.workTotal ? <><div className="ws-research-status-bars" role="list">{WS_RESEARCH_STATUS_OPTIONS.map(option => { const count = option[0] === 'in_progress' ? summary.inProgress : summary[option[0]]; return <div role="listitem" className="ws-research-status-row" key={option[0]}><span>{option[1]}</span><span className="ws-research-status-track" aria-hidden="true"><span data-status={option[0]} style={{ width:(summary.workTotal ? count / summary.workTotal * 100 : 0) + '%' }} /></span><strong>{count}</strong></div>; })}</div><div className="ws-list ws-research-work-list">{workItems.map(item => <article className="ws-row" key={item.id}><div className="ws-row-main"><div className="ws-inline ws-meta"><WsBadge>{wsResearchKindLabel(item.kind)}</WsBadge><span>{wsResearchStatusLabel(item.status)}</span><span>{item.date}</span><span>{wsResearchPersonName(people, item.ownerKey)}</span></div><strong>{item.title}</strong>{item.dueDate && <p>Due {item.dueDate}</p>}{item.notes && <p>{item.notes}</p>}{renderHistory(item)}</div>{wsResearchCanEdit(item, me, project) && <button type="button" className="ws-button ws-button-quiet" onClick={() => startEdit(item)}>Edit</button>}</article>)}</div></> : <div className="ws-empty">No tasks, experiments, or milestones are recorded. Add the first work item without estimating a completion score.</div>}
      </section>

      <section className="ws-panel" aria-labelledby="research-responsibility-title">
        <div className="ws-panel-head"><div><div className="ws-kicker">Explicit responsibility</div><h2 id="research-responsibility-title">Team responsibility</h2></div></div>
        {summary.byOwner.length ? <div className="ws-research-responsibility">{summary.byOwner.map(owner => <div key={owner.ownerKey || 'unassigned'}><strong>{wsResearchPersonName(people, owner.ownerKey)}</strong><span>{owner.total} tracked work item{owner.total === 1 ? '' : 's'}</span><span>{owner.completed} completed - {owner.blocked} blocked</span></div>)}</div> : <div className="ws-empty">Responsibility appears after the team records work. Unassigned work will remain visibly labeled Unassigned.</div>}
      </section>

      <section className="ws-panel" aria-labelledby="research-measurements-title">
        <div className="ws-panel-head"><div><div className="ws-kicker">Team-entered, not reviewed findings</div><h2 id="research-measurements-title">Measurements</h2></div><WsBadge>{measurements.length} recorded</WsBadge></div>
        {measurements.length ? <><div className="ws-table-wrap" tabIndex="0" role="region" aria-label="Project measurements table"><table className="ws-table ws-research-table"><caption>All explicit project measurements. This table is the accessible equivalent of the selected raw scatter plot.</caption><thead><tr><th>Date</th><th>Metric and value</th><th>Condition</th><th>Experiment</th><th>Approved source</th><th>Status</th><th>Action</th></tr></thead><tbody>{measurements.map(item => { const experiment = items.find(candidate => candidate.id === item.experimentId); const source = approvedSources.find(entry => entry.id === item.sourceEntryId); const sourceSnapshot = source ? wsResearchSourceSnapshot(source) : null; return <tr key={item.id}><td>{item.date}</td><td><strong>{item.metric}</strong><br />{item.value} {item.unit}</td><td>{item.condition}</td><td>{experiment ? experiment.title : 'Not linked'}</td><td>{sourceSnapshot ? <details className="ws-research-table-source"><summary>{sourceSnapshot.title}</summary><p>{sourceSnapshot.body}</p>{sourceSnapshot.rationale && <p><strong>Rationale:</strong> {sourceSnapshot.rationale}</p>}<span className="ws-meta">{sourceSnapshot.date} - {sourceSnapshot.author}</span></details> : item.sourceEntryId}</td><td>{wsResearchStatusLabel(item.status)}</td><td>{wsResearchCanEdit(item, me, project) ? <button type="button" className="ws-link" onClick={() => startEdit(item)}>Edit</button> : 'Read only'}{renderHistory(item)}</td></tr>; })}</tbody></table></div><div className="ws-research-series"><div className="ws-research-section-head"><div><h3>Selected raw series</h3><p className="ws-meta">Only records with the exact same metric, unit, condition, and related experiment appear together.</p></div><label className="ws-field"><span>Series</span><select className="ws-select" value={selectedSeries ? selectedSeries.key : ''} onChange={event => setSelectedSeriesKey(event.target.value)}>{seriesGroups.map(series => <option key={series.key} value={series.key}>{wsResearchSeriesLabel(series, items)}</option>)}</select></label></div>{selectedSeries && <><p className="ws-meta">{selectedSeries.items.length} raw measurement{selectedSeries.items.length === 1 ? '' : 's'} - no averaging or incompatible-unit aggregation.</p><WsResearchPlot series={selectedSeries} /></>}</div></> : <div className="ws-empty">No measurements are recorded. Enter a value, unit, condition, date, and approved source explicitly; nothing is extracted from prose.</div>}
      </section>
    </div>
  );
}
