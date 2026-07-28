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
$('discover-form')?.addEventListener('submit', e => { e.preventDefault(); doDiscover(); });

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
  host.innerHTML = ''; // Will show skeleton
  $('selection-bar').classList.add('hide');
  State.selectedPapers.clear();
  updateSelectionCount();

  // Show skeleton while searching
  host.innerHTML = Array(3).fill(
    '<div class="skeleton-card" style="padding:18px 20px 16px 52px">' +
    '<div class="skeleton-line"></div><div class="skeleton-line"></div>' +
    '<div class="skeleton-line" style="width:40%"></div>' +
    '</div>'
  ).join('');

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

$('discover-sort')?.addEventListener('change', () => {
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
$('discover-results')?.addEventListener('change', e => {
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

$('discover-results')?.addEventListener('click', e => {
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

$('index-selected-btn')?.addEventListener('click', async () => {
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
  // Show skeleton while loading
  host.innerHTML = Array(3).fill(
    '<div class="skeleton-card" style="padding:18px 20px 16px 52px">' +
    '<div class="skeleton-line"></div><div class="skeleton-line"></div>' +
    '<div class="skeleton-line" style="width:50%"></div>' +
    '</div>'
  ).join('');
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

$('library-filter')?.addEventListener('change', loadLibrary);

$('library-results')?.addEventListener('click', async e => {
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

