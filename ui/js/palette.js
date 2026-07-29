/* ── Command Palette (⌘K) ─────────────────────────────── */
'use strict';

const PALETTE_COMMANDS = [
  // Navigation
  { id: 'nav-dashboard', label: 'Go to Dashboard', hint: 'Overview & stats', icon: 'grid', action: () => navigate('dashboard') },
  { id: 'nav-search', label: 'Go to Search', hint: 'Semantic search', icon: 'search', action: () => navigate('search') },
  { id: 'nav-chat', label: 'Go to Chat', hint: 'Ask your library', icon: 'chat', action: () => navigate('chat') },
  { id: 'nav-index', label: 'Go to Index', hint: 'Add sources', icon: 'upload', action: () => navigate('index') },
  { id: 'nav-research', label: 'Go to Research', hint: 'Discover papers', icon: 'book', action: () => navigate('research') },
  { id: 'nav-tools', label: 'Go to AI Tools', hint: 'Deep research & more', icon: 'wrench', action: () => navigate('tools') },
  { id: 'nav-graph', label: 'Go to Graph', hint: 'Knowledge graph', icon: 'graph', action: () => navigate('graph') },
  { id: 'nav-settings', label: 'Go to Settings', hint: 'Configuration', icon: 'settings', action: () => navigate('settings') },
  { id: 'nav-admin', label: 'Go to Admin', hint: 'System management', icon: 'shield', action: () => navigate('admin') },
  // Actions
  { id: 'act-new-chat', label: 'New Chat Session', hint: 'Start fresh', icon: 'plus', action: () => { navigate('chat'); const b = $('chat-new-btn'); if (b) b.click(); } },
  { id: 'act-refresh', label: 'Refresh Dashboard', hint: 'Reload stats', icon: 'refresh', action: () => { navigate('dashboard'); refreshDashboard(); } },
  { id: 'act-theme', label: 'Toggle Theme', hint: 'Dark / Light', icon: 'theme', action: () => { applyTheme(State.theme === 'dark' ? 'light' : 'dark'); } },
  { id: 'act-collapse', label: 'Toggle Sidebar', hint: 'Collapse rail', icon: 'sidebar', action: () => { const s = $('sidebar'); s.classList.toggle('collapsed-rail'); localStorage.setItem('sidebar-collapsed', s.classList.contains('collapsed-rail') ? '1' : '0'); } },
];

const PALETTE_ICONS = {
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
  wrench: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="5" cy="19" r="2"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
  theme: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
  sidebar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>',
};

let paletteOpen = false;
let paletteIndex = 0;
let paletteFiltered = [];

function buildPaletteDOM() {
  if ($('cmd-palette')) return;
  const el = document.createElement('div');
  el.id = 'cmd-palette';
  el.className = 'cmd-palette';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', 'Command palette');
  el.innerHTML =
    '<div class="cmd-palette-backdrop"></div>' +
    '<div class="cmd-palette-panel">' +
      '<div class="cmd-palette-input-row">' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>' +
        '<input type="text" id="cmd-palette-input" placeholder="Type a command or search…" autocomplete="off" spellcheck="false" />' +
        '<kbd>ESC</kbd>' +
      '</div>' +
      '<div class="cmd-palette-list" id="cmd-palette-list" role="listbox"></div>' +
      '<div class="cmd-palette-footer">' +
        '<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>' +
        '<span><kbd>↵</kbd> select</span>' +
        '<span><kbd>esc</kbd> close</span>' +
      '</div>' +
    '</div>';
  document.body.appendChild(el);

  el.querySelector('.cmd-palette-backdrop').addEventListener('click', closePalette);
  $('cmd-palette-input').addEventListener('input', () => renderPalette($('cmd-palette-input').value));
  $('cmd-palette-input').addEventListener('keydown', handlePaletteKeys);
  $('cmd-palette-list').addEventListener('click', e => {
    const item = e.target.closest('.cmd-item');
    if (item) executePaletteItem(parseInt(item.dataset.idx, 10));
  });
}

function openPalette() {
  buildPaletteDOM();
  paletteOpen = true;
  $('cmd-palette').classList.add('open');
  const input = $('cmd-palette-input');
  input.value = '';
  renderPalette('');
  setTimeout(() => input.focus(), 30);
}

function closePalette() {
  paletteOpen = false;
  const el = $('cmd-palette');
  if (el) el.classList.remove('open');
}

function renderPalette(query) {
  const q = query.toLowerCase().trim();
  paletteFiltered = q
    ? PALETTE_COMMANDS.filter(c => c.label.toLowerCase().includes(q) || (c.hint || '').toLowerCase().includes(q))
    : PALETTE_COMMANDS;
  paletteIndex = 0;
  const list = $('cmd-palette-list');
  if (!paletteFiltered.length) {
    list.innerHTML = '<div class="cmd-empty">No matching commands</div>';
    return;
  }
  list.innerHTML = paletteFiltered.map((c, i) =>
    '<div class="cmd-item' + (i === 0 ? ' active' : '') + '" data-idx="' + i + '" role="option">' +
      '<span class="cmd-icon">' + (PALETTE_ICONS[c.icon] || '') + '</span>' +
      '<span class="cmd-label">' + esc(c.label) + '</span>' +
      (c.hint ? '<span class="cmd-hint">' + esc(c.hint) + '</span>' : '') +
    '</div>'
  ).join('');
}

function handlePaletteKeys(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    paletteIndex = Math.min(paletteIndex + 1, paletteFiltered.length - 1);
    updatePaletteActive();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    paletteIndex = Math.max(paletteIndex - 1, 0);
    updatePaletteActive();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    executePaletteItem(paletteIndex);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closePalette();
  }
}

function updatePaletteActive() {
  qsa('.cmd-item', $('cmd-palette-list')).forEach((el, i) => {
    el.classList.toggle('active', i === paletteIndex);
    if (i === paletteIndex) el.scrollIntoView({ block: 'nearest' });
  });
}

function executePaletteItem(idx) {
  const cmd = paletteFiltered[idx];
  if (!cmd) return;
  closePalette();
  setTimeout(() => cmd.action(), 50);
}
