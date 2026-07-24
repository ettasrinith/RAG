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

async function saveWikiConfig() {
  const baseUrl = $('wiki-base-url').value.trim();
  const email = $('wiki-email').value.trim();
  const apiToken = $('wiki-api-token').value.trim();
  const spaces = $('wiki-spaces').value.trim().split(',').map(s => s.trim()).filter(Boolean);
  const query = $('wiki-query').value.trim();
  const maxResults = parseInt($('wiki-max-results').value, 10) || 200;

  if (!baseUrl) throw new Error('Base URL is required');
  if (!email || !apiToken) throw new Error('Email and API token are required');

  // Save to env-like config via legacy endpoint
  await api('/config', {
    method: 'POST',
    body: JSON.stringify({
      confluence_base_url: baseUrl,
      confluence_email: email,
      confluence_api_token: apiToken,
      confluence_spaces: spaces,
      confluence_query: query,
      confluence_max_results: maxResults,
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
  } else if (State.source === 'wiki') {
    const baseUrl = $('wiki-base-url').value.trim();
    const email = $('wiki-email').value.trim();
    const apiToken = $('wiki-api-token').value.trim();
    if (!baseUrl || !email || !apiToken) { toast('Credentials required', 'Enter Confluence URL, email, and API token.', 'error'); return; }
    try { await saveWikiConfig(); } catch (e) { toast('Config save failed', e.message, 'error'); return; }
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
      }
    });
  } catch (e) {
    addLog('Failed: ' + e.message, 'error');
    toast('Indexing failed', e.message, 'error');
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

