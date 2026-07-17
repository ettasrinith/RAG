const API = '';
let currentPage = 'dashboard';
let currentSourceMode = 'local';
let keyBuffer = '';

const SOURCE_MODES = ['local', 'github', 'website', 'arxiv', 'youtube', 'zip'];

const pageMeta = {
  dashboard: {
    title: 'Dashboard',
    subtitle: 'A cleaner workspace for indexing GitHub repositories, local folders, and academic material.'
  },
  search: {
    title: 'Search',
    subtitle: 'Search code, notes, docs, and indexed learning content.'
  },
  chat: {
    title: 'Chat',
    subtitle: 'Ask grounded questions over your indexed sources.'
  },
  index: {
    title: 'Index',
    subtitle: 'Use local folders, GitHub, or a reusable website crawler to build your retrieval base.'
  },
  settings: {
    title: 'Settings',
    subtitle: 'Tune answer model, embeddings, chunking, and retrieval behavior.'
  }
};

document.querySelectorAll('.nav-item').forEach((item) => {
  item.addEventListener('click', () => navigate(item.dataset.page));
});

document.querySelectorAll('#sourceModeButtons .segment').forEach((button) => {
  button.addEventListener('click', () => setSourceMode(button.dataset.mode));
});

document.getElementById('menuButton')?.addEventListener('click', () => toggleSidebar(true));
document.getElementById('sidebarBackdrop')?.addEventListener('click', () => toggleSidebar(false));
document.addEventListener('keydown', handleGlobalShortcuts);

function toggleSidebar(open) {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const next = typeof open === 'boolean' ? open : !sidebar.classList.contains('open');
  sidebar.classList.toggle('open', next);
  backdrop.classList.toggle('show', next);
}

function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.page === page));
  document.querySelectorAll('.page').forEach((section) => section.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');
  document.getElementById('pageTitle').textContent = pageMeta[page]?.title || page;
  document.getElementById('pageSubtitle').textContent = pageMeta[page]?.subtitle || '';
  toggleSidebar(false);

  if (page === 'dashboard') refreshDashboard();
  if (page === 'search') loadSearchFilters();
  if (page === 'index') loadIndexConfig();
  if (page === 'settings') loadSettings();
}

async function api(path, opts = {}) {
  const token = (localStorage.getItem('kh_token') || '').trim();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'X-API-Key': token } : {}),
    ...(opts.headers || {}),
  };
  const res = await fetch(API + path, { ...opts, headers, credentials: 'same-origin' });
  const ct = res.headers.get('content-type') || '';

  if (!res.ok) {
    let message = 'Request failed';
    try {
      if (ct.includes('application/json')) {
        const err = await res.json();
        message = err.detail || err.error || message;
      } else {
        message = await res.text();
      }
    } catch (_) {}
    throw new Error(message || 'Request failed');
  }

  if (ct.includes('text/event-stream')) return res;
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

function showToast(title, text = '') {
  const region = document.getElementById('toastRegion');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<strong>${escapeHtml(title)}</strong>${text ? `<p>${escapeHtml(text)}</p>` : ''}`;
  region.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 3200);
}

function handleGlobalShortcuts(event) {
  const tag = document.activeElement?.tagName?.toLowerCase();
  const typing = tag === 'input' || tag === 'textarea';

  if (event.key === '/' && !typing) {
    event.preventDefault();
    navigate('search');
    setTimeout(() => document.getElementById('searchQuery')?.focus(), 30);
    return;
  }

  if (typing) return;

  keyBuffer += event.key.toLowerCase();
  if (keyBuffer.length > 2) keyBuffer = keyBuffer.slice(-2);

  if (keyBuffer === 'gd') navigate('dashboard');
  if (keyBuffer === 'gs') navigate('search');
  if (keyBuffer === 'gc') navigate('chat');
  if (keyBuffer === 'gi') navigate('index');

  clearTimeout(handleGlobalShortcuts._t);
  handleGlobalShortcuts._t = setTimeout(() => { keyBuffer = ''; }, 500);
}

function updateClock() {
  const now = new Date();
  document.getElementById('clockPill').textContent = now.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}
setInterval(updateClock, 1000);
updateClock();

function formatNumber(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toLocaleString() : String(value || '0');
}

function setStatus(state = {}) {
  const indexing = !!state.indexing;
  const stopped = !!state.stop_requested && !indexing;
  const errored = !!state.error;

  let css = 'idle';
  let label = 'Idle';
  if (errored) {
    css = 'error';
    label = 'Error';
  } else if (indexing) {
    css = 'running';
    label = 'Indexing';
  } else if (stopped) {
    css = 'stopped';
    label = 'Stopped';
  }

  const sidebar = document.getElementById('sidebarStatus');
  sidebar.innerHTML = `<span class="status-dot ${css}"></span><span>${label}</span>`;
  document.getElementById('topbarStatus').textContent = label;

  const badge = document.getElementById('indexStatusBadge');
  if (badge) badge.innerHTML = `<span class="status-dot ${css}"></span><span>${label}</span>`;

  const startBtn = document.getElementById('startIndexButton');
  const stopBtn = document.getElementById('stopIndexButton');
  if (startBtn) startBtn.disabled = indexing;
  if (stopBtn) stopBtn.disabled = !indexing;
}

async function pollStatus() {
  try {
    const status = await api('/sync/status');
    setStatus(status);
  } catch (_) {}
}
setInterval(pollStatus, 3000);

function repoItem(name, count, max) {
  const width = max > 0 ? Math.max(6, Math.round((count / max) * 100)) : 6;
  return `
    <div class="repo-item">
      <strong>${escapeHtml(name)}</strong>
      <p>${formatNumber(count)} chunks indexed</p>
      <div class="repo-progress"><span style="width:${width}%"></span></div>
    </div>
  `;
}

async function refreshDashboard() {
  try {
    const [health, repos, cfg] = await Promise.all([
      api('/health'),
      api('/repos'),
      api('/config')
    ]);

    const repoCounts = health.repo_counts || {};
    document.getElementById('statDocs').textContent = formatNumber((health.repos || []).length);
    document.getElementById('statChunks').textContent = formatNumber(health.rows || 0);
    document.getElementById('statRepos').textContent = formatNumber((health.repos || []).length);
    document.getElementById('statRows').textContent = formatNumber(health.rows || 0);

    const repoList = document.getElementById('repoList');
    const repoNames = repos.repos || [];
    const counts = repos.counts || {};
    const max = Math.max(...repoNames.map((name) => counts[name] || 0), 0);

    if (!repoNames.length) {
      repoList.innerHTML = emptyBox('No repositories indexed yet', 'Start with a local folder or GitHub repo in the Index page.');
    } else {
      repoList.innerHTML = repoNames.map((name) => repoItem(name, counts[name] || 0, max)).join('');
    }

    const github = cfg.github || {};
    const website = cfg.website || {};
    const documents = cfg.documents || {};
    let sourceTitle = github.local_path || 'Local folder not set';
    let sourceMeta = 'Local folder mode is enabled for local project or study material indexing.';

    if (github.mode === 'github') {
      sourceTitle = github.repo || 'GitHub repository not set';
      sourceMeta = 'GitHub token mode is enabled for remote repository indexing.';
    } else if (github.mode === 'website') {
      sourceTitle = website.label || (website.start_urls || [])[0] || 'Website crawler not set';
      sourceMeta = 'Website crawler mode is enabled for pulling information from sites, docs, blogs, notice boards, and portals.';
    } else if (github.mode === 'arxiv') {
      sourceTitle = (cfg.arxiv || {}).label || 'arXiv papers';
      sourceMeta = 'arXiv mode is enabled for indexing research paper abstracts, metadata, and PDF text.';
    } else if (github.mode === 'youtube') {
      sourceTitle = (cfg.youtube || {}).label || 'YouTube transcripts';
      sourceMeta = 'YouTube mode is enabled for indexing lecture and tutorial transcripts.';
    } else if (github.mode === 'zip') {
      sourceTitle = documents.label || 'ZIP upload';
      sourceMeta = 'ZIP mode is enabled for uploaded bundles of notes, docs, and project files.';
    }

    document.getElementById('heroSourceTitle').textContent = sourceTitle;
    document.getElementById('heroSourceMeta').textContent = sourceMeta;
  } catch (error) {
    showToast('Dashboard error', error.message);
  }
}

async function loadSearchFilters() {
  try {
    const repos = await api('/repos');
    const select = document.getElementById('searchRepoSelect');
    select.innerHTML = '<option value="">All repositories</option>';
    (repos.repos || []).forEach((repo) => {
      const option = document.createElement('option');
      option.value = repo;
      option.textContent = repo;
      select.appendChild(option);
    });
  } catch (_) {}
}

function loadingBox(text) {
  return `<div class="loading-box"><div class="spinner"></div><div class="loading-copy">${escapeHtml(text)}</div></div>`;
}

function emptyBox(title, text) {
  return `<div class="empty-box"><strong>${escapeHtml(title)}</strong><p class="empty-subtext">${escapeHtml(text)}</p></div>`;
}

function resultCard(hit, index) {
  const tags = [
    hit.repo ? `<span class="tag">Repo: ${escapeHtml(hit.repo)}</span>` : '',
    hit.source ? `<span class="tag">Source: ${escapeHtml(hit.source)}</span>` : '',
    hit.author ? `<span class="tag">Author: ${escapeHtml(hit.author)}</span>` : '',
    hit.hierarchy ? `<span class="tag">Path: ${escapeHtml(hit.hierarchy)}</span>` : '',
    `<span class="tag">Score: ${escapeHtml(formatScore(hit.score))}</span>`
  ].filter(Boolean).join('');

  return `
    <div class="result-card" data-url="${escapeAttr(hit.url || '')}">
      <div class="results-header">
        <div>
          <strong>${escapeHtml(hit.title || `Result ${index + 1}`)}</strong>
          <div class="result-tags">${tags}</div>
        </div>
      </div>
      <p>${escapeHtml(hit.snippet || '')}</p>
      ${hit.summary ? `<p><strong>Summary:</strong> ${escapeHtml(hit.summary)}</p>` : ''}
    </div>
  `;
}

async function doSearch(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = {
    q: form.get('q'),
    k: parseInt(form.get('k'), 10),
    hybrid: form.get('hybrid') === 'on',
    rerank: form.get('rerank') === 'on' ? true : null,
    repo: form.get('repo') || null,
    source: form.get('source') || null,
  };

  const host = document.getElementById('searchResults');
  document.getElementById('searchButton').disabled = true;
  host.innerHTML = loadingBox('Searching indexed content...');

  try {
    const result = await api('/search', { method: 'POST', body: JSON.stringify(body) });
    const hits = result.results || [];

    if (!hits.length) {
      host.innerHTML = emptyBox('No results found', 'Try another query, a different source filter, or a broader keyword.');
      return false;
    }

    host.innerHTML = hits.map(resultCard).join('');
    host.querySelectorAll('.result-card').forEach((card) => {
      card.addEventListener('click', () => {
        const url = card.dataset.url;
        if (url) window.open(url, '_blank');
      });
    });
  } catch (error) {
    host.innerHTML = emptyBox('Search failed', error.message);
    showToast('Search failed', error.message);
  } finally {
    document.getElementById('searchButton').disabled = false;
  }

  return false;
}

function useSampleQuery() {
  document.getElementById('searchQuery').value = 'Where is indexing handled and how is search connected to chat?';
  document.getElementById('searchQuery').focus();
}

function appendMessage(role, content) {
  const wrap = document.createElement('div');
  wrap.className = `message ${role}`;
  wrap.innerHTML = `
    <div class="bubble">${content}</div>
    <span class="message-meta">${role === 'user' ? 'You' : 'Assistant'}</span>
  `;
  document.getElementById('chatMessages').appendChild(wrap);
  document.getElementById('chatMessages').scrollTop = document.getElementById('chatMessages').scrollHeight;
  return wrap;
}

function handleChatKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendChat();
  }
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const sendButton = document.getElementById('chatSendButton');
  const text = input.value.trim();
  if (!text) return;

  appendMessage('user', escapeHtml(text));
  input.value = '';
  sendButton.disabled = true;
  document.getElementById('chatStatus').textContent = 'Retrieving';

  const assistant = appendMessage('assistant', '<span class="typing"><span></span><span></span><span></span></span>');
  const bubble = assistant.querySelector('.bubble');
  let sources = [];
  let started = false;

  const webMode = !!document.getElementById('webMode')?.checked;
  const webUrls = splitLines(document.getElementById('webUrls')?.value);
  const endpoint = webMode ? '/web/ask' : '/chat';
  const requestBody = webMode
    ? { q: text, urls: webUrls.length ? webUrls : null, k: 8 }
    : { q: text, k: 8 };

  try {
    const response = await api(endpoint, { method: 'POST', body: JSON.stringify(requestBody) });
    if (!(response instanceof Response) || !response.body) {
      throw new Error('Streaming response unavailable');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let payload;
        try {
          payload = JSON.parse(line.slice(6));
        } catch (_) {
          continue;
        }

        if (payload.type === 'sources') {
          sources = payload.sources || [];
          document.getElementById('chatStatus').textContent = `${sources.length} sources`;
        }

        if (payload.type === 'error') {
          bubble.textContent = `Error: ${payload.error}`;
          document.getElementById('chatStatus').textContent = 'Failed';
          showToast(webMode ? 'Web answer failed' : 'Chat failed', payload.error);
          return;
        }

        if (payload.type === 'status') {
          document.getElementById('chatStatus').textContent = payload.text || 'Working';
        }

        if (payload.type === 'token') {
          if (!started) {
            bubble.textContent = '';
            started = true;
          }
          bubble.textContent += payload.text;
          document.getElementById('chatMessages').scrollTop = document.getElementById('chatMessages').scrollHeight;
        }

        if (payload.type === 'done') {
          document.getElementById('chatStatus').textContent = 'Ready';
          if (sources.length) {
            const links = document.createElement('div');
            links.className = 'source-links';
            sources.forEach((source, i) => {
              const a = document.createElement('a');
              a.href = source.url || '#';
              a.target = '_blank';
              a.rel = 'noreferrer';
              a.textContent = `[${i + 1}] ${source.title || source.repo || 'Source'}`;
              links.appendChild(a);
            });
            assistant.appendChild(links);
          }
        }
      }
    }
  } catch (error) {
    bubble.textContent = `Error: ${error.message}`;
    document.getElementById('chatStatus').textContent = 'Failed';
    showToast('Chat failed', error.message);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

function setSourceMode(mode) {
  currentSourceMode = SOURCE_MODES.includes(mode) ? mode : 'local';
  document.querySelectorAll('#sourceModeButtons .segment').forEach((button) => {
    button.classList.toggle('active', button.dataset.mode === currentSourceMode);
  });
  const panels = {
    local: document.getElementById('localModeFields'),
    github: document.getElementById('githubModeFields'),
    website: document.getElementById('websiteModeFields'),
    arxiv: document.getElementById('arxivModeFields'),
    youtube: document.getElementById('youtubeModeFields'),
    zip: document.getElementById('zipModeFields'),
  };
  Object.entries(panels).forEach(([key, el]) => {
    if (el) el.style.display = currentSourceMode === key ? 'block' : 'none';
  });
  renderSourceSummary();
}

function splitLines(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function renderSourceSummary() {
  const host = document.getElementById('sourceSummary');
  const path = document.getElementById('repoPath')?.value?.trim() || 'Not set';
  const repo = document.getElementById('githubRepo')?.value?.trim() || 'Not set';
  const branch = document.getElementById('githubBranch')?.value?.trim() || 'Default branch';
  const commits = document.getElementById('githubCommitsEnabled')?.checked;
  const websiteLabel = document.getElementById('websiteLabel')?.value?.trim() || 'Website crawl';
  const websiteStartUrls = splitLines(document.getElementById('websiteStartUrls')?.value);
  const websiteSitemapUrls = splitLines(document.getElementById('websiteSitemapUrls')?.value);
  const websiteMaxPages = document.getElementById('websiteMaxPages')?.value || '150';
  const websiteMaxDepth = document.getElementById('websiteMaxDepth')?.value || '2';
  const websiteRespectRobots = document.getElementById('websiteRespectRobots')?.checked;
  const arxivLabel = document.getElementById('arxivLabel')?.value?.trim() || 'arXiv papers';
  const arxivIds = splitLines(document.getElementById('arxivIds')?.value);
  const arxivUrls = splitLines(document.getElementById('arxivUrls')?.value);
  const youtubeLabel = document.getElementById('youtubeLabel')?.value?.trim() || 'YouTube transcripts';
  const youtubeUrls = splitLines(document.getElementById('youtubeUrls')?.value);
  const youtubeVideoIds = splitLines(document.getElementById('youtubeVideoIds')?.value);
  const youtubeLanguages = (document.getElementById('youtubeLanguages')?.value || 'en').split(',').map((v) => v.trim()).filter(Boolean);
  const zipLabel = document.getElementById('zipLabel')?.value?.trim() || 'ZIP upload';
  const zipSummary = document.getElementById('zipUploadSummary')?.dataset?.path || '';

  if (currentSourceMode === 'github') {
    host.innerHTML = `
      <div class="summary-item">
        <strong>GitHub token mode</strong>
        <p>Repository: ${escapeHtml(repo)}</p>
        <p>Branch: ${escapeHtml(branch)}</p>
        <p>Commits: ${commits ? 'Enabled' : 'Disabled'}</p>
      </div>
    `;
    return;
  }

  if (currentSourceMode === 'website') {
    host.innerHTML = `
      <div class="summary-item">
        <strong>${escapeHtml(websiteLabel)}</strong>
        <p>Start URLs: ${escapeHtml(String(websiteStartUrls.length || 0))}</p>
        <p>Sitemaps: ${escapeHtml(String(websiteSitemapUrls.length || 0))}</p>
        <p>Max pages: ${escapeHtml(String(websiteMaxPages))} · Max depth: ${escapeHtml(String(websiteMaxDepth))}</p>
        <p>Robots.txt: ${websiteRespectRobots ? 'Respected' : 'Ignored'}</p>
        ${websiteStartUrls.length ? `<p>First URL: ${escapeHtml(websiteStartUrls[0])}</p>` : ''}
      </div>
    `;
    return;
  }

  if (currentSourceMode === 'arxiv') {
    host.innerHTML = `
      <div class="summary-item">
        <strong>${escapeHtml(arxivLabel)}</strong>
        <p>Papers configured: ${escapeHtml(String(arxivIds.length + arxivUrls.length))}</p>
        <p>PDF extraction: ${document.getElementById('arxivIncludePdfText')?.checked ? 'Enabled' : 'Abstract only'}</p>
      </div>
    `;
    return;
  }

  if (currentSourceMode === 'youtube') {
    host.innerHTML = `
      <div class="summary-item">
        <strong>${escapeHtml(youtubeLabel)}</strong>
        <p>Videos configured: ${escapeHtml(String(youtubeUrls.length + youtubeVideoIds.length))}</p>
        <p>Languages: ${escapeHtml(youtubeLanguages.join(', ') || 'en')}</p>
      </div>
    `;
    return;
  }

  if (currentSourceMode === 'zip') {
    host.innerHTML = `
      <div class="summary-item">
        <strong>${escapeHtml(zipLabel)}</strong>
        <p>Upload status: ${zipSummary ? 'Ready to index extracted files' : 'No ZIP uploaded yet'}</p>
      </div>
    `;
    return;
  }

  host.innerHTML = `
    <div class="summary-item">
      <strong>Local folder mode</strong>
      <p>Path: ${escapeHtml(path)}</p>
      <p>Great for local repos, markdown notes, project docs, and lab folders.</p>
    </div>
  `;
}

['repoPath', 'githubRepo', 'githubBranch', 'githubPat', 'githubCommitsEnabled', 'websiteLabel', 'websiteStartUrls', 'websiteSitemapUrls', 'websiteIncludePatterns', 'websiteExcludePatterns', 'websiteMaxPages', 'websiteMaxDepth', 'websiteMinTextChars', 'websiteDelaySeconds', 'websiteSameDomainOnly', 'websiteRespectRobots', 'websiteEnabled', 'arxivEnabled', 'arxivLabel', 'arxivIds', 'arxivUrls', 'arxivIncludePdfText', 'youtubeEnabled', 'youtubeLabel', 'youtubeUrls', 'youtubeVideoIds', 'youtubeLanguages', 'youtubeIncludeTimestamps', 'zipLabel', 'zipFile'].forEach((id) => {
  document.addEventListener('input', (event) => {
    if (event.target && event.target.id === id) renderSourceSummary();
  });
  document.addEventListener('change', (event) => {
    if (event.target && event.target.id === id) renderSourceSummary();
  });
});

async function loadIndexConfig() {
  try {
    const [cfg, status] = await Promise.all([api('/config'), api('/sync/status')]);
    const github = cfg.github || {};
    const website = cfg.website || {};
    const arxiv = cfg.arxiv || {};
    const youtube = cfg.youtube || {};
    const documents = cfg.documents || {};
    document.getElementById('repoPath').value = cfg.repo_path || github.local_path || '';
    document.getElementById('githubRepo').value = github.repo || '';
    document.getElementById('githubPat').value = github.pat || '';
    document.getElementById('githubBranch').value = github.branch || '';
    document.getElementById('githubCommitsEnabled').checked = !!github.commits_enabled;
    document.getElementById('websiteEnabled').checked = !!website.enabled;
    document.getElementById('websiteLabel').value = website.label || '';
    document.getElementById('websiteStartUrls').value = (website.start_urls || []).join('\n');
    document.getElementById('websiteSitemapUrls').value = (website.sitemap_urls || []).join('\n');
    document.getElementById('websiteIncludePatterns').value = (website.include_patterns || []).join('\n');
    document.getElementById('websiteExcludePatterns').value = (website.exclude_patterns || []).join('\n');
    document.getElementById('websiteMaxPages').value = website.max_pages ?? 150;
    document.getElementById('websiteMaxDepth').value = website.max_depth ?? 2;
    document.getElementById('websiteMinTextChars').value = website.min_text_chars ?? 250;
    document.getElementById('websiteDelaySeconds').value = website.delay_seconds ?? 0.15;
    document.getElementById('websiteSameDomainOnly').checked = website.same_domain_only !== false;
    document.getElementById('websiteRespectRobots').checked = website.respect_robots_txt !== false;
    document.getElementById('arxivEnabled').checked = !!arxiv.enabled;
    document.getElementById('arxivLabel').value = arxiv.label || 'arxiv-papers';
    document.getElementById('arxivIds').value = (arxiv.ids || []).join('\n');
    document.getElementById('arxivUrls').value = (arxiv.urls || []).join('\n');
    document.getElementById('arxivIncludePdfText').checked = arxiv.include_pdf_text !== false;
    document.getElementById('youtubeEnabled').checked = !!youtube.enabled;
    document.getElementById('youtubeLabel').value = youtube.label || 'youtube-transcripts';
    document.getElementById('youtubeUrls').value = (youtube.urls || []).join('\n');
    document.getElementById('youtubeVideoIds').value = (youtube.video_ids || []).join('\n');
    document.getElementById('youtubeLanguages').value = (youtube.languages || ['en']).join(', ');
    document.getElementById('youtubeIncludeTimestamps').checked = youtube.include_timestamps !== false;
    document.getElementById('zipLabel').value = documents.label || 'zip-upload';
    setSourceMode(github.mode || 'local');
    setStatus(status);
    renderSourceSummary();

    if (status.last_result) {
      showIndexSummary(status.last_result);
    }
  } catch (error) {
    showToast('Failed to load index config', error.message);
  }
}

async function browseFolders() {
  const list = document.getElementById('folderList');
  if (list.classList.contains('open')) {
    list.classList.remove('open');
    list.innerHTML = '';
    return;
  }

  list.classList.add('open');
  list.innerHTML = '<div class="folder-item">Scanning common locations...</div>';

  try {
    const result = await api('/folders');
    const folders = result.folders || [];
    if (!folders.length) {
      list.innerHTML = '<div class="folder-item">No git folders found in common locations.</div>';
      return;
    }

    list.innerHTML = folders.map((folder) => `
      <div class="folder-item" data-path="${escapeAttr(folder.path)}">
        <strong>${escapeHtml(folder.name)}</strong><br>
        <span class="result-meta">${escapeHtml(folder.path)}</span>
      </div>
    `).join('');

    list.querySelectorAll('.folder-item').forEach((item) => {
      item.addEventListener('click', () => {
        const path = item.dataset.path;
        if (path) document.getElementById('repoPath').value = path;
        list.classList.remove('open');
        list.innerHTML = '';
        renderSourceSummary();
      });
    });
  } catch (error) {
    list.innerHTML = `<div class="folder-item">Error: ${escapeHtml(error.message)}</div>`;
  }
}

async function saveSourceConfig() {
  const body = {
    repo_path: document.getElementById('repoPath').value || null,
    github_mode: currentSourceMode,
    github_repo: document.getElementById('githubRepo').value || null,
    github_pat: document.getElementById('githubPat').value || null,
    github_branch: document.getElementById('githubBranch').value || null,
    github_commits_enabled: currentSourceMode === 'github' ? document.getElementById('githubCommitsEnabled').checked : false,
    website_enabled: currentSourceMode === 'website' ? document.getElementById('websiteEnabled').checked : false,
    website_label: document.getElementById('websiteLabel').value || null,
    website_start_urls: splitLines(document.getElementById('websiteStartUrls').value),
    website_sitemap_urls: splitLines(document.getElementById('websiteSitemapUrls').value),
    website_same_domain_only: document.getElementById('websiteSameDomainOnly').checked,
    website_include_patterns: splitLines(document.getElementById('websiteIncludePatterns').value),
    website_exclude_patterns: splitLines(document.getElementById('websiteExcludePatterns').value),
    website_max_pages: parseInt(document.getElementById('websiteMaxPages').value || '150', 10),
    website_max_depth: parseInt(document.getElementById('websiteMaxDepth').value || '2', 10),
    website_delay_seconds: parseFloat(document.getElementById('websiteDelaySeconds').value || '0.15'),
    website_min_text_chars: parseInt(document.getElementById('websiteMinTextChars').value || '250', 10),
    website_respect_robots_txt: document.getElementById('websiteRespectRobots').checked,
    documents_enabled: currentSourceMode === 'zip',
    documents_label: document.getElementById('zipLabel')?.value || 'zip-upload',
    documents_paths: document.getElementById('zipUploadSummary')?.dataset?.path ? [document.getElementById('zipUploadSummary').dataset.path] : [],
    documents_recursive: true,
    arxiv_enabled: currentSourceMode === 'arxiv' ? document.getElementById('arxivEnabled')?.checked : false,
    arxiv_label: document.getElementById('arxivLabel')?.value || 'arxiv-papers',
    arxiv_ids: splitLines(document.getElementById('arxivIds')?.value),
    arxiv_urls: splitLines(document.getElementById('arxivUrls')?.value),
    arxiv_include_pdf_text: document.getElementById('arxivIncludePdfText')?.checked,
    youtube_enabled: currentSourceMode === 'youtube' ? document.getElementById('youtubeEnabled')?.checked : false,
    youtube_label: document.getElementById('youtubeLabel')?.value || 'youtube-transcripts',
    youtube_urls: splitLines(document.getElementById('youtubeUrls')?.value),
    youtube_video_ids: splitLines(document.getElementById('youtubeVideoIds')?.value),
    youtube_languages: (document.getElementById('youtubeLanguages')?.value || 'en').split(',').map((v) => v.trim()).filter(Boolean),
    youtube_include_timestamps: document.getElementById('youtubeIncludeTimestamps')?.checked,
    github_files_enabled: currentSourceMode === 'local' || currentSourceMode === 'github',
  };

  try {
    await api('/config', { method: 'POST', body: JSON.stringify(body) });
    renderSourceSummary();
    refreshDashboard();
    showToast('Source saved', 'Your indexing source configuration has been updated.');
  } catch (error) {
    showToast('Save failed', error.message);
  }
}

function addLog(text, tone = 'info') {
  const log = document.getElementById('progressLog');
  const item = document.createElement('div');
  item.className = `log-item ${tone}`;
  item.innerHTML = `<span class="log-mark"></span><div>${escapeHtml(text)}</div>`;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function setProgress(percent, label) {
  const safe = Math.max(0, Math.min(100, percent));
  document.getElementById('progressFill').style.width = `${safe}%`;
  document.getElementById('progressPercent').textContent = `${Math.round(safe)}%`;
  if (label) document.getElementById('progressLabel').textContent = label;
}

function showIndexSummary(result) {
  if (!result) return;
  const host = document.getElementById('sourceSummary');
  const current = host.innerHTML;
  const summary = `
    <div class="summary-item">
      <strong>Last indexing run</strong>
      <p>Documents: ${formatNumber(result.total_docs || 0)}</p>
      <p>Chunks: ${formatNumber(result.total_chunks || 0)}</p>
      <p>Rows: ${formatNumber(result.total_rows || 0)}</p>
      <p>Elapsed: ${escapeHtml(String(result.elapsed || 0))}s</p>
      ${result.cancelled ? '<p>Run status: cancelled</p>' : ''}
      ${result.errors && result.errors.length ? `<p>Errors: ${escapeHtml(result.errors.join(', '))}</p>` : ''}
    </div>
  `;
  host.innerHTML = `${current}${summary}`;
}

async function uploadZipBundle() {
  const fileInput = document.getElementById('zipFile');
  const file = fileInput?.files?.[0];
  if (!file) {
    showToast('ZIP file required', 'Choose a ZIP file before indexing.');
    return null;
  }

  const form = new FormData();
  form.append('file', file);
  form.append('label', document.getElementById('zipLabel')?.value || 'zip-upload');

  const token = (localStorage.getItem('kh_token') || '').trim();
  const res = await fetch('/uploads/zip', {
    method: 'POST',
    body: form,
    headers: token ? { 'X-API-Key': token } : {},
    credentials: 'same-origin',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || 'ZIP upload failed');
  }

  const host = document.getElementById('zipUploadSummary');
  host.dataset.path = data.path || '';
  host.classList.remove('hidden-block');
  host.innerHTML = `<strong>${escapeHtml(data.label || 'ZIP upload')}</strong><p>Extracted files: ${escapeHtml(String(data.files || 0))}</p><p>Path: ${escapeHtml(data.path || '')}</p>`;
  return data;
}

async function startIndexing() {
  const forceFull = document.getElementById('forceFull').checked;
  const body = {
    repo_path: currentSourceMode === 'local' ? (document.getElementById('repoPath').value || '') : '',
    force_full: forceFull,
  };

  if (currentSourceMode === 'local' && !body.repo_path.trim()) {
    showToast('Repository path required', 'Choose a local folder before indexing.');
    return;
  }

  if (currentSourceMode === 'github') {
    const repo = document.getElementById('githubRepo').value.trim();
    const pat = document.getElementById('githubPat').value.trim();
    if (!repo || !pat) {
      showToast('GitHub repo and token required', 'Provide owner/repo and a GitHub token.');
      return;
    }
    await saveSourceConfig();
  }

  if (currentSourceMode === 'website') {
    const startUrls = splitLines(document.getElementById('websiteStartUrls').value);
    if (!document.getElementById('websiteEnabled').checked) {
      showToast('Enable website crawler', 'Turn on the website crawler before indexing.');
      return;
    }
    if (!startUrls.length) {
      showToast('Website start URL required', 'Provide at least one start URL for the crawler.');
      return;
    }
    await saveSourceConfig();
  }

  if (currentSourceMode === 'arxiv') {
    const ids = splitLines(document.getElementById('arxivIds').value);
    const urls = splitLines(document.getElementById('arxivUrls').value);
    if (!document.getElementById('arxivEnabled').checked) {
      showToast('Enable arXiv indexing', 'Turn on arXiv indexing before starting.');
      return;
    }
    if (!ids.length && !urls.length) {
      showToast('arXiv input required', 'Provide at least one arXiv ID or URL.');
      return;
    }
    await saveSourceConfig();
  }

  if (currentSourceMode === 'youtube') {
    const urls = splitLines(document.getElementById('youtubeUrls').value);
    const ids = splitLines(document.getElementById('youtubeVideoIds').value);
    if (!document.getElementById('youtubeEnabled').checked) {
      showToast('Enable YouTube indexing', 'Turn on YouTube indexing before starting.');
      return;
    }
    if (!urls.length && !ids.length) {
      showToast('YouTube input required', 'Provide at least one video URL or video ID.');
      return;
    }
    await saveSourceConfig();
  }

  if (currentSourceMode === 'zip') {
    const uploaded = await uploadZipBundle();
    if (!uploaded?.path) return;
    await saveSourceConfig();
  }

  if (!['github', 'website', 'arxiv', 'youtube', 'zip'].includes(currentSourceMode)) {
    await saveSourceConfig();
  }

  const card = document.getElementById('progressCard');
  card.style.display = 'block';
  document.getElementById('progressLog').innerHTML = '';
  document.getElementById('progressText').textContent = 'Starting...';
  setProgress(4, 'Starting indexing');
  addLog('Indexing started', 'info');

  try {
    const response = await api('/sync/start', { method: 'POST', body: JSON.stringify(body) });
    if (!(response instanceof Response) || !response.body) {
      throw new Error('Could not start indexing');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let totalDocs = 0;
    let totalChunks = 0;
    let connectorCount = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try {
          event = JSON.parse(line.slice(6));
        } catch (_) {
          continue;
        }

        if (event.type === 'started') {
          addLog(`Started at ${event.time || 'now'}`, 'info');
          setProgress(8, 'Pipeline started');
        }
        if (event.type === 'connector_start') {
          addLog(`Connector started: ${event.key}`, 'info');
          setProgress(Math.max(14, 18 + connectorCount * 10), `Running ${event.key}`);
        }
        if (event.type === 'doc_indexed') {
          totalDocs = event.total_docs || totalDocs;
          totalChunks = event.total_chunks || totalChunks;
          document.getElementById('progressText').textContent = `${formatNumber(totalDocs)} documents, ${formatNumber(totalChunks)} chunks`;
          const p = Math.min(92, 18 + totalDocs * 2 + totalChunks * 0.15 + connectorCount * 8);
          setProgress(p, `Indexed ${formatNumber(totalDocs)} documents`);
        }
        if (event.type === 'connector_done') {
          connectorCount += 1;
          addLog(`Connector completed: ${event.key} (${event.docs || 0} docs)`, 'success');
          setProgress(Math.min(95, 30 + connectorCount * 18), `Completed ${connectorCount} connector(s)`);
        }
        if (event.type === 'connector_skipped') {
          addLog(`Connector skipped: ${event.key} (${event.reason || 'no reason'})`, 'warning');
        }
        if (event.type === 'connector_error') {
          addLog(`Connector error: ${event.key} - ${event.error}`, 'error');
        }
        if (event.type === 'error') {
          addLog(`Error: ${event.error}`, 'error');
          showToast('Indexing failed', event.error);
        }
        if (event.type === 'done' || event.type === 'cancelled') {
          setProgress(100, event.cancelled ? 'Cancelled' : 'Completed');
          document.getElementById('progressText').textContent = `${formatNumber(event.total_docs || totalDocs)} documents, ${formatNumber(event.total_chunks || totalChunks)} chunks`;
          addLog(event.cancelled ? 'Indexing cancelled' : 'Indexing completed', event.cancelled ? 'warning' : 'success');
          showIndexSummary(event);
          refreshDashboard();
        }
      }
    }
  } catch (error) {
    addLog(`Indexing failed: ${error.message}`, 'error');
    showToast('Indexing failed', error.message);
  } finally {
    pollStatus();
  }
}

async function stopIndexing() {
  try {
    await api('/sync/stop', { method: 'POST' });
    addLog('Stop requested', 'warning');
    showToast('Stop requested', 'The current indexing run is being stopped.');
  } catch (error) {
    showToast('Stop failed', error.message);
  }
}

async function clearIndex() {
  if (!confirm('Clear the entire index? This cannot be undone.')) return;
  try {
    await api('/sync/clear', { method: 'POST' });
    document.getElementById('sourceSummary').innerHTML = emptyBox('Index cleared', 'All indexed rows were removed successfully.');
    refreshDashboard();
    showToast('Index cleared', 'All indexed data has been removed.');
  } catch (error) {
    showToast('Clear failed', error.message);
  }
}

async function loadSettings() {
  try {
    const cfg = await api('/config');
    document.getElementById('setLLMProvider').value = cfg.llm.provider || 'anthropic';
    document.getElementById('setLLMModel').value = cfg.llm.model || '';
    document.getElementById('setLLMTemp').value = cfg.llm.temperature ?? 0.2;
    document.getElementById('setLLMMaxTokens').value = cfg.llm.max_tokens ?? 2000;
    document.getElementById('setEmbModel').value = cfg.embedding.model || '';
    document.getElementById('setChunkSize').value = cfg.chunking.chunk_size ?? 512;
    document.getElementById('setChunkOverlap').value = cfg.chunking.chunk_overlap ?? 50;
    document.getElementById('setTopK').value = cfg.search.top_k ?? 10;
    document.getElementById('setRerank').checked = !!cfg.search.rerank;
    document.getElementById('setApiToken').value = localStorage.getItem('kh_token') || '';
  } catch (error) {
    showToast('Settings load failed', error.message);
  }
}

async function saveSettings() {
  localStorage.setItem('kh_token', (document.getElementById('setApiToken').value || '').trim());
  const body = {
    llm_provider: document.getElementById('setLLMProvider').value,
    llm_model: document.getElementById('setLLMModel').value,
    llm_temperature: parseFloat(document.getElementById('setLLMTemp').value),
    llm_max_tokens: parseInt(document.getElementById('setLLMMaxTokens').value, 10),
    embedding_model: document.getElementById('setEmbModel').value,
    chunk_size: parseInt(document.getElementById('setChunkSize').value, 10),
    chunk_overlap: parseInt(document.getElementById('setChunkOverlap').value, 10),
    top_k: parseInt(document.getElementById('setTopK').value, 10),
    rerank: document.getElementById('setRerank').checked,
  };

  try {
    await api('/config', { method: 'POST', body: JSON.stringify(body) });
    document.getElementById('settingsStatus').textContent = 'Saved';
    setTimeout(() => { document.getElementById('settingsStatus').textContent = ''; }, 2200);
    showToast('Settings saved', 'Your retrieval and model settings were updated.');
  } catch (error) {
    showToast('Save failed', error.message);
  }
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function escapeAttr(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function formatScore(score) {
  if (score == null || score === '') return '—';
  const n = Number(score);
  return Number.isFinite(n) ? n.toFixed(4) : String(score);
}

document.getElementById('zipFile')?.addEventListener('change', () => renderSourceSummary());

navigate('dashboard');
pollStatus();
