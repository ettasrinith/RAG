/* ── ═══ KNOWLEDGE GRAPH ═════════════════════════════ */

// Entity type colors
const ENTITY_COLORS = {
  PERSON: '#3b82f6',
  ORGANIZATION: '#10b981',
  CODE_CLASS: '#8b5cf6',
  FUNCTION: '#f97316',
  MODULE: '#14b8a6',
  CONCEPT: '#ec4899',
  FILE: '#6b7280',
  API_ENDPOINT: '#ef4444',
  DEPENDENCY: '#eab308',
};

let graphNetwork = null;
let currentGraphRepo = null;
let graphNodes = [];
let graphEdges = [];

async function loadGraphRepos() {
  const repoList = $('graph-repo-list');
  try {
    const stats = await api('/v1/admin:kg-stats');
    const repos = stats.repos || [];
    if (!repos.length) {
      repoList.innerHTML = '<div class="empty-sm">No knowledge graphs yet. Index data to build a graph.</div>';
      return;
    }
    repoList.innerHTML = repos.map(r =>
      '<div class="graph-repo-item" data-repo="' + escAttr(r) + '">' +
        '<span>' + esc(r) + '</span>' +
      '</div>'
    ).join('');

    // Update stats
    $('kg-entities').textContent = stats.total_entities || 0;
    $('kg-relations').textContent = stats.total_relations || 0;

    // Build legend
    const legendItems = $('graph-legend-items');
    const types = stats.entity_types || {};
    legendItems.innerHTML = Object.entries(types).map(([type, count]) =>
      '<div class="legend-item">' +
        '<span class="legend-dot" style="background:' + (ENTITY_COLORS[type] || '#6b7280') + '"></span>' +
        '<span>' + esc(type) + ' (' + count + ')</span>' +
      '</div>'
    ).join('');

  } catch (e) {
    repoList.innerHTML = '<div class="empty-sm">Failed to load graph data</div>';
  }
}

async function loadGraph(repo) {
  if (!repo) return;
  currentGraphRepo = repo;

  // Update active state
  qsa('.graph-repo-item').forEach(el => el.classList.toggle('active', el.dataset.repo === repo));

  const canvas = $('graph-canvas');
  const empty = $('graph-empty');
  const detail = $('graph-node-detail');

  // Show loading
  empty.innerHTML = '<div style="padding:60px 20px"><div class="skeleton-line" style="width:40%;margin:0 auto 12px"></div><div class="skeleton-line" style="width:60%;margin:0 auto"></div></div>';
  empty.style.display = 'flex';
  canvas.style.display = 'none';
  detail.classList.add('hide');

  try {
    const data = await api('/graph/' + encodeURIComponent(repo));
    const entities = data.entities || [];
    const relations = data.relations || [];

    if (!entities.length) {
      empty.innerHTML = '<div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="5" cy="19" r="2"/></svg></div><h3>No entities found</h3><p>This repository has no extracted entities yet.</p>';
      return;
    }

    // Build vis-network data
    const nodeMap = new Map();
    graphNodes = entities.map((e, i) => {
      const id = e.id || e.name + '_' + i;
      nodeMap.set(e.name, id);
      return {
        id: id,
        label: e.name.length > 25 ? e.name.slice(0, 22) + '…' : e.name,
        title: e.name + ' (' + (e.type || 'unknown') + ')',
        color: {
          background: ENTITY_COLORS[e.type] || '#6b7280',
          border: ENTITY_COLORS[e.type] || '#6b7280',
          highlight: { background: ENTITY_COLORS[e.type] || '#6b7280', border: '#fff' },
        },
        font: { color: '#e5e7eb', size: 12 },
        size: 15,
        type: e.type,
        entityData: e,
      };
    });

    graphEdges = relations.map((r, i) => {
      const sourceId = nodeMap.get(r.source);
      const targetId = nodeMap.get(r.target);
      if (sourceId == null || targetId == null) return null;
      return {
        id: 'e' + i,
        from: sourceId,
        to: targetId,
        label: r.relation || '',
        title: (r.source || '') + ' → ' + (r.relation || '') + ' → ' + (r.target || ''),
        color: { color: '#4b5563', highlight: '#9ca3af' },
        font: { color: '#9ca3af', size: 10, strokeWidth: 0 },
        arrows: 'to',
        smooth: { type: 'continuous' },
      };
    }).filter(Boolean);

    // Render graph
    empty.style.display = 'none';
    canvas.style.display = 'block';

    const nodes = new vis.DataSet(graphNodes);
    const edges = new vis.DataSet(graphEdges);

    if (graphNetwork) {
      graphNetwork.destroy();
    }

    graphNetwork = new vis.Network(canvas, { nodes, edges }, {
      physics: {
        enabled: true,
        barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 150, springConstant: 0.04 },
        stabilization: { iterations: 150 },
      },
      interaction: { hover: true, tooltipDelay: 200 },
      nodes: { borderWidth: 2 },
      edges: { width: 1 },
    });

    // Node click handler
    graphNetwork.on('click', params => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        const node = graphNodes.find(n => n.id === nodeId);
        if (node) showNodeDetail(node);
      } else {
        detail.classList.add('hide');
      }
    });

  } catch (e) {
    empty.innerHTML = '<div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="5" cy="19" r="2"/></svg></div><h3>Failed to load graph</h3><p>' + esc(e.message) + '</p>';
    empty.style.display = 'flex';
    canvas.style.display = 'none';
  }
}

function showNodeDetail(node) {
  const detail = $('graph-node-detail');
  const data = node.entityData || {};
  $('node-detail-name').textContent = data.name || node.label;
  const typeBadge = $('node-detail-type');
  typeBadge.textContent = data.type || 'unknown';
  typeBadge.style.background = (ENTITY_COLORS[data.type] || '#6b7280') + '22';
  typeBadge.style.color = ENTITY_COLORS[data.type] || '#6b7280';

  // Meta info
  const meta = $('node-detail-meta');
  const metaRows = [];
  if (data.repo) metaRows.push('<div class="meta-row"><span>Repository</span><span>' + esc(data.repo) + '</span></div>');
  if (data.file) metaRows.push('<div class="meta-row"><span>File</span><span>' + esc(data.file) + '</span></div>');
  if (data.line) metaRows.push('<div class="meta-row"><span>Line</span><span>' + esc(String(data.line)) + '</span></div>');
  meta.innerHTML = metaRows.join('');

  // Related documents
  const docsList = $('node-detail-docs-list');
  const connectedEdges = graphEdges.filter(e => e.from === node.id || e.to === node.id);
  if (connectedEdges.length) {
    docsList.innerHTML = connectedEdges.slice(0, 5).map(e => {
      const otherId = e.from === node.id ? e.to : e.from;
      const other = graphNodes.find(n => n.id === otherId);
      return '<div class="node-doc-item">' + esc(other ? other.label : 'Unknown') + ' <span style="color:var(--text-muted)">(' + esc(e.label) + ')</span></div>';
    }).join('');
  } else {
    docsList.innerHTML = '<div class="empty-sm">No connections</div>';
  }

  detail.classList.remove('hide');
}

// Graph repo click handler
$('graph-repo-list')?.addEventListener('click', e => {
  const item = e.target.closest('.graph-repo-item');
  if (item && item.dataset.repo) loadGraph(item.dataset.repo);
});

// Close node detail
$('node-detail-close')?.addEventListener('click', () => {
  $('graph-node-detail').classList.add('hide');
});

// Graph search
$('graph-search-input')?.addEventListener('input', e => {
  const query = e.target.value.toLowerCase();
  if (!graphNetwork) return;
  if (!query) {
    // Reset all nodes
    graphNodes.forEach(n => { n.hidden = false; });
  } else {
    graphNodes.forEach(n => {
      n.hidden = !(n.label.toLowerCase().includes(query) || (n.entityData && n.entityData.type && n.entityData.type.toLowerCase().includes(query)));
    });
  }
  graphNetwork.setData({ nodes: new vis.DataSet(graphNodes.filter(n => !n.hidden)), edges: new vis.DataSet(graphEdges) });
});

// Refresh button
$('graph-refresh')?.addEventListener('click', () => {
  loadGraphRepos();
  if (currentGraphRepo) loadGraph(currentGraphRepo);
});

// Load graph when view becomes active
if ($('view-graph')) {
  const observer = new MutationObserver(() => {
    if ($('view-graph').classList.contains('active')) {
      loadGraphRepos();
      if (!currentGraphRepo) {
        $('graph-empty').style.display = 'flex';
        $('graph-canvas').style.display = 'none';
      }
    }
  });
  observer.observe($('view-graph'), { attributes: true, attributeFilter: ['class'] });
}

