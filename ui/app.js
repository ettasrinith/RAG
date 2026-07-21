let currentSource = 'local';

// --- Navigation ---
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

document.querySelectorAll('.source-tab').forEach(tab => {
  tab.addEventListener('click', () => switchSource(tab.dataset.source));
});

function navigate(page) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');

  if (page === 'search') loadRepos();
  if (page === 'index') loadConfig();
}

function switchSource(source) {
  currentSource = source;
  document.querySelectorAll('.source-tab').forEach(t => t.classList.toggle('active', t.dataset.source === source));
  document.querySelectorAll('.source-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`panel-${source}`).classList.add('active');
}

// --- API helper ---
async function api(path, opts = {}) {
  const token = (localStorage.getItem('kh_token') || '').trim();
  const headers = { 'Content-Type': 'application/json', ...(token ? { 'X-API-Key': token } : {}), ...(opts.headers || {}) };
  const res = await fetch(path, { ...opts, headers });
  const ct = res.headers.get('content-type') || '';

  if (!res.ok) {
    const err = ct.includes('application/json') ? await res.json() : await res.text();
    throw new Error(err.detail || err.error || 'Request failed');
  }

  if (ct.includes('text/event-stream')) return res;
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

// --- Toast ---
function toast(title, text = '') {
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = `<strong>${esc(title)}</strong>${text ? `<p>${esc(text)}</p>` : ''}`;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); }, 3000);
}

// --- Status polling ---
async function pollStatus() {
  try {
    const s = await api('/sync/status');
    const dot = document.querySelector('.status-dot');
    const txt = document.getElementById('statusText');
    const badge = document.getElementById('progressBadge');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');

    if (s.indexing) {
      dot.className = 'status-dot indexing';
      txt.textContent = 'Indexing...';
      if (badge) { badge.textContent = 'Running'; badge.className = 'badge active'; }
      if (startBtn) startBtn.disabled = true;
      if (stopBtn) stopBtn.disabled = false;
    } else {
      dot.className = 'status-dot';
      txt.textContent = 'Ready';
      if (badge) { badge.textContent = 'Idle'; badge.className = 'badge'; }
      if (startBtn) startBtn.disabled = false;
      if (stopBtn) stopBtn.disabled = true;
    }
  } catch (_) {}
}
setInterval(pollStatus, 3000);
pollStatus();

// --- Index page ---
function switchSourcePanel(source) {
  currentSource = source;
  document.querySelectorAll('.source-tab').forEach(t => t.classList.toggle('active', t.dataset.source === source));
  document.querySelectorAll('.source-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`panel-${source}`).classList.add('active');
}

async function loadConfig() {
  try {
    const [cfg, status] = await Promise.all([api('/config'), api('/sync/status')]);
    const gh = cfg.github || {};

    document.getElementById('repoPath').value = cfg.repo_path || gh.local_path || '';
    document.getElementById('githubRepo').value = gh.repo || '';
    document.getElementById('githubPat').value = gh.pat || '';
    document.getElementById('githubBranch').value = gh.branch || '';

    const w = cfg.website || {};
    document.getElementById('websiteStartUrls').value = (w.start_urls || []).join('\n');
    document.getElementById('websiteMaxPages').value = w.max_pages ?? 150;
    document.getElementById('websiteMaxDepth').value = w.max_depth ?? 2;
    document.getElementById('websiteSameDomainOnly').checked = w.same_domain_only !== false;

    const a = cfg.arxiv || {};
    document.getElementById('arxivQuery').value = a.query || '';
    document.getElementById('arxivMaxResults').value = a.max_results ?? 50;
    document.getElementById('arxivIds').value = [...(a.ids || []), ...(a.urls || [])].join('\n');

    const y = cfg.youtube || {};
    document.getElementById('youtubeUrls').value = [...(y.urls || []), ...(y.video_ids || [])].join('\n');

    switchSourcePanel(gh.mode || 'local');
  } catch (e) {
    toast('Failed to load config', e.message);
  }
}

async function browseFolders() {
  const list = document.getElementById('folderList');
  if (list.classList.contains('open')) {
    list.classList.remove('open');
    return;
  }

  list.classList.add('open');
  list.innerHTML = '<div class="folder-item">Scanning...</div>';

  try {
    const { folders } = await api('/folders');
    if (!folders.length) {
      list.innerHTML = '<div class="folder-item">No git folders found.</div>';
      return;
    }
    list.innerHTML = folders.map(f => `
      <div class="folder-item" data-path="${escAttr(f.path)}">
        <strong>${esc(f.name)}</strong>
        <span>${esc(f.path)}</span>
      </div>
    `).join('');
    list.querySelectorAll('.folder-item').forEach(item => {
      item.addEventListener('click', () => {
        document.getElementById('repoPath').value = item.dataset.path;
        list.classList.remove('open');
      });
    });
  } catch (e) {
    list.innerHTML = `<div class="folder-item">${esc(e.message)}</div>`;
  }
}

async function saveSourceConfig() {
  const body = {
    repo_path: document.getElementById('repoPath').value || null,
    github_mode: currentSource,
    github_repo: document.getElementById('githubRepo').value || null,
    github_pat: document.getElementById('githubPat').value || null,
    github_branch: document.getElementById('githubBranch').value || null,
    github_files_enabled: currentSource === 'local' || currentSource === 'github',
    website_start_urls: splitLines(document.getElementById('websiteStartUrls').value),
    website_max_pages: intVal('websiteMaxPages', 150),
    website_max_depth: intVal('websiteMaxDepth', 2),
    website_same_domain_only: document.getElementById('websiteSameDomainOnly').checked,
    arxiv_query: document.getElementById('arxivQuery').value.trim() || null,
    arxiv_max_results: intVal('arxivMaxResults', 50),
    arxiv_ids: splitLines(document.getElementById('arxivIds').value),
    youtube_urls: splitLines(document.getElementById('youtubeUrls').value),
  };

  try {
    await api('/config', { method: 'POST', body: JSON.stringify(body) });
    toast('Saved');
  } catch (e) {
    toast('Save failed', e.message);
  }
}

async function startIndexing() {
  const path = document.getElementById('repoPath').value.trim();
  if (currentSource === 'local' && !path) {
    toast('Path required', 'Enter a folder path first.');
    return;
  }

  await saveSourceConfig();

  const card = document.getElementById('progressCard');
  card.classList.remove('hidden');
  document.getElementById('progressLog').innerHTML = '';
  setProgress(4, 'Starting...');
  addLog('Indexing started');

  try {
    const res = await api('/sync/start', {
      method: 'POST',
      body: JSON.stringify({ repo_path: currentSource === 'local' ? path : '', force_full: document.getElementById('forceFull').checked }),
    });

    if (!(res instanceof Response) || !res.body) throw new Error('Could not start');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }

        if (ev.type === 'doc_indexed') {
          const p = Math.min(90, 20 + (ev.total_docs || 0) * 2);
          setProgress(p, `${ev.total_docs || 0} docs, ${ev.total_chunks || 0} chunks`);
        }
        if (ev.type === 'connector_done') {
          addLog(`Done: ${ev.key} (${ev.docs || 0} docs)`, 'success');
        }
        if (ev.type === 'error') {
          addLog(`Error: ${ev.error}`, 'error');
          toast('Indexing failed', ev.error);
        }
        if (ev.type === 'done' || ev.type === 'cancelled') {
          setProgress(100, ev.cancelled ? 'Cancelled' : 'Completed');
          addLog(ev.cancelled ? 'Cancelled' : 'Completed', 'success');
          pollStatus();
        }
      }
    }
  } catch (e) {
    addLog(`Failed: ${e.message}`, 'error');
    toast('Indexing failed', e.message);
  }
}

async function stopIndexing() {
  try {
    await api('/sync/stop', { method: 'POST' });
    addLog('Stop requested');
  } catch (e) {
    toast('Stop failed', e.message);
  }
}

function setProgress(pct, label) {
  document.getElementById('progressFill').style.width = `${Math.min(100, Math.max(0, pct))}%`;
  document.getElementById('progressPercent').textContent = `${Math.round(pct)}%`;
  if (label) document.getElementById('progressLabel').textContent = label;
}

function addLog(text, type = '') {
  const log = document.getElementById('progressLog');
  const el = document.createElement('div');
  el.className = `log-entry ${type}`;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

// --- Search ---
async function loadRepos() {
  try {
    const { repos } = await api('/repos');
    const sel = document.getElementById('searchRepo');
    sel.innerHTML = '<option value="">All sources</option>';
    (repos || []).forEach(r => {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = r;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

async function doSearch(e) {
  e.preventDefault();
  const q = document.getElementById('searchQuery').value.trim();
  if (!q) return false;

  const host = document.getElementById('searchResults');
  document.getElementById('searchBtn').disabled = true;
  host.innerHTML = '<div class="empty-state">Searching...</div>';

  try {
    const result = await api('/search', {
      method: 'POST',
      body: JSON.stringify({
        q,
        k: 10,
        hybrid: document.getElementById('searchHybrid').checked,
        repo: document.getElementById('searchRepo').value || null,
        source: document.getElementById('searchSource').value || null,
      }),
    });

    const hits = result.results || [];
    if (!hits.length) {
      host.innerHTML = '<div class="empty-state"><strong>No results</strong>Try a different query.</div>';
      return false;
    }

    host.innerHTML = hits.map((h, i) => {
      const fileUrl = h.url || (h.title ? `/file?path=${encodeURIComponent(h.title)}` : '');
      return `
      <div class="result" ${fileUrl ? `onclick="window.open('${escAttr(fileUrl)}', '_blank')"` : ''} ${fileUrl ? 'style="cursor:pointer"' : ''}>
        <div class="result-title">${esc(h.title || `Result ${i + 1}`)}</div>
        <div class="result-meta">
          ${h.repo ? `<span class="tag">${esc(h.repo)}</span>` : ''}
          ${h.source ? `<span class="tag">${esc(h.source)}</span>` : ''}
          ${h.score != null ? `<span class="tag">${Number(h.score).toFixed(4)}</span>` : ''}
        </div>
        <div class="result-snippet">${esc((h.snippet || '').slice(0, 300))}</div>
      </div>`;
    }).join('');
  } catch (e) {
    host.innerHTML = `<div class="empty-state"><strong>Search failed</strong>${esc(e.message)}</div>`;
  } finally {
    document.getElementById('searchBtn').disabled = false;
  }
  return false;
}

// --- Chat ---
async function sendChat(e) {
  e.preventDefault();
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return false;

  addChatMsg('user', esc(text));
  input.value = '';
  document.getElementById('chatBtn').disabled = true;

  const wrapper = addChatMsg('assistant', '<span class="typing"><span></span><span></span><span></span></span>');
  const bubble = wrapper.querySelector('.bubble');
  let sources = [];
  let started = false;

  try {
    const res = await api('/chat', { method: 'POST', body: JSON.stringify({ q: text, k: 8 }) });
    if (!(res instanceof Response) || !res.body) throw new Error('No response');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let payload;
        try { payload = JSON.parse(line.slice(6)); } catch { continue; }

        if (payload.type === 'sources') sources = payload.sources || [];
        if (payload.type === 'error') { bubble.textContent = `Error: ${payload.error}`; break; }
        if (payload.type === 'token') {
          if (!started) { bubble.textContent = ''; started = true; }
          bubble.textContent += payload.text;
          scrollChat();
        }
        if (payload.type === 'done' && sources.length) {
          const links = document.createElement('div');
          links.className = 'source-links';
          sources.forEach((s, i) => {
            const a = document.createElement('a');
            a.href = s.url || '#';
            a.target = '_blank';
            a.textContent = `[${i + 1}] ${s.title || s.repo || 'Source'}`;
            links.appendChild(a);
          });
          wrapper.appendChild(links);
        }
      }
    }
  } catch (e) {
    bubble.textContent = `Error: ${e.message}`;
  } finally {
    document.getElementById('chatBtn').disabled = false;
    input.focus();
  }
  return false;
}

function addChatMsg(role, content) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = `<div class="bubble">${content}</div>`;
  document.getElementById('chatMessages').appendChild(div);
  scrollChat();
  return div;
}

function scrollChat() {
  const el = document.getElementById('chatMessages');
  el.scrollTop = el.scrollHeight;
}

// --- Helpers ---
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function escAttr(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function splitLines(v) {
  return String(v || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
}

function intVal(id, fallback) {
  return parseInt(document.getElementById(id)?.value || String(fallback), 10);
}

// --- Init ---
navigate('index');
