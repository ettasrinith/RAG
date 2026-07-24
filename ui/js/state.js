/* ============================================================
   Knowledge Hub v2 -- Application Logic
   Modern SPA with SSE streaming, instant search, live dashboard
   ============================================================ */
'use strict';

/* ── State ───────────────────────────────────────────────── */
const State = {
  view: 'dashboard',
  source: 'folder',
  zipPath: null,
  selectedPapers: new Map(),
  discovered: [],
  streaming: false,
  theme: localStorage.getItem('kh-theme') || 'dark',
  indexProgress: null,
  health: null,
  viewsLoaded: new Set(),
};

/* ── Component Loader ────────────────────────────────────── */
const VIEWS = ['dashboard', 'search', 'chat', 'index', 'research', 'graph', 'settings', 'admin'];
const viewCache = {};

async function loadView(viewName) {
  if (State.viewsLoaded.has(viewName)) return;
  if (viewCache[viewName]) {
    insertView(viewName, viewCache[viewName]);
    return;
  }
  try {
    const res = await fetch('/static/views/' + viewName + '.html');
    if (!res.ok) throw new Error('Failed to load view: ' + viewName);
    const html = await res.text();
    viewCache[viewName] = html;
    insertView(viewName, html);
  } catch (e) {
    console.error('View load error:', viewName, e);
  }
}

function insertView(viewName, html) {
  const container = $('views-container');
  if (!container) return;
  // Create a temporary container to parse the HTML
  const temp = document.createElement('div');
  temp.innerHTML = html;
  const section = temp.querySelector('section.view');
  if (section) {
    container.appendChild(section);
    State.viewsLoaded.add(viewName);
  }
}

async function loadAllViews() {
  const container = $('views-container');
  if (!container) return;
  // Load all views in parallel
  const promises = VIEWS.map(v => loadView(v));
  await Promise.all(promises);
}

/* ── DOM helpers ─────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const qs = (s, p) => (p || document).querySelector(s);
const qsa = (s, p) => (p || document).querySelectorAll(s);

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function escAttr(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function highlight(text, query) {
  const s = String(text || '');
  const terms = String(query || '').toLowerCase().split(/\s+/).filter(t => t.length > 1);
  if (!terms.length) return esc(s);
  const safe = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp('(' + safe.join('|') + ')', 'ig');
  let out = '', last = 0, m;
  while ((m = re.exec(s))) {
    out += esc(s.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
    if (m[0].length === 0) re.lastIndex++;
  }
  return out + esc(s.slice(last));
}

/* ── Toast system ────────────────────────────────────────── */
function toast(title, text = '', type = '') {
  const container = $('toast-container');
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' toast-' + type : '');
  el.innerHTML = '<strong>' + esc(title) + '</strong>' + (text ? '<p>' + esc(text) + '</p>' : '') +
    '<div class="toast-progress"></div>';
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-exit');
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

/* ── API client ──────────────────────────────────────────── */
async function api(path, opts = {}) {
  const token = (localStorage.getItem('kh_token') || '').trim();
  const headers = { 'Content-Type': 'application/json', ...(token ? { 'X-API-Key': token } : {}), ...(opts.headers || {}) };
  if (opts.body instanceof FormData) delete headers['Content-Type'];
  const res = await fetch(path, { ...opts, headers });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    let msg = 'Request failed';
    try { const j = await res.json(); msg = j.detail || j.error || msg; } catch (_) { try { msg = await res.text() || msg; } catch (_e) {} }
    throw new Error(msg);
  }
  if (ct.includes('text/event-stream')) return res;
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

async function apiStream(path, body, onEvent) {
  const token = (localStorage.getItem('kh_token') || '').trim();
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { 'X-API-Key': token } : {}) },
    body: JSON.stringify(body),
  });
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('text/event-stream')) {
    let j = {};
    try { j = await res.json(); } catch (_) {}
    throw new Error(j.error || j.detail || 'Could not start stream');
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const l of lines) {
      if (!l.startsWith('data: ')) continue;
      try { onEvent(JSON.parse(l.slice(6))); } catch (_) {}
    }
  }
}

/* ── Theme ───────────────────────────────────────────────── */
function applyTheme(theme) {
  State.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('kh-theme', theme);
  // Update setting radio
  qsa('.theme-option').forEach(el => el.classList.toggle('active', el.dataset.themeVal === theme));
}

applyTheme(State.theme);

$('theme-toggle').addEventListener('click', () => {
  applyTheme(State.theme === 'dark' ? 'light' : 'dark');
});

document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    navigate('search');
    $('search-input').focus();
  }
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) {
    e.preventDefault();
    navigate('search');
    $('search-input').focus();
  }
  if (e.key === 'Escape' && document.activeElement) document.activeElement.blur();
});

/* ── Navigation ──────────────────────────────────────────── */
async function navigate(view) {
  State.view = view;
  // Load view if not loaded yet
  if (!State.viewsLoaded.has(view)) {
    await loadView(view);
  }
  // Sidebar
  qsa('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  // Views
  qsa('.view').forEach(v => v.classList.remove('active'));
  const target = $('view-' + view);
  if (target) target.classList.add('active');
  // Close mobile sidebar
  $('sidebar').classList.remove('open');
  $('sidebar-overlay').classList.remove('open');
  // Re-attach event listeners for dynamically loaded views
  reattachViewListeners(view);
  // Auto-focus / load data
  if (view === 'search') $('search-input')?.focus();
  if (view === 'chat') $('chat-input')?.focus();
  if (view === 'dashboard') refreshDashboard();
  if (view === 'research') { loadCollectionPicker(); loadLibrary(); }
  if (view === 'settings') loadSettings();
  if (view === 'admin') loadAdmin();
  if (view === 'graph') { loadGraphRepos(); }
}

/* ── Re-attach event listeners for dynamic views ──────────── */
function reattachViewListeners(view) {
  // Search view listeners
  if (view === 'search') {
    $('search-form')?.addEventListener('submit', e => { e.preventDefault(); doSearch(); });
    $('filter-source')?.addEventListener('change', doSearch);
    $('filter-repo')?.addEventListener('change', doSearch);
    $('filter-hybrid')?.addEventListener('change', doSearch);
  }

  // Chat view listeners
  if (view === 'chat') {
    $('chat-scope-selector')?.addEventListener('click', e => {
      const btn = e.target.closest('.scope-btn');
      if (!btn) return;
      qsa('.scope-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      chatScope = btn.dataset.scope;
    });
    $('agent-mode-toggle')?.addEventListener('change', e => {
      agentMode = e.target.checked;
      const input = $('chat-input');
      if (agentMode) {
        input.placeholder = 'Ask anything — agent will reason step by step…';
      } else {
        input.placeholder = 'Ask a question about your knowledge…';
      }
    });
    $('chat-suggestions')?.addEventListener('click', e => {
      const chip = e.target.closest('.suggestion-chip');
      if (!chip) return;
      $('chat-input').value = chip.dataset.q;
      sendChatMessage();
    });
    $('chat-input')?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
    });
    $('chat-input')?.addEventListener('input', () => {
      $('chat-send-btn').disabled = !$('chat-input').value.trim();
    });
    $('chat-send-btn')?.addEventListener('click', sendChatMessage);
    $('chat-new-btn')?.addEventListener('click', () => {
      currentSessionId = null;
      clearChatMessages();
      loadSessions();
    });
    $('chat-new-session-btn')?.addEventListener('click', () => {
      currentSessionId = null;
      clearChatMessages();
      loadSessions();
    });
    $('sessions-list')?.addEventListener('click', e => {
      const del = e.target.closest('.session-del');
      if (del) {
        e.stopPropagation();
        if (confirm('Delete this session?')) deleteSession(del.dataset.del);
        return;
      }
      const item = e.target.closest('.session-item');
      if (item && item.dataset.sid) switchSession(item.dataset.sid);
    });
    $('chat-attach-btn')?.addEventListener('click', () => $('chat-file-input')?.click());
    $('chat-attachment-remove')?.addEventListener('click', () => {
      attachedFile = null;
      attachedFileContent = '';
      $('chat-attachment-bar').style.display = 'none';
    });
    $('chat-messages')?.addEventListener('click', e => {
      const fb = e.target.closest('.fb-btn');
      if (!fb) return;
      const msgEl = fb.closest('.msg');
      const msgId = msgEl?.dataset?.msgId;
      const feedback = fb.dataset.fb;
      if (msgId) {
        saveFeedback(msgId, feedback);
        qsa('.fb-btn', msgEl).forEach(b => b.classList.remove('selected'));
        fb.classList.add('selected');
      }
    });
  }

  // Index view listeners
  if (view === 'index') {
    qsa('.source-card').forEach(c => {
      c.addEventListener('click', () => {
        qsa('.source-card').forEach(x => x.classList.remove('selected'));
        c.classList.add('selected');
        State.source = c.dataset.source;
        qsa('.config-panel').forEach(p => p.classList.remove('open'));
        const panel = $('panel-' + State.source);
        if (panel) panel.classList.add('open');
      });
    });
    $('folder-browse')?.addEventListener('click', async () => {
      const dd = $('folder-dropdown');
      if (dd.classList.contains('open')) { dd.classList.remove('open'); return; }
      dd.classList.add('open');
      dd.innerHTML = '<div class="folder-item"><strong>Scanning…</strong></div>';
      try {
        const { folders } = await api('/folders');
        if (!folders || !folders.length) {
          dd.innerHTML = '<div class="folder-item"><strong>No folders found</strong></div>';
          return;
        }
        dd.innerHTML = folders.map(f =>
          '<div class="folder-item" data-path="' + escAttr(f.path) + '"><strong>' + esc(f.name) + '</strong><span>' + esc(f.path) + '</span></div>'
        ).join('');
      } catch (e) {
        dd.innerHTML = '<div class="folder-item"><strong>' + esc(e.message) + '</strong></div>';
      }
    });
    $('folder-dropdown')?.addEventListener('click', e => {
      const item = e.target.closest('.folder-item');
      if (!item || !item.dataset.path) return;
      $('folder-path').value = item.dataset.path;
      $('folder-dropdown').classList.remove('open');
    });
    $('index-start-btn')?.addEventListener('click', startIndexing);
    $('index-stop-btn')?.addEventListener('click', stopIndexing);
  }

  // Research view listeners
  if (view === 'research') {
    qsa('.research-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        qsa('.research-tab').forEach(t => t.classList.remove('active'));
        qsa('.rtab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const target = $('rtab-' + tab.dataset.rtab);
        if (target) target.classList.add('active');
      });
    });
    $('discover-form')?.addEventListener('submit', e => { e.preventDefault(); discoverPapers(); });
    $('library-filter')?.addEventListener('change', loadLibrary);
    $('index-selected-btn')?.addEventListener('click', async () => {
      if (!State.selectedPapers.size) { toast('No papers', 'Select papers to index first.', 'error'); return; }
      const collection = $('collection-picker').value || 'default';
      try {
        await streamIndexPapers([...State.selectedPapers.values()], collection);
      } catch (e) {
        toast('Indexing failed', e.message, 'error');
      }
    });
  }

  // Graph view listeners
  if (view === 'graph') {
    $('graph-repo-list')?.addEventListener('click', e => {
      const item = e.target.closest('.graph-repo-item');
      if (item && item.dataset.repo) loadGraph(item.dataset.repo);
    });
    $('node-detail-close')?.addEventListener('click', () => {
      $('graph-node-detail').classList.add('hide');
    });
    $('graph-search-input')?.addEventListener('input', e => {
      const query = e.target.value.toLowerCase();
      if (!graphNetwork) return;
      if (!query) {
        graphNodes.forEach(n => { n.hidden = false; });
      } else {
        graphNodes.forEach(n => {
          n.hidden = !(n.label.toLowerCase().includes(query) || (n.entityData && n.entityData.type && n.entityData.type.toLowerCase().includes(query)));
        });
      }
      graphNetwork.setData({ nodes: new vis.DataSet(graphNodes.filter(n => !n.hidden)), edges: new vis.DataSet(graphEdges) });
    });
    $('graph-refresh')?.addEventListener('click', () => {
      loadGraphRepos();
      if (currentGraphRepo) loadGraph(currentGraphRepo);
    });
  }

  // Settings view listeners
  if (view === 'settings') {
    $('settings-save-key')?.addEventListener('click', () => {
      const key = $('settings-api-key').value.trim();
      localStorage.setItem('kh_token', key);
      toast('API Key saved', key ? 'Key has been stored.' : 'Key cleared.', 'warning');
    });
    $('settings-clear-btn')?.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to clear all indexed data? This cannot be undone.')) return;
      try {
        await api('/sync/clear', { method: 'POST' });
        toast('Cleared', 'All indexed data has been cleared.', 'warning');
        refreshDashboard();
      } catch (e) {
        toast('Clear failed', e.message, 'error');
      }
    });
    qsa('.theme-option').forEach(opt => {
      opt.addEventListener('click', () => {
        const theme = opt.dataset.themeVal;
        if (theme === 'system') {
          const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
          applyTheme(prefersDark ? 'dark' : 'light');
        } else {
          applyTheme(theme);
        }
      });
    });
  }

  // Admin view listeners
  if (view === 'admin') {
    $('admin-health-refresh')?.addEventListener('click', loadAdminHealth);
    $('admin-connectors-refresh')?.addEventListener('click', loadAdminConnectors);
    $('admin-collections-refresh')?.addEventListener('click', loadAdminCollections);
    $('admin-jobs-refresh')?.addEventListener('click', loadAdminJobs);
    $('admin-cache-refresh')?.addEventListener('click', loadAdminCacheStats);
    $('admin-tools-refresh')?.addEventListener('click', loadAdminTools);
    $('admin-save-config')?.addEventListener('click', async () => {
      try {
        const embeddingModel = $('admin-embed-model').value;
        const llmProvider = $('admin-llm-provider').value;
        const llmModel = $('admin-llm-model').value.trim();
        const chunkSize = parseInt($('admin-chunk-size').value, 10);
        const chunkOverlap = parseInt($('admin-chunk-overlap').value, 10);
        const searchRerank = $('admin-rerank').value === 'true';
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
  }
}

qsa('.nav-item').forEach(b => b.addEventListener('click', () => navigate(b.dataset.view)));

// Quick actions on dashboard
qsa('.qa-btn[data-view]').forEach(b => b.addEventListener('click', () => navigate(b.dataset.view)));

// Mobile sidebar toggle
$('sidebar-overlay').addEventListener('click', () => {
  $('sidebar').classList.remove('open');
  $('sidebar-overlay').classList.remove('open');
});

// Hamburger for mobile (not in HTML — we add it dynamically on small screens)
function initMobileSidebar() {
  const hamburger = document.createElement('button');
  hamburger.id = 'mobile-menu-btn';
  hamburger.className = 'btn btn-ghost btn-sm';
  hamburger.style.cssText = 'position:fixed;top:16px;left:16px;z-index:45;display:none;padding:8px 10px;';
  hamburger.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>';
  document.body.appendChild(hamburger);
  hamburger.addEventListener('click', () => {
    $('sidebar').classList.toggle('open');
    $('sidebar-overlay').classList.toggle('open');
  });
  const mql = window.matchMedia('(max-width: 768px)');
  function handleMobile(e) {
    hamburger.style.display = e.matches ? 'flex' : 'none';
    if (!e.matches) {
      $('sidebar').classList.remove('open');
      $('sidebar-overlay').classList.remove('open');
    }
  }
  mql.addListener(handleMobile);
  handleMobile(mql);
}
initMobileSidebar();

/* ── Status SSE (push, not poll) ─────────────────────────── */
let statusSource = null;

function connectStatusSSE() {
  if (statusSource) statusSource.close();
  const token = (localStorage.getItem('kh_token') || '').trim();
  const url = token ? '/sync/events?token=' + encodeURIComponent(token) : '/sync/events';
  statusSource = new EventSource(url);
  statusSource.onmessage = function (e) {
    try {
      var s = JSON.parse(e.data);
      State.health = s;
      var dot = $('status-dot');
      var txt = $('status-text');
      if (!dot || !txt) return;
      if (s.indexing) {
        dot.className = 'status-dot indexing';
        txt.textContent = 'Indexing…';
        var sb = $('index-start-btn');
        if (sb) sb.disabled = true;
        var sp = $('index-stop-btn');
        if (sp) sp.disabled = false;
      } else {
        dot.className = 'status-dot';
        txt.textContent = 'Ready';
        var sb = $('index-start-btn');
        if (sb) sb.disabled = false;
        var sp = $('index-stop-btn');
        if (sp) sp.disabled = true;
      }
    } catch (_) {}
  };
  // EventSource auto-reconnects — no manual handling needed.
}

connectStatusSSE();

