/* URI workspace shell. This file is concatenated into the existing Babel script. */

const WS_NAV = [
  ['home', 'Home'],
  ['projects', 'Projects'],
  ['evidence', 'Evidence'],
  ['reviews', 'Reviews'],
  ['handoffs', 'Handoffs'],
  ['discover', 'Discover'],
];

const WS_PROJECT_TABS = [
  ['overview', 'Overview'],
  ['research', 'Research'],
  ['record', 'Record'],
  ['evidence', 'Evidence'],
  ['people', 'People'],
  ['settings', 'Settings'],
];

const WS_RECORD_TYPES = ['decision', 'method', 'result', 'deadend', 'blocker', 'next'];
const WS_MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function wsRecordSummary(projects){
  const entries = (projects || []).flatMap(project => Array.isArray(project.log) ? project.log : []).filter(entry => entry && entry.ack !== false);
  const typeCounts = WS_RECORD_TYPES.map(type => ({
    type,
    label:(TYPES[type] && TYPES[type].label) || type,
    count:entries.filter(entry => entry.t === type).length,
  }));
  const dated = entries.map(entry => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(entry.d || ''));
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const stamp = Date.UTC(year, month - 1, day);
    const date = new Date(stamp);
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
    return { key:match[1] + '-' + match[2], value:match[0], stamp, year, month:month - 1 };
  }).filter(Boolean);
  const latest = dated.reduce((current, item) => !current || item.stamp > current.stamp ? item : current, null);
  if (!latest) {
    return { approvedTotal:entries.length, typeCounts, latestDate:'', periodLabel:'No dated approved entries', activity:[] };
  }
  const latestMonthIndex = latest.year * 12 + latest.month;
  const activity = [];
  for (let offset = 5; offset >= 0; offset -= 1) {
    const monthIndex = latestMonthIndex - offset;
    const year = Math.floor(monthIndex / 12);
    const month = ((monthIndex % 12) + 12) % 12;
    const key = year + '-' + String(month + 1).padStart(2, '0');
    activity.push({
      key,
      label:WS_MONTH_NAMES[month].slice(0, 3),
      longLabel:WS_MONTH_NAMES[month] + ' ' + year,
      count:dated.filter(item => item.key === key).length,
    });
  }
  const first = activity[0];
  const last = activity[activity.length - 1];
  const periodLabel = first.longLabel.slice(-4) === last.longLabel.slice(-4)
    ? first.longLabel.replace(/ \d{4}$/, '') + '-' + last.longLabel
    : first.longLabel + '-' + last.longLabel;
  return { approvedTotal:entries.length, typeCounts, latestDate:latest.value, periodLabel, activity };
}

function WsIcon({ name }){
  const shapes = {
    home:<><path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.5V21h13V9.5"/><path d="M9.5 21v-7h5v7"/></>,
    projects:<><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M8 5V3h8v2"/><path d="M3 10h18"/></>,
    evidence:<><path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4"/><path d="M9 12h6M9 16h6"/></>,
    reviews:<><path d="M9 4h6l1 2h3v15H5V6h3z"/><path d="m8.5 13 2 2 5-5"/></>,
    handoffs:<><path d="M4 7h12"/><path d="m12 3 4 4-4 4"/><path d="M20 17H8"/><path d="m12 13-4 4 4 4"/></>,
    discover:<><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/></>,
  };
  return <svg className="ws-nav-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{shapes[name]}</svg>;
}

function wsReadState(personKey){
  try {
    const raw = localStorage.getItem('uri.workspace.' + personKey);
    const saved = raw ? JSON.parse(raw) : null;
    if (!saved || typeof saved !== 'object') return {};
    const sections = [...WS_NAV.map(item => item[0]), 'project'];
    const tabs = WS_PROJECT_TABS.map(item => item[0]);
    return {
      section:sections.includes(saved.section) ? saved.section : undefined,
      selectedProjectId:typeof saved.selectedProjectId === 'string' ? saved.selectedProjectId : undefined,
      projectTab:tabs.includes(saved.projectTab) ? saved.projectTab : undefined,
    };
  } catch (_) {
    return {};
  }
}

function wsEntrySources(entry){
  const values = [];
  const add = value => {
    if (!value) return;
    if (Array.isArray(value)) { value.forEach(add); return; }
    if (typeof value === 'string') { values.push(value); return; }
    const label = value.label || value.name || value.filename || value.title || value.ref || value.id || 'Source';
    const detail = [value.page && ('page ' + value.page), value.section, value.url, value.quote].filter(Boolean).join(' - ');
    values.push(detail ? label + ': ' + detail : label);
  };
  add(entry.sources);
  add(entry.sourceRefs);
  add(entry.citations);
  add(entry.source);
  add(entry.attachments);
  add(entry.files);
  return [...new Set(values)];
}

function wsMarkdown(project){
  if (!project) return '';
  const entries = [...(project.log || [])].sort((a, b) => String(a.d || '').localeCompare(String(b.d || '')));
  const approved = entries.filter(e => e.ack !== false);
  const methods = approved.filter(e => e.t === 'method');
  const failed = approved.filter(e => e.t === 'deadend');
  const decisions = approved.filter(e => e.t === 'decision');
  const next = approved.filter(e => e.t === 'next');
  const latestResult = [...entries].reverse().find(e => e.t === 'result' && e.ack !== false);
  const lines = [
    '# ' + project.name,
    '',
    project.code || 'Project record',
    '',
    '## Start here',
    '',
    latestResult ? latestResult.h + ': ' + latestResult.b : project.oneLine,
    '',
    '### Suggested first steps',
    '',
    ...(next.length ? next.map(e => '- ' + e.h + ': ' + e.b) : ['- No open next step is recorded.']),
    '',
    '### Recorded methods',
    '',
    ...(methods.length ? methods.map(e => '- ' + e.h + ': ' + e.b) : ['- No method is recorded.']),
    '',
    '### Failed approaches',
    '',
    ...(failed.length ? failed.map(e => '- ' + e.h + ': ' + e.b + (e.why ? ' Why: ' + e.why : '')) : ['- No failed approach is recorded.']),
    '',
    '### Decision rationale',
    '',
    ...(decisions.length ? decisions.map(e => '- ' + e.h + ': ' + (e.why || e.b)) : ['- No decision rationale is recorded.']),
    '',
    '### Files of record',
    '',
    ...((project.artifacts || []).length ? project.artifacts.map(a => '- `' + a.n + '` - ' + a.d) : ['- No file is recorded.']),
    '',
    '### People',
    '',
    ...((project.contacts || []).length ? project.contacts.map(c => '- ' + c.n + ' - ' + c.r + (c.c ? ' (' + c.c + ')' : '')) : ['- No contact is recorded.']),
    '',
    '## Full authorized history',
    '',
  ];
  entries.forEach(e => {
    const type = TYPES[e.t] ? TYPES[e.t].label : e.t;
    lines.push('### ' + (e.d || 'Date not recorded') + ' - ' + type + ' - ' + e.h);
    lines.push('');
    lines.push('Author: ' + (e.au || 'Not recorded'));
    lines.push('');
    lines.push('Review status: ' + (e.ack === false ? 'Pending review - not part of the official record' : 'Published'));
    lines.push('');
    lines.push(e.b || 'No detail recorded.');
    if (e.why) { lines.push(''); lines.push('Rationale: ' + e.why); }
    if (e.supersedes) { lines.push(''); lines.push('Supersedes: ' + e.supersedes); }
    if (Array.isArray(e.links) && e.links.length) {
      lines.push('');
      lines.push('Record relationships:');
      e.links.forEach(link => lines.push('- ' + (link.t || 'relates to') + ': ' + (link.to || 'reference not recorded')));
    }
    const refs = wsEntrySources(e);
    if (refs.length) {
      lines.push('');
      lines.push('Sources:');
      refs.forEach(ref => lines.push('- ' + ref));
    }
    lines.push('');
  });
  lines.push('## Unavailable or omitted material');
  lines.push('');
  lines.push('- Unpublished drafts and review comments are omitted.');
  lines.push('- Material without an authorized reference in the project record is unavailable in this export.');
  lines.push('');
  lines.push('This packet contains the full authorized historical record available in this workspace, including superseded decisions when they are present in the log.');
  return lines.join('\n');
}

function WsBadge({ children, tone }){
  return <span className={'ws-badge' + (tone ? ' ws-badge-' + tone : '')}>{children}</span>;
}

function WsEntryRow({ entry, onSelect }){
  const type = TYPES[entry.t] || { label:entry.t || 'Update', mark:'-' };
  const refs = wsEntrySources(entry);
  const content = (
    <>
      <div className="ws-row-main">
        <div className="ws-inline ws-meta">
          <span aria-hidden="true">{type.mark}</span>
          <span>{type.label}</span>
          <span>{entry.d}</span>
          <span>{entry.au}</span>
          {entry.ack === false && <WsBadge tone="attention">Awaiting review</WsBadge>}
        </div>
        <strong>{entry.h}</strong>
        <p>{entry.b}</p>
        {refs.length > 0 && <div className="ws-inline">{refs.map(ref => <span className="ws-citation" key={ref}>{ref}</span>)}</div>}
      </div>
    </>
  );
  return onSelect
    ? <button type="button" className="ws-row" onClick={onSelect}>{content}</button>
    : <div className="ws-row">{content}</div>;
}

function WsPageHead({ eyebrow, title, subtitle, actions }){
  return (
    <header className="ws-page-head">
      <div>
        {eyebrow && <div className="ws-eyebrow">{eyebrow}</div>}
        <h1 className="ws-title">{title}</h1>
        {subtitle && <p className="ws-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="ws-actions">{actions}</div>}
    </header>
  );
}

function WsHero({ eyebrow, title, subtitle, actions, metadata, metrics }){
  return (
    <header className="ws-hero">
      <div className="ws-hero-copy">
        {eyebrow && <div className="ws-eyebrow">{eyebrow}</div>}
        <h1 className="ws-title">{title}</h1>
        {subtitle && <p className="ws-subtitle">{subtitle}</p>}
        {metadata && <div className="ws-inline ws-meta ws-hero-meta">{metadata}</div>}
        {actions && <div className="ws-actions">{actions}</div>}
        {metrics && <div className="ws-hero-metrics">{metrics}</div>}
      </div>
      <div className="ws-hero-art" aria-hidden="true">
        <svg viewBox="0 0 280 190" fill="none" focusable="false">
          <path d="M27 145C74 110 104 132 137 95S201 42 255 55" />
          <path d="M45 52h74M70 78h104M126 120h108" />
          <circle cx="27" cy="145" r="8" />
          <circle cx="137" cy="95" r="11" />
          <circle cx="255" cy="55" r="8" />
          <circle cx="45" cy="52" r="5" />
          <circle cx="119" cy="52" r="5" />
          <circle cx="70" cy="78" r="5" />
          <circle cx="174" cy="78" r="5" />
          <circle cx="126" cy="120" r="5" />
          <circle cx="234" cy="120" r="5" />
        </svg>
      </div>
    </header>
  );
}

function WsRecordVisual({ projects }){
  const summary = wsRecordSummary(projects);
  const largestType = Math.max(1, ...summary.typeCounts.map(item => item.count));
  const busiestMonth = Math.max(1, ...summary.activity.map(item => item.count));
  return (
    <section className="ws-visual-summary" aria-label="Approved research record summary">
      <div className="ws-coverage">
        <div className="ws-visual-head">
          <h2>Research record coverage</h2>
          <span className="ws-meta">{summary.approvedTotal} approved {summary.approvedTotal === 1 ? 'entry' : 'entries'}</span>
        </div>
        <p className="ws-meta">Approved entries by record type</p>
        <div className="ws-coverage-list" role="list">
          {summary.typeCounts.map(item => (
            <div className="ws-coverage-row" role="listitem" key={item.type}>
              <span className="ws-coverage-label">{item.label}</span>
              <span className="ws-coverage-track" aria-hidden="true"><span className="ws-coverage-fill" style={{ width:(item.count / largestType * 100) + '%' }} /></span>
              <strong className="ws-coverage-count">{item.count}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="ws-activity-chart">
        <div className="ws-visual-head">
          <h2>Record activity</h2>
          <span className="ws-meta">Approved entries</span>
        </div>
        <p className="ws-meta">{summary.activity.length ? summary.periodLabel + ' - six-month window' : summary.periodLabel}</p>
        {summary.activity.length ? (
          <div className="ws-activity-bars" role="list" aria-label={'Approved record entries from ' + summary.periodLabel}>
            {summary.activity.map(item => (
              <div className="ws-activity-bar" role="listitem" aria-label={item.longLabel + ': ' + item.count + (item.count === 1 ? ' approved entry' : ' approved entries')} key={item.key}>
                <strong className="ws-activity-count">{item.count}</strong>
                <span className="ws-activity-column" aria-hidden="true" style={{ height:(item.count / busiestMonth * 100) + '%' }} />
                <span className="ws-activity-label" title={item.longLabel}>{item.label}</span>
              </div>
            ))}
          </div>
        ) : <div className="ws-empty">Add a dated, approved entry to begin the activity view.</div>}
      </div>
    </section>
  );
}

function WsProjectPicker({ projects, selectedId, onSelect, label }){
  if (!projects.length) return null;
  return (
    <label className="ws-field">
      <span>{label || 'Project'}</span>
      <select className="ws-select" value={selectedId || ''} onChange={e => onSelect(e.target.value)}>
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
    </label>
  );
}

function WsProjectHome({ project, me, people, onAddEvidence, onOpenHandoff, onTab }){
  const approved = sortedLog(project).filter(e => e.ack !== false);
  const summary = wsRecordSummary([project]);
  const latestResult = approved.find(e => e.t === 'result');
  const next = approved.find(e => e.t === 'next');
  const sourceGaps = singleSource(project);
  const gaps = [...sourceGaps.live, ...sourceGaps.orphaned];
  const advisor = project.pi || 'Not recorded';
  const studentLead = project.current && project.current[0] ? project.current[0].n : 'No current student lead';
  const approvedNext = summary.typeCounts.find(item => item.type === 'next').count;
  return (
    <>
      <WsHero
        eyebrow={project.code}
        title={project.name}
        subtitle={project.oneLine}
        metadata={<><WsBadge>{project.status === 'handoff' ? 'Handoff pending' : project.status === 'archived' ? 'Archived' : 'Active'}</WsBadge><span>PI / advisor: {advisor}</span><span>Student lead: {studentLead}</span><span>Private workspace</span></>}
        actions={<button type="button" className="ws-button ws-button-primary" onClick={onAddEvidence}>Add evidence</button>}
        metrics={<><div><strong>{summary.approvedTotal}</strong><span>Approved entries</span></div><div><strong>{approvedNext}</strong><span>Recorded next steps</span></div><div><strong>{summary.latestDate || 'None'}</strong><span>Latest dated update</span></div></>}
      />
      <ResearchProjectSummary key={me.k + ':' + project.id} project={project} me={me} onOpen={() => onTab('research')} />
      <div className="ws-grid ws-grid-two ws-overview-split">
        <div className="ws-stack ws-overview-context">
          <section className="ws-panel">
            <div className="ws-panel-head"><h2>Current state</h2><WsBadge>Official record</WsBadge></div>
            {latestResult ? <><h3>{latestResult.h}</h3><details className="ws-research-narrative"><summary>Read the full current-state explanation</summary><p>{latestResult.b}</p></details></> : <details className="ws-research-narrative"><summary>Read the full project objective</summary><p>{project.oneLine}</p></details>}
          </section>
          <section className="ws-panel">
            <div className="ws-panel-head"><h2>Next action</h2></div>
            {next ? <><h3>{next.h}</h3><details className="ws-research-narrative"><summary>Read the full next-action explanation</summary><p>{next.b}</p></details></> : <div className="ws-empty">No next action is recorded. Add an update so the next researcher has a concrete starting point.</div>}
          </section>
          <section className="ws-callout">
            <div className="ws-callout-title">
              <div>
                <div className="ws-kicker">Handoff readiness</div>
                <h2>{gaps.length ? gaps.length + (gaps.length === 1 ? ' entry has' : ' entries have') + ' one recorded author' : 'No single-author continuity flag found'}</h2>
              </div>
            </div>
            {gaps.length ? (
              <ul className="ws-list">
                {gaps.slice(0, 3).map(({ e, who }) => <li className="ws-row" key={e.id}><span><strong>One recorded author: {who.n}</strong><br />{e.h}</span></li>)}
              </ul>
            ) : <p>This checks the written record only. It does not prove that another person is ready to perform the work.</p>}
            <div className="ws-callout-actions"><button type="button" className="ws-button ws-button-quiet" onClick={onOpenHandoff}>What would be lost?</button></div>
          </section>
        </div>
        <WsRecordVisual projects={[project]} />
      </div>
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Recent approved updates</h2><button type="button" className="ws-link" onClick={() => onTab('record')}>Open full record</button></div>
        <div className="ws-list">
          {approved.slice(0, 4).map(entry => <WsEntryRow key={entry.id} entry={entry} />)}
          {!approved.length && <div className="ws-empty">No approved updates yet. Add the first evidence-backed update.</div>}
        </div>
      </section>
    </>
  );
}

function WsProjectRecord({ project }){
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const entries = sortedLog(project).filter(entry => {
    const typeMatch = filter === 'all' || entry.t === filter;
    const text = (entry.h + ' ' + entry.b + ' ' + entry.au).toLowerCase();
    return typeMatch && text.includes(query.trim().toLowerCase());
  });
  return (
    <>
      <WsPageHead eyebrow={project.code} title="Project record" subtitle="Historical decisions, methods, results, failures, blockers, and next steps. Items pending review are labeled." />
      <div className="ws-inline">
        <label className="ws-field ws-search"><span>Search this record</span><input className="ws-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search statements or authors" /></label>
        <label className="ws-field"><span>Type</span><select className="ws-select" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All types</option>{TYPE_ORDER.map(type => <option value={type} key={type}>{TYPES[type].label}</option>)}</select></label>
      </div>
      <div className="ws-list">
        {entries.map(entry => <WsEntryRow key={entry.id} entry={entry} />)}
        {!entries.length && <div className="ws-empty">No published entry matches this search.</div>}
      </div>
    </>
  );
}

function WsProjectEvidence({ project, onAddEvidence }){
  const linked = sortedLog(project).filter(entry => wsEntrySources(entry).length);
  return (
    <>
      <WsPageHead eyebrow={project.code} title="Evidence" subtitle="Original material and the published statements it supports." actions={<button type="button" className="ws-button ws-button-primary" onClick={onAddEvidence}>Add evidence</button>} />
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Files of record</h2></div>
        <div className="ws-list">{(project.artifacts || []).map(a => <div className="ws-row" key={a.n}><div><strong>{a.n}</strong><p>{a.d}</p></div></div>)}</div>
        {!(project.artifacts || []).length && <div className="ws-empty">No file is recorded for this project.</div>}
      </section>
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Source-linked updates</h2><span className="ws-meta">{linked.length} published</span></div>
        <div className="ws-list">{linked.map(entry => <WsEntryRow key={entry.id} entry={entry} />)}</div>
        {!linked.length && <div className="ws-empty">The current prototype record has no per-entry source references. New evidence can add them without rewriting historical entries.</div>}
      </section>
    </>
  );
}

function WsLossSimulation({ project }){
  const projectPeople = PEOPLE.filter(person => (person.projects || []).includes(project.id));
  const signaturePeople = PEOPLE.filter(person => (project.log || []).some(entry => String(entry.au || '').split('/').map(x => x.trim()).includes(person.s)));
  const people = [...new Map([...projectPeople, ...signaturePeople].map(person => [person.k, person])).values()];
  const [gone, setGone] = useState([]);
  const affected = (project.log || []).filter(entry => {
    const authors = String(entry.au || '').split('/').map(x => x.trim());
    return authors.length > 0 && authors.every(short => {
      const person = PEOPLE.find(candidate => candidate.s === short);
      return person && gone.includes(person.k);
    });
  });
  const byType = TYPE_ORDER.map(type => [type, affected.filter(entry => entry.t === type).length]).filter(([, count]) => count);
  return (
    <section className="ws-callout">
      <div className="ws-callout-title">
        <div><div className="ws-kicker">Scenario, not a prediction</div><h2>What would be lost?</h2></div>
        <WsBadge tone="attention">Simulation</WsBadge>
      </div>
      <p>Select people to treat their authored entries as unavailable. This measures the written record, not everything a person knows or another person's practical readiness.</p>
      <div className="ws-inline">
        {people.map(person => <button type="button" key={person.k} className={'ws-button ws-button-quiet' + (gone.includes(person.k) ? ' is-active' : '')} aria-pressed={gone.includes(person.k)} onClick={() => setGone(current => current.includes(person.k) ? current.filter(k => k !== person.k) : [...current, person.k])}>{person.n}</button>)}
      </div>
      {!gone.length ? <div className="ws-empty">Choose a person to inspect the procedures, decisions, and dependencies tied only to their record.</div> : (
        <div className="ws-stack">
          <div className="ws-stats">{byType.map(([type, count]) => <div key={type}><strong>{count}</strong><span>{TYPES[type].label}{count === 1 ? '' : 's'}</span></div>)}</div>
          <div className="ws-list">{affected.map(entry => <WsEntryRow key={entry.id} entry={entry} />)}{!affected.length && <div className="ws-empty">No entry becomes unavailable under this scenario.</div>}</div>
        </div>
      )}
    </section>
  );
}

function WsProjectPeople({ project }){
  const assigned = PEOPLE.filter(person => (person.projects || []).includes(project.id));
  return (
    <>
      <WsPageHead eyebrow={project.code} title="People" subtitle="Who is involved, how to reach them, and where the record depends on one person." />
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Project team</h2></div>
        <div className="ws-list">
          {assigned.map(person => <div className="ws-row" key={person.k}><span className="ws-avatar" aria-hidden="true">{person.i}</span><div><strong>{person.n}</strong><p>{person.line}{person.state ? ' - ' + person.state : ''}</p></div></div>)}
          {!assigned.length && <div className="ws-empty">No account assignment is recorded.</div>}
        </div>
      </section>
      <WsLossSimulation project={project} />
    </>
  );
}

function WsProjectSettings({ project, onOpenLegacy }){
  return (
    <>
      <WsPageHead eyebrow={project.code} title="Settings" subtitle="Prototype access and review rules for this project." />
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Sharing</h2><WsBadge>Private</WsBadge></div>
        <p>This browser prototype shows the project only to demo identities assigned to it. A production pilot still requires server-enforced access and persistent accounts.</p>
      </section>
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Original prototype</h2></div>
        <p>Open the earlier project view for the map, legacy continuity score, and complete research-journal presentation.</p>
        <button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('project', project.id)}>Open original project</button>
      </section>
    </>
  );
}

function WsHandoff({ project }){
  const [copyState, setCopyState] = useState('');
  const markdown = useMemo(() => wsMarkdown(project), [project]);
  const approved = (project.log || []).filter(e => e.ack !== false);
  const next = approved.filter(e => e.t === 'next');
  const methods = approved.filter(e => e.t === 'method');
  const failures = approved.filter(e => e.t === 'deadend');

  async function copyMarkdown(){
    try {
      await navigator.clipboard.writeText(markdown);
      setCopyState('Copied');
    } catch (_) {
      const area = document.createElement('textarea');
      area.value = markdown;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand('copy');
      document.body.removeChild(area);
      setCopyState(copied ? 'Copied' : 'Copy failed');
    }
  }

  function downloadMarkdown(){
    const blob = new Blob([markdown], { type:'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = (project.code || project.id || 'project').toLowerCase() + '-handoff.md';
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <WsPageHead eyebrow="Start here and export" title={project.name} subtitle="A readable brief followed by the complete authorized historical record." actions={<><button type="button" className="ws-button ws-button-quiet" onClick={copyMarkdown}>Copy context for AI</button><button type="button" className="ws-button ws-button-primary" onClick={downloadMarkdown}>Download Markdown</button></>} />
      {copyState && <div className="ws-alert" role="status">{copyState}. The export includes the historical log and recorded source references.</div>}
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Start here</h2><WsBadge>{approved.length} published entries</WsBadge></div>
        <p>{project.oneLine}</p>
        <div className="ws-grid ws-grid-three">
          <div><h3>Recorded methods</h3><p>{methods.length ? methods.map(e => e.h).join('; ') : 'No method is recorded.'}</p></div>
          <div><h3>Failed approaches</h3><p>{failures.length ? failures.map(e => e.h).join('; ') : 'No failed approach is recorded.'}</p></div>
          <div><h3>First steps</h3><p>{next.length ? next.map(e => e.h).join('; ') : 'No next step is recorded.'}</p></div>
        </div>
      </section>
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Markdown packet preview</h2><span className="ws-meta">Pending items labeled; drafts excluded</span></div>
        <pre className="ws-source-body">{markdown}</pre>
      </section>
    </>
  );
}

function WsHome({ projects, me, onOpenProject, onAddEvidence }){
  const recent = projects.flatMap(project => (project.log || []).filter(entry => entry.ack !== false).map(entry => ({ project, entry }))).sort((a, b) => String(b.entry.d).localeCompare(String(a.entry.d))).slice(0, 5);
  const handoffs = projects.filter(project => project.status === 'handoff');
  const summary = wsRecordSummary(projects);
  const recordedNext = summary.typeCounts.find(item => item.type === 'next').count;
  return (
    <>
      <WsHero
        eyebrow="Undergraduate Research Incubator"
        title={'Welcome, ' + (me.n || 'researcher')}
        subtitle="See where your accessible projects stand and continue the next recorded action."
        actions={projects[0] && <button type="button" className="ws-button ws-button-primary" onClick={() => onAddEvidence(projects[0].id)}>Add evidence</button>}
        metrics={<><div><strong>{projects.length}</strong><span>Accessible projects</span></div><div><strong>{recordedNext}</strong><span>Recorded next steps</span></div><div><strong>{handoffs.length}</strong><span>Handoffs pending</span></div></>}
      />
      <div className="ws-grid ws-grid-two ws-home-overview">
        <section className="ws-panel">
          <div className="ws-panel-head"><h2>Projects</h2></div>
          <div className="ws-list">
            {projects.map(project => {
              const next = sortedLog(project).find(entry => entry.t === 'next' && entry.ack !== false);
              return <button type="button" className="ws-row" key={project.id} onClick={() => onOpenProject(project.id)}><div><div className="ws-inline ws-meta"><WsBadge>{project.status}</WsBadge><span>{project.code}</span></div><strong>{project.name}</strong><p>{next ? 'Next: ' + next.h : project.oneLine}</p></div></button>;
            })}
            {!projects.length && <div className="ws-empty">This demo identity has no accessible projects. Choose another identity below the navigation.</div>}
          </div>
        </section>
        <WsRecordVisual projects={projects} />
      </div>
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Recent approved record</h2></div>
        <div className="ws-list">{recent.map(({ project, entry }) => <WsEntryRow key={project.id + entry.id} entry={entry} onSelect={() => onOpenProject(project.id, 'record')} />)}{!recent.length && <div className="ws-empty">No approved record is available.</div>}</div>
      </section>
    </>
  );
}

function WsProjects({ projects, query, setQuery, onOpenProject }){
  const q = query.trim().toLowerCase();
  const shown = projects.filter(project => {
    const projectText = [project.name, project.code, project.field, project.pi, project.oneLine].join(' ');
    const recordText = (project.log || []).map(entry => [entry.h, entry.b, entry.au].join(' ')).join(' ');
    return (projectText + ' ' + recordText).toLowerCase().includes(q);
  });
  return (
    <>
      <WsPageHead title="Projects" subtitle="Only projects available to the selected demo identity appear here." />
      <label className="ws-field ws-search"><span>Search accessible projects and records</span><input className="ws-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search project names, findings, methods, or authors" /></label>
      <div className="ws-list">
        {shown.map(project => <button type="button" className="ws-row" key={project.id} onClick={() => onOpenProject(project.id)}><div><div className="ws-inline ws-meta"><WsBadge>{project.status}</WsBadge><span>{project.code}</span><span>{project.field}</span></div><strong>{project.name}</strong><p>{project.oneLine}</p></div><span className="ws-meta">{project.log.length} entries</span></button>)}
        {!shown.length && <div className="ws-empty">No accessible project or published record matches this search.</div>}
      </div>
    </>
  );
}

function WsDiscover({ shelf, me, accessibleIds, onOpenLegacy }){
  const [query, setQuery] = useState('');
  const available = (shelf || []).filter(item => me.scope === 'all' || accessibleIds.has(item.parent) || item.shelvedBy === me.k).filter(item => !item.claimedBy);
  const shown = available.filter(item => [item.name, item.oneLine, item.field, item.reasonText].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <>
      <WsPageHead eyebrow="The Shelf" title="Discover paused work" subtitle="Projects with existing work, a reason they stopped, and recorded next steps." actions={<button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('shelf')}>Open original Shelf</button>} />
      <label className="ws-field ws-search"><span>Search material you can access</span><input className="ws-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search shelved projects" /></label>
      <div className="ws-grid ws-grid-two">
        {shown.map(item => <article className="ws-panel" key={item.id}><div className="ws-panel-head"><div><div className="ws-kicker">{item.code}</div><h2>{item.name}</h2></div><WsBadge>{item.visibility === 'partner' ? 'Partner listed' : 'Internal'}</WsBadge></div><p>{item.oneLine}</p><div className="ws-inline ws-meta"><span>{(item.built || []).length} established findings</span><span>{(item.remaining || []).length} next steps</span></div><button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('shelfitem', item.id)}>Read revival brief</button></article>)}
      </div>
      {!shown.length && <div className="ws-empty">No accessible shelved project matches this search.</div>}
    </>
  );
}

function ResearchWorkspace({ projects, me, onIdentityChange, onPublishEntries, shelf, onOpenLegacy }){
  const initial = wsReadState(me.k);
  const accessibleProjects = useMemo(() => (projects || []).filter(project => me.scope === 'all' || (me.projects || []).includes(project.id)), [projects, me]);
  const accessibleIds = useMemo(() => new Set(accessibleProjects.map(project => project.id)), [accessibleProjects]);
  const firstId = accessibleProjects[0] ? accessibleProjects[0].id : '';
  const [section, setSection] = useState(initial.section || 'home');
  const [selectedProjectId, setSelectedProjectId] = useState(initial.selectedProjectId || firstId);
  const [projectTab, setProjectTab] = useState(initial.projectTab || 'overview');
  const [query, setQuery] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const identityRef = useRef(me.k);
  const selectedProject = accessibleProjects.find(project => project.id === selectedProjectId) || accessibleProjects[0] || null;
  const identities = PEOPLE.filter(person => person.tier !== 'partner');

  useEffect(() => {
    if (identityRef.current === me.k) return;
    identityRef.current = me.k;
    const saved = wsReadState(me.k);
    setSection(saved.section || 'home');
    setSelectedProjectId(saved.selectedProjectId || ((projects || []).find(project => me.scope === 'all' || (me.projects || []).includes(project.id)) || {}).id || '');
    setProjectTab(saved.projectTab || 'overview');
    setQuery('');
  }, [me.k, me.scope, me.projects, projects]);

  useEffect(() => {
    if (selectedProjectId && accessibleIds.has(selectedProjectId)) return;
    setSelectedProjectId(firstId);
  }, [selectedProjectId, firstId, accessibleIds]);

  useEffect(() => {
    try {
      localStorage.setItem('uri.workspace.' + me.k, JSON.stringify({ section, selectedProjectId, projectTab }));
    } catch (_) {}
  }, [section, selectedProjectId, projectTab, me.k]);

  function navigate(nextSection){
    setSection(nextSection);
    setMenuOpen(false);
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top:0, behavior:reduceMotion ? 'auto' : 'smooth' });
  }

  function openProject(id, tab){
    if (!accessibleIds.has(id)) return;
    setSelectedProjectId(id);
    setProjectTab(tab || 'overview');
    navigate('project');
  }

  function openEvidence(id){
    if (id && accessibleIds.has(id)) setSelectedProjectId(id);
    navigate('evidence');
  }

  function handlePublished(projectId, entries){
    if (onPublishEntries) onPublishEntries(projectId, entries);
    if (accessibleIds.has(projectId)) setSelectedProjectId(projectId);
    setProjectTab('record');
    navigate('project');
  }

  const safeOpenLegacy = onOpenLegacy || (() => {});

  return (
    <div className={'ws-app' + (menuOpen ? ' menu-open' : '')}>
      <a className="skip" href="#workspace-main">Skip to workspace content</a>
      <button type="button" className="ws-mobile-menu" aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(open => !open)}>Menu</button>
      {menuOpen && <button type="button" className="ws-drawer-backdrop" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
      <aside id="workspace-navigation" className={'ws-sidebar' + (menuOpen ? ' is-open' : '')}>
        <div className="ws-sidebar-head">
          <button type="button" className="ws-brand" onClick={() => navigate('home')} aria-label="URI workspace home"><span>URI</span><small>Research workspace</small></button>
        </div>
        <nav className="ws-nav" aria-label="Workspace">
          <div className="ws-nav-label">Workspace</div>
          {WS_NAV.map(([key, label]) => <button type="button" key={key} className={'ws-nav-item' + (section === key ? ' is-active' : '')} aria-current={section === key ? 'page' : undefined} onClick={() => navigate(key)}><WsIcon name={key} /><span>{label}</span></button>)}
          {accessibleProjects.length > 0 && <><div className="ws-nav-label">Projects</div>{accessibleProjects.map(project => <button type="button" className={'ws-nav-item' + (section === 'project' && selectedProject && selectedProject.id === project.id ? ' is-active' : '')} key={project.id} onClick={() => openProject(project.id)}><span>{project.name}</span><small>{project.code}</small></button>)}</>}
        </nav>
        <div className="ws-sidebar-foot">
          <label className="ws-field ws-demo"><span>Demo identity</span><select className="ws-select" value={me.k} onChange={e => { const person = byKey(e.target.value); if (person && onIdentityChange) onIdentityChange(person); }}>{identities.map(person => <option value={person.k} key={person.k}>{person.n}</option>)}</select></label>
          <div className="ws-inline"><span className="ws-avatar" aria-hidden="true">{me.i}</span><div><strong>{me.n}</strong><div className="ws-meta">{me.line}</div></div></div>
          <button type="button" className="ws-link" onClick={() => safeOpenLegacy('register')}>Original prototype</button>
        </div>
      </aside>
      <div className="ws-main">
        <header className="ws-topbar">
          <div><div className="ws-topbar-title">{section === 'project' && selectedProject ? selectedProject.name : (WS_NAV.find(item => item[0] === section) || ['', 'Project'])[1]}</div><div className="ws-topbar-meta">Demo workspace - browser-stored data</div></div>
          {accessibleProjects.length > 0 && !['evidence', 'reviews'].includes(section) && <WsProjectPicker projects={accessibleProjects} selectedId={selectedProject ? selectedProject.id : firstId} onSelect={id => openProject(id)} label="Current project" />}
        </header>
        <main id="workspace-main" className="ws-content">
          {section === 'home' && <WsHome projects={accessibleProjects} me={me} onOpenProject={openProject} onAddEvidence={openEvidence} />}
          {section === 'projects' && <WsProjects projects={accessibleProjects} query={query} setQuery={setQuery} onOpenProject={openProject} />}
          {(section === 'evidence' || section === 'reviews') && (
            accessibleProjects.length
              ? <EvidenceWorkspace key={me.k + ':' + section + ':' + (selectedProject ? selectedProject.id : firstId)} projects={accessibleProjects} me={me} initialProjectId={selectedProject ? selectedProject.id : firstId} mode={section === 'reviews' ? 'reviews' : 'evidence'} onPublished={handlePublished} onOpenProject={id => openProject(id)} />
              : <div className="ws-empty">This demo identity has no accessible project for evidence or review.</div>
          )}
          {section === 'handoffs' && (selectedProject ? <><WsProjectPicker projects={accessibleProjects} selectedId={selectedProject.id} onSelect={setSelectedProjectId} label="Handoff project" /><WsHandoff project={selectedProject} /></> : <div className="ws-empty">This demo identity has no accessible project to hand off.</div>)}
          {section === 'discover' && <WsDiscover shelf={shelf || []} me={me} accessibleIds={accessibleIds} onOpenLegacy={safeOpenLegacy} />}
          {section === 'project' && selectedProject && (
            <>
              <div className="ws-tabs" role="tablist" aria-label="Project sections">{WS_PROJECT_TABS.map(([key, label]) => <button type="button" role="tab" aria-selected={projectTab === key} className={'ws-tab' + (projectTab === key ? ' is-active' : '')} key={key} onClick={() => setProjectTab(key)}>{label}</button>)}</div>
              {projectTab === 'overview' && <WsProjectHome project={selectedProject} me={me} people={PEOPLE} onAddEvidence={() => openEvidence(selectedProject.id)} onOpenHandoff={() => navigate('handoffs')} onTab={setProjectTab} />}
              {projectTab === 'research' && <ResearchProjectWorkspace key={me.k + ':' + selectedProject.id} project={selectedProject} me={me} people={PEOPLE} />}
              {projectTab === 'record' && <WsProjectRecord project={selectedProject} />}
              {projectTab === 'evidence' && <WsProjectEvidence project={selectedProject} onAddEvidence={() => openEvidence(selectedProject.id)} />}
              {projectTab === 'people' && <WsProjectPeople project={selectedProject} />}
              {projectTab === 'settings' && <WsProjectSettings project={selectedProject} onOpenLegacy={safeOpenLegacy} />}
            </>
          )}
          {section === 'project' && !selectedProject && <div className="ws-empty">Choose a demo identity with access to a project.</div>}
        </main>
      </div>
    </div>
  );
}
