let currentSource = 'local';
let selectedPapers = new Map(); // paper_id -> PaperCard
let discoveredPapers = []; // all papers from last discover

// --- Scroll effect for topbar ---
let lastScrollY = 0;
window.addEventListener('scroll', () => {
  const topbar = document.querySelector('.topbar');
  if (window.scrollY > 10) {
    topbar.classList.add('scrolled');
  } else {
    topbar.classList.remove('scrolled');
  }
  lastScrollY = window.scrollY;
}, { passive: true });

// --- Keyboard shortcut ---
document.addEventListener('keydown', e => {
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) {
    e.preventDefault();
    const searchInput = document.getElementById('searchQuery');
    if (searchInput) { navigate('search'); searchInput.focus(); }
  }
  if (e.key === 'Escape') {
    document.activeElement?.blur();
  }
});

// --- Navigation ---
document.querySelectorAll('.topnav-btn').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

document.querySelectorAll('.source-tab').forEach(tab => {
  tab.addEventListener('click', () => switchSource(tab.dataset.source));
});

// Upload zone
const uploadZone = document.getElementById('uploadZone');
const zipFile = document.getElementById('zipFile');
if (uploadZone) {
  uploadZone.addEventListener('click', () => zipFile.click());
  uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
  uploadZone.addEventListener('dragleave', () => { uploadZone.classList.remove('dragover'); });
  uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      zipFile.files = e.dataTransfer.files;
      uploadZone.querySelector('p').textContent = e.dataTransfer.files[0].name;
    }
  });
  zipFile.addEventListener('change', () => {
    if (zipFile.files.length) uploadZone.querySelector('p').textContent = zipFile.files[0].name;
  });
}

function navigate(page) {
  document.querySelectorAll('.topnav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`page-${page}`);
  target.classList.add('active');
  // Re-trigger animation by removing and re-adding
  target.style.animation = 'none';
  target.offsetHeight; // force reflow
  target.style.animation = '';
  if (page === 'search') { loadRepos(); document.getElementById('searchQuery').focus(); }
  if (page === 'research') loadLibrary();
  if (page === 'index') loadConfig();
  if (page === 'chat') document.getElementById('chatInput').focus();
}

function switchSource(source) {
  currentSource = source;
  document.querySelectorAll('.source-tab').forEach(t => t.classList.toggle('active', t.dataset.source === source));
  document.querySelectorAll('.source-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`panel-${source}`);
  if (panel) panel.classList.add('active');
}

// --- API ---
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

// --- Status ---
async function pollStatus() {
  try {
    const s = await api('/sync/status');
    const dot = document.getElementById('statusDot');
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

// --- Index ---
function switchSourcePanel(source) {
  currentSource = source;
  document.querySelectorAll('.source-tab').forEach(t => t.classList.toggle('active', t.dataset.source === source));
  document.querySelectorAll('.source-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`panel-${source}`);
  if (panel) panel.classList.add('active');
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
  } catch (e) { toast('Failed to load config', e.message); }
}

async function browseFolders() {
  const list = document.getElementById('folderList');
  if (list.classList.contains('open')) { list.classList.remove('open'); return; }
  list.classList.add('open');
  list.innerHTML = '<div class="folder-item">Scanning...</div>';
  try {
    const { folders } = await api('/folders');
    if (!folders.length) { list.innerHTML = '<div class="folder-item">No git folders found.</div>'; return; }
    list.innerHTML = folders.map(f => `
      <div class="folder-item" data-path="${escAttr(f.path)}">
        <strong>${esc(f.name)}</strong>
        <span>${esc(f.path)}</span>
      </div>`).join('');
    list.querySelectorAll('.folder-item').forEach(item => {
      item.addEventListener('click', () => {
        document.getElementById('repoPath').value = item.dataset.path;
        list.classList.remove('open');
      });
    });
  } catch (e) { list.innerHTML = `<div class="folder-item">${esc(e.message)}</div>`; }
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
  } catch (e) { toast('Save failed', e.message); }
}

async function startIndexing() {
  const path = document.getElementById('repoPath').value.trim();
  if (currentSource === 'local' && !path) { toast('Path required', 'Enter a folder path first.'); return; }
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
        if (ev.type === 'connector_done') addLog(`Done: ${ev.key} (${ev.docs || 0} docs)`, 'success');
        if (ev.type === 'error') { addLog(`Error: ${ev.error}`, 'error'); toast('Indexing failed', ev.error); }
        if (ev.type === 'done' || ev.type === 'cancelled') {
          setProgress(100, ev.cancelled ? 'Cancelled' : 'Completed');
          addLog(ev.cancelled ? 'Cancelled' : 'Completed', 'success');
          pollStatus();
        }
      }
    }
  } catch (e) { addLog(`Failed: ${e.message}`, 'error'); toast('Indexing failed', e.message); }
}

async function stopIndexing() {
  try { await api('/sync/stop', { method: 'POST' }); addLog('Stop requested'); }
  catch (e) { toast('Stop failed', e.message); }
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

function showSearchSkeleton(host) {
  host.innerHTML = Array(4).fill('').map(() => `
    <div class="skeleton-card">
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
    </div>`).join('');
}

async function doSearch(e) {
  e.preventDefault();
  const q = document.getElementById('searchQuery').value.trim();
  if (!q) return false;
  const host = document.getElementById('searchResults');
  document.getElementById('searchBtn').disabled = true;
  showSearchSkeleton(host);
  try {
    const result = await api('/search', {
      method: 'POST',
      body: JSON.stringify({
        q, k: 10,
        hybrid: document.getElementById('searchHybrid').checked,
        repo: document.getElementById('searchRepo').value || null,
        source: document.getElementById('searchSource').value || null,
      }),
    });
    const hits = result.results || [];
    if (!hits.length) {
      host.innerHTML = '<div class="empty-state"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg><strong>No results found</strong>Try a different query or adjust filters.</div>';
      return false;
    }
    const countHtml = `<div class="result-count">${hits.length} result${hits.length !== 1 ? 's' : ''} for "${esc(q)}"</div>`;
    const cardsHtml = hits.map((h, i) => {
      const fileUrl = h.url || (h.title ? `/file?path=${encodeURIComponent(h.title)}` : '');
      const sourceLabel = (h.source || '').replace('github_files', 'file').replace('github_commits', 'commit');
      const delay = i * 60;
      return `
      <div class="result-card" ${fileUrl ? `onclick="window.open('${escAttr(fileUrl)}', '_blank')"` : ''} style="animation-delay:${delay}ms${fileUrl ? ';cursor:pointer' : ''}">
        <div class="title">${esc(h.title || `Result ${i + 1}`)}</div>
        <div class="meta">
          ${h.repo ? `<span class="pill">${esc(h.repo)}</span>` : ''}
          ${sourceLabel ? `<span class="pill">${esc(sourceLabel)}</span>` : ''}
          ${h.score != null ? `<span class="pill score">${Number(h.score).toFixed(3)}</span>` : ''}
        </div>
        <div class="snippet">${esc((h.snippet || '').slice(0, 400))}</div>
        ${h.url ? `<div class="path-label">${esc(h.url)}</div>` : ''}
      </div>`;
    }).join('');
    host.innerHTML = countHtml + cardsHtml;
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
    const res = await api('/chat', { method: 'POST', body: JSON.stringify({ q: text, k: 8, scope: document.getElementById('chatScope')?.value || null }) });
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
            a.href = s.url || (s.title ? `/file?path=${encodeURIComponent(s.title)}` : '#');
            a.target = '_blank';
            a.textContent = `[${i + 1}] ${s.title || s.repo || 'Source'}`;
            links.appendChild(a);
          });
          wrapper.appendChild(links);
        }
      }
    }
  } catch (e) { bubble.textContent = `Error: ${e.message}`; }
  finally { document.getElementById('chatBtn').disabled = false; input.focus(); }
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

function toggleChatScope() {
  const toggle = document.getElementById('chatScopeToggle');
  const scope = document.getElementById('chatScope');
  const label = document.getElementById('chatScopeLabel');
  if (toggle.checked) {
    scope.value = 'research';
    label.textContent = 'Ask about research papers';
  } else {
    scope.value = 'main';
    label.textContent = 'Ask about my papers';
  }
}

function scrollChat() {
  const el = document.getElementById('chatMessages');
  el.scrollTop = el.scrollHeight;
}

// --- Research ---
async function doDiscover(e) {
  e.preventDefault();
  const q = document.getElementById('discoverQuery').value.trim();
  if (!q) return false;

  const sources = [];
  if (document.getElementById('srcArxiv').checked) sources.push('arxiv');
  if (document.getElementById('srcS2').checked) sources.push('semantic_scholar');
  if (document.getElementById('srcOA').checked) sources.push('openalex');

  if (!sources.length) { toast('No sources', 'Select at least one source.'); return false; }

  const limit = parseInt(document.getElementById('discoverLimit').value, 10);
  const host = document.getElementById('discoverResults');
  const status = document.getElementById('discoverStatus');
  const actions = document.getElementById('discoverActions');

  document.getElementById('discoverBtn').disabled = true;
  status.textContent = `Searching ${sources.join(', ')}...`;
  status.classList.remove('hidden');
  host.innerHTML = '';
  actions.classList.add('hidden');
  selectedPapers.clear();
  updateSelectedCount();

  try {
    const result = await api('/research/discover', {
      method: 'POST',
      body: JSON.stringify({ q, sources, limit_per_source: limit }),
    });

    discoveredPapers = result.papers || [];
    const totalFound = result.total_found || 0;
    const alreadyIdx = result.already_indexed || 0;
    status.textContent = `Found ${totalFound} papers (${alreadyIdx} already indexed)`;

    if (!discoveredPapers.length) {
      host.innerHTML = '<div class="empty-state"><strong>No papers found</strong>Try a different query or adjust sources.</div>';
      return false;
    }

    renderPaperCards(discoveredPapers, host, false);
    actions.classList.remove('hidden');
    loadCollectionPicker();
  } catch (err) {
    host.innerHTML = `<div class="empty-state"><strong>Discover failed</strong>${esc(err.message)}</div>`;
  } finally {
    document.getElementById('discoverBtn').disabled = false;
  }
  return false;
}

function renderPaperCards(papers, container, isLibrary) {
  container.innerHTML = papers.map((p, i) => {
    const delay = i * 50;
    const sourceBadge = p.source ? `<span class="pill source-badge source-${esc(p.source)}">${esc(p.source)}</span>` : '';
    const yearBadge = p.year ? `<span class="pill">${esc(String(p.year))}</span>` : '';
    const citations = p.citation_count != null ? `<span class="pill score">${esc(String(p.citation_count))} cites</span>` : '';
    const venueBadge = p.venue ? `<span class="pill">${esc(p.venue.slice(0, 40))}</span>` : '';
    const indexedBadge = p.already_indexed ? '<span class="pill indexed-badge">Indexed</span>' : '';
    const checkbox = !isLibrary && !p.already_indexed
      ? `<label class="paper-select"><input type="checkbox" data-idx="${i}" onchange="togglePaperSelect(this, ${i})"><span class="toggle-slider"></span></label>`
      : '';
    const deleteBtn = isLibrary
      ? `<button class="btn danger btn-sm" onclick="deletePaper('${escAttr(p.paper_id)}')">Remove</button>`
      : '';
    const link = p.abs_url || p.pdf_url || '';

    return `
      <div class="paper-card" data-idx="${i}" style="animation-delay:${delay}ms">
        <div class="paper-card-top">
          ${checkbox}
          <div class="paper-card-title">${link ? `<a href="${escAttr(link)}" target="_blank">${esc(p.title)}</a>` : esc(p.title)}</div>
          ${deleteBtn}
        </div>
        <div class="paper-card-meta">
          ${sourceBadge} ${yearBadge} ${citations} ${venueBadge} ${indexedBadge}
          ${p.authors && p.authors.length ? `<span class="pill">${esc(p.authors.slice(0, 3).join(', '))}${p.authors.length > 3 ? ' et al.' : ''}</span>` : ''}
        </div>
        <div class="paper-card-abstract">${esc((p.abstract || '').slice(0, 300))}${(p.abstract || '').length > 300 ? '...' : ''}</div>
      </div>`;
  }).join('');
}

function togglePaperSelect(checkbox, idx) {
  const paper = discoveredPapers[idx];
  if (!paper) return;
  if (checkbox.checked) {
    selectedPapers.set(paper.paper_id, paper);
  } else {
    selectedPapers.delete(paper.paper_id);
  }
  updateSelectedCount();
}

function updateSelectedCount() {
  const el = document.getElementById('selectedCount');
  if (el) el.textContent = `${selectedPapers.size} selected`;
}

async function indexSelectedPapers() {
  if (!selectedPapers.size) { toast('No papers', 'Select papers first.'); return; }

  const collection = document.getElementById('collectionPicker').value || 'default';
  const card = document.getElementById('researchProgressCard');
  card.classList.remove('hidden');
  document.getElementById('researchProgressLog').innerHTML = '';
  setResearchProgress(4, 'Starting...');
  addResearchLog('Indexing started');

  const papersArray = Array.from(selectedPapers.values());

  try {
    const res = await api('/research/index', {
      method: 'POST',
      body: JSON.stringify({
        paper_ids: papersArray.map(p => p.paper_id),
        papers: papersArray,
        collection,
      }),
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
        if (ev.type === 'paper_indexed') {
          const p = Math.min(90, 20 + (ev.total_papers || 0) * 5);
          setResearchProgress(p, `${ev.total_papers || 0} papers, ${ev.total_chunks || 0} chunks`);
        }
        if (ev.type === 'paper_error') addResearchLog(`Error: ${ev.error}`, 'error');
        if (ev.type === 'done' || ev.type === 'cancelled') {
          setResearchProgress(100, ev.cancelled ? 'Cancelled' : 'Completed');
          addResearchLog(ev.cancelled ? 'Cancelled' : 'Completed', 'success');
          selectedPapers.clear();
          updateSelectedCount();
          loadLibrary();
        }
      }
    }
  } catch (err) {
    addResearchLog(`Failed: ${err.message}`, 'error');
    toast('Indexing failed', err.message);
  }
}

function setResearchProgress(pct, label) {
  document.getElementById('researchProgressFill').style.width = `${Math.min(100, Math.max(0, pct))}%`;
  document.getElementById('researchProgressPercent').textContent = `${Math.round(pct)}%`;
  if (label) document.getElementById('researchProgressLabel').textContent = label;
}

function addResearchLog(text, type = '') {
  const log = document.getElementById('researchProgressLog');
  const el = document.createElement('div');
  el.className = `log-entry ${type}`;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function loadLibrary() {
  const collection = document.getElementById('libraryCollection')?.value || '';
  const host = document.getElementById('libraryResults');
  host.innerHTML = '<div class="empty-state"><strong>Loading...</strong></div>';

  try {
    let url = '/research/catalog';
    if (collection) url += `?collection=${encodeURIComponent(collection)}`;
    const data = await api(url);
    const ids = data.papers || [];

    if (!ids.length) {
      host.innerHTML = '<div class="empty-state"><strong>No papers indexed yet</strong>Use Discover to find and index papers.</div>';
      return;
    }

    // Load collections into the library dropdown
    const libSelect = document.getElementById('libraryCollection');
    if (libSelect && data.collections) {
      libSelect.innerHTML = '<option value="">All collections</option>';
      data.collections.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        libSelect.appendChild(opt);
      });
    }

    // For now, search to get full metadata
    const searchResult = await api('/research/search', {
      method: 'POST',
      body: JSON.stringify({ q: '*', k: ids.length, collection: collection || null }),
    });

    const papers = (searchResult.results || []).map(r => ({
      paper_id: r.paper_id || '',
      title: r.title || '',
      source: r.source || '',
      year: r.year || null,
      venue: '',
      citation_count: null,
      authors: r.author ? [r.author] : [],
      abstract: r.snippet || '',
      abs_url: r.url || '',
      pdf_url: '',
      already_indexed: true,
    }));

    renderPaperCards(papers, host, true);
  } catch (err) {
    host.innerHTML = `<div class="empty-state"><strong>Failed to load library</strong>${esc(err.message)}</div>`;
  }
}

async function loadCollectionPicker() {
  try {
    const data = await api('/research/collections');
    const select = document.getElementById('collectionPicker');
    if (!select) return;
    select.innerHTML = '<option value="default">Default collection</option>';
    (data.collections || []).forEach(c => {
      if (c === 'default') return;
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = c;
      select.appendChild(opt);
    });
  } catch (_) {}
}

async function deletePaper(paperId) {
  if (!confirm('Remove this paper from the research library?')) return;
  try {
    await api('/research/delete', {
      method: 'POST',
      body: JSON.stringify({ paper_ids: [paperId] }),
    });
    toast('Removed', 'Paper deleted from library.');
    loadLibrary();
  } catch (err) {
    toast('Delete failed', err.message);
  }
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
navigate('search');
