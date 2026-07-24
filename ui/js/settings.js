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

