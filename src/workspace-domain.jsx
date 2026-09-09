/* Pure project lifecycle and research graph helpers. */

const WS_STASHED_STATUSES = new Set(['stashed', 'archived']);

function wsIsStashed(project){
  return !!project && WS_STASHED_STATUSES.has(project.status);
}

function wsValidateStash(input){
  const reason = String(input && input.reason || '').trim();
  const nextStep = String(input && input.nextStep || '').trim();
  if (!reason) return { ok:false, error:'Record why this project stopped.', errorField:'reason' };
  if (!nextStep) return { ok:false, error:'Record the recommended next step.', errorField:'nextStep' };
  return { ok:true, value:{ reason, nextStep, visibility:input.visibility === 'lab' ? 'lab' : 'private' } };
}

function wsProjectBuckets(projects){
  const all = Array.isArray(projects) ? projects.filter(Boolean) : [];
  return {
    active:all.filter(project => !wsIsStashed(project)),
    stashed:all.filter(wsIsStashed),
  };
}

function wsCanManageProject(project, person){
  if (!project || !person || !['pi', 'phd'].includes(person.tier)) return false;
  return person.scope === 'all' || (person.projects || []).includes(project.id);
}

function wsLifecycleEvent(action, actorKey, now, extra){
  return { action, actorKey, at:now, ...(extra || {}) };
}

function wsStashProject(project, input){
  const validated = wsValidateStash(input);
  if (!validated.ok) return validated;
  if (!project || wsIsStashed(project)) return { ok:false, error:'This project is already stashed.' };
  return {
    ok:true,
    project:{
      ...project,
      status:'stashed',
      stashedOn:input.now,
      stashedBy:input.actorKey,
      stashReason:validated.value.reason,
      stashNextStep:validated.value.nextStep,
      stashVisibility:validated.value.visibility,
      lifecycle:[...(project.lifecycle || []), wsLifecycleEvent('stashed', input.actorKey, input.now)],
    },
  };
}

function wsSetStashVisibility(project, input){
  if (!wsIsStashed(project)) return { ok:false, error:'Only a stashed project can change archive visibility.' };
  const visibility = input.visibility === 'lab' ? 'lab' : 'private';
  return {
    ok:true,
    project:{
      ...project,
      stashVisibility:visibility,
      lifecycle:[
        ...(project.lifecycle || []),
        wsLifecycleEvent(visibility === 'lab' ? 'shared' : 'made-private', input.actorKey, input.now),
      ],
    },
  };
}

function wsResumeProject(project, input){
  if (!wsIsStashed(project)) return { ok:false, error:'Only a stashed project can be resumed.' };
  return {
    ok:true,
    project:{
      ...project,
      status:'active',
      resumedOn:input.now,
      lifecycle:[...(project.lifecycle || []), wsLifecycleEvent('resumed', input.actorKey, input.now)],
    },
  };
}

function wsContinueProject(source, input){
  if (!wsIsStashed(source)) return { ok:false, error:'Only a stashed project can be continued.' };
  if (!input || !input.newId || !input.newCode || !input.actor) return { ok:false, error:'Continuation details are incomplete.' };
  const actor = input.actor;
  const entry = {
    id:input.newId + '-origin',
    d:String(input.now || '').slice(0, 10),
    t:'method',
    au:actor.s || actor.n,
    h:'Continued from ' + source.code,
    b:'This project continues the stashed record in ' + source.code + '. Read that immutable record before changing the next step.',
    ack:true,
    sourceProjectId:source.id,
  };
  const project = {
    ...source,
    id:input.newId,
    code:input.newCode,
    name:source.name + ' - continuation',
    status:'active',
    continuedFrom:source.id,
    started:String(input.now || '').slice(0, 10),
    current:[{ n:actor.n, i:actor.i, r:actor.line }],
    contacts:(source.contacts || []).map(item => ({ ...item })),
    artifacts:(source.artifacts || []).map(item => ({ ...item })),
    reading:(source.reading || []).map(item => ({ ...item })),
    log:[entry],
    lifecycle:[wsLifecycleEvent('continued', actor.k, input.now, { sourceProjectId:source.id })],
  };
  delete project.stashedOn;
  delete project.stashedBy;
  delete project.stashReason;
  delete project.stashNextStep;
  delete project.stashVisibility;
  delete project.archivedOn;
  delete project.archiveNote;
  return { ok:true, sourceProject:source, project };
}

function wsGraphSourceValues(entry){
  const values = [];
  const add = value => {
    if (!value) return;
    if (Array.isArray(value)) { value.forEach(add); return; }
    if (typeof value === 'string') { if (value.trim()) values.push(value.trim()); return; }
    if (typeof value === 'object') add(value.label || value.name || value.filename || value.title || value.ref || value.id);
  };
  ['sources', 'sourceRefs', 'citations', 'source', 'attachments', 'files'].forEach(key => add(entry && entry[key]));
  return [...new Set(values)];
}

function wsGraphStableId(prefix, value){
  let hash = 2166136261;
  const text = String(value).trim().toLowerCase();
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return prefix + ':' + (hash >>> 0).toString(36);
}

function wsBuildResearchGraph(projects, researchItems, options){
  const includePending = !!(options && options.includePending);
  const nodes = [];
  const edges = [];
  const warnings = [];
  const nodeIds = new Set();
  const edgeIds = new Set();
  const addNode = node => {
    if (!nodeIds.has(node.id)) {
      nodeIds.add(node.id);
      nodes.push(node);
    }
    return node.id;
  };
  const addEdge = edge => {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      warnings.push('Skipped unresolved connection: ' + edge.id);
      return;
    }
    if (!edgeIds.has(edge.id)) {
      edgeIds.add(edge.id);
      edges.push(edge);
    }
  };
  const sourceNodes = new Map();
  const visibleProjects = (projects || []).filter(project => project && project.id);

  visibleProjects.forEach(project => {
    const projectNodeId = 'project:' + project.id;
    addNode({
      id:projectNodeId,
      label:project.name || project.code || 'Untitled project',
      type:'project',
      projectId:project.id,
      projectIds:[project.id],
      status:wsIsStashed(project) ? 'stashed' : 'active',
      detail:project.oneLine || '',
      target:{ section:'project', projectId:project.id, projectTab:'overview' },
    });

    (project.log || []).filter(entry => entry && (includePending || entry.ack !== false)).forEach(entry => {
      const entryId = 'entry:' + project.id + ':' + entry.id;
      const type = entry.t === 'decision' ? 'decision' : 'record';
      addNode({
        id:entryId,
        label:entry.h || 'Untitled record',
        type,
        projectId:project.id,
        projectIds:[project.id],
        status:entry.ack === false ? 'pending' : 'approved',
        detail:entry.b || '',
        target:{ section:'project', projectId:project.id, projectTab:'record', entryId:entry.id },
      });
      addEdge({
        id:entryId + '>' + projectNodeId,
        source:entryId,
        target:projectNodeId,
        type:'belongs-to',
        label:'Belongs to ' + (project.code || project.name),
      });
      wsGraphSourceValues(entry).forEach(label => {
        const sourceId = wsGraphStableId('source', label);
        if (!sourceNodes.has(sourceId)) {
          const node = {
            id:sourceId,
            label,
            type:'source',
            projectId:null,
            projectIds:[],
            status:'recorded',
            detail:'Explicitly named source',
            target:null,
          };
          sourceNodes.set(sourceId, node);
          addNode(node);
        }
        const sourceNode = sourceNodes.get(sourceId);
        if (!sourceNode.projectIds.includes(project.id)) sourceNode.projectIds.push(project.id);
        addEdge({
          id:entryId + '>' + sourceId,
          source:entryId,
          target:sourceId,
          type:'uses',
          label:(type === 'decision' ? 'Decision supported by ' : 'Uses ') + label,
        });
      });
    });

    (project.artifacts || []).forEach((artifact, index) => {
      const artifactId = 'artifact:' + project.id + ':' + index;
      addNode({
        id:artifactId,
        label:artifact.n || 'Unnamed artifact',
        type:'artifact',
        projectId:project.id,
        projectIds:[project.id],
        status:'recorded',
        detail:artifact.d || '',
        target:{ section:'project', projectId:project.id, projectTab:'overview' },
      });
      addEdge({
        id:artifactId + '>' + projectNodeId,
        source:artifactId,
        target:projectNodeId,
        type:'belongs-to',
        label:'Artifact of ' + (project.code || project.name),
      });
    });
  });

  const projectIds = new Set(visibleProjects.map(project => project.id));
  const visibleResearch = (researchItems || []).filter(item => item && projectIds.has(item.projectId));
  visibleResearch.forEach(item => {
    addNode({
      id:'research:' + item.projectId + ':' + item.id,
      label:item.title || item.metric || 'Untitled research item',
      type:'research',
      projectId:item.projectId,
      projectIds:[item.projectId],
      status:item.status || 'recorded',
      detail:item.notes || '',
      target:{ section:'project', projectId:item.projectId, projectTab:'research', researchId:item.id },
    });
  });
  visibleResearch.forEach(item => {
    const researchId = 'research:' + item.projectId + ':' + item.id;
    addEdge({
      id:researchId + '>project:' + item.projectId,
      source:researchId,
      target:'project:' + item.projectId,
      type:'belongs-to',
      label:'Tracked in project',
    });
    if (item.sourceEntryId) {
      addEdge({
        id:researchId + '>entry:' + item.projectId + ':' + item.sourceEntryId,
        source:researchId,
        target:'entry:' + item.projectId + ':' + item.sourceEntryId,
        type:'supported-by',
        label:'Supported by approved evidence',
      });
    }
    if (item.experimentId) {
      addEdge({
        id:researchId + '>research:' + item.projectId + ':' + item.experimentId,
        source:researchId,
        target:'research:' + item.projectId + ':' + item.experimentId,
        type:'linked-experiment',
        label:'Linked to experiment',
      });
    }
  });

  visibleProjects.filter(project => project.continuedFrom && projectIds.has(project.continuedFrom)).forEach(project => {
    addEdge({
      id:'project:' + project.id + '>project:' + project.continuedFrom,
      source:'project:' + project.id,
      target:'project:' + project.continuedFrom,
      type:'continued-from',
      label:'Continued from stashed project',
    });
  });

  return {
    nodes,
    edges,
    warnings,
    counts:{
      nodes:nodes.length,
      edges:edges.length,
      projects:nodes.filter(node => node.type === 'project').length,
      sources:nodes.filter(node => ['source', 'artifact'].includes(node.type)).length,
    },
  };
}

function wsFilterResearchGraph(graph, filters){
  const scope = filters && filters.scope || 'all';
  const query = String(filters && filters.query || '').trim().toLowerCase();
  const types = new Set(filters && Array.isArray(filters.types) ? filters.types : []);
  const scoped = (graph.nodes || []).filter(node => scope === 'all'
    || node.projectId === scope || (node.projectIds || []).includes(scope));
  const scopedIds = new Set(scoped.map(node => node.id));
  const scopedEdges = (graph.edges || []).filter(edge => scopedIds.has(edge.source) && scopedIds.has(edge.target));
  const matches = scoped.filter(node => {
    const typeMatch = !types.size || types.has(node.type) || (!query && node.type === 'project');
    const text = [node.label, node.detail, node.type, node.projectId].filter(Boolean).join(' ').toLowerCase();
    return typeMatch && (!query || text.includes(query));
  });
  const keep = new Set(matches.map(node => node.id));
  if (query || types.size) {
    scopedEdges.forEach(edge => {
      if (keep.has(edge.source) || keep.has(edge.target)) {
        keep.add(edge.source);
        keep.add(edge.target);
      }
    });
  } else {
    scoped.forEach(node => keep.add(node.id));
  }
  const nodes = scoped.filter(node => keep.has(node.id));
  const ids = new Set(nodes.map(node => node.id));
  const edges = scopedEdges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
  return {
    ...graph,
    nodes,
    edges,
    counts:{
      nodes:nodes.length,
      edges:edges.length,
      projects:nodes.filter(node => node.type === 'project').length,
      sources:nodes.filter(node => ['source', 'artifact'].includes(node.type)).length,
    },
  };
}

function wsLayoutResearchGraph(graph, width, height){
  const ordered = [...(graph.nodes || [])].sort((left, right) => left.id.localeCompare(right.id));
  const nodes = ordered.map((node, index) => {
    const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2;
    return {
      ...node,
      x:width / 2 + Math.cos(angle) * width * 0.32,
      y:height / 2 + Math.sin(angle) * height * 0.32,
    };
  });
  const byId = new Map(nodes.map(node => [node.id, node]));
  for (let step = 0; step < 220; step += 1) {
    const cooling = 1 - step / 220;
    for (let left = 0; left < nodes.length; left += 1) {
      for (let right = left + 1; right < nodes.length; right += 1) {
        const a = nodes[left];
        const b = nodes[right];
        const dx = b.x - a.x || 0.01;
        const dy = b.y - a.y || 0.01;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const push = Math.max(0, 74 - distance) * 0.18 * cooling;
        a.x -= dx / distance * push;
        a.y -= dy / distance * push;
        b.x += dx / distance * push;
        b.y += dy / distance * push;
      }
    }
    (graph.edges || []).forEach(edge => {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b) return;
      const dx = b.x - a.x || 0.01;
      const dy = b.y - a.y || 0.01;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const pull = (distance - 128) * 0.025 * cooling;
      a.x += dx / distance * pull;
      a.y += dy / distance * pull;
      b.x -= dx / distance * pull;
      b.y -= dy / distance * pull;
    });
    nodes.forEach(node => {
      node.x += (width / 2 - node.x) * 0.003 * cooling;
      node.y += (height / 2 - node.y) * 0.003 * cooling;
      node.x = Math.max(28, Math.min(width - 28, node.x));
      node.y = Math.max(28, Math.min(height - 28, node.y));
    });
  }
  return nodes;
}

function wsPersistProjectTransition(storage, key, appState, transition){
  if (!transition || !transition.ok) return transition || { ok:false, error:'Project transition failed.' };
  const current = appState.projects || [];
  const projects = transition.sourceProject
    ? [...current, transition.project]
    : current.map(project => project.id === transition.project.id ? transition.project : project);
  try {
    storage.setItem(key, JSON.stringify({ ...appState, projects }));
    return { ...transition, projects };
  } catch (error) {
    return { ok:false, error:'Could not save this project change locally: ' + (error.message || 'storage failed') };
  }
}
