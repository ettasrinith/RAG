/* ── ═══ CHAT ═══════════════════════════════════════════ */

let chatHistory = [];
let chatScope = 'main';
let currentSessionId = null;
let attachedFile = null;
let attachedFileContent = '';
let agentMode = false;

function addChatMessage(role, html, msgId) {
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  div.innerHTML = html;
  if (msgId) div.dataset.msgId = msgId;
  // Add feedback buttons for assistant messages
  if (role === 'assistant' && msgId) {
    const fb = document.createElement('div');
    fb.className = 'msg-feedback';
    fb.innerHTML =
      '<button class="fb-btn fb-up" data-fb="up" title="Good answer">👍</button>' +
      '<button class="fb-btn fb-down" data-fb="down" title="Bad answer">👎</button>';
    div.appendChild(fb);
  }
  $('chat-messages').appendChild(div);
  scrollChat();
  return div;
}

function scrollChat() {
  const el = $('chat-messages');
  el.scrollTop = el.scrollHeight;
}

/* ── Session Management ──────────────────────────────── */
async function loadSessions() {
  try {
    const sessions = await api('/v1/sessions');
    const list = $('sessions-list');
    if (!sessions || !sessions.length) {
      list.innerHTML = '<div class="empty-sm">No sessions yet</div>';
      return;
    }
    list.innerHTML = sessions.map(s =>
      '<div class="session-item' + (s.id === currentSessionId ? ' active' : '') + '" data-sid="' + escAttr(s.id) + '">' +
      '<span class="si-title">' + esc(s.title || 'New chat') + '</span>' +
      '<span class="si-meta">' + (s.message_count || 0) + ' messages</span>' +
      '<button class="session-del" data-del="' + escAttr(s.id) + '" title="Delete">×</button>' +
      '</div>'
    ).join('');
  } catch (_) {}
}

async function createSession() {
  try {
    const s = await api('/v1/sessions', { method: 'POST', body: JSON.stringify({ title: 'New chat' }) });
    currentSessionId = s.id;
    loadSessions();
    clearChatMessages();
    return s;
  } catch (_) { return null; }
}

async function switchSession(sid) {
  currentSessionId = sid;
  loadSessions();
  // Load messages
  try {
    const msgs = await api('/v1/sessions/' + sid);
    clearChatMessages();
    for (const m of msgs) {
      if (m.role === 'user') {
        addChatMessage('user', esc(m.content), m.id);
      } else {
        const rendered = renderCitations(m.content, m.sources || []);
        const div = addChatMessage('assistant', '<div>' + rendered + '</div>', m.id);
        if (m.sources && m.sources.length) {
          renderSources(m.sources);
        }
      }
    }
  } catch (_) {}
}

async function deleteSession(sid) {
  try {
    await api('/v1/sessions/' + sid, { method: 'DELETE' });
    if (currentSessionId === sid) {
      currentSessionId = null;
      clearChatMessages();
    }
    loadSessions();
  } catch (_) {}
}

async function saveMessage(role, content, sources) {
  if (!currentSessionId) {
    const s = await createSession();
    if (!s) return null;
  }
  try {
    const msg = await api('/v1/sessions/' + currentSessionId + '/messages', {
      method: 'POST',
      body: JSON.stringify({ role, content, sources: sources || null }),
    });
    loadSessions();
    return msg;
  } catch (_) { return null; }
}

async function saveFeedback(msgId, feedback) {
  if (!currentSessionId || !msgId) return;
  try {
    await api('/v1/sessions/' + currentSessionId + '/messages/' + msgId + '/feedback', {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    });
  } catch (_) {}
}

function clearChatMessages() {
  const msgs = $('chat-messages');
  msgs.innerHTML = '';
  const welcome = $('chat-welcome');
  if (welcome) msgs.appendChild(welcome.cloneNode(true));
  $('sources-list').innerHTML = '<div class="empty-sm">No sources yet. Ask a question to see sources.</div>';
  $('sources-count').textContent = '0';
  chatHistory = [];
}

// Session sidebar events
$('chat-new-session-btn')?.addEventListener('click', () => {
  currentSessionId = null;
  clearChatMessages();
  loadSessions();
});

$('sessions-list')?.addEventListener('click', e => {
  const del = e.target.closest('.session-del');
  if (del) {
    e.stopPropagation();
    if (confirm('Delete this session?')) deleteSession(del.dataset.del);
    return;
  }
  const item = e.target.closest('.session-item');
  if (item && item.dataset.sid) switchSession(item.dataset.sid);
});

/* ── File Attachments ────────────────────────────────── */
$('chat-attach-btn')?.addEventListener('click', () => $('chat-file-input')?.click());

$('chat-file-input')?.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  attachedFile = file;
  $('chat-attachment-bar').style.display = 'flex';
  $('attachment-chip').textContent = '📎 ' + file.name;
  // Read file content
  try {
    attachedFileContent = await file.text();
  } catch (_) {
    attachedFileContent = '';
  }
  e.target.value = '';
});

$('chat-attachment-remove')?.addEventListener('click', () => {
  attachedFile = null;
  attachedFileContent = '';
  $('chat-attachment-bar').style.display = 'none';
});

/* ── Scope selector ──────────────────────────────────── */
$('chat-scope-selector')?.addEventListener('click', e => {
  const btn = e.target.closest('.scope-btn');
  if (!btn) return;
  qsa('.scope-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  chatScope = btn.dataset.scope;
});

/* ── Agent mode toggle ─────────────────────────────── */
$('agent-mode-toggle')?.addEventListener('change', e => {
  agentMode = e.target.checked;
  const input = $('chat-input');
  if (agentMode) {
    input.placeholder = 'Ask anything — agent will reason step by step…';
  } else {
    input.placeholder = 'Ask a question about your knowledge…';
  }
});

// Suggestion chips
$('chat-suggestions')?.addEventListener('click', e => {
  const chip = e.target.closest('.suggestion-chip');
  if (!chip) return;
  $('chat-input').value = chip.dataset.q;
  sendChatMessage();
});

$('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
});
$('chat-input').addEventListener('input', () => {
  $('chat-send-btn').disabled = !$('chat-input').value.trim();
});
$('chat-send-btn').addEventListener('click', sendChatMessage);
$('chat-new-btn').addEventListener('click', () => {
  currentSessionId = null;
  clearChatMessages();
  loadSessions();
});

// Message feedback
$('chat-messages').addEventListener('click', e => {
  const fb = e.target.closest('.fb-btn');
  if (!fb) return;
  const msgEl = fb.closest('.msg');
  const msgId = msgEl?.dataset?.msgId;
  const feedback = fb.dataset.fb;
  if (msgId) {
    saveFeedback(msgId, feedback);
    // Visual feedback
    qsa('.fb-btn', msgEl).forEach(b => b.classList.remove('selected'));
    fb.classList.add('selected');
  }
});

async function sendChatMessage() {
  const inp = $('chat-input');
  const q = inp.value.trim();
  if (!q || State.streaming) return;

  // Route to agent mode if enabled
  if (agentMode) {
    sendAgentMessage(q);
    return;
  }

  // Build query with optional file context
  let fullQuery = q;
  if (attachedFileContent) {
    fullQuery = q + '\n\n--- Attached file: ' + attachedFile.name + ' ---\n' + attachedFileContent.slice(0, 8000);
  }

  inp.value = '';
  $('chat-send-btn').disabled = true;
  State.streaming = true;

  // Remove welcome
  const welcome = $('chat-welcome');
  if (welcome) welcome.remove();

  // Save user message
  const userMsg = await saveMessage('user', q);
  addChatMessage('user', esc(q), userMsg?.id);
  const msgEl = addChatMessage('assistant', '<span class="typing"><span></span><span></span><span></span></span>');

  let content = '';
  let sources = [];
  let started = false;

  try {
    await apiStream('/chat', { q: fullQuery, k: 8, scope: chatScope }, ev => {
      if (ev.type === 'sources') {
        sources = ev.sources || [];
        renderSources(sources);
      } else if (ev.type === 'token') {
        if (!started) { msgEl.innerHTML = ''; started = true; }
        content += ev.text;
        msgEl.innerHTML = '<div>' + renderCitations(content, sources) + '</div>';
        scrollChat();
      } else if (ev.type === 'done') {
        msgEl.innerHTML = '<div>' + renderCitations(content, sources) + '</div>';
        // Re-add feedback buttons
        const fbDiv = document.createElement('div');
        fbDiv.className = 'msg-feedback';
        fbDiv.innerHTML =
          '<button class="fb-btn fb-up" data-fb="up" title="Good answer">👍</button>' +
          '<button class="fb-btn fb-down" data-fb="down" title="Bad answer">👎</button>';
        msgEl.appendChild(fbDiv);
        // Save assistant message
        saveMessage('assistant', content, sources);
        // Clear attachment
        attachedFile = null;
        attachedFileContent = '';
        $('chat-attachment-bar').style.display = 'none';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
        inp.focus();
        scrollChat();
      } else if (ev.type === 'error') {
        msgEl.innerHTML = '<div>Error: ' + esc(ev.error || 'unknown') + '</div>';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
      }
    });
  } catch (e) {
    msgEl.innerHTML = '<div>Error: ' + esc(e.message) + '</div>';
  } finally {
    State.streaming = false;
    $('chat-send-btn').disabled = false;
    inp.focus();
    scrollChat();
  }
}

/* ── Agent Mode Message ──────────────────────────────── */
async function sendAgentMessage(q) {
  const inp = $('chat-input');

  // Build query with optional file context
  let fullQuery = q;
  if (attachedFileContent) {
    fullQuery = q + '\n\n--- Attached file: ' + attachedFile.name + ' ---\n' + attachedFileContent.slice(0, 8000);
  }

  inp.value = '';
  $('chat-send-btn').disabled = true;
  State.streaming = true;

  // Remove welcome
  const welcome = $('chat-welcome');
  if (welcome) welcome.remove();

  // Save user message
  const userMsg = await saveMessage('user', q);
  addChatMessage('user', esc(q), userMsg?.id);

  // Create agent message container
  const msgEl = document.createElement('div');
  msgEl.className = 'msg assistant agent-msg';
  msgEl.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  $('chat-messages').appendChild(msgEl);
  scrollChat();

  let content = '';
  let sources = [];
  let toolCalls = [];
  let currentThinking = null;
  let thinkingContent = '';
  let answerStarted = false;
  let toolsContainer = null;

  try {
    await apiStream('/v1/agent:ask', { q: fullQuery, k: 8, stream: true }, ev => {
      if (ev.type === 'thinking') {
        // LLM reasoning tokens
        if (!currentThinking) {
          thinkingContent = '';
          const thinkingEl = document.createElement('div');
          thinkingEl.className = 'agent-thinking expanded';
          thinkingEl.innerHTML =
            '<div class="agent-thinking-header">' +
              '<span class="thinking-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg></span>' +
              '<span>Reasoning… (round ' + (ev.round || 1) + ')</span>' +
              '<span class="thinking-chevron"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg></span>' +
            '</div>' +
            '<div class="agent-thinking-body"></div>';
          currentThinking = thinkingEl;
          thinkingContent = '';
          msgEl.innerHTML = '';
          msgEl.appendChild(thinkingEl);
          // Make thinking collapsible
          thinkingEl.querySelector('.agent-thinking-header').addEventListener('click', () => {
            thinkingEl.classList.toggle('expanded');
          });
        }
        thinkingContent += ev.text;
        const body = currentThinking.querySelector('.agent-thinking-body');
        body.textContent = thinkingContent;
        body.scrollTop = body.scrollHeight;
        scrollChat();
      } else if (ev.type === 'tool_call') {
        // Tool being called
        if (!toolsContainer) {
          toolsContainer = document.createElement('div');
          toolsContainer.className = 'agent-tools';
          msgEl.appendChild(toolsContainer);
        }
        // Collapse thinking when tool call starts
        if (currentThinking) {
          currentThinking.classList.remove('expanded');
          currentThinking = null;
        }
        const toolName = ev.tool || 'unknown';
        const args = ev.arguments || {};
        const argsStr = Object.entries(args).map(([k, v]) => k + ': ' + (typeof v === 'string' ? v.slice(0, 50) : JSON.stringify(v))).join(', ');
        const toolEl = document.createElement('div');
        toolEl.className = 'agent-tool-call';
        toolEl.dataset.toolId = toolName + '_' + Date.now();
        toolEl.innerHTML =
          '<span class="tool-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></span>' +
          '<span class="tool-name">' + esc(toolName) + '</span>' +
          '<span class="tool-detail">' + esc(argsStr) + '</span>' +
          '<span class="tool-status running">Running</span>';
        toolsContainer.appendChild(toolEl);
        scrollChat();
      } else if (ev.type === 'tool_result') {
        // Tool completed
        if (toolsContainer) {
          const lastTool = toolsContainer.querySelector('.tool-status.running');
          if (lastTool) {
            lastTool.className = 'tool-status done';
            lastTool.textContent = 'Done';
          }
        }
        // Show result summary
        if (ev.result && typeof ev.result === 'object') {
          const resultSummary = ev.result.summary || (ev.result.results ? ev.result.results.length + ' results found' : 'Completed');
          const resultEl = document.createElement('div');
          resultEl.className = 'agent-tool-result';
          resultEl.textContent = resultSummary;
          toolsContainer.appendChild(resultEl);
        }
        scrollChat();
      } else if (ev.type === 'tool_error') {
        // Tool failed
        if (toolsContainer) {
          const lastTool = toolsContainer.querySelector('.tool-status.running');
          if (lastTool) {
            lastTool.className = 'tool-status error';
            lastTool.textContent = 'Error';
          }
        }
        scrollChat();
      } else if (ev.type === 'sources') {
        sources = ev.sources || [];
        renderSources(sources);
      } else if (ev.type === 'answer') {
        // Final answer tokens
        if (!answerStarted) {
          // Collapse thinking if still open
          if (currentThinking) {
            currentThinking.classList.remove('expanded');
            currentThinking = null;
          }
          // Add answer section
          const answerDiv = document.createElement('div');
          answerDiv.className = 'agent-answer';
          answerDiv.innerHTML = '<div></div>';
          msgEl.appendChild(answerDiv);
          answerStarted = true;
        }
        content += ev.text;
        const answerDiv = msgEl.querySelector('.agent-answer > div');
        if (answerDiv) {
          answerDiv.innerHTML = renderCitations(content, sources);
        }
        scrollChat();
      } else if (ev.type === 'done') {
        // Stream complete
        if (!answerStarted && content) {
          // Shouldn't happen, but handle edge case
          const answerDiv = document.createElement('div');
          answerDiv.className = 'agent-answer';
          answerDiv.innerHTML = '<div>' + renderCitations(content, sources) + '</div>';
          msgEl.appendChild(answerDiv);
        }
        // Add feedback buttons
        const fbDiv = document.createElement('div');
        fbDiv.className = 'msg-feedback';
        fbDiv.innerHTML =
          '<button class="fb-btn fb-up" data-fb="up" title="Good answer">👍</button>' +
          '<button class="fb-btn fb-down" data-fb="down" title="Bad answer">👎</button>';
        msgEl.appendChild(fbDiv);
        // Save assistant message
        saveMessage('assistant', content, sources);
        // Clear attachment
        attachedFile = null;
        attachedFileContent = '';
        $('chat-attachment-bar').style.display = 'none';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
        inp.focus();
        scrollChat();
      } else if (ev.type === 'error') {
        msgEl.innerHTML = '<div>Error: ' + esc(ev.error || 'unknown') + '</div>';
        State.streaming = false;
        $('chat-send-btn').disabled = false;
      }
    });
  } catch (e) {
    msgEl.innerHTML = '<div>Error: ' + esc(e.message) + '</div>';
  } finally {
    State.streaming = false;
    $('chat-send-btn').disabled = false;
    inp.focus();
    scrollChat();
  }
}

/* ── Inline Citations ─────────────────────────────────── */
function renderCitations(text, sources) {
  // Render [1], [2] etc. as clickable links to the source panel
  let safe = esc(text);
  if (sources && sources.length) {
    safe = safe.replace(/\[(\d+)\]/g, (match, num) => {
      const idx = parseInt(num, 10) - 1;
      if (idx >= 0 && idx < sources.length) {
        const url = sources[idx].url || '#';
        return '<a class="citation" href="' + escAttr(url) + '" target="_blank" rel="noopener" title="' + esc(sources[idx].title || '') + '">[' + num + ']</a>';
      }
      return match;
    });
  }
  return safe;
}

function renderSources(sources) {
  const list = $('sources-list');
  $('sources-count').textContent = sources.length;
  if (!sources.length) {
    list.innerHTML = '<div class="empty-sm">No sources found</div>';
    return;
  }
  list.innerHTML = sources.map((s, i) => {
    const snippet = s.snippet || s.text || '';
    const snippetHtml = snippet ? '<span class="si-snippet">' + esc(snippet.slice(0, 200)) + (snippet.length > 200 ? '…' : '') + '</span>' : '';
    const link = s.url ? '<a href="' + escAttr(s.url) + '" target="_blank" rel="noopener" class="si-link">Open source →</a>' : '';
    return '<div class="source-item" data-idx="' + (i + 1) + '">' +
    '<span class="si-num">[' + (i + 1) + ']</span>' +
    '<div class="si-body">' +
    '<span class="si-title">' + esc(s.title || 'Untitled') + '</span>' +
    '<span class="si-meta">' + esc(s.source || '') + (s.repo ? ' · ' + esc(s.repo) : '') + (s.score ? ' · ' + Number(s.score).toFixed(3) : '') + '</span>' +
    snippetHtml +
    link +
    '</div></div>';
  }).join('');
}

