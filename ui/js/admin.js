/* ── ═══ ADMIN PANEL ═══════════════════════════════ */

async function loadAdmin() {
  loadAdminHealth();
  loadAdminConnectors();
  loadAdminCollections();
  loadAdminJobs();
  loadAdminCacheStats();
  loadAdminTools();
  loadAdminConfig();
}

async function loadAdminHealth() {
  try {
    const r = await api('/v1/health');
    const dot = $('ah-health-dot');
    dot.className = 'admin-dot ' + (r.status || 'unknown');
    $('ah-status').textContent = r.status || 'unknown';
    $('ah-uptime').textContent = r.uptime_s ? formatDuration(r.uptime_s) : '—';
    if (r.components) {
      const vs = r.components.vector_store;
      $('ah-vector').textContent = vs ? (vs.detail ? `${vs.status} (${vs.detail})` : vs.status) : '—';
      const db = r.components.database;
      $('ah-db').textContent = db ? (db.detail ? `${db.status} (${db.detail})` : db.status) : '—';
      const em = r.components.embedding_model;
      $('ah-embedding').textContent = em ? (em.detail ? `${em.status} (${em.detail})` : em.status) : '—';
    }
  } catch (e) {
    $('ah-status').textContent = 'unreachable';
  }
}

async function loadAdminConnectors() {
  const el = $('admin-connectors-list');
  try {
    const [repos, counts] = await Promise.all([
      api('/repos'),
      api('/health'),
    ]);
    const repoList = repos.repos || [];
    const repoCounts = counts.repo_counts || {};
    if (!repoList.length) {
      el.innerHTML = '<div class="empty-sm">No connectors configured</div>';
      return;
    }
    el.innerHTML = repoList.map(r => `
      <div class="admin-list-item">
        <div>
          <span class="admin-item-name">${esc(r)}</span>
          <span class="admin-item-meta">${repoCounts[r] || 0} chunks</span>
        </div>
        <span class="admin-badge active">Active</span>
      </div>
    `).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-sm">Failed to load connectors</div>';
  }
}

async function loadAdminCollections() {
  const el = $('admin-collections-list');
  try {
    const r = await api('/v1/collections');
    const collections = r.data || [];
    if (!collections.length) {
      el.innerHTML = '<div class="empty-sm">No collections yet</div>';
      return;
    }
    el.innerHTML = collections.map(c => `
      <div class="admin-list-item">
        <div>
          <span class="admin-item-name">${esc(c.name || c.id)}</span>
          <span class="admin-item-meta">${c.kind || 'default'} · ${c.doc_count || 0} docs</span>
        </div>
        <span class="admin-badge ${c.status === 'idle' ? 'idle' : 'active'}">${esc(c.status || 'idle')}</span>
      </div>
    `).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-sm">Failed to load collections</div>';
  }
}

async function loadAdminJobs() {
  const el = $('admin-jobs-list');
  try {
    const r = await api('/v1/jobs');
    const jobs = r.data || [];
    if (!jobs.length) {
      el.innerHTML = '<div class="empty-sm">No recent jobs</div>';
      return;
    }
    el.innerHTML = jobs.slice(0, 10).map(j => {
      const pct = j.items_total ? Math.round((j.items_done / j.items_total) * 100) : 0;
      return `
        <div class="admin-list-item">
          <div>
            <span class="admin-item-name">${esc(j.source || 'unknown')}</span>
            <span class="admin-item-meta">${j.items_done || 0}/${j.items_total || 0} · ${esc(j.state || 'pending')}</span>
          </div>
          <span class="admin-badge ${j.state === 'done' ? 'active' : j.state === 'failed' ? 'error' : 'idle'}">${esc(j.state || 'pending')}</span>
        </div>
      `;
    }).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-sm">Failed to load jobs</div>';
  }
}

async function loadAdminCacheStats() {
  try {
    const r = await api('/v1/admin:cache-stats');
    const emb = r.embedding || {};
    const search = r.search || {};
    const embHits = emb.hits || 0;
    const embMisses = emb.misses || 0;
    const searchHits = search.hits || 0;
    const searchMisses = search.misses || 0;
    const embTotal = embHits + embMisses;
    const searchTotal = searchHits + searchMisses;
    $('ac-embed-hits').textContent = embHits;
    $('ac-embed-misses').textContent = embMisses;
    $('ac-search-hits').textContent = searchHits;
    $('ac-search-misses').textContent = searchMisses;
    $('ac-embed-rate').style.width = embTotal > 0 ? Math.round((embHits / embTotal) * 100) + '%' : '0%';
    $('ac-search-rate').style.width = searchTotal > 0 ? Math.round((searchHits / searchTotal) * 100) + '%' : '0%';
  } catch (e) {
    // Fallback to placeholder values if endpoint unavailable
    $('ac-embed-hits').textContent = '—';
    $('ac-embed-misses').textContent = '—';
    $('ac-search-hits').textContent = '—';
    $('ac-search-misses').textContent = '—';
    $('ac-embed-rate').style.width = '0%';
    $('ac-search-rate').style.width = '0%';
  }
}

async function loadAdminTools() {
  const el = $('admin-tools-list');
  try {
    const r = await api('/v1/agent:tools');
    const tools = r.tools || [];
    if (!tools.length) {
      el.innerHTML = '<div class="empty-sm">No agent tools loaded</div>';
      return;
    }
    el.innerHTML = tools.map(t => {
      const cat = (t.category || 'general').toLowerCase();
      const catClass = ['search','analysis','utility','research'].includes(cat) ? ' cat-' + cat : ' cat-general';
      return `
      <div class="admin-list-item">
        <div>
          <span class="admin-item-name">${esc(t.name)}</span>
          <span class="admin-item-meta">${esc(t.description).slice(0, 80)}${t.description.length > 80 ? '…' : ''}</span>
        </div>
        <span class="admin-badge${catClass}">${esc(t.category || 'general')}</span>
      </div>
    `;
    }).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-sm">Failed to load tools</div>';
  }
}

async function loadAdminConfig() {
  try {
    const r = await api('/v1/admin:config');
    // Set embedding model
    if (r.embedding && r.embedding.model) {
      const sel = $('admin-embed-model');
      for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === r.embedding.model) { sel.selectedIndex = i; break; }
      }
    }
    // Set LLM provider
    if (r.llm && r.llm.provider) {
      const providerSel = $('admin-llm-provider');
      for (let i = 0; i < providerSel.options.length; i++) {
        if (providerSel.options[i].value === r.llm.provider) { providerSel.selectedIndex = i; break; }
      }
    }
    // Set LLM model
    if (r.llm && r.llm.model) $('admin-llm-model').value = r.llm.model;
    // Set chunk size
    if (r.chunking && r.chunking.chunk_size) $('admin-chunk-size').value = r.chunking.chunk_size;
    // Set chunk overlap
    if (r.chunking && r.chunking.chunk_overlap !== undefined) $('admin-chunk-overlap').value = r.chunking.chunk_overlap;
    // Set rerank
    if (r.search && r.search.rerank !== undefined) {
      $('admin-rerank').value = r.search.rerank ? 'true' : 'false';
    }
  } catch (e) {
    // Fallback to health endpoint if admin config unavailable
    try {
      const r = await api('/health');
      if (r.embedding_model) {
        const sel = $('admin-embed-model');
        for (let i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === r.embedding_model) { sel.selectedIndex = i; break; }
        }
      }
      if (r.llm_model) $('admin-llm-model').value = r.llm_model;
    } catch (_) {}
  }
}

$('admin-health-refresh')?.addEventListener('click', loadAdminHealth);
$('admin-connectors-refresh')?.addEventListener('click', loadAdminConnectors);
$('admin-collections-refresh')?.addEventListener('click', loadAdminCollections);
$('admin-jobs-refresh')?.addEventListener('click', loadAdminJobs);
$('admin-cache-refresh')?.addEventListener('click', loadAdminCacheStats);
$('admin-tools-refresh')?.addEventListener('click', loadAdminTools);

$('admin-save-config')?.addEventListener('click', async () => {
  try {
    // Collect all form values
    const embeddingModel = $('admin-embed-model').value;
    const llmProvider = $('admin-llm-provider').value;
    const llmModel = $('admin-llm-model').value.trim();
    const chunkSize = parseInt($('admin-chunk-size').value, 10);
    const chunkOverlap = parseInt($('admin-chunk-overlap').value, 10);
    const searchRerank = $('admin-rerank').value === 'true';

    // Build config update payload
    const payload = {};
    if (embeddingModel) payload.embedding_model = embeddingModel;
    if (llmProvider) payload.llm_provider = llmProvider;
    if (llmModel) payload.llm_model = llmModel;
    if (!isNaN(chunkSize)) payload.chunk_size = chunkSize;
    if (!isNaN(chunkOverlap)) payload.chunk_overlap = chunkOverlap;
    payload.search_rerank = searchRerank;

    await api('/v1/admin:config', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    toast('Config Saved', 'Configuration updated successfully.', 'success');
  } catch (e) {
    toast('Save failed', e.message, 'error');
  }
});

function formatDuration(seconds) {
  if (seconds < 60) return Math.round(seconds) + 's';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm';
  return (seconds / 3600).toFixed(1) + 'h';
}

