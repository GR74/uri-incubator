/* URI workspace shell. This file is concatenated into the existing Babel script. */

const WS_NAV = [
  ['home', 'Home'],
  ['projects', 'Projects'],
  ['evidence', 'Evidence'],
  ['reviews', 'Reviews'],
  ['handoffs', 'Handoffs'],
  ['map', 'Map'],
  ['discover', 'Discover'],
];

const WS_ANALYSIS = [
  ['map', 'Map', 'map'],
  ['risk', 'Continuity risk', 'risk'],
  ['shelf', 'The Shelf', 'shelf'],
  ['extract', 'Shelve a project', 'extract'],
];

const WS_DEMO = [
  { who:'okonkwo', section:'home', role:'Faculty',
    title:'The group director opens the week',
    body:'Three projects, what each one is waiting on, and how much of the record is actually approved rather than sitting in drafts.' },
  { who:'yusuf', section:'reviews', role:'PhD mentor',
    title:'The PhD mentor clears the review queue',
    body:'Undergraduates write the record; the mentor signs it off. Nothing reaches an incoming student until a second reader has agreed it is true.' },
  { who:'priya', section:'evidence', role:'Outgoing undergraduate',
    title:'The student who is leaving writes it down',
    body:'Priya graduates in December. Evidence she adds now becomes the opening pages of the next student’s brief — anything she does not write leaves with her.' },
  { who:'priya', section:'handoffs', role:'Outgoing undergraduate',
    title:'Her project is packaged as a handoff',
    body:'The packet assembles itself from approved entries only. Drafts and pending items are labelled or excluded rather than quietly included.' },
  { who:'tobias', section:'handoffs', role:'Incoming undergraduate',
    title:'The new student arrives to a written project',
    body:'Tobias starts in September on a project that is already two years old. He begins from what worked, what failed, and where to pick up — not a blank page.' },
  { who:'tobias', section:'discover', role:'Incoming undergraduate',
    title:'And can see what else is available',
    body:'Shelved work that a graduate student stopped, with the reason it stopped stated plainly. That is where the next project comes from.' },
];

const WS_TIER = {
  ug:'Undergraduate', phd:'PhD student', pi:'Faculty', alum:'Alum', partner:'Partner',
};

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

function wsWorkspaceNavKey(section){
  return section === 'project' ? 'projects' : section;
}

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

function WsIdentityPicker({ me, identities, onSelect }){
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = e => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = e => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [open]);
  const groups = [];
  identities.forEach(person => {
    const tier = WS_TIER[person.tier] || 'Other';
    const found = groups.find(group => group.tier === tier);
    if (found) found.people.push(person); else groups.push({ tier, people:[person] });
  });
  return (
    <div className="ws-identity" ref={box}>
      <div className="ws-nav-label">Viewing as</div>
      <button type="button" className="ws-identity-trigger" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="ws-avatar" aria-hidden="true">{me.i}</span>
        <span className="ws-identity-copy">
          <strong>{me.n}</strong>
          <span className="ws-identity-tier" data-tier={me.tier}>{WS_TIER[me.tier] || 'Member'}</span>
        </span>
        <span className="ws-identity-caret" aria-hidden="true">&#9662;</span>
      </button>
      {open && (
        <div className="ws-identity-menu" role="listbox" aria-label="Demo identity">
          {groups.map(group => (
            <div key={group.tier} className="ws-identity-group">
              <div className="ws-identity-grouphead">{group.tier}</div>
              {group.people.map(person => (
                <button type="button" role="option" aria-selected={person.k === me.k} key={person.k}
                  className={'ws-identity-option' + (person.k === me.k ? ' is-active' : '')}
                  onClick={() => { onSelect(person); setOpen(false); }}>
                  <span className="ws-avatar" aria-hidden="true">{person.i}</span>
                  <span className="ws-identity-copy"><strong>{person.n}</strong><span className="ws-meta">{person.line}</span></span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WsIcon({ name }){
  const shapes = {
    home:<><path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.5V21h13V9.5"/><path d="M9.5 21v-7h5v7"/></>,
    projects:<><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M8 5V3h8v2"/><path d="M3 10h18"/></>,
    evidence:<><path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4"/><path d="M9 12h6M9 16h6"/></>,
    reviews:<><path d="M9 4h6l1 2h3v15H5V6h3z"/><path d="m8.5 13 2 2 5-5"/></>,
    handoffs:<><path d="M4 7h12"/><path d="m12 3 4 4-4 4"/><path d="M20 17H8"/><path d="m12 13-4 4 4 4"/></>,
    discover:<><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/></>,
    map:<><circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="17" r="2.4"/><path d="M7.9 8.4 10.6 15M16.4 7.8 13.6 15M8.2 6.6h7.4"/></>,
    risk:<><path d="M12 3.5 21 19H3z"/><path d="M12 10v4M12 16.6v.2"/></>,
    shelf:<><rect x="3.5" y="4.5" width="17" height="6"/><rect x="3.5" y="13.5" width="17" height="6"/></>,
    extract:<><path d="M12 3.5v11M8.4 11l3.6 3.6 3.6-3.6"/><path d="M4.5 16.5v3h15v-3"/></>,
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

/* The banner used to hold a decorative squiggle shaped like the map but meaning
   nothing. In a product about evidence, an ornament shaped like data is the wrong
   ornament -- so it is now drawn from the reader's own position: them at the
   centre, their projects around them, and the people they share a record with. */
function WsHeroMap({ me, projects }){
  const mine = (projects || []).filter(project =>
    ((me.projects || []).includes(project.id)) ||
    (project.log || []).some(entry => authorsOf(entry).some(person => person.k === me.k)));
  const others = [];
  mine.forEach(project => (project.log || []).forEach(entry => authorsOf(entry).forEach(person => {
    if (person.k !== me.k && !others.some(other => other.k === person.k)) others.push(person);
  })));
  const cx = 140, cy = 95;
  const ring = mine.slice(0, 4).map((project, i, all) => {
    const angle = -Math.PI / 2 + (i / Math.max(1, all.length)) * Math.PI * 2;
    return { x: cx + Math.cos(angle) * 60, y: cy + Math.sin(angle) * 50 };
  });
  const outer = others.slice(0, 7).map((person, i, all) => {
    const angle = -Math.PI / 2 + ((i + 0.5) / Math.max(1, all.length)) * Math.PI * 2;
    return { x: cx + Math.cos(angle) * 112, y: cy + Math.sin(angle) * 76 };
  });
  const nearest = point => ring.reduce((best, node) => {
    const d = Math.hypot(node.x - point.x, node.y - point.y);
    return !best || d < best.d ? { node, d } : best;
  }, null);
  return (
    <svg viewBox="0 0 280 190" fill="none" focusable="false" role="img"
         aria-label={'Your position in the record: ' + pl(mine.length,'project','projects') + ', ' + pl(others.length,'person','people') + ' you share a record with'}>
      {outer.map((point, i) => { const hit = nearest(point); return hit
        ? <path key={'o' + i} d={'M' + point.x + ' ' + point.y + 'L' + hit.node.x + ' ' + hit.node.y} /> : null; })}
      {ring.map((point, i) => <path key={'r' + i} d={'M' + cx + ' ' + cy + 'L' + point.x + ' ' + point.y} />)}
      {outer.map((point, i) => <circle key={'c' + i} cx={point.x} cy={point.y} r="4" />)}
      {ring.map((point, i) => <circle key={'p' + i} cx={point.x} cy={point.y} r="7.5" />)}
      <circle cx={cx} cy={cy} r="11.5" className="ws-hero-you" />
    </svg>
  );
}

function WsHero({ eyebrow, title, subtitle, actions, metadata, metrics, art }){
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
      <div className="ws-hero-art">{art}</div>
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
  const buckets = wsProjectBuckets(projects);
  return (
    <label className="ws-field ws-project-picker">
      <span>{label || 'Project'}</span>
      <select className="ws-select" value={selectedId || ''} onChange={e => onSelect(e.target.value)}>
        {!!buckets.active.length && <optgroup label="Active projects">{buckets.active.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</optgroup>}
        {!!buckets.stashed.length && <optgroup label="Stashed projects">{buckets.stashed.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</optgroup>}
      </select>
    </label>
  );
}

function WsWorkspaceTabs({ section, onNavigate, onOpenLegacy }){
  const activeKey = wsWorkspaceNavKey(section);
  return (
    <nav className="ws-workspace-tabs" aria-label="Workspace sections">
      {WS_NAV.map(([key, label]) => <button type="button" key={key} className={'ws-tab' + (activeKey === key ? ' is-active' : '')} aria-current={activeKey === key ? 'page' : undefined} onClick={() => onNavigate(key)}>{label}</button>)}
      {WS_ANALYSIS.filter(item => item[0] === 'risk' || item[0] === 'extract').map(([key, label]) => <button type="button" key={key} className="ws-tab" onClick={() => onOpenLegacy(key)}>{label}</button>)}
    </nav>
  );
}

function WsProjectContext({ project, projectTab, onTab, onProjects }){
  if (!project) return null;
  return (
    <div className="ws-project-context">
      <div className="ws-breadcrumb"><button type="button" className="ws-link" onClick={onProjects}>Projects</button><span aria-hidden="true">/</span><strong>{project.name}</strong>{wsIsStashed(project) && <WsBadge>Stashed</WsBadge>}</div>
      <div className="ws-tabs" role="tablist" aria-label="Project sections">
        {WS_PROJECT_TABS.map(([key, label]) => <button type="button" role="tab" aria-selected={projectTab === key} className={'ws-tab' + (projectTab === key ? ' is-active' : '')} key={key} onClick={() => onTab(key)}>{label}</button>)}
      </div>
    </div>
  );
}

function WsHeader({ section, project, projectTab, projects, me, identities, onNavigate, onProject, onTab, onIdentity, onOpenLegacy, onPlayDemo }){
  return (
    <header className="ws-shell-header">
      <div className="ws-header-row">
        <button type="button" className="ws-brand ws-brand-horizontal" onClick={() => onNavigate('home')} aria-label="URI workspace home"><span>URI</span><small>Research workspace</small></button>
        <div className="ws-header-controls">
          <WsProjectPicker projects={projects} selectedId={project ? project.id : ''} onSelect={onProject} label="Current project" />
          <WsIdentityPicker me={me} identities={identities} onSelect={person => onIdentity(person.k)} />
          <button type="button" className="ws-button ws-button-quiet ws-demo-header" onClick={onPlayDemo}>Guided demo</button>
          <button type="button" className="ws-link ws-original-link" onClick={() => onOpenLegacy('register')}>Original prototype</button>
        </div>
      </div>
      <WsWorkspaceTabs section={section} onNavigate={onNavigate} onOpenLegacy={onOpenLegacy} />
      {section === 'project' && <WsProjectContext project={project} projectTab={projectTab} onTab={onTab} onProjects={() => onNavigate('projects')} />}
    </header>
  );
}

function WsProjectHome({ project, me, people, onAddEvidence, onOpenHandoff, onTab, onOpenMap }){
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
        metadata={<><WsBadge>{wsIsStashed(project) ? 'Stashed' : project.status === 'handoff' ? 'Handoff pending' : 'Active'}</WsBadge><span>PI / advisor: {advisor}</span><span>Student lead: {studentLead}</span><span>{wsIsStashed(project) && project.stashVisibility === 'lab' ? 'Shared with lab' : 'Private workspace'}</span></>}
        actions={wsIsStashed(project) ? <><button type="button" className="ws-button ws-button-quiet" onClick={onOpenMap}>Open source map</button><button type="button" className="ws-button ws-button-primary" onClick={onOpenHandoff}>Export archive</button></> : <><button type="button" className="ws-button ws-button-quiet" onClick={onOpenMap}>View connections</button><button type="button" className="ws-button ws-button-primary" onClick={onAddEvidence}>Add evidence</button></>}
        metrics={<><div><strong>{summary.approvedTotal}</strong><span>Approved entries</span></div><div><strong>{approvedNext}</strong><span>Recorded next steps</span></div><div><strong>{summary.latestDate || 'None'}</strong><span>Latest dated update</span></div></>}
        art={<WsHeroMap me={me} projects={[project]} />}
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
      <WsPageHead eyebrow={project.code} title="Evidence" subtitle="Original material and the published statements it supports." actions={!wsIsStashed(project) && <button type="button" className="ws-button ws-button-primary" onClick={onAddEvidence}>Add evidence</button>} />
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

function WsProjectSettings({ project, me, onOpenLegacy, onStash, onResume, onSetStashVisibility }){
  const [reason, setReason] = useState('');
  const [nextStep, setNextStep] = useState('');
  const [visibility, setVisibility] = useState('private');
  const [feedback, setFeedback] = useState('');
  const canManage = wsCanManageProject(project, me);

  function stash(event){
    event.preventDefault();
    if (!canManage || typeof onStash !== 'function') return;
    const result = onStash(project, { reason, nextStep, visibility });
    setFeedback(result && result.ok ? 'Project stashed. Its record is now read only.' : (result && result.error) || 'The project could not be stashed.');
  }

  function resume(){
    if (!canManage || typeof onResume !== 'function') return;
    const result = onResume(project);
    setFeedback(result && result.ok ? 'Project resumed. Editing is available again.' : (result && result.error) || 'The project could not be resumed.');
  }

  function changeVisibility(nextVisibility){
    if (!canManage || typeof onSetStashVisibility !== 'function') return;
    const result = onSetStashVisibility(project, nextVisibility);
    setFeedback(result && result.ok ? (nextVisibility === 'lab' ? 'Archive shared with the lab.' : 'Archive made private.') : (result && result.error) || 'Archive visibility could not be changed.');
  }

  return (
    <>
      <WsPageHead eyebrow={project.code} title="Settings" subtitle="Manage access, lifecycle, and the durable record for this project." />
      {feedback && <div className="ws-alert" role="status">{feedback}</div>}
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Sharing</h2><WsBadge>{wsIsStashed(project) && project.stashVisibility === 'lab' ? 'Lab shared' : 'Private'}</WsBadge></div>
        <p>{wsIsStashed(project) ? 'A lab-shared archive appears in Discover so another researcher can create a linked continuation. The source archive remains unchanged.' : 'This active project is visible only to demo identities assigned to it.'}</p>
        {wsIsStashed(project) && canManage && <button type="button" className="ws-button ws-button-quiet" onClick={() => changeVisibility(project.stashVisibility === 'lab' ? 'private' : 'lab')}>{project.stashVisibility === 'lab' ? 'Make archive private' : 'Share archive with lab'}</button>}
      </section>
      {!wsIsStashed(project) && <section className="ws-panel ws-stash-panel">
        <div className="ws-panel-head"><div><div className="ws-kicker">Reversible lifecycle change</div><h2>Stash this project</h2></div><WsBadge tone="attention">Read-only archive</WsBadge></div>
        <p>Stashing preserves decisions, evidence, research tracking, people, and source links. The project leaves active work but stays searchable and exportable.</p>
        {canManage ? <form className="ws-stack" onSubmit={stash} noValidate>
          <label className="ws-field"><span>Why did work stop?</span><textarea className="ws-textarea" rows="3" value={reason} onChange={event => setReason(event.target.value)} required /></label>
          <label className="ws-field"><span>Recommended next step</span><textarea className="ws-textarea" rows="3" value={nextStep} onChange={event => setNextStep(event.target.value)} required /></label>
          <label className="ws-field"><span>Archive visibility</span><select className="ws-select" value={visibility} onChange={event => setVisibility(event.target.value)}><option value="private">Private to assigned team</option><option value="lab">Share with lab in Discover</option></select></label>
          <div className="ws-actions"><button type="submit" className="ws-button ws-button-primary">Stash project</button></div>
        </form> : <div className="ws-empty">Only the project PI or assigned PhD mentor can stash this project.</div>}
      </section>}
      {wsIsStashed(project) && <section className="ws-panel ws-stash-panel">
        <div className="ws-panel-head"><div><div className="ws-kicker">{project.stashedOn || project.archivedOn ? 'Stashed ' + new Date(project.stashedOn || project.archivedOn).toLocaleDateString() : 'Stashed project'}</div><h2>Archived project record</h2></div><WsBadge>Read only</WsBadge></div>
        <dl className="ws-stash-summary"><div><dt>Why work stopped</dt><dd>{project.stashReason || 'No reason recorded.'}</dd></div><div><dt>Recommended next step</dt><dd>{project.stashNextStep || 'No next step recorded.'}</dd></div></dl>
        {canManage && <div className="ws-actions"><button type="button" className="ws-button ws-button-primary" onClick={resume}>Resume this project</button></div>}
      </section>}
      <section className="ws-panel">
        <div className="ws-panel-head"><h2>Original prototype</h2></div>
        <p>Open the earlier project view for the map, legacy continuity score, and complete research-journal presentation.</p>
        <button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('project', project.id)}>Open original project</button>
      </section>
    </>
  );
}

/* A small Markdown renderer for the subset the export actually produces.
   Builds React elements rather than setting innerHTML, so nothing in a record
   can inject markup into the page. */
function wsInline(text, keyPrefix){
  const out = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0, match, i = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const key = keyPrefix + '-' + (i++);
    if (token.startsWith('**')) out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('`')) out.push(<code key={key}>{token.slice(1, -1)}</code>);
    else out.push(<em key={key}>{token.slice(1, -1)}</em>);
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function WsMarkdown({ source }){
  const blocks = [];
  const lines = String(source || '').split(/\r?\n/);
  let list = null, para = [];
  const flushPara = () => { if (para.length) { blocks.push({ kind:'p', text:para.join(' ') }); para = []; } };
  const flushList = () => { if (list) { blocks.push({ kind:'ul', items:list }); list = null; } };
  lines.forEach(raw => {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) { flushPara(); flushList(); return; }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { flushPara(); flushList(); blocks.push({ kind:'h' + heading[1].length, text:heading[2] }); return; }
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) { flushPara(); flushList(); blocks.push({ kind:'hr' }); return; }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) { flushPara(); list = list || []; list.push(bullet[1]); return; }
    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) { flushPara(); flushList(); blocks.push({ kind:'quote', text:quote[1] }); return; }
    flushList();
    para.push(line.trim());
  });
  flushPara(); flushList();
  return (
    <div className="ws-md">
      {blocks.map((block, i) => {
        const key = 'b' + i;
        if (block.kind === 'hr') return <hr key={key} />;
        if (block.kind === 'ul') return <ul key={key}>{block.items.map((item, j) => <li key={j}>{wsInline(item, key + '-' + j)}</li>)}</ul>;
        if (block.kind === 'quote') return <blockquote key={key}>{wsInline(block.text, key)}</blockquote>;
        if (block.kind === 'h1') return <h1 key={key}>{wsInline(block.text, key)}</h1>;
        if (block.kind === 'h2') return <h2 key={key}>{wsInline(block.text, key)}</h2>;
        if (block.kind === 'h3') return <h3 key={key}>{wsInline(block.text, key)}</h3>;
        if (block.kind === 'h4') return <h4 key={key}>{wsInline(block.text, key)}</h4>;
        return <p key={key}>{wsInline(block.text, key)}</p>;
      })}
    </div>
  );
}

function WsHandoff({ project }){
  const [showSource, setShowSource] = useState(false);
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
        <div className="ws-panel-head">
          <h2>Handoff packet</h2>
          <div className="ws-inline">
            <span className="ws-meta">Pending items labeled; drafts excluded</span>
            <div className="ws-toggle" role="group" aria-label="Packet view">
              <button type="button" className={'ws-toggle-item' + (!showSource ? ' is-active' : '')}
                aria-pressed={!showSource} onClick={() => setShowSource(false)}>Formatted</button>
              <button type="button" className={'ws-toggle-item' + (showSource ? ' is-active' : '')}
                aria-pressed={showSource} onClick={() => setShowSource(true)}>Markdown</button>
            </div>
          </div>
        </div>
        {showSource ? <pre className="ws-source-body">{markdown}</pre> : <WsMarkdown source={markdown} />}
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
        art={<WsHeroMap me={me} projects={projects} />}
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
  const [view, setView] = useState('active');
  const buckets = wsProjectBuckets(projects);
  const q = query.trim().toLowerCase();
  const collection = view === 'stashed' ? buckets.stashed : buckets.active;
  const shown = collection.filter(project => {
    const projectText = [project.name, project.code, project.field, project.pi, project.oneLine].join(' ');
    const recordText = (project.log || []).map(entry => [entry.h, entry.b, entry.au].join(' ')).join(' ');
    return (projectText + ' ' + recordText).toLowerCase().includes(q);
  });
  return (
    <>
      <WsPageHead title="Projects" subtitle="Only projects available to the selected demo identity appear here." />
      <div className="ws-tabs" role="tablist" aria-label="Project lifecycle"><button type="button" role="tab" aria-selected={view === 'active'} className={'ws-tab' + (view === 'active' ? ' is-active' : '')} onClick={() => setView('active')}>Active <span className="ws-count">{buckets.active.length}</span></button><button type="button" role="tab" aria-selected={view === 'stashed'} className={'ws-tab' + (view === 'stashed' ? ' is-active' : '')} onClick={() => setView('stashed')}>Stashed <span className="ws-count">{buckets.stashed.length}</span></button></div>
      <label className="ws-field ws-search"><span>Search accessible projects and records</span><input className="ws-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search project names, findings, methods, or authors" /></label>
      <div className="ws-list">
        {shown.map(project => <button type="button" className="ws-row" key={project.id} onClick={() => onOpenProject(project.id)}><div><div className="ws-inline ws-meta"><WsBadge>{project.status}</WsBadge><span>{project.code}</span><span>{project.field}</span></div><strong>{project.name}</strong><p>{project.oneLine}</p></div><span className="ws-meta">{project.log.length} entries</span></button>)}
        {!shown.length && <div className="ws-empty">{q ? 'No project or published record matches this search.' : 'No ' + view + ' projects are available.'}</div>}
      </div>
    </>
  );
}

const WS_GRAPH_TYPES = [
  ['project', 'Project'],
  ['record', 'Record'],
  ['decision', 'Decision'],
  ['research', 'Research'],
  ['artifact', 'Artifact'],
  ['source', 'Source'],
];

function WsResearchMap({ projects, scope, onScopeChange, me, onOpenTarget }){
  const [query, setQuery] = useState('');
  const [types, setTypes] = useState([]);
  const [includePending, setIncludePending] = useState(false);
  const [selectedId, setSelectedId] = useState('');
  const [listView, setListView] = useState(false);
  const researchItems = useMemo(() => {
    const storage = wsResearchBrowserStorage(window);
    if (!storage.ok) return [];
    const read = wsResearchRead(storage.storage);
    return (projects || []).flatMap(project => wsResearchCurrent(read.state, project.id));
  }, [projects]);
  const graph = useMemo(() => wsBuildResearchGraph(projects, researchItems, { includePending }), [projects, researchItems, includePending]);
  const filtered = useMemo(() => wsFilterResearchGraph(graph, { scope, query, types }), [graph, scope, query, types]);
  const positions = useMemo(() => wsLayoutResearchGraph(filtered, 980, 580), [filtered]);
  const byId = useMemo(() => new Map(positions.map(node => [node.id, node])), [positions]);
  const selected = byId.get(selectedId) || null;
  const connected = useMemo(() => {
    if (!selected) return new Set();
    const ids = new Set([selected.id]);
    filtered.edges.forEach(edge => {
      if (edge.source === selected.id) ids.add(edge.target);
      if (edge.target === selected.id) ids.add(edge.source);
    });
    return ids;
  }, [selected, filtered]);
  const canSeePending = ['pi', 'phd'].includes(me.tier);

  function toggleType(type){
    setTypes(current => current.includes(type) ? current.filter(item => item !== type) : [...current, type]);
  }

  function activate(node){
    setSelectedId(node.id);
  }

  return (
    <>
      <WsPageHead eyebrow="Lab knowledge graph" title="Research map" subtitle="Trace how projects, evidence, decisions, research work, files, and named sources connect across the lab." />
      <section className="ws-map-toolbar" aria-label="Map filters">
        <label className="ws-field"><span>Scope</span><select className="ws-select" value={scope} onChange={event => onScopeChange(event.target.value)}><option value="all">All lab projects</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}{wsIsStashed(project) ? ' (stashed)' : ''}</option>)}</select></label>
        <label className="ws-field ws-search"><span>Find a node</span><input className="ws-input" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search sources, decisions, files..." /></label>
        <button type="button" className="ws-button ws-button-quiet" aria-pressed={listView} onClick={() => setListView(value => !value)}>{listView ? 'Show map' : 'Show list'}</button>
        {canSeePending && <label className="ws-check"><input type="checkbox" checked={includePending} onChange={event => setIncludePending(event.target.checked)} /><span>Include pending review</span></label>}
      </section>
      <div className="ws-map-type-filters" aria-label="Node types">
        {WS_GRAPH_TYPES.map(([type, label]) => <button type="button" key={type} className={'ws-map-type ws-map-type-' + type + (types.includes(type) ? ' is-active' : '')} aria-pressed={types.includes(type)} onClick={() => toggleType(type)}><span aria-hidden="true" />{label}</button>)}
      </div>
      <div className="ws-map-summary" role="status"><strong>{filtered.counts.nodes}</strong> nodes, <strong>{filtered.counts.edges}</strong> connections across <strong>{filtered.counts.projects}</strong> projects</div>
      {listView ? (
        <section className="ws-panel ws-map-list" aria-label="Research map as a list">
          <div className="ws-list">{positions.map(node => <button type="button" className="ws-row" key={node.id} onClick={() => activate(node)}><div><div className="ws-inline ws-meta"><WsBadge>{node.type}</WsBadge>{node.status && <span>{node.status}</span>}</div><strong>{node.label}</strong><p>{node.detail || 'No additional detail recorded.'}</p></div></button>)}{!positions.length && <div className="ws-empty">No nodes match these filters.</div>}</div>
        </section>
      ) : (
        <section className="ws-map-stage" aria-label="Interactive research relationship map">
          <svg className="ws-map-canvas" viewBox="0 0 980 580" role="img" aria-label={'Research map with ' + filtered.counts.nodes + ' nodes and ' + filtered.counts.edges + ' connections'}>
            <g className="ws-map-edges">{filtered.edges.map(edge => {
              const source = byId.get(edge.source);
              const target = byId.get(edge.target);
              if (!source || !target) return null;
              const highlighted = selected && (edge.source === selected.id || edge.target === selected.id);
              return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={highlighted ? 'is-highlighted' : ''}><title>{edge.label}</title></line>;
            })}</g>
            <g className="ws-map-nodes">{positions.map(node => {
              const active = node.id === selectedId;
              const muted = selected && !connected.has(node.id);
              const radius = node.type === 'project' ? 15 : node.type === 'source' ? 8 : 10;
              return <g key={node.id} className={'ws-map-node ws-map-node-' + node.type + (active ? ' is-selected' : '') + (muted ? ' is-muted' : '')} role="button" tabIndex="0" aria-label={node.type + ': ' + node.label} onClick={() => activate(node)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(node); } }}>
                <circle cx={node.x} cy={node.y} r={radius} />
                <text x={node.x + radius + 5} y={node.y + 4}>{node.label.length > 28 ? node.label.slice(0, 26) + '...' : node.label}</text>
              </g>;
            })}</g>
          </svg>
          {!positions.length && <div className="ws-map-empty">No nodes match these filters.</div>}
        </section>
      )}
      {selected && <aside className="ws-map-detail" aria-live="polite"><div><div className="ws-inline ws-meta"><WsBadge>{selected.type}</WsBadge>{selected.status && <span>{selected.status}</span>}</div><h2>{selected.label}</h2><p>{selected.detail || 'No additional detail recorded.'}</p></div>{selected.target && <button type="button" className="ws-button ws-button-primary" onClick={() => onOpenTarget(selected.target)}>Open record</button>}</aside>}
      {!!graph.warnings.length && <details className="ws-map-warnings"><summary>{graph.warnings.length} unresolved connection{graph.warnings.length === 1 ? '' : 's'} skipped</summary><ul>{graph.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    </>
  );
}

function WsDiscover({ shelf, projects, me, accessibleIds, onOpenLegacy, onContinue }){
  const [query, setQuery] = useState('');
  const [feedback, setFeedback] = useState('');
  const available = (shelf || []).filter(item => me.scope === 'all' || accessibleIds.has(item.parent) || item.shelvedBy === me.k).filter(item => !item.claimedBy);
  const sharedProjects = (projects || []).filter(project => wsIsStashed(project) && project.stashVisibility === 'lab');
  const q = query.trim().toLowerCase();
  const shown = available.filter(item => [item.name, item.oneLine, item.field, item.reasonText].join(' ').toLowerCase().includes(q));
  const shownArchives = sharedProjects.filter(project => [project.name, project.oneLine, project.field, project.stashReason, project.stashNextStep].join(' ').toLowerCase().includes(q));

  function continueArchive(project){
    if (typeof onContinue !== 'function') return;
    const result = onContinue(project);
    setFeedback(result && result.ok ? 'Created a linked active continuation from ' + project.code + '.' : (result && result.error) || 'The continuation could not be created.');
  }
  return (
    <>
      <WsPageHead eyebrow="The Shelf" title="Discover paused work" subtitle="Projects with existing work, a reason they stopped, and recorded next steps." actions={<button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('shelf')}>Open original Shelf</button>} />
      <label className="ws-field ws-search"><span>Search material you can access</span><input className="ws-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search shelved projects" /></label>
      {feedback && <div className="ws-alert" role="status">{feedback}</div>}
      {!!shownArchives.length && <><div className="ws-section-heading"><div><div className="ws-kicker">Shared archives</div><h2>Continue a stashed lab project</h2></div></div><div className="ws-grid ws-grid-two">{shownArchives.map(project => <article className="ws-panel" key={project.id}><div className="ws-panel-head"><div><div className="ws-kicker">{project.code}</div><h2>{project.name}</h2></div><WsBadge>Stashed</WsBadge></div><p>{project.oneLine}</p><dl className="ws-stash-summary"><div><dt>Why it stopped</dt><dd>{project.stashReason}</dd></div><div><dt>Next step</dt><dd>{project.stashNextStep}</dd></div></dl><button type="button" className="ws-button ws-button-primary" onClick={() => continueArchive(project)}>Continue as new project</button></article>)}</div></>}
      <div className="ws-section-heading"><div><div className="ws-kicker">Legacy shelf</div><h2>Prepared revival briefs</h2></div></div>
      <div className="ws-grid ws-grid-two">
        {shown.map(item => <article className="ws-panel" key={item.id}><div className="ws-panel-head"><div><div className="ws-kicker">{item.code}</div><h2>{item.name}</h2></div><WsBadge>{item.visibility === 'partner' ? 'Partner listed' : 'Internal'}</WsBadge></div><p>{item.oneLine}</p><div className="ws-inline ws-meta"><span>{(item.built || []).length} established findings</span><span>{(item.remaining || []).length} next steps</span></div><button type="button" className="ws-button ws-button-quiet" onClick={() => onOpenLegacy('shelfitem', item.id)}>Read revival brief</button></article>)}
      </div>
      {!shown.length && !shownArchives.length && <div className="ws-empty">No accessible shelved project or shared archive matches this search.</div>}
    </>
  );
}

function ResearchWorkspace({ projects, me, onIdentityChange, onPublishEntries, shelf, onOpenLegacy, onStash, onResume, onSetStashVisibility, onContinue }){
  const initial = wsReadState(me.k);
  const accessibleProjects = useMemo(() => (projects || []).filter(project => me.scope === 'all' || (me.projects || []).includes(project.id)), [projects, me]);
  const projectBuckets = useMemo(() => wsProjectBuckets(accessibleProjects), [accessibleProjects]);
  const accessibleIds = useMemo(() => new Set(accessibleProjects.map(project => project.id)), [accessibleProjects]);
  const firstId = projectBuckets.active[0] ? projectBuckets.active[0].id : (accessibleProjects[0] ? accessibleProjects[0].id : '');
  const [section, setSection] = useState(initial.section || 'home');
  const [selectedProjectId, setSelectedProjectId] = useState(initial.selectedProjectId || firstId);
  const [projectTab, setProjectTab] = useState(initial.projectTab || 'overview');
  const [query, setQuery] = useState('');
  const [mapScope, setMapScope] = useState('all');
  const [demo, setDemo] = useState(null);
  const demoRef = useRef(null);
  const [demoPlaying, setDemoPlaying] = useState(true);
  const identityRef = useRef(me.k);
  const selectedProject = accessibleProjects.find(project => project.id === selectedProjectId) || accessibleProjects.find(project => project.id === firstId) || null;
  const identities = PEOPLE.filter(person => person.tier !== 'partner');

  useEffect(() => {
    if (identityRef.current === me.k) return;
    identityRef.current = me.k;
    const saved = wsReadState(me.k);
    setSection(demoRef.current !== null ? WS_DEMO[demoRef.current].section : (saved.section || 'home'));
    const nextProjects = (projects || []).filter(project => me.scope === 'all' || (me.projects || []).includes(project.id));
    const nextBuckets = wsProjectBuckets(nextProjects);
    setSelectedProjectId(saved.selectedProjectId || ((nextBuckets.active[0] || nextProjects[0]) || {}).id || '');
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

  React.useLayoutEffect(() => {
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [section, selectedProjectId, projectTab]);

  /* the demo drives the same controls a person would, so nothing is faked */
  function runDemo(index){
    if (index === null || index >= WS_DEMO.length) { demoRef.current = null; setDemo(null); return; }
    const stop = WS_DEMO[index];
    demoRef.current = index;
    setDemo(index);
    const person = byKey(stop.who);
    if (person && person.k !== me.k && onIdentityChange) onIdentityChange(person);
    setSection(stop.section);
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top:0, behavior:reduceMotion ? 'auto' : 'smooth' });
  }
  useEffect(() => {
    if (demo === null || !demoPlaying) return;
    const timer = setTimeout(() => {
      if (demo + 1 >= WS_DEMO.length) { demoRef.current = null; setDemo(null); return; }
      runDemo(demo + 1);
    }, 9000);
    return () => clearTimeout(timer);
  }, [demo, demoPlaying]);

  function navigate(nextSection){
    setSection(nextSection);
    window.scrollTo(0, 0);
  }

  function openProject(id, tab){
    if (!accessibleIds.has(id)) return;
    setSelectedProjectId(id);
    setProjectTab(tab || 'overview');
    navigate('project');
  }

  function selectProject(id){
    if (!accessibleIds.has(id)) return;
    setSelectedProjectId(id);
    if (section !== 'project') navigate('project');
  }

  function openEvidence(id){
    if (id && accessibleIds.has(id)) setSelectedProjectId(id);
    navigate('evidence');
  }

  function openMap(id){
    if (id && accessibleIds.has(id)) setSelectedProjectId(id);
    setMapScope(id && accessibleIds.has(id) ? id : 'all');
    setSection('map');
    window.scrollTo(0, 0);
  }

  function openMapTarget(target){
    if (!target || !accessibleIds.has(target.projectId)) return;
    openProject(target.projectId, target.projectTab || 'overview');
  }

  function handlePublished(projectId, entries){
    if (onPublishEntries) onPublishEntries(projectId, entries);
    if (accessibleIds.has(projectId)) setSelectedProjectId(projectId);
    setProjectTab('record');
    navigate('project');
  }

  function handleContinue(project){
    if (typeof onContinue !== 'function') return { ok:false, error:'Project continuation is unavailable.' };
    const result = onContinue(project);
    if (result && result.ok && result.project) {
      setSelectedProjectId(result.project.id);
      setProjectTab('overview');
      setSection('project');
      window.scrollTo(0, 0);
    }
    return result;
  }

  const safeOpenLegacy = onOpenLegacy || (() => {});

  return (
    <div className="ws-app">
      <a className="skip" href="#workspace-main">Skip to workspace content</a>
      <WsHeader section={section} project={selectedProject} projectTab={projectTab} projects={accessibleProjects} me={me} identities={identities} onNavigate={key => key === 'map' ? openMap() : navigate(key)} onProject={selectProject} onTab={setProjectTab} onIdentity={key => { const person = byKey(key); if (person && onIdentityChange) onIdentityChange(person); }} onOpenLegacy={safeOpenLegacy} onPlayDemo={() => { setDemoPlaying(true); runDemo(0); }} />
      {demo !== null && (
        <div className="ws-demobar" role="region" aria-label="Guided demo">
          <div className="ws-demobar-steps" aria-hidden="true">
            {WS_DEMO.map((_, i) => <button type="button" key={i} className={'ws-demobar-dot' + (i === demo ? ' is-active' : i < demo ? ' is-done' : '')} onClick={() => { setDemoPlaying(false); runDemo(i); }} tabIndex={-1} />)}
          </div>
          <div className="ws-demobar-copy">
            <div className="ws-demobar-meta">{WS_DEMO[demo].role} &middot; stop {demo + 1} of {WS_DEMO.length}</div>
            <strong>{WS_DEMO[demo].title}</strong>
            <p>{WS_DEMO[demo].body}</p>
          </div>
          <div className="ws-demobar-controls">
            <button type="button" className="ws-button ws-button-quiet" onClick={() => setDemoPlaying(p => !p)}>{demoPlaying ? 'Pause' : 'Play'}</button>
            <button type="button" className="ws-button ws-button-quiet" disabled={demo === 0} onClick={() => { setDemoPlaying(false); runDemo(demo - 1); }}>Back</button>
            <button type="button" className="ws-button ws-button-primary" onClick={() => { setDemoPlaying(false); runDemo(demo + 1); }}>{demo + 1 >= WS_DEMO.length ? 'Finish' : 'Next'}</button>
            <button type="button" className="ws-link" onClick={() => { demoRef.current = null; setDemo(null); }}>Exit</button>
          </div>
        </div>
      )}
      <main id="workspace-main" className="ws-content">
          {section === 'home' && <WsHome projects={projectBuckets.active} me={me} onOpenProject={openProject} onAddEvidence={openEvidence} />}
          {section === 'projects' && <WsProjects projects={accessibleProjects} query={query} setQuery={setQuery} onOpenProject={openProject} />}
          {(section === 'evidence' || section === 'reviews') && (
            accessibleProjects.length
              ? <EvidenceWorkspace key={me.k + ':' + section + ':' + (selectedProject ? selectedProject.id : firstId)} projects={accessibleProjects} me={me} initialProjectId={selectedProject ? selectedProject.id : firstId} mode={section === 'reviews' ? 'reviews' : 'evidence'} onPublished={handlePublished} onOpenProject={id => openProject(id)} />
              : <div className="ws-empty">This demo identity has no accessible project for evidence or review.</div>
          )}
          {section === 'handoffs' && (selectedProject ? <><WsProjectPicker projects={accessibleProjects} selectedId={selectedProject.id} onSelect={setSelectedProjectId} label="Handoff project" /><WsHandoff project={selectedProject} /></> : <div className="ws-empty">This demo identity has no accessible project to hand off.</div>)}
          {section === 'map' && <WsResearchMap projects={accessibleProjects} scope={mapScope} onScopeChange={setMapScope} me={me} onOpenTarget={openMapTarget} />}
          {section === 'discover' && <WsDiscover shelf={shelf || []} projects={projects || []} me={me} accessibleIds={accessibleIds} onOpenLegacy={safeOpenLegacy} onContinue={handleContinue} />}
          {section === 'project' && selectedProject && (
            <>
              {wsIsStashed(selectedProject) && <div className="ws-stashed-banner" role="status"><div><strong>This project is stashed and read only.</strong><span>{selectedProject.stashReason || 'Its full record remains available for reference and export.'}</span></div><div className="ws-actions"><button type="button" className="ws-button ws-button-quiet" onClick={() => openMap(selectedProject.id)}>View connections</button><button type="button" className="ws-button ws-button-quiet" onClick={() => navigate('handoffs')}>Export archive</button></div></div>}
              {projectTab === 'overview' && <WsProjectHome project={selectedProject} me={me} people={PEOPLE} onAddEvidence={() => openEvidence(selectedProject.id)} onOpenHandoff={() => navigate('handoffs')} onTab={setProjectTab} onOpenMap={() => openMap(selectedProject.id)} />}
              {projectTab === 'research' && <ResearchProjectWorkspace key={me.k + ':' + selectedProject.id} project={selectedProject} me={me} people={PEOPLE} />}
              {projectTab === 'record' && <WsProjectRecord project={selectedProject} />}
              {projectTab === 'evidence' && <WsProjectEvidence project={selectedProject} onAddEvidence={() => openEvidence(selectedProject.id)} />}
              {projectTab === 'people' && <WsProjectPeople project={selectedProject} />}
              {projectTab === 'settings' && <WsProjectSettings project={selectedProject} me={me} onOpenLegacy={safeOpenLegacy} onStash={onStash} onResume={onResume} onSetStashVisibility={onSetStashVisibility} />}
            </>
          )}
          {section === 'project' && !selectedProject && <div className="ws-empty">Choose a demo identity with access to a project.</div>}
      </main>
    </div>
  );
}
