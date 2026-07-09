// Chat UI for the durable support agent. Vanilla JS, no build step.
// Talks to whichever gateway BACKEND_URL points at (see config.js).

const API = window.BACKEND_URL;
const $ = (id) => document.getElementById(id);

let conversationId = null;
let assistantCount = 0; // assistant messages rendered from the server transcript

// ── tiny fetch helper ────────────────────────────────────────────────────────
async function call(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? {} : res.json();
}

// ── markdown (assistant messages only) ──────────────────────────────────────
// Tiny renderer for what the model actually emits: bold/italic/code, bullet
// and numbered lists, pipe tables. Input is HTML-escaped first → XSS-safe.
function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\s][^*]*)\*/g, '<em>$1</em>');
}

const isTableRow = (s) => /^\s*\|.*\|\s*$/.test(s);
const isTableSep = (s) => /^\s*\|[\s:|-]+\|\s*$/.test(s);
const splitRow = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

function mdToHtml(md) {
  const esc = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const lines = esc.split('\n');
  let html = '', list = null, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${para.join('<br>')}</p>`; para = []; } };
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();

    // pipe table: header row + separator row, then body rows
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flushPara(); closeList();
      const cells = (r) => splitRow(r).map((c) => inlineMd(c));
      html += '<table><thead><tr>'
        + cells(line).map((c) => `<th>${c}</th>`).join('')
        + '</tr></thead><tbody>';
      i++; // skip separator
      while (i + 1 < lines.length && isTableRow(lines[i + 1].trimEnd())) {
        i++;
        html += '<tr>' + cells(lines[i]).map((c) => `<td>${c}</td>`).join('') + '</tr>';
      }
      html += '</tbody></table>';
      continue;
    }

    const ul = line.match(/^\s*[-*•]\s+(.*)/);
    const ol = line.match(/^\s*(\d+)[.)]\s+(.*)/);
    if (ul || ol) {
      flushPara();
      const want = ul ? 'ul' : 'ol';
      if (list !== want) {
        closeList();
        html += ul ? '<ul>' : `<ol start="${ol[1]}">`;
        list = want;
      }
      html += `<li>${inlineMd(ul ? ul[1] : ol[2])}</li>`;
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(inlineMd(line));
    }
  }
  flushPara(); closeList();
  return html;
}

// ── rendering ────────────────────────────────────────────────────────────────
function addMsg(role, content, { counted = true } = {}) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') div.innerHTML = mdToHtml(content);
  else div.textContent = content;
  $('chat').appendChild(div);
  div.scrollIntoView({ behavior: 'smooth' });
  if (role === 'assistant' && counted) assistantCount++;
  return div;
}

function renderTranscript(messages) {
  $('chat').querySelectorAll('.msg').forEach((el) => el.remove());
  assistantCount = 0;
  for (const m of messages) addMsg(m.role, m.content);
}

function setBusy(busy, label) {
  $('input').disabled = busy;
  $('send').disabled = busy;
  const t = $('chat').querySelector('.typing');
  if (t) t.remove();
  if (busy) addMsg('assistant typing', label || 'thinking…');
  else $('input').focus();
}

function showError(message) {
  const el = $('error');
  el.textContent = message;
  el.style.display = 'block';
  setTimeout(() => (el.style.display = 'none'), 6000);
}

// ── approval card (the HITL moment) ─────────────────────────────────────────
function showApprovalCard(pending) {
  const card = document.createElement('div');
  card.className = 'approval-card';
  card.innerHTML = `
    <div class="title">⏸ Purchase approval required</div>
    <div class="desc"></div>
    <button class="pill approve">Approve</button>
    <button class="reject">Reject</button>`;
  card.querySelector('.desc').textContent =
    pending.description || `Track IDs: ${(pending.trackIds || []).join(', ')}`;
  card.querySelector('.approve').onclick = () => decide(card, true);
  card.querySelector('.reject').onclick = () => decide(card, false);
  $('chat').appendChild(card);
  card.scrollIntoView({ behavior: 'smooth' });
}

async function decide(card, approved) {
  card.querySelectorAll('button').forEach((b) => (b.disabled = true));
  try {
    // Baseline from the SERVER, not the client render count: multi-step turns
    // put intermediate assistant texts (alongside tool calls) in the server
    // transcript that were never rendered here, so the client count lags.
    const { messages } = await call('GET', `/conversations/${conversationId}/transcript`);
    const baseline = messages.filter((m) => m.role === 'assistant').length;
    await call('POST', `/conversations/${conversationId}/approve`, { approved });
    card.remove();
    setBusy(true, approved ? 'completing purchase…' : 'cancelling…');
    await pollUntilSettled(baseline);
  } catch (e) {
    showError(e.message);
    card.querySelectorAll('button').forEach((b) => (b.disabled = false));
  }
}

// After an approval signal the turn resumes server-side; poll until a new
// assistant message lands (or another approval is requested — multi-purchase turns).
async function pollUntilSettled(baselineAssistant) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const [{ messages }, { pending }] = await Promise.all([
      call('GET', `/conversations/${conversationId}/transcript`),
      call('GET', `/conversations/${conversationId}/pending-approval`),
    ]);
    if (pending) {
      renderTranscript(messages);
      setBusy(false);
      showApprovalCard(pending);
      return;
    }
    const serverCount = messages.filter((m) => m.role === 'assistant').length;
    if (serverCount > baselineAssistant) {
      renderTranscript(messages);
      setBusy(false);
      return;
    }
  }
  setBusy(false);
  showError('Timed out waiting for the agent — check the worker.');
}

// ── lazily start the workflow on the first message ──────────────────────────
// No sign-in step: the customer identity comes from the auth gate (cloud) or a
// default (local), resolved server-side. First send creates the conversation.
async function ensureConversation() {
  if (conversationId) return;
  const { conversationId: id } = await call('POST', '/conversations', {});
  conversationId = id;
  // clickable workflow ID → opens this conversation's workflow in the Temporal UI
  const link = document.createElement('a');
  link.href = `${window.TEMPORAL_UI_BASE}/workflows/${encodeURIComponent(id)}`;
  link.target = '_blank';
  link.rel = 'noopener';
  link.innerHTML = '<span class="label">workflowId:&nbsp;</span>';
  link.append(id);
  $('conv-id').replaceChildren(link);
}

// ── send a message (blocks until the turn settles — see contract) ───────────
$('composer').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('input').value.trim();
  if (!text) return;
  $('input').value = '';
  addMsg('user', text);
  setBusy(true);
  try {
    await ensureConversation();
    const r = await call('POST', `/conversations/${conversationId}/messages`, { text });
    setBusy(false);
    if (r.reply) addMsg('assistant', r.reply);
    if (r.status === 'awaiting_approval') {
      const { pending } = await call('GET', `/conversations/${conversationId}/pending-approval`);
      if (pending) showApprovalCard(pending);
    }
  } catch (err) {
    setBusy(false);
    showError(err.message);
  }
};

// ── API status panel (uptime-style) — the LLM kill-switch for THIS conversation ─
// Provider/model come from config.js (the gateway's env); the outage flag is
// per-conversation, so flipping it only affects your own session.
let llmDown = false;

function renderStatus(down) {
  llmDown = !!down;
  $('api-status').className = llmDown ? 'down' : 'ok';
  $('as-provider').textContent =
    { anthropic: 'Anthropic API', openai: 'OpenAI API' }[window.LLM_PROVIDER] || 'LLM API';
  $('as-state').textContent = llmDown ? 'Major outage' : 'Operational';
  $('as-model').textContent = window.LLM_MODEL || '';
}

async function refreshStatus() {
  if (!conversationId) return renderStatus(false);  // no session yet → operational
  try {
    const { down } = await call('GET', `/conversations/${conversationId}/llm-status`);
    renderStatus(down);
  } catch { /* ignore transient errors */ }
}

$('api-status').onclick = async () => {
  try {
    await ensureConversation();  // the switch is scoped to a conversation, so start one
    const { down } = await call('POST', `/conversations/${conversationId}/llm-status`,
                                { down: !llmDown });
    renderStatus(down);
  } catch (err) { showError(err.message); }
};

renderStatus(false);
setInterval(refreshStatus, 5000);  // keep the panel live

// ── on load ──────────────────────────────────────────────────────────────────
addMsg('assistant',
  'Hi! I can help you find music, check your orders, or buy tracks. What are you looking for?',
  { counted: false });  // client-side greeting; not part of the server transcript
$('input').focus();
