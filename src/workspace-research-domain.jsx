const WS_RESEARCH_STORAGE_KEY = 'uri.research.v1';
const WS_RESEARCH_KINDS = ['task', 'experiment', 'milestone', 'measurement'];
const WS_RESEARCH_STATUSES = ['planned', 'in_progress', 'blocked', 'completed'];
const WS_RESEARCH_TRACKING_STATUS = 'Team-entered operational tracking; not reviewed scientific findings';
let wsResearchIdCounter = 0;

function wsResearchEmpty() {
  return { version: 1, revisions: [] };
}

function wsResearchIsObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function wsResearchNonblank(value) {
  return typeof value === 'string' && value.trim() !== '';
}

function wsResearchDateValid(value, optional) {
  if (optional && value === '') return true;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parts = value.split('-').map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  return date.getUTCFullYear() === parts[0]
    && date.getUTCMonth() === parts[1] - 1
    && date.getUTCDate() === parts[2];
}

function wsResearchInstantValid(value) {
  if (typeof value !== 'string') return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

function wsResearchRevisionError(item) {
  if (!wsResearchIsObject(item)) return 'Each revision must be an object.';
  if (!wsResearchNonblank(item.id)) return 'Each revision needs a stable item ID.';
  if (!Number.isInteger(item.revision) || item.revision < 1) return 'Revision numbers must be positive integers.';
  if (!wsResearchNonblank(item.projectId)) return 'Each revision needs a project ID.';
  if (!WS_RESEARCH_KINDS.includes(item.kind)) return 'Each revision has an invalid kind.';
  if (!wsResearchNonblank(item.title)) return 'Each revision needs a title.';
  if (typeof item.ownerKey !== 'string') return 'Each revision has an invalid owner.';
  if (!WS_RESEARCH_STATUSES.includes(item.status)) return 'Each revision has an invalid status.';
  if (!wsResearchDateValid(item.date, false)) return 'Each revision needs a valid date.';
  if (!wsResearchDateValid(item.dueDate, true)) return 'Each revision has an invalid due date.';
  if (typeof item.notes !== 'string') return 'Each revision has invalid notes.';
  if (typeof item.sourceEntryId !== 'string') return 'Each revision has an invalid source entry ID.';
  if (typeof item.experimentId !== 'string') return 'Each revision has an invalid experiment ID.';
  if (typeof item.metric !== 'string') return 'Each revision has an invalid metric.';
  if (typeof item.unit !== 'string') return 'Each revision has an invalid unit.';
  if (typeof item.condition !== 'string') return 'Each revision has an invalid condition.';
  if (item.kind === 'measurement') {
    if (typeof item.value !== 'number' || !Number.isFinite(item.value)) return 'Measurement values must be finite numbers.';
    if (!wsResearchNonblank(item.metric)) return 'Measurements need a metric.';
    if (!wsResearchNonblank(item.unit)) return 'Measurements need a unit.';
    if (!wsResearchNonblank(item.condition)) return 'Measurements need a condition.';
    if (!wsResearchNonblank(item.sourceEntryId)) return 'Measurements need a source entry ID.';
  } else if (item.value !== null) {
    return 'Nonmeasurement values must be null.';
  }
  if (!wsResearchNonblank(item.authorKey)) return 'Each revision needs an original author.';
  if (!wsResearchNonblank(item.updatedBy)) return 'Each revision needs an updating author.';
  if (!wsResearchInstantValid(item.updatedAt)) return 'Each revision needs a valid update timestamp.';
  return '';
}

function wsResearchValidate(state) {
  try {
    if (!wsResearchIsObject(state)) return { ok: false, error: 'Research state must be an object.' };
    if (state.version !== 1) return { ok: false, error: 'Unsupported research state version.' };
    if (!Array.isArray(state.revisions)) return { ok: false, error: 'Research revisions must be an array.' };

    const chains = new Map();
    for (const item of state.revisions) {
      const itemError = wsResearchRevisionError(item);
      if (itemError) return { ok: false, error: itemError };

      const previous = chains.get(item.id);
      if (!previous) {
        if (item.revision !== 1) return { ok: false, error: 'Every revision chain must begin at revision 1.' };
      } else {
        if (item.revision !== previous.revision + 1) {
          return { ok: false, error: 'Revision chains must be contiguous and cannot contain duplicates.' };
        }
        if (item.projectId !== previous.projectId || item.kind !== previous.kind || item.authorKey !== previous.authorKey) {
          return { ok: false, error: 'A revision chain cannot change project, kind, or original author.' };
        }
        if (new Date(item.updatedAt).getTime() < new Date(previous.updatedAt).getTime()) {
          return { ok: false, error: 'Revision timestamps cannot move backward.' };
        }
      }
      chains.set(item.id, item);
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: 'Research state contains an unreadable value.' };
  }
}

function wsResearchRead(storage) {
  const empty = wsResearchEmpty();
  try {
    if (!storage || typeof storage.getItem !== 'function') {
      return { state: empty, error: 'Research storage is unavailable.' };
    }
    const raw = storage.getItem(WS_RESEARCH_STORAGE_KEY);
    if (raw === null) return { state: empty, error: null };
    if (typeof raw !== 'string') return { state: empty, error: 'Stored research data is malformed.' };
    const state = JSON.parse(raw);
    const validation = wsResearchValidate(state);
    if (!validation.ok) return { state: empty, error: 'Stored research data is invalid: ' + validation.error };
    return { state, error: null };
  } catch (error) {
    const detail = error && typeof error.message === 'string' ? ': ' + error.message : '';
    return { state: empty, error: 'Could not read stored research data' + detail + '.' };
  }
}

function wsResearchCurrent(state, projectId) {
  if (!wsResearchValidate(state).ok || !wsResearchNonblank(projectId)) return [];
  const latest = new Map();
  state.revisions.forEach(item => {
    if (item.projectId === projectId) latest.set(item.id, item);
  });
  return Array.from(latest.values());
}

function wsResearchHasProjectAccess(me, project) {
  if (!wsResearchIsObject(me) || !wsResearchIsObject(project) || !wsResearchNonblank(project.id)) return false;
  if (me.tier === 'partner') return false;
  return me.scope === 'all' || (Array.isArray(me.projects) && me.projects.includes(project.id));
}

function wsResearchCanEdit(item, me, project) {
  try {
    if (!wsResearchIsObject(item) || !wsResearchHasProjectAccess(me, project)) return false;
    if (item.projectId !== project.id || !wsResearchNonblank(me.k)) return false;
    const assignedOperationalOwner = item.ownerKey === me.k
      && ['task', 'experiment', 'milestone'].includes(item.kind);
    return item.authorKey === me.k || assignedOperationalOwner || me.tier === 'pi' || me.tier === 'phd';
  } catch (error) {
    return false;
  }
}

function wsResearchMember(people, ownerKey, projectId) {
  if (ownerKey === '') return true;
  if (!Array.isArray(people)) return false;
  const person = people.find(candidate => wsResearchIsObject(candidate) && candidate.k === ownerKey);
  if (!person || person.tier === 'partner') return false;
  return person.scope === 'all' || (Array.isArray(person.projects) && person.projects.includes(projectId));
}

function wsResearchApprovedSource(project, sourceEntryId) {
  if (!wsResearchNonblank(sourceEntryId) || !Array.isArray(project.log)) return false;
  return project.log.some(entry => wsResearchIsObject(entry)
    && entry.id === sourceEntryId
    && entry.ack !== false);
}

function wsResearchTimestamp(now) {
  if (typeof now === 'undefined') return new Date().toISOString();
  if (typeof now === 'string' && wsResearchInstantValid(now)) return now;
  try {
    if (now && typeof now.toISOString === 'function') {
      const value = now.toISOString();
      return wsResearchInstantValid(value) ? value : '';
    }
  } catch (error) {
    return '';
  }
  return '';
}

function wsResearchNewId(existingIds) {
  let id = '';
  do {
    if (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function') {
      id = 'research-' + crypto.randomUUID();
    } else {
      wsResearchIdCounter += 1;
      id = 'research-' + Date.now().toString(36) + '-' + wsResearchIdCounter.toString(36)
        + '-' + Math.random().toString(36).slice(2, 10);
    }
  } while (existingIds.has(id));
  return id;
}

function wsResearchSave(state, input, me, project, people, now) {
  try {
    const stateValidation = wsResearchValidate(state);
    if (!stateValidation.ok) return { ok: false, error: 'Cannot save into invalid research state: ' + stateValidation.error };
    if (!wsResearchIsObject(input)) return { ok: false, error: 'Research input must be an object.' };
    const dueDate = typeof input.dueDate === 'undefined' ? '' : input.dueDate;
    const sourceEntryId = typeof input.sourceEntryId === 'undefined' ? '' : input.sourceEntryId;
    const experimentId = typeof input.experimentId === 'undefined' ? '' : input.experimentId;
    if (!wsResearchHasProjectAccess(me, project)) return { ok: false, error: 'You do not have access to this project.' };
    if (!wsResearchNonblank(me.k)) return { ok: false, error: 'A valid author identity is required.' };
    if (input.projectId !== project.id) return { ok: false, error: 'Research input must match the selected project.' };
    if (!WS_RESEARCH_KINDS.includes(input.kind)) return { ok: false, error: 'Choose a valid tracking kind.' };
    if (!wsResearchNonblank(input.title)) return { ok: false, error: 'Title is required.' };
    if (typeof input.ownerKey !== 'string' || !wsResearchMember(people, input.ownerKey, project.id)) {
      return { ok: false, error: 'Owner must be an internal project member or unassigned.' };
    }
    if (!WS_RESEARCH_STATUSES.includes(input.status)) return { ok: false, error: 'Choose a valid status.' };
    if (!wsResearchDateValid(input.date, false)) return { ok: false, error: 'Enter a valid work or observation date.' };
    if (!wsResearchDateValid(dueDate, true)) return { ok: false, error: 'Enter a valid due date or leave it blank.' };
    if (typeof input.notes !== 'string') return { ok: false, error: 'Notes must be text.' };
    if (typeof sourceEntryId !== 'string') return { ok: false, error: 'Source entry ID must be text.' };
    if (typeof experimentId !== 'string') return { ok: false, error: 'Experiment ID must be text.' };
    if (typeof input.metric !== 'string' || typeof input.unit !== 'string' || typeof input.condition !== 'string') {
      return { ok: false, error: 'Metric, unit, and condition must be text.' };
    }

    if (input.kind === 'measurement') {
      if (!wsResearchNonblank(input.metric)) return { ok: false, error: 'Measurement metric is required.' };
      if (typeof input.value !== 'number' || !Number.isFinite(input.value)) {
        return { ok: false, error: 'Measurement value must be a finite number.' };
      }
      if (!wsResearchNonblank(input.unit)) return { ok: false, error: 'Measurement unit is required; use dimensionless when appropriate.' };
      if (!wsResearchNonblank(input.condition)) return { ok: false, error: 'Measurement condition is required.' };
      if (!wsResearchNonblank(sourceEntryId)) return { ok: false, error: 'Measurement source is required.' };
    } else if (input.value !== null) {
      return { ok: false, error: 'Nonmeasurement value must be null.' };
    }

    if (sourceEntryId !== '' && !wsResearchApprovedSource(project, sourceEntryId)) {
      return { ok: false, error: 'Source must identify an existing approved project entry.' };
    }
    if (experimentId !== '') {
      const experiment = wsResearchCurrent(state, project.id).find(item => item.id === experimentId);
      if (!experiment || experiment.kind !== 'experiment') {
        return { ok: false, error: 'Related experiment must be a current experiment in this project.' };
      }
    }

    const hasId = typeof input.id !== 'undefined';
    let previous = null;
    if (hasId) {
      if (!wsResearchNonblank(input.id)) return { ok: false, error: 'Existing items require a valid ID.' };
      const matching = state.revisions.filter(item => item.id === input.id);
      previous = matching.length ? matching[matching.length - 1] : null;
      if (!previous) return { ok: false, error: 'The item being edited no longer exists.' };
      if (input.revision !== previous.revision) return { ok: false, error: 'Stale revision. Reload the latest item before saving.' };
      if (input.projectId !== previous.projectId || input.kind !== previous.kind) {
        return { ok: false, error: 'An existing item cannot change project or kind.' };
      }
      if (!wsResearchCanEdit(previous, me, project)) {
        return { ok: false, error: 'Only the original author, the assigned operational owner, or a PI/PhD reviewer can edit this item.' };
      }
    } else if (typeof input.revision !== 'undefined') {
      return { ok: false, error: 'New items cannot specify a revision.' };
    }

    const updatedAt = wsResearchTimestamp(now);
    if (!updatedAt) return { ok: false, error: 'A valid ISO update timestamp is required.' };
    if (previous && new Date(updatedAt).getTime() < new Date(previous.updatedAt).getTime()) {
      return { ok: false, error: 'Update time cannot precede the latest revision.' };
    }
    const ids = new Set(state.revisions.map(item => item.id));
    const item = {
      id: previous ? previous.id : wsResearchNewId(ids),
      revision: previous ? previous.revision + 1 : 1,
      projectId: project.id,
      kind: input.kind,
      title: input.title,
      ownerKey: input.ownerKey,
      status: input.status,
      date: input.date,
      dueDate,
      notes: input.notes,
      sourceEntryId,
      experimentId,
      metric: input.metric,
      value: input.kind === 'measurement' ? input.value : null,
      unit: input.unit,
      condition: input.condition,
      authorKey: previous ? previous.authorKey : me.k,
      updatedBy: me.k,
      updatedAt,
    };
    const nextState = { version: 1, revisions: [...state.revisions, item] };
    const nextValidation = wsResearchValidate(nextState);
    if (!nextValidation.ok) return { ok: false, error: 'Could not create a valid revision: ' + nextValidation.error };
    return { ok: true, state: nextState, item };
  } catch (error) {
    return { ok: false, error: 'Research input contains an unreadable value.' };
  }
}

function wsResearchSummary(items) {
  const summary = {
    workTotal: 0,
    completed: 0,
    inProgress: 0,
    blocked: 0,
    planned: 0,
    measurementTotal: 0,
    byOwner: [],
  };
  if (!Array.isArray(items)) return summary;
  const owners = new Map();
  items.forEach(item => {
    if (!wsResearchIsObject(item)) return;
    if (item.kind === 'measurement') {
      summary.measurementTotal += 1;
      return;
    }
    if (!['task', 'experiment', 'milestone'].includes(item.kind)) return;
    summary.workTotal += 1;
    if (item.status === 'completed') summary.completed += 1;
    if (item.status === 'in_progress') summary.inProgress += 1;
    if (item.status === 'blocked') summary.blocked += 1;
    if (item.status === 'planned') summary.planned += 1;
    const ownerKey = typeof item.ownerKey === 'string' ? item.ownerKey : '';
    if (!owners.has(ownerKey)) owners.set(ownerKey, { ownerKey, total: 0, completed: 0, blocked: 0 });
    const owner = owners.get(ownerKey);
    owner.total += 1;
    if (item.status === 'completed') owner.completed += 1;
    if (item.status === 'blocked') owner.blocked += 1;
  });
  summary.byOwner = Array.from(owners.values());
  return summary;
}

function wsResearchCsvString(value) {
  let text = '';
  try {
    text = String(value === null || typeof value === 'undefined' ? '' : value);
  } catch (error) {
    text = '';
  }
  text = text.replace(/\r\n|\r|\n/g, '\r\n');
  if (/^\s*[=+\-@]/.test(text) || /^[\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

function wsResearchCsv(items, people) {
  const columns = [
    'id', 'revision', 'projectId', 'kind', 'title', 'ownerKey', 'ownerName', 'status',
    'date', 'dueDate', 'notes', 'sourceEntryId', 'experimentId', 'metric', 'value',
    'unit', 'condition', 'authorKey', 'authorName', 'updatedBy', 'updatedByName',
    'updatedAt', 'trackingStatus',
  ];
  const safeItems = Array.isArray(items) ? items : [];
  const safePeople = Array.isArray(people) ? people : [];
  const nameFor = key => {
    const person = safePeople.find(candidate => wsResearchIsObject(candidate) && candidate.k === key);
    return person && typeof person.n === 'string' ? person.n : '';
  };
  const rows = [columns.map(wsResearchCsvString).join(',')];
  safeItems.forEach(item => {
    if (!wsResearchIsObject(item)) return;
    const values = [
      item.id, item.revision, item.projectId, item.kind, item.title,
      item.ownerKey, nameFor(item.ownerKey), item.status, item.date, item.dueDate,
      item.notes, item.sourceEntryId, item.experimentId, item.metric, item.value,
      item.unit, item.condition, item.authorKey, nameFor(item.authorKey),
      item.updatedBy, nameFor(item.updatedBy), item.updatedAt, WS_RESEARCH_TRACKING_STATUS,
    ];
    rows.push(values.map((value, index) => {
      if (columns[index] === 'value' && typeof value === 'number' && Number.isFinite(value)) {
        return '"' + String(value) + '"';
      }
      return wsResearchCsvString(value);
    }).join(','));
  });
  return '\ufeff' + rows.join('\r\n') + '\r\n';
}

function wsResearchJson(state, projectId) {
  const validation = wsResearchValidate(state);
  if (!validation.ok) throw new Error('Cannot export invalid research state: ' + validation.error);
  if (!wsResearchNonblank(projectId)) throw new Error('A project ID is required for research export.');
  return JSON.stringify({
    version: 1,
    projectId,
    trackingStatus: WS_RESEARCH_TRACKING_STATUS,
    revisions: state.revisions.filter(item => item.projectId === projectId),
  }, null, 2);
}
