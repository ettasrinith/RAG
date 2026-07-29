/* ── ═══ DASHBOARD ════════════════════════════════════ */

async function refreshDashboard() {
  try {
    const health = await api('/health');
    const repos = await api('/repos');

    const repoCount = (repos.repos || []).length;
    const el = id => $(id);
    if (el('stat-docs')) el('stat-docs').textContent = health.rows != null ? health.rows.toLocaleString() : '0';
    if (el('stat-repos')) el('stat-repos').textContent = repoCount > 0 ? String(repoCount) : '0';
    if (el('stat-papers')) el('stat-papers').textContent = health.research_rows != null ? health.research_rows.toLocaleString() : '0';
    if (el('stat-model')) el('stat-model').textContent = health.llm_model || 'N/A';

    // Repo chart
    const chartEl = $('dash-repo-chart');
    if (!chartEl) return;
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

    // Activity / system status
    const activityEl = $('dash-activity');
    if (activityEl) {
      activityEl.innerHTML = [
        { type: 'index', text: (health.rows || 0).toLocaleString() + ' documents · ' + (health.research_rows || 0).toLocaleString() + ' papers indexed' },
        { type: 'search', text: 'Embedding: ' + (health.embedding_model || 'N/A') },
        { type: 'chat', text: 'LLM: ' + (health.llm_model || 'N/A') },
        { type: health.indexing ? 'research' : 'index', text: health.indexing ? 'Indexing in progress…' : 'System idle — ready' },
      ].map(a =>
        '<div class="activity-item"><span class="activity-dot ' + a.type + '"></span>' + esc(a.text) + '</div>'
      ).join('');
    }

    // Collections
    const collEl = $('dash-collections');
    if (collEl) {
      try {
        const coll = await api('/v1/collections');
        const items = coll.data || [];
        if (items.length) {
          collEl.innerHTML = items.slice(0, 6).map(c =>
            '<div class="collection-row">' +
            '<span class="collection-dot"></span>' +
            '<span class="collection-name">' + esc(c.name || c.id) + '</span>' +
            '<span class="collection-meta">' + esc(c.description || '') + '</span>' +
            '</div>'
          ).join('');
        } else {
          collEl.innerHTML = '<div class="state-sm">No collections yet — create one in Admin.</div>';
        }
      } catch (_) {
        collEl.innerHTML = '<div class="state-sm">Could not load collections</div>';
      }
    }

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
  if (!sel) return;
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
    if (!sel) return;
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

let searchTimer;

/* Bind search-view listeners once the view exists in the DOM.
   The search view is loaded dynamically, so these elements are not
   present at script-load time. Called from reattachViewListeners('search'),
   guarded so each listener is attached exactly once. */
let searchViewBound = false;
function bindSearchViewListeners() {
  if (searchViewBound) return;
  const chips = $('filter-chips');
  const results = $('results-list');
  const input = $('search-input');
  const form = $('search-form');
  if (!chips || !results || !input || !form) return;
  searchViewBound = true;

  // Remove active filter chips
  chips.addEventListener('click', e => {
    const rm = e.target.closest('.chip-rm');
    if (!rm) return;
    if (rm.dataset.clear === 'source') $('filter-source').value = '';
    if (rm.dataset.clear === 'repo') $('filter-repo').value = '';
    doSearch();
  });

  // Click card to open URL
  results.addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const card = e.target.closest('.result-card');
    if (card && card.dataset.url) window.open(card.dataset.url, '_blank');
  });

  // Instant (debounced) search as you type
  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(doSearch, 280);
  });

  form.addEventListener('submit', e => { e.preventDefault(); doSearch(); });
  $('filter-source').addEventListener('change', doSearch);
  $('filter-repo').addEventListener('change', doSearch);
  $('filter-hybrid').addEventListener('change', doSearch);
}

