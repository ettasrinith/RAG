/* ── ═══ INIT ════════════════════════════════════════ */

(async function init() {
  // Load all views first
  await loadAllViews();
  // Re-attach listeners for all loaded views
  VIEWS.forEach(v => reattachViewListeners(v));
  loadRepoFilter();
  // Load dashboard data on start
  setTimeout(refreshDashboard, 300);
  // Research collection picker
  loadCollectionPicker();
})();

console.log('🔬 Knowledge Hub v2 · UI initialized');
