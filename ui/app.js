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
};

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
  el.innerHTML = '<strong>' + esc(title) + '</strong>' + (text ? '<p>' + esc(text) + '</p>' : '');
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
function navigate(view) {
  State.view = view;
  // Sidebar
  qsa('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  // Views
  qsa('.view').forEach(v => v.classList.remove('active'));
  const target = $('view-' + view);
  if (target) target.classList.add('active');
  // Close mobile sidebar
  $('sidebar').classList.remove('open');
  $('sidebar-overlay').classList.remove('open');
  // Auto-focus / load data
  if (view === 'search') $('search-input').focus();
  if (view === 'chat') $('chat-input').focus();
  if (view === 'dashboard') refreshDashboard();
  if (view === 'research') { loadCollectionPicker(); loadLibrary(); }
  if (view === 'settings') loadSettings();
  if (view === 'admin') loadAdmin();
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

/* ── Status polling ──────────────────────────────────────── */
async function pollStatus() {
  try {
    const s = await api('/sync/status');
    State.health = s;
    const dot = $('status-dot');
    const txt = $('status-text');
    if (s.indexing) {
      dot.className = 'status-dot indexing';
      txt.textContent = 'Indexing…';
      $('index-start-btn').disabled = true;
      $('index-stop-btn').disabled = false;
    } else {
      dot.className = 'status-dot';
      txt.textContent = 'Ready';
      $('index-start-btn').disabled = false;
      $('index-stop-btn').disabled = true;
    }
  } catch (_) {}
}
setInterval(pollStatus, 4000);

/* ── ═══ DASHBOARD ════════════════════════════════════ */

async function refreshDashboard() {
  try {
    const health = await api('/health');
    const repos = await api('/repos');

    $('stat-docs').textContent = health.rows != null ? health.rows.toLocaleString() : '—';
    $('stat-repos').textContent = (repos.repos || []).length || '—';
    $('stat-papers').textContent = health.research_rows != null ? health.research_rows.toLocaleString() : '—';
    $('stat-chats').textContent = health.llm_model || '—';

    // About info
    $('about-embedding').textContent = health.embedding_model || '—';
    $('about-llm').textContent = health.llm_model || '—';
    $('about-status').textContent = health.ok ? 'Online' : '—';

    // Repo chart
    const chartEl = $('dash-repo-chart');
    const counts = repos.counts || {};
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (entries.length) {
      const maxCount = Math.max(...entries.map(e => e[1]), 1);
      chartEl.innerHTML = entries.map(([name, count]) =>
        '<div class="repo-bar-row">' +
        '<span class="repo-bar-label">' + esc(name) + '</span>' +
        '<div class="repo-bar-track"><div class="repo-bar-fill" style="width:' + (count / maxCount * 100) + '%"></div></div>' +
        '<span class="repo-bar-count">' + count + '</span>' +
        '</div>'
      ).join('');
    } else {
      chartEl.innerHTML = '<div class="empty-sm">No repositories indexed yet</div>';
    }

    // Activity
    const activityEl = $('dash-activity');
    activityEl.innerHTML = [
      { type: 'index', text: 'Index has ' + (health.rows || 0) + ' documents' },
      { type: 'search', text: 'Search across ' + ((repos.repos || []).length || 0) + ' repos' },
      { type: 'chat', text: 'LLM: ' + (health.llm_model || 'N/A') },
    ].map(a =>
      '<div class="activity-item"><span class="activity-dot ' + a.type + '"></span>' + esc(a.text) + '</div>'
    ).join('');

  } catch (e) {
    toast('Dashboard Error', e.message, 'error');
  }
}

$('dashboard-refresh')?.addEventListener('click', refreshDashboard);

/* ── ═══ SEARCH ═══════════════════════════════════════ */

const SOURCE_LABELS = [
  ['github_files', 'Files'],
  ['github_commits', 'Commits'],
  ['website', 'Website'],
  ['arxiv', 'arXiv'],
  ['youtube', 'YouTube'],
  ['documents', 'Documents'],
];

(function initSourceFilter() {
  const sel = $('filter-source');
  SOURCE_LABELS.forEach(([v, l]) => {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = l;
    sel.appendChild(o);
  });
})();

async function loadRepoFilter() {
  try {
    const { repos, counts } = await api('/repos');
    const sel = $('filter-repo');
    sel.innerHTML = '<option value="">All repositories</option>';
    (repos || []).forEach(r => {
      const o = document.createElement('option');
      o.value = r;
      o.textContent = r + (counts && counts[r] != null ? ' (' + counts[r] + ')' : '');
      sel.appendChild(o);
    });
  } catch (_) {}
}

function updateFilterChips() {
  const src = $('filter-source').value;
  const repo = $('filter-repo').value;
  const chips = $('filter-chips');
  let html = '';
  if (src) html += '<span class="chip">Source: ' + esc((SOURCE_LABELS.find(x => x[0] === src) || [])[1] || src) + '<span class="chip-rm" data-clear="source">×</span></span>';
  if (repo) html += '<span class="chip">Repo: ' + esc(repo) + '<span class="chip-rm" data-clear="repo">×</span></span>';
  chips.innerHTML = html;
}

$('filter-chips').addEventListener('click', e => {
  const rm = e.target.closest('.chip-rm');
  if (!rm) return;
  if (rm.dataset.clear === 'source') $('filter-source').value = '';
  if (rm.dataset.clear === 'repo') $('filter-repo').value = '';
  doSearch();
});

async function doSearch() {
  const q = $('search-input').value.trim();
  const host = $('results-list');
  const empty = $('search-empty');
  updateFilterChips();

  if (!q) {
    host.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  // Show skeleton
  host.innerHTML = Array(4).fill(
    '<div class="skeleton-card">' +
    '<div class="skeleton-line"></div><div class="skeleton-line"></div>' +
    '<div class="skeleton-line"></div><div class="skeleton-line"></div>' +
    '</div>'
  ).join('');

  try {
    const d = await api('/search', {
      method: 'POST',
      body: JSON.stringify({
        q,
        k: 12,
        source: $('filter-source').value || null,
        repo: $('filter-repo').value || null,
      }),
    });
    renderSearchResults(q, d.results || []);
  } catch (e) {
    host.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Search failed</h3><p>' + esc(e.message) + '</p></div>';
  }
}

function renderSearchResults(q, hits) {
  const host = $('results-list');
  const metaParent = $('search-results');

  // Remove old meta
  const oldMeta = qs('.results-meta', metaParent);
  if (oldMeta) oldMeta.remove();

  if (!hits.length) {
    host.innerHTML = '<div class="empty-state"><div class="empty-icon">🔎</div><h3>No results</h3><p>Try a different query or clear filters.</p></div>';
    return;
  }

  // Meta
  const meta = document.createElement('div');
  meta.className = 'results-meta';
  meta.innerHTML = '<strong>' + hits.length + '</strong> results for "' + esc(q) + '"';
  metaParent.insertBefore(meta, host);

  // Cards
  host.innerHTML = hits.map((h, i) => {
    const url = h.url || (h.title ? '/file?path=' + encodeURIComponent(h.title) : '');
    const src = (h.source || '').replace('github_files', 'file').replace('github_commits', 'commit');
    const score = h.score != null && isFinite(h.score)
      ? '<span class="score-badge">' + Number(h.score).toFixed(3) + '</span>'
      : '';
    return '<article class="result-card" style="animation-delay:' + (i * 50) + 'ms"' +
      (url ? ' data-url="' + escAttr(url) + '"' : '') + '>' +
      '<div class="top"><div>' +
      '<div class="title">' + (url
        ? '<a href="' + escAttr(url) + '" target="_blank" rel="noopener">' + esc(h.title || 'Untitled') + '</a>'
        : esc(h.title || 'Untitled')) + '</div>' +
      '<div class="meta-row">' +
      (src ? '<span class="badge source">' + esc(src) + '</span>' : '') +
      (h.repo ? '<span class="badge">' + esc(h.repo) + '</span>' : '') +
      (h.author ? '<span class="badge author">' + esc(h.author) + '</span>' : '') +
      (h.year ? '<span class="badge year">' + h.year + '</span>' : '') +
      '</div></div>' + score + '</div>' +
      '<div class="snippet">' + highlight(h.snippet, q) + '</div>' +
      (h.summary ? '<div class="summary-line"><strong>Summary: </strong>' + esc(h.summary) + '</div>' : '') +
      '</article>';
  }).join('');
}

// Click card to open URL
$('results-list').addEventListener('click', e => {
  if (e.target.closest('a')) return;
  const card = e.target.closest('.result-card');
  if (card && card.dataset.url) window.open(card.dataset.url, '_blank');
});

let searchTimer;
$('search-input').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 280);
});
$('search-form').addEventListener('submit', e => { e.preventDefault(); doSearch(); });
$('filter-source').addEventListener('change', doSearch);
$('filter-repo').addEventListener('change', doSearch);
$('filter-hybrid').addEventListener('change', doSearch);

/* ── ═══ CHAT ═══════════════════════════════════════════ */

let chatHistory = [];
let chatScope = 'main';
let currentSessionId = null;
let attachedFile = null;
let attachedFileContent = '';

function addChatMessage(role, html, msgId) {
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  div.innerHTML = html;
  if (msgId) div.dataset.msgId = msgId;
  // Add feedback buttons for assistant messages
  if (role === 'assistant' && msgId) {
    const fb = document.createElement('div');
    fb.className = 'msg-feedback';
    fb.innerHTML =
      '<button class="fb-btn fb-up" data-fb="up" title="Good answer">👍</button>' +
      '<button class="fb-btn fb-down" data-fb="down" title="Bad answer">👎</button>';
    div.appendChild(fb);
  }
  $('chat-messages').appendChild(div);
  scrollChat();
  return div;
}

function scrollChat() {
  const el = $('chat-messages');
  el.scrollTop = el.scrollHeight;
}

/* ── Session Management ──────────────────────────────── */
async function loadSessions() {
  try {
    const sessions = await api('/v1/sessions');
    const list = $('sessions-list');
    if (!sessions || !sessions.length) {
      list.innerHTML = '<div class="empty-sm">No sessions yet</div>';
      return;
    }
    list.innerHTML = sessions.map(s =>
      '<div class="session-item' + (s.id === currentSessionId ? ' active' : '') + '" data-sid="' + escAttr(s.id) + '">' +
      '<span class="si-title">' + esc(s.title || 'New chat') + '</span>' +
      '<span class="si-meta">' + (s.message_count || 0) + ' messages</span>' +
      '<button class="session-del" data-del="' + escAttr(s.id) + '" title="Delete">×</button>' +
      '</div>'
    ).join('');
  } catch (_) {}
}

async function createSession() {
  try {
    const s = await api('/v1/sessions', { method: 'POST', body: JSON.stringify({ title: 'New chat' }) });
    currentSessionId = s.id;
    loadSessions();
    clearChatMessages();
    return s;
  } catch (_) { return null; }
}

async function switchSession(sid) {
  currentSessionId = sid;
  loadSessions();
  // Load messages
  try {
    const msgs = await api('/v1/sessions/' + sid);
    clearChatMessages();
    for (const m of msgs) {
      if (m.role === 'user') {
        addChatMessage('user', esc(m.content), m.id);
      } else {
        const rendered = renderCitations(m.content, m.sources || []);
        const div = addChatMessage('assistant', '<div>' + rendered + '</div>', m.id);
        if (m.sources && m.sources.length) {
          renderSources(m.sources);
        }
      }
    }
  } catch (_) {}
}

async function deleteSession(sid) {
  try {
    await api('/v1/sessions/' + sid, { method: 'DELETE' });
    if (currentSessionId === sid) {
      currentSessionId = null;
      clearChatMessages();
    }
    loadSessions();
  } catch (_) {}
}

async function saveMessage(role, content, sources) {
  if (!currentSessionId) {
    const s = await createSession();
    if (!s) return null;
  }
  try {
    const msg = await api('/v1/sessions/' + currentSessionId + '/messages', {
      method: 'POST',
      body: JSON.stringify({ role, content, sources: sources || null }),
    });
    loadSessions();
    return msg;
  } catch (_) { return null; }
}

async function saveFeedback(msgId, feedback) {
  if (!currentSessionId || !msgId) return;
  try {
    await api('/v1/sessions/' + currentSessionId + '/messages/' + msgId + '/feedback', {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    });
  } catch (_) {}
}

function clearChatMessages() {
  const msgs = $('chat-messages');
  msgs.innerHTML = '';
  const welcome = $('chat-welcome');
  if (welcome) msgs.appendChild(welcome.cloneNode(true));
  $('sources-list').innerHTML = '<div class="empty-sm">No sources yet. Ask a question to see sources.</div>';
  $('sources-count').textContent = '0';
  chatHistory = [];
}

// Session sidebar events
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

/* ── File Attachments ────────────────────────────────── */
$('chat-attach-btn')?.addEventListener('click', () => $('chat-file-input')?.click());

$('chat-file-input')?.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  attachedFile = file;
  $('chat-attachment-bar').style.display = 'flex';
  $('attachment-chip').textContent = '📎 ' + file.name;
  // Read file content
  try {
    attachedFileContent = await file.text();
  } catch (_) {
    attachedFileContent = '';
  }
  e.target.value = '';
});

$('chat-attachment-remove')?.addEventListener('click', () => {
  attachedFile = null;
  attachedFileContent = '';
  $('chat-attachment-bar').style.display = 'none';
});

/* ── Scope selector ──────────────────────────────────── */
$('chat-scope-selector')?.addEventListener('click', e => {
  const btn = e.target.closest('.scope-btn');
  if (!btn) return;
  qsa('.scope-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  chatScope = btn.dataset.scope;
});

// Suggestion chips
$('chat-suggestions')?.addEventListener('click', e => {
  const chip = e.target.closest('.suggestion-chip');
  if (!chip) return;
  $('chat-input').value = chip.dataset.q;
  sendChatMessage();
});

$('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
});
$('chat-input').addEventListener('input', () => {
  $('chat-send-btn').disabled = !$('chat-input').value.trim();
});
$('chat-send-btn').addEventListener('click', sendChatMessage);
$('chat-new-btn').addEventListener('click', () => {
  currentSessionId = null;
  clearChatMessages();
  loadSessions();
});

// Message feedback
$('chat-messages').addEventListener('click', e => {
  const fb = e.target.closest('.fb-btn');
  if (!fb) return;
  const msgEl = fb.closest('.msg');
  const msgId = msgEl?.dataset?.msgId;
  const feedback = fb.dataset.fb;
  if (msgId) {
    saveFeedback(msgId, feedback);
    // Visual feedback
    qsa('.fb-btn', msgEl).forEach(b => b.classList.remove('selected'));
    fb.classList.add('selected');
  }
});

async function sendChatMessage() {
  const inp = $('chat-input');
  const q = inp.value.trim();
  if (!q || State.streaming) return;

  // Build query with optional file context
  let fullQuery = q;
  if (attachedFileContent) {
    fullQuery = q + '\n\n--- Attached file: ' + attachedFile.name + ' ---\n' + attachedFileContent.slice(0, 8000);
  }

  inp.value = '';
  $('chat-send-btn').disabled = true;
  State.streaming = true;

  // Remove welcome
  const welcome = $('chat-welcome');
  if (welcome) welcome.remove();

  // Save user message
  const userMsg = await saveMessage('user', q);
  addChatMessage('user', esc(q), userMsg?.id);
  const msgEl = addChatMessage('assistant', '<span class="typing"><span></span><span></span><span></span></span>');

  let content = '';
  let sources = [];
  let started = false;

  try {
    await apiStream('/chat', { q: fullQuery, k: 8, scope: chatScope }, ev => {
      if (ev.type === 'sources') {
        sources = ev.sources || [];
        renderSources(sources);
      } else if (ev.type === 'token') {
        if (!started) { msgEl.innerHTML = ''; started = true; }
        content += ev.text;
        msgEl.innerHTML = '<div>' + renderCitations(content, sources) + '</div>';
        scrollChat();
      } else if (ev.type === 'done') {
        msgEl.innerHTML = '<div>' + renderCitations(content, sources) + '</div>';
        // Re-add feedback buttons
        const fbDiv = document.createElement('div');
        fbDiv.className = 'msg-feedback';
        fbDiv.innerHTML =
          '<button class="fb-btn fb-up" data-fb="up" title="Good answer">👍</button>' +
          '<button class="fb-btn fb-down" data-fb="down" title="Bad answer">👎</button>';
        msgEl.appendChild(fbDiv);
        // Save assistant message
        saveMessage('assistant', content, sources);
        // Clear attachment
        attachedFile = null;
        attachedFileContent = '';
        $('chat-attachment-bar').style.display = 'none';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
        inp.focus();
        scrollChat();
      } else if (ev.type === 'error') {
        msgEl.innerHTML = '<div>Error: ' + esc(ev.error || 'unknown') + '</div>';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
      }
    });
  } catch (e) {
    msgEl.innerHTML = '<div>Error: ' + esc(e.message) + '</div>';
  } finally {
    State.streaming = false;
    $('chat-send-btn').disabled = false;
    inp.focus();
    scrollChat();
  }
}

/* ── Inline Citations ─────────────────────────────────── */
function renderCitations(text, sources) {
  // Render [1], [2] etc. as clickable links to the source panel
  let safe = esc(text);
  if (sources && sources.length) {
    safe = safe.replace(/\[(\d+)\]/g, (match, num) => {
      const idx = parseInt(num, 10) - 1;
      if (idx >= 0 && idx < sources.length) {
        const url = sources[idx].url || '#';
        return '<a class="citation" href="' + escAttr(url) + '" target="_blank" rel="noopener" title="' + esc(sources[idx].title || '') + '">[' + num + ']</a>';
      }
      return match;
    });
  }
  return safe;
}

function renderSources(sources) {
  const list = $('sources-list');
  $('sources-count').textContent = sources.length;
  if (!sources.length) {
    list.innerHTML = '<div class="empty-sm">No sources found</div>';
    return;
  }
  list.innerHTML = sources.map((s, i) => {
    const snippet = s.snippet || s.text || '';
    const snippetHtml = snippet ? '<span class="si-snippet">' + esc(snippet.slice(0, 200)) + (snippet.length > 200 ? '…' : '') + '</span>' : '';
    const link = s.url ? '<a href="' + escAttr(s.url) + '" target="_blank" rel="noopener" class="si-link">Open source →</a>' : '';
    return '<div class="source-item" data-idx="' + (i + 1) + '">' +
    '<span class="si-num">[' + (i + 1) + ']</span>' +
    '<div class="si-body">' +
    '<span class="si-title">' + esc(s.title || 'Untitled') + '</span>' +
    '<span class="si-meta">' + esc(s.source || '') + (s.repo ? ' · ' + esc(s.repo) : '') + (s.score ? ' · ' + Number(s.score).toFixed(3) : '') + '</span>' +
    snippetHtml +
    link +
    '</div></div>';
  }).join('');
}

/* ── ═══ INDEX ═════════════════════════════════════════ */

// Source card selection
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
// Open folder panel by default
const defaultCard = qs('.source-card[data-source="folder"]');
if (defaultCard) defaultCard.click();

// Folder browser
$('folder-browse').addEventListener('click', async () => {
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

$('folder-dropdown').addEventListener('click', e => {
  const item = e.target.closest('.folder-item');
  if (!item || !item.dataset.path) return;
  $('folder-path').value = item.dataset.path;
  $('folder-dropdown').classList.remove('open');
});

// ZIP upload
const uz = $('upload-zone');
const zf = $('zip-file');
uz.addEventListener('click', () => zf.click());
uz.addEventListener('dragover', e => { e.preventDefault(); uz.classList.add('dragover'); });
uz.addEventListener('dragleave', () => uz.classList.remove('dragover'));
uz.addEventListener('drop', e => {
  e.preventDefault();
  uz.classList.remove('dragover');
  if (e.dataTransfer.files.length) uploadZipFile(e.dataTransfer.files[0]);
});
zf.addEventListener('change', () => { if (zf.files.length) uploadZipFile(zf.files[0]); });

async function uploadZipFile(file) {
  if (!/\.zip$/i.test(file.name)) { toast('Not a ZIP', 'Please choose a .zip file.', 'error'); return; }
  const status = $('upload-status');
  status.innerHTML = '<div class="upload-file-item"><span class="name">⏳ Uploading ' + esc(file.name) + '…</span></div>';
  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('label', file.name.replace(/\.zip$/i, ''));
    const token = (localStorage.getItem('kh_token') || '').trim();
    const res = await fetch('/uploads/zip', {
      method: 'POST',
      headers: token ? { 'X-API-Key': token } : {},
      body: fd,
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.detail || 'Upload failed');
    State.zipPath = j.path;
    status.innerHTML = '<div class="upload-file-item"><span class="name">📦 ' + esc(file.name) + '</span><span class="count">' + j.files + ' files</span><span class="rm" id="zip-clear">×</span></div>';
    toast('Uploaded', 'Extracted ' + j.files + ' files — ready to index.', 'warning');
  } catch (e) {
    State.zipPath = null;
    status.innerHTML = '';
    toast('Upload failed', e.message, 'error');
  }
}

$('upload-status')?.addEventListener('click', e => {
  if (e.target.id === 'zip-clear') {
    State.zipPath = null;
    $('upload-status').innerHTML = '';
    zf.value = '';
  }
});

// Config save
async function saveGithubConfig() {
  await api('/config', {
    method: 'POST',
    body: JSON.stringify({
      github_mode: 'github',
      github_repo: $('github-repo').value.trim() || null,
      github_pat: $('github-pat').value.trim() || null,
      github_branch: $('github-branch').value.trim() || null,
      github_files_enabled: true,
    }),
  });
}

async function saveYoutubeConfig() {
  const urls = $('youtube-urls').value.trim().split('\n').map(l => l.trim()).filter(Boolean);
  const ids = $('youtube-ids').value.trim().split('\n').map(l => l.trim()).filter(Boolean);
  const langs = $('youtube-langs').value.trim().split(',').map(l => l.trim()).filter(Boolean);
  const timestamps = $('youtube-timestamps').checked;
  await api('/config', {
    method: 'POST',
    body: JSON.stringify({
      github_mode: 'youtube',
      youtube_urls: urls,
      youtube_video_ids: ids,
      youtube_languages: langs.length ? langs : ['en'],
      youtube_include_timestamps: timestamps,
    }),
  });
}

// Progress helpers
function setProgress(pct, label) {
  $('progress-fill').style.width = Math.min(100, Math.max(0, pct)) + '%';
  $('progress-pct').textContent = Math.round(pct) + '%';
  if (label) $('progress-label').textContent = label;
}

function addLog(text, type = '') {
  const log = $('progress-log');
  const el = document.createElement('div');
  el.className = 'log-entry ' + type;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

// Start indexing
$('index-start-btn').addEventListener('click', startIndexing);

async function startIndexing() {
  let repoPath = '';
  if (State.source === 'folder') {
    repoPath = $('folder-path').value.trim();
    if (!repoPath) { toast('Path required', 'Enter or browse to a folder first.', 'error'); return; }
  } else if (State.source === 'github') {
    if (!$('github-repo').value.trim()) { toast('Repo required', 'Enter owner/repo first.', 'error'); return; }
    try { await saveGithubConfig(); } catch (e) { toast('Config save failed', e.message, 'error'); return; }
  } else if (State.source === 'zip') {
    if (!State.zipPath) { toast('Upload first', 'Drop a ZIP to extract it, then index.', 'error'); return; }
    repoPath = State.zipPath;
  } else if (State.source === 'youtube') {
    const urls = $('youtube-urls').value.trim();
    const ids = $('youtube-ids').value.trim();
    if (!urls && !ids) { toast('URLs or IDs required', 'Enter at least one YouTube URL or video ID.', 'error'); return; }
    try { await saveYoutubeConfig(); } catch (e) { toast('Config save failed', e.message, 'error'); return; }
  }

  const panel = $('progress-panel');
  panel.classList.remove('hide');
  $('progress-log').innerHTML = '';
  setProgress(4, 'Starting…');
  addLog('Indexing started');
  $('index-start-btn').disabled = true;
  $('index-stop-btn').disabled = false;

  try {
    await apiStream('/sync/start', { repo_path: repoPath, force_full: $('force-full').checked }, ev => {
      if (ev.type === 'doc_indexed') {
        setProgress(Math.min(90, 20 + (ev.total_docs || 0) * 2), (ev.total_docs || 0) + ' docs · ' + (ev.total_chunks || 0) + ' chunks');
      } else if (ev.type === 'connector_done') {
        addLog('Done: ' + ev.key + ' (' + (ev.docs || 0) + ' docs)', 'success');
      } else if (ev.type === 'error') {
        addLog('Error: ' + ev.error, 'error');
        toast('Indexing failed', ev.error, 'error');
      } else if (ev.type === 'done' || ev.type === 'cancelled') {
        setProgress(100, ev.cancelled ? 'Cancelled' : 'Completed');
        addLog(ev.cancelled ? 'Cancelled' : 'Completed', 'success');
        toast(ev.cancelled ? 'Indexing cancelled' : 'Indexing complete', '', 'warning');
        $('index-start-btn').disabled = false;
        $('index-stop-btn').disabled = true;
        pollStatus();
      }
    });
  } catch (e) {
    addLog('Failed: ' + e.message, 'error');
    toast('Indexing failed', e.message, 'error');
  } finally {
    pollStatus();
  }
}

$('index-stop-btn').addEventListener('click', async () => {
  try {
    await api('/sync/stop', { method: 'POST' });
    addLog('Stop requested…');
  } catch (e) {
    toast('Stop failed', e.message, 'error');
  }
});

/* ── ═══ RESEARCH ══════════════════════════════════════ */

// Tabs
qsa('.research-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    qsa('.research-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    qsa('.rtab-content').forEach(c => c.classList.remove('active'));
    const target = $('rtab-' + tab.dataset.rtab);
    if (target) target.classList.add('active');
    if (tab.dataset.rtab === 'library') loadLibrary();
  });
});

// Source toggles
qsa('.src-tgl').forEach(tgl => {
  tgl.addEventListener('click', () => {
    const cb = tgl.querySelector('input[type="checkbox"]');
    if (cb) {
      cb.checked = !cb.checked;
      tgl.classList.toggle('active', cb.checked);
    }
  });
});

function authorsStr(p) {
  if (Array.isArray(p.authors)) return p.authors.slice(0, 3).join(', ') + (p.authors.length > 3 ? ' et al.' : '');
  return p.authors || p.author || '';
}

// Discover
$('discover-form').addEventListener('submit', e => { e.preventDefault(); doDiscover(); });

async function doDiscover() {
  const q = $('discover-query').value.trim();
  if (!q) return;

  const sources = [];
  if ($('src-arxiv').checked) sources.push('arxiv');
  if ($('src-s2').checked) sources.push('semantic_scholar');
  if ($('src-oa').checked) sources.push('openalex');
  if (!sources.length) { toast('No sources', 'Select at least one source.', 'error'); return; }

  const host = $('discover-results');
  const status = $('discover-status');
  $('discover-btn').disabled = true;
  status.style.display = 'flex';
  status.innerHTML = '<span class="spinner-sm"></span> Searching ' + sources.join(', ') + '…';
  host.innerHTML = '';
  $('selection-bar').classList.add('hide');
  State.selectedPapers.clear();
  updateSelectionCount();

  try {
    const d = await api('/research/discover', {
      method: 'POST',
      body: JSON.stringify({
        q,
        sources,
        limit_per_source: parseInt($('discover-limit').value, 10) || 10,
      }),
    });
    State.discovered = d.papers || [];
    status.innerHTML = 'Found <strong>' + (d.total_found || State.discovered.length) + '</strong> papers' +
      (d.already_indexed ? ' (' + d.already_indexed + ' already indexed)' : '');
    if (!State.discovered.length) {
      host.innerHTML = '<div class="empty-state"><div class="empty-icon">🔬</div><h3>No papers found</h3><p>Try a different query or enable more sources.</p></div>';
      return;
    }
    renderPapers(sortPapers(State.discovered), host, false, q);
    $('selection-bar').classList.remove('hide');
    loadCollectionPicker();
  } catch (e) {
    status.style.display = 'none';
    host.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Discover failed</h3><p>' + esc(e.message) + '</p></div>';
  } finally {
    $('discover-btn').disabled = false;
  }
}

function sortPapers(list) {
  const mode = $('discover-sort').value;
  const a = [...list];
  if (mode === 'year_desc') a.sort((x, y) => (y.year || 0) - (x.year || 0));
  else if (mode === 'citations_desc') a.sort((x, y) => (y.citation_count || 0) - (x.citation_count || 0));
  return a;
}

$('discover-sort').addEventListener('change', () => {
  if (State.discovered.length) {
    renderPapers(sortPapers(State.discovered), $('discover-results'), false, $('discover-query').value.trim());
  }
});

function renderPapers(papers, host, isLibrary, q) {
  host.innerHTML = papers.map((p, i) => {
    const id = p.paper_id || p.id || '';
    const link = p.abs_url || p.pdf_url || p.url || '';
    const au = authorsStr(p);
    const sel = !isLibrary && !p.already_indexed
      ? '<label class="paper-select"><input type="checkbox" data-id="' + escAttr(id) + '" ' + (State.selectedPapers.has(id) ? 'checked' : '') + ' /><span class="box">✓</span></label>'
      : '';
    const del = isLibrary ? '<button class="btn btn-danger btn-sm" data-del="' + escAttr(id) + '">Remove</button>' : '';
    const indexBtn = (!isLibrary && !p.already_indexed)
      ? '<button class="btn btn-primary btn-sm" data-indexone="' + escAttr(id) + '" data-title="' + escAttr(p.title || '') + '">Index</button>'
      : '';
    const pdfBtn = p.pdf_url
      ? '<a class="btn btn-secondary btn-sm" href="' + escAttr(p.pdf_url) + '" target="_blank" rel="noopener">PDF</a>'
      : '';
    const idxBadge = p.already_indexed ? '<span class="badge" style="background:var(--amber-soft);color:var(--amber)">Indexed</span>' : '';
    const abstract = (p.abstract || p.snippet || '');
    return '<article class="paper-card' + (State.selectedPapers.has(id) ? ' selected' : '') + '" style="animation-delay:' + (i * 45) + 'ms">' + sel +
      '<div class="paper-title">' + (link
        ? '<a href="' + escAttr(link) + '" target="_blank" rel="noopener">' + esc(p.title || 'Untitled') + '</a>'
        : esc(p.title || 'Untitled')) + '</div>' +
      (au ? '<div class="paper-authors">' + esc(au) + '</div>' : '') +
      '<div class="paper-meta">' +
      (p.source ? '<span class="badge source">' + esc(p.source) + '</span>' : '') +
      (p.year ? '<span class="badge year">' + esc(String(p.year)) + '</span>' : '') +
      (p.citation_count != null ? '<span class="badge cites">' + esc(String(p.citation_count)) + ' cites</span>' : '') +
      (p.venue ? '<span class="badge">' + esc(String(p.venue).slice(0, 40)) + '</span>' : '') +
      idxBadge +
      '</div>' +
      (abstract ? '<div class="paper-abstract">' + highlight(abstract, q || '') + '</div>' : '') +
      '<div class="paper-actions">' + indexBtn + pdfBtn + del + '</div>' +
      '</article>';
  }).join('');
}

// Selection
$('discover-results').addEventListener('change', e => {
  const cb = e.target.closest('input[type=checkbox][data-id]');
  if (!cb) return;
  const id = cb.dataset.id;
  const paper = State.discovered.find(p => (p.paper_id || p.id) === id);
  if (cb.checked) { if (paper) State.selectedPapers.set(id, paper); }
  else State.selectedPapers.delete(id);
  const card = cb.closest('.paper-card');
  if (card) card.classList.toggle('selected', cb.checked);
  updateSelectionCount();
});

$('discover-results').addEventListener('click', e => {
  const one = e.target.closest('[data-indexone]');
  if (one) indexSinglePaper(one.dataset.indexone, one.dataset.title);
});

function updateSelectionCount() {
  $('selection-count').textContent = State.selectedPapers.size + ' selected';
}

async function loadCollectionPicker() {
  try {
    const d = await api('/research/collections');
    const sel = $('collection-picker');
    sel.innerHTML = '<option value="default">default</option>';
    (d.collections || []).forEach(c => {
      if (c === 'default') return;
      const o = document.createElement('option');
      o.value = c;
      o.textContent = c;
      sel.appendChild(o);
    });
    // Library filter
    const lib = $('library-filter');
    if (lib) {
      lib.innerHTML = '<option value="">All collections</option>';
      (d.collections || []).forEach(c => {
        const o = document.createElement('option');
        o.value = c;
        o.textContent = c;
        lib.appendChild(o);
      });
    }
  } catch (_) {}
}

// Research progress
function setRProgress(pct, label) {
  $('research-prog-fill').style.width = Math.min(100, Math.max(0, pct)) + '%';
  $('research-prog-pct').textContent = Math.round(pct) + '%';
  if (label) $('research-prog-label').textContent = label;
}
function addRLog(text, type = '') {
  const log = $('research-prog-log');
  const el = document.createElement('div');
  el.className = 'log-entry ' + type;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function streamIndexPapers(papers, collection) {
  const panel = $('research-progress-panel');
  panel.classList.remove('hide');
  $('research-prog-log').innerHTML = '';
  setRProgress(4, 'Starting…');
  addRLog('Indexing ' + papers.length + ' paper(s)…');
  await apiStream('/research/index', {
    paper_ids: papers.map(p => p.paper_id || p.id),
    papers,
    collection,
  }, ev => {
    if (ev.type === 'paper_indexed') {
      setRProgress(Math.min(90, 20 + (ev.total_papers || 0) * 8), (ev.total_papers || 0) + ' papers');
    } else if (ev.type === 'paper_error') {
      addRLog('Error: ' + ev.error, 'error');
    } else if (ev.type === 'error') {
      addRLog('Error: ' + ev.error, 'error');
      toast('Indexing failed', ev.error, 'error');
    } else if (ev.type === 'done' || ev.type === 'cancelled') {
      setRProgress(100, ev.cancelled ? 'Cancelled' : 'Completed');
      addRLog(ev.cancelled ? 'Cancelled' : 'Completed', 'success');
      toast(ev.cancelled ? 'Cancelled' : 'Papers indexed', '', 'warning');
      State.selectedPapers.clear();
      updateSelectionCount();
      loadLibrary();
    }
  });
}

$('index-selected-btn').addEventListener('click', async () => {
  if (!State.selectedPapers.size) { toast('No papers', 'Select papers to index first.', 'error'); return; }
  const collection = $('collection-picker').value || 'default';
  try {
    await streamIndexPapers([...State.selectedPapers.values()], collection);
  } catch (e) {
    addRLog('Failed: ' + e.message, 'error');
    toast('Indexing failed', e.message, 'error');
  }
});

async function indexSinglePaper(id, title) {
  const paper = State.discovered.find(p => (p.paper_id || p.id) === id);
  const papers = paper ? [paper] : [{ paper_id: id, title }];
  const collection = $('collection-picker').value || 'default';
  try {
    await streamIndexPapers(papers, collection);
  } catch (e) {
    toast('Indexing failed', e.message, 'error');
  }
}

/* ── Research Library ────────────────────────────────────── */

async function loadLibrary() {
  const collection = $('library-filter').value || '';
  const host = $('library-results');
  host.innerHTML = '<div style="text-align:center;padding:40px"><span class="spinner-sm"></span></div>';
  try {
    let url = '/research/catalog';
    if (collection) url += '?collection=' + encodeURIComponent(collection);
    const cat = await api(url);
    const ids = cat.papers || [];
    $('library-count').textContent = ids.length ? ids.length + ' papers' : '';

    if (!ids.length) {
      host.innerHTML = '<div class="empty-state"><div class="empty-icon">📚</div><h3>No papers indexed</h3><p>Use Discover to find and index papers.</p></div>';
      return;
    }
    const sr = await api('/research/search', {
      method: 'POST',
      body: JSON.stringify({
        q: '*',
        k: Math.max(ids.length, 1),
        collection: collection || null,
      }),
    });
    const papers = (sr.results || []).map(r => ({
      paper_id: r.paper_id || '',
      title: r.title || '',
      source: r.source || '',
      year: r.year || null,
      authors: r.author ? [r.author] : [],
      abstract: r.snippet || '',
      abs_url: r.url || '',
      already_indexed: true,
    }));
    renderPapers(papers, host, true, '');
  } catch (e) {
    host.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Failed to load library</h3><p>' + esc(e.message) + '</p></div>';
  }
}

$('library-filter').addEventListener('change', loadLibrary);

$('library-results').addEventListener('click', async e => {
  const btn = e.target.closest('[data-del]');
  if (!btn) return;
  if (!confirm('Remove this paper from the research library?')) return;
  try {
    await api('/research/delete', {
      method: 'POST',
      body: JSON.stringify({ paper_ids: [btn.dataset.del] }),
    });
    toast('Removed', 'Paper deleted from library.', 'warning');
    loadLibrary();
  } catch (e) {
    toast('Delete failed', e.message, 'error');
  }
});

/* ── ═══ KNOWLEDGE GRAPH ═════════════════════════════ */

// Simple placeholder — the graph is a visualization that would need D3.js or similar
// We show a message and a simple entity list if available
async function loadGraph() {
  try {
    // Check if graph is enabled by hitting health or a graph endpoint
    const health = await api('/health');
    const graphEl = $('graph-empty');
    const canvas = $('graph-canvas');
    // Try to fetch repos for graph
    const repos = await api('/repos');
    const repoList = repos.repos || [];
    if (repoList.length) {
      // Show basic repo info — full graph would need D3.js
      graphEl.querySelector('h3').textContent = 'Knowledge Graph';
      graphEl.querySelector('p').textContent = repoList.length + ' repos available. Enable knowledge_graph in config.yaml for entity extraction.';
      graphEl.innerHTML += '<div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center">' +
        repoList.slice(0, 10).map(r => '<span class="badge" style="font-size:13px;padding:6px 14px">' + esc(r) + '</span>').join('') +
        '</div>';
    }
  } catch (_) {}
}

// Load graph when view becomes active (handled in navigate -> but we also load on init)
if ($('view-graph')) {
  const observer = new MutationObserver(() => {
    if ($('view-graph').classList.contains('active')) loadGraph();
  });
  observer.observe($('view-graph'), { attributes: true, attributeFilter: ['class'] });
}

/* ── ═══ SETTINGS ════════════════════════════════════ */

function loadSettings() {
  const savedKey = localStorage.getItem('kh_token') || '';
  if (savedKey) $('settings-api-key').value = savedKey;
}

$('settings-save-key').addEventListener('click', () => {
  const key = $('settings-api-key').value.trim();
  localStorage.setItem('kh_token', key);
  toast('API Key saved', key ? 'Key has been stored.' : 'Key cleared.', 'warning');
});

$('settings-clear-btn').addEventListener('click', async () => {
  if (!confirm('Are you sure you want to clear all indexed data? This cannot be undone.')) return;
  try {
    await api('/sync/clear', { method: 'POST' });
    toast('Cleared', 'All indexed data has been cleared.', 'warning');
    refreshDashboard();
  } catch (e) {
    toast('Clear failed', e.message, 'error');
  }
});

// Theme options in settings
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
      $('ah-vector').textContent = vs ? `${vs.status} (${vs.detail || ''})` : '—';
      const db = r.components.database;
      $('ah-db').textContent = db ? `${db.status} (${db.detail || ''})` : '—';
      const em = r.components.embedding_model;
      $('ah-embedding').textContent = em ? `${em.status} (${em.detail || ''})` : '—';
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
    // Cache stats are server-side; show placeholder until /v1/cache-stats exists
    $('ac-embed-hits').textContent = '—';
    $('ac-embed-misses').textContent = '—';
    $('ac-search-hits').textContent = '—';
    $('ac-search-misses').textContent = '—';
    $('ac-embed-rate').style.width = '0%';
    $('ac-search-rate').style.width = '0%';
  } catch (e) {}
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
    el.innerHTML = tools.map(t => `
      <div class="admin-list-item">
        <div>
          <span class="admin-item-name">${esc(t.name)}</span>
          <span class="admin-item-meta">${esc(t.description).slice(0, 80)}${t.description.length > 80 ? '...' : ''}</span>
        </div>
        <span class="admin-badge idle">${esc(t.category || 'general')}</span>
      </div>
    `).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-sm">Failed to load tools</div>';
  }
}

async function loadAdminConfig() {
  try {
    const r = await api('/health');
    if (r.embedding_model) {
      const sel = $('admin-embed-model');
      for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === r.embedding_model) { sel.selectedIndex = i; break; }
      }
    }
    if (r.llm_model) $('admin-llm-model').value = r.llm_model;
  } catch (e) {}
}

$('admin-health-refresh')?.addEventListener('click', loadAdminHealth);
$('admin-connectors-refresh')?.addEventListener('click', loadAdminConnectors);
$('admin-collections-refresh')?.addEventListener('click', loadAdminCollections);
$('admin-jobs-refresh')?.addEventListener('click', loadAdminJobs);
$('admin-cache-refresh')?.addEventListener('click', loadAdminCacheStats);
$('admin-tools-refresh')?.addEventListener('click', loadAdminTools);

$('admin-save-config')?.addEventListener('click', async () => {
  try {
    await api('/config', {
      method: 'POST',
      body: JSON.stringify({
        // Config save goes through legacy endpoint
      }),
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

/* ── ═══ INIT ════════════════════════════════════════ */

(async function init() {
  loadRepoFilter();
  pollStatus();
  // Load dashboard data on start
  setTimeout(refreshDashboard, 300);
  // Research collection picker
  loadCollectionPicker();
})();

console.log('🔬 Knowledge Hub v2 · UI initialized');
