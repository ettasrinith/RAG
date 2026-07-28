/* ── ═══ RESEARCH TOOLS ══════════════════════════════════ */

// Tab switching
function initToolsTabs() {
  qsa('#tools-tabs .research-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      qsa('#tools-tabs .research-tab').forEach(t => t.classList.remove('active'));
      qsa('.ttab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      const target = $('ttab-' + tab.dataset.ttab);
      if (target) target.classList.add('active');
    });
  });
}

// ── Deep Research ──────────────────────────────────────────

function initDeepResearch() {
  const form = $('deep-research-form');
  if (!form) return;
  form.addEventListener('submit', e => { e.preventDefault(); runDeepResearch(); });
  $('dr-copy')?.addEventListener('click', () => {
    const text = $('dr-report')?.innerText || '';
    navigator.clipboard.writeText(text).then(() => toast('Copied', 'Report copied to clipboard.'));
  });
}

async function runDeepResearch() {
  const question = $('dr-question').value.trim();
  if (!question) { toast('Missing question', 'Enter a research question.', 'error'); return; }

  const depth = parseInt($('dr-depth').value, 10) || 3;
  $('dr-submit').disabled = true;
  $('dr-progress').classList.remove('hide');
  $('dr-results').classList.add('hide');
  $('dr-steps').innerHTML = '';
  $('dr-progress-fill').style.width = '5%';
  $('dr-progress-msg').textContent = 'Starting deep research…';

  try {
    await apiStream('/v1/research-tools:deep-research', { question, depth, stream: true }, ev => {
      if (ev.type === 'status') {
        $('dr-progress-msg').textContent = ev.message;
        if (ev.progress) $('dr-progress-fill').style.width = Math.round(ev.progress * 100) + '%';
      } else if (ev.type === 'decomposed') {
        $('dr-progress-fill').style.width = '15%';
        $('dr-steps').innerHTML = '<div class="dr-step"><strong>Sub-queries:</strong><ul>' +
          ev.sub_queries.map(q => '<li>' + esc(q) + '</li>').join('') + '</ul></div>';
      } else if (ev.type === 'search_results') {
        $('dr-progress-fill').style.width = '50%';
        const stepEl = document.createElement('div');
        stepEl.className = 'dr-step';
        stepEl.innerHTML = '<strong>Search:</strong> ' + esc(ev.query) +
          ' <span class="badge">' + ev.total_found + ' found</span>';
        $('dr-steps').appendChild(stepEl);
      } else if (ev.type === 'report') {
        $('dr-progress-fill').style.width = '100%';
        $('dr-progress').classList.add('hide');
        $('dr-results').classList.remove('hide');
        $('dr-report').innerHTML = renderMarkdown(ev.report);
        $('dr-papers-count').textContent = ev.papers_found + ' papers';
        $('dr-duration').textContent = (ev.duration_ms / 1000).toFixed(1) + 's';
        // Sources
        if (ev.sources && ev.sources.length) {
          $('dr-sources').innerHTML = '<h4>Sources</h4><ol class="source-list">' +
            ev.sources.map(s => '<li><a href="' + escAttr(s.url || '#') + '" target="_blank">' +
              esc(s.title || 'Untitled') + '</a>' +
              (s.year ? ' (' + s.year + ')' : '') + '</li>').join('') + '</ol>';
        }
      } else if (ev.type === 'done') {
        $('dr-submit').disabled = false;
      }
    });
  } catch (e) {
    $('dr-progress').classList.add('hide');
    toast('Research failed', e.message, 'error');
  } finally {
    $('dr-submit').disabled = false;
  }
}

// ── Literature Review ──────────────────────────────────────

function initLitReview() {
  const form = $('lit-review-form');
  if (!form) return;
  form.addEventListener('submit', e => { e.preventDefault(); runLitReview(); });
  $('lr-copy')?.addEventListener('click', () => {
    const text = $('lr-report')?.innerText || '';
    navigator.clipboard.writeText(text).then(() => toast('Copied', 'Review copied to clipboard.'));
  });
  $('lr-external-tgl')?.addEventListener('click', () => {
    const cb = $('lr-external');
    cb.checked = !cb.checked;
    $('lr-external-tgl').classList.toggle('active', cb.checked);
  });
}

async function runLitReview() {
  const topic = $('lr-topic').value.trim();
  if (!topic) { toast('Missing topic', 'Enter a research topic.', 'error'); return; }

  const length = $('lr-length').value;
  const maxPapers = parseInt($('lr-max-papers').value, 10) || 15;
  const focus = $('lr-focus').value.trim();
  const includeExternal = $('lr-external').checked;

  $('lr-submit').disabled = true;
  $('lr-progress').classList.remove('hide');
  $('lr-results').classList.add('hide');
  $('lr-progress-msg').textContent = 'Gathering papers…';
  $('lr-papers-found').innerHTML = '';

  try {
    await apiStream('/v1/research-tools:literature-review', {
      topic, max_papers: maxPapers, length, focus, include_external: includeExternal, stream: true,
    }, ev => {
      if (ev.type === 'status') {
        $('lr-progress-msg').textContent = ev.message;
      } else if (ev.type === 'papers_found') {
        $('lr-papers-found').innerHTML = '<span class="badge">' + ev.count + ' papers found</span> ' +
          ev.papers.slice(0, 5).map(p => '<span class="badge source">' + esc(p.title?.slice(0, 40) || '') + '</span>').join(' ');
      } else if (ev.type === 'review') {
        $('lr-progress').classList.add('hide');
        $('lr-results').classList.remove('hide');
        $('lr-report').innerHTML = renderMarkdown(ev.review);
        $('lr-word-count').textContent = ev.word_count + ' words';
        $('lr-duration').textContent = (ev.duration_ms / 1000).toFixed(1) + 's';
      } else if (ev.type === 'done') {
        $('lr-submit').disabled = false;
      }
    });
  } catch (e) {
    $('lr-progress').classList.add('hide');
    toast('Review failed', e.message, 'error');
  } finally {
    $('lr-submit').disabled = false;
  }
}

// ── Recommendations ────────────────────────────────────────

function initRecommendations() {
  const form = $('recommend-form');
  if (!form) return;
  form.addEventListener('submit', e => { e.preventDefault(); runRecommend(); });
  $('rec-path-btn')?.addEventListener('click', runReadingPath);
}

async function runRecommend() {
  const title = $('rec-title').value.trim();
  if (!title) { toast('Missing title', 'Enter a paper title.', 'error'); return; }

  const authors = $('rec-authors').value.trim();
  const abstract = $('rec-abstract').value.trim();
  const strategy = $('rec-strategy').value;
  const k = parseInt($('rec-count').value, 10) || 10;

  $('rec-submit').disabled = true;
  $('rec-results').classList.add('hide');
  $('rec-path-results').classList.add('hide');

  try {
    const data = await api('/v1/research-tools:recommend', {
      method: 'POST',
      body: JSON.stringify({ title, authors, abstract, k, strategy }),
    });
    $('rec-results').classList.remove('hide');
    $('rec-results-title').textContent = 'Because you read "' + title.slice(0, 50) + '"';
    $('rec-count-badge').textContent = data.count + ' recommendations';
    renderRecommendations(data.recommendations || []);
  } catch (e) {
    toast('Recommendation failed', e.message, 'error');
  } finally {
    $('rec-submit').disabled = false;
  }
}

function renderRecommendations(recs) {
  const grid = $('rec-grid');
  if (!recs.length) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">📚</div><h3>No recommendations</h3><p>Try a different paper or strategy.</p></div>';
    return;
  }
  grid.innerHTML = recs.map((r, i) => {
    const typeColors = { semantic: 'var(--primary)', author: 'var(--green)', topic: 'var(--amber)', citation: 'var(--purple)' };
    const color = typeColors[r.match_type] || 'var(--primary)';
    return '<article class="rec-card" style="animation-delay:' + (i * 50) + 'ms">' +
      '<div class="rec-type" style="background:' + color + '"></div>' +
      '<div class="rec-body">' +
      '<div class="rec-title">' + (r.url ? '<a href="' + escAttr(r.url) + '" target="_blank">' + esc(r.title) + '</a>' : esc(r.title)) + '</div>' +
      (r.authors ? '<div class="rec-authors">' + esc(r.authors) + '</div>' : '') +
      '<div class="rec-meta">' +
      (r.year ? '<span class="badge year">' + r.year + '</span>' : '') +
      '<span class="badge" style="border-color:' + color + '">' + esc(r.match_type) + '</span>' +
      (r.citation_count ? '<span class="badge cites">' + r.citation_count + ' cites</span>' : '') +
      '<span class="rec-score">' + (r.score * 100).toFixed(0) + '% match</span>' +
      '</div>' +
      (r.reason ? '<div class="rec-reason">💡 ' + esc(r.reason) + '</div>' : '') +
      (r.abstract ? '<div class="rec-abstract">' + esc(r.abstract.slice(0, 200)) + '…</div>' : '') +
      '</div></article>';
  }).join('');
}

async function runReadingPath() {
  const title = $('rec-title').value.trim();
  if (!title) { toast('Missing title', 'Enter a starting paper title.', 'error'); return; }

  $('rec-path-btn').disabled = true;
  $('rec-results').classList.add('hide');
  $('rec-path-results').classList.remove('hide');
  $('reading-path').innerHTML = '<div class="spinner-sm"></div> Generating reading path…';

  try {
    const data = await api('/v1/research-tools:reading-path', {
      method: 'POST',
      body: JSON.stringify({ title, depth: 4 }),
    });
    renderReadingPath(data.path || []);
  } catch (e) {
    $('reading-path').innerHTML = '<div class="empty-state"><p>' + esc(e.message) + '</p></div>';
  } finally {
    $('rec-path-btn').disabled = false;
  }
}

function renderReadingPath(path) {
  const host = $('reading-path');
  if (!path.length) {
    host.innerHTML = '<div class="empty-state"><p>No path generated.</p></div>';
    return;
  }
  host.innerHTML = path.map((p, i) => {
    const isLast = i === path.length - 1;
    return '<div class="path-step">' +
      '<div class="path-node">' +
      '<span class="path-num">' + (i + 1) + '</span>' +
      '<div class="path-info">' +
      '<div class="path-title">' + (p.url ? '<a href="' + escAttr(p.url) + '" target="_blank">' + esc(p.title) + '</a>' : esc(p.title)) + '</div>' +
      (p.authors ? '<div class="path-authors">' + esc(p.authors) + '</div>' : '') +
      '<div class="path-reason">' + esc(p.reason || '') + '</div>' +
      '</div></div>' +
      (!isLast ? '<div class="path-connector"></div>' : '') +
      '</div>';
  }).join('');
}

// ── Document Parser ────────────────────────────────────────

function initDocParser() {
  const form = $('parse-form');
  if (!form) return;
  form.addEventListener('submit', e => { e.preventDefault(); runParse(); });

  // File upload
  const fileInput = $('parse-file-input');
  const dropZone = $('parse-drop-zone');

  fileInput?.addEventListener('change', () => {
    if (fileInput.files.length) uploadAndParse(fileInput.files[0]);
  });

  dropZone?.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone?.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) uploadAndParse(e.dataTransfer.files[0]);
  });

  // Toggle buttons
  $('parse-tables-tgl')?.addEventListener('click', () => {
    const cb = $('parse-tables');
    cb.checked = !cb.checked;
    $('parse-tables-tgl').classList.toggle('active', cb.checked);
  });
  $('parse-llm-tgl')?.addEventListener('click', () => {
    const cb = $('parse-llm');
    cb.checked = !cb.checked;
    $('parse-llm-tgl').classList.toggle('active', cb.checked);
  });
}

async function runParse() {
  const content = $('parse-content').value.trim();
  if (!content) { toast('No content', 'Paste content or upload a file.', 'error'); return; }

  $('parse-submit').disabled = true;
  $('parse-results').classList.add('hide');

  try {
    const data = await api('/v1/research-tools:parse', {
      method: 'POST',
      body: JSON.stringify({
        content,
        extract_tables: $('parse-tables').checked,
        structure_with_llm: $('parse-llm').checked,
      }),
    });
    renderParseResults(data);
  } catch (e) {
    toast('Parse failed', e.message, 'error');
  } finally {
    $('parse-submit').disabled = false;
  }
}

async function uploadAndParse(file) {
  $('parse-submit').disabled = true;
  $('parse-results').classList.add('hide');
  toast('Parsing', 'Uploading ' + file.name + '…');

  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('extract_tables', $('parse-tables').checked ? 'true' : 'false');

    const token = (localStorage.getItem('kh_token') || '').trim();
    const res = await fetch('/v1/research-tools:parse-file', {
      method: 'POST',
      headers: token ? { 'X-API-Key': token } : {},
      body: formData,
    });
    if (!res.ok) throw new Error('Upload failed');
    const data = await res.json();
    renderParseResults(data);
  } catch (e) {
    toast('Parse failed', e.message, 'error');
  } finally {
    $('parse-submit').disabled = false;
  }
}

function renderParseResults(data) {
  $('parse-results').classList.remove('hide');
  $('parse-method').textContent = data.parse_method || 'standard';
  $('parse-pages').textContent = (data.pages || 1) + ' pages';
  $('parse-table-count').textContent = (data.table_count || 0) + ' tables';

  let html = '';

  // Metadata
  if (data.metadata && Object.keys(data.metadata).length) {
    html += '<div class="parse-section"><h4>Metadata</h4><div class="parse-meta-grid">';
    for (const [k, v] of Object.entries(data.metadata)) {
      html += '<div class="parse-meta-item"><span class="key">' + esc(k) + '</span><span class="val">' + esc(String(v)) + '</span></div>';
    }
    html += '</div></div>';
  }

  // Tables
  if (data.tables && data.tables.length) {
    html += '<div class="parse-section"><h4>Extracted Tables (' + data.tables.length + ')</h4>';
    data.tables.forEach((t, i) => {
      html += '<div class="parse-table-wrap"><h5>Table ' + (i + 1) + (t.page ? ' (page ' + t.page + ')' : '') + '</h5>';
      if (t.markdown) {
        html += '<pre class="parse-table-md">' + esc(t.markdown) + '</pre>';
      }
      html += '</div>';
    });
    html += '</div>';
  }

  // Structured (LLM)
  if (data.structured) {
    html += '<div class="parse-section"><h4>LLM Analysis</h4><pre class="parse-structured">' + esc(JSON.stringify(data.structured, null, 2)) + '</pre></div>';
  }

  // Text preview
  if (data.full_text) {
    html += '<div class="parse-section"><h4>Text Preview</h4><div class="parse-text-preview">' + esc(data.full_text.slice(0, 2000)) + '</div></div>';
  }

  $('parse-output').innerHTML = html;
}

// ── Markdown renderer (simple) ─────────────────────────────

function renderMarkdown(text) {
  if (!text) return '';
  let html = esc(text);
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  // Lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p><(h[234]|ul|ol)/g, '<$1').replace(/<\/(h[234]|ul|ol)><\/p>/g, '</$1>');
  return html;
}

// ── Init all tools ─────────────────────────────────────────

function initResearchTools() {
  initToolsTabs();
  initDeepResearch();
  initLitReview();
  initRecommendations();
  initDocParser();
}
