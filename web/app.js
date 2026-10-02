// Chat UI for the durable travel-planner agent. Vanilla JS, no build step.
// Talks to whichever gateway BACKEND_URL points at (see config.js).

// Never trust a localhost BACKEND_URL when we're not on localhost: in the
// deployed container the gateway serves a dynamic /config.js (BACKEND_URL="",
// same-origin https), but a stale/CDN-cached static config.js can leave the
// localhost default in place — and fetching http://localhost from an https page
// is blocked as mixed content. Fall back to same-origin so the app works
// regardless of what config.js says; local dev (on localhost) is untouched.
const _backend = window.BACKEND_URL || '';
const API =
  location.hostname !== 'localhost' && /localhost|127\.0\.0\.1/.test(_backend)
    ? ''
    : _backend;
const $ = (id) => document.getElementById(id);

let conversationId = null;
let assistantCount = 0; // assistant messages rendered from the server transcript

// Persist the conversation id so a page reload (a manual refresh, or reopening the
// tab) reattaches to the SAME durable workflow instead of orphaning it and starting
// a new one. The workflow survives on the server — this pointer is what lets the UI
// find it again. (A worker crash doesn't reload the page, so it doesn't need this;
// only a browser reload loses the in-memory id.) See boot()/rehydrate() at the bottom.
const CONV_KEY = 'travelAgent.conversationId';
// Where to keep that pointer. Crashable envs are ephemeral and provisioned fresh
// (a new crash-<hash> subdomain each time), so they must open on a clean slate and
// never auto-resume a prior visit's conversation. sessionStorage is scoped to the
// tab session: it survives an in-demo refresh (rehydrate still reattaches) but is
// empty on a fresh load / new tab / newly provisioned workspace. Always-on cloud and
// local dev keep localStorage, so a reload reattaches across browser sessions as before.
const convStore = window.IS_CRASHABLE === true ? sessionStorage : localStorage;
// Drop any pointer an older (localStorage-based) build left on a crashable subdomain,
// so a pre-existing id can't leak into a fresh session on the first load after upgrade.
if (convStore !== localStorage) { try { localStorage.removeItem(CONV_KEY); } catch { /* ignore */ } }
const GREETING =
  "Hi! Where would you like to travel? I can find events, flights, and hotels, do a deep-dive research pass on a destination — and book your trip.";

// ── tiny fetch helper ────────────────────────────────────────────────────────
async function call(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error(err.error || `${res.status} ${res.statusText}`);
    e.status = res.status;                  // let callers tell transient 5xx from a real 4xx
    throw e;
  }
  return res.status === 204 ? {} : res.json();
}

// ── markdown (assistant messages only) ──────────────────────────────────────
// Tiny renderer for what the model actually emits: headings, bold/italic/code,
// bullet and numbered lists, pipe tables. Input is HTML-escaped first → XSS-safe.
function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*\*([\s\S]+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/___([\s\S]+?)___/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__([\s\S]+?)__/g, '<strong>$1</strong>')
    .replace(/\*([^*\s][\s\S]*?)\*/g, '<em>$1</em>');
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

    const h = line.match(/^(#{1,3})\s+(.*)/);
    const ul = line.match(/^\s*[-*•]\s+(.*)/);
    const ol = line.match(/^\s*(\d+)[.)]\s+(.*)/);
    if (h) {
      flushPara(); closeList();
      const n = h[1].length + 1;  // #→h2, ##→h3, ###→h4 (h1 is reserved for the hero)
      html += `<h${n}>${inlineMd(h[2])}</h${n}>`;
    } else if (ul || ol) {
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

// A long turn can run many seconds (LLM + tool calls), so a static "thinking…"
// reads as frozen. The indicator is animated (bouncing dots) and, when the caller
// doesn't name a specific action, it slowly rotates through what the agent is doing
// so the user stays oriented. A research turn swaps this out for the richer
// progress card (renderProgress removes the .typing bubble) once its phase lands.
let typingTimer = null;
// Kept intentionally generic: this rotation fires for EVERY non-research turn
// (a question, an itinerary edit, a booking — not just flight/hotel searches), so
// the phrasing must be true regardless of intent. Naming a specific tool here would
// lie on the turns that don't run it. Real per-tool narration would need a workflow
// query surfacing the current step (see setBusy note).
const WORKING_PHRASES = [
  'Thinking through your request…',
  'Working through the details…',
  'Weighing the best options…',
  'Pulling your response together…',
];

function stopTypingRotation() {
  if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
}

function setBusy(busy, label) {
  $('input').disabled = busy;
  $('send').disabled = busy;
  stopTypingRotation();
  const t = $('chat').querySelector('.typing');
  if (t) t.remove();
  if (!busy) { $('input').focus(); return; }

  const bubble = addMsg('assistant typing', '', { counted: false });
  bubble.innerHTML =
    '<span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>' +
    '<span class="typing-label"></span>';
  const labelEl = bubble.querySelector('.typing-label');

  if (label) { labelEl.textContent = label; return; }  // caller named the action → don't rotate

  let i = 0;
  labelEl.textContent = WORKING_PHRASES[0];
  typingTimer = setInterval(() => {
    i += 1;
    // Play the list once, then settle on a steady "Still working…" rather than
    // looping back — cycling the same phrases on a long turn reads as fake. The
    // dots keep bouncing (CSS), so it still looks alive after we stop rotating.
    const next = i < WORKING_PHRASES.length ? WORKING_PHRASES[i] : 'Still working…';
    labelEl.classList.add('fading');                    // fade out, swap text, fade back in
    setTimeout(() => {
      labelEl.textContent = next;
      labelEl.classList.remove('fading');
    }, 320);
    if (i >= WORKING_PHRASES.length) stopTypingRotation();
  }, 2600);
}

function showError(message) {
  const el = $('error');
  el.textContent = message;
  el.style.display = 'block';
  setTimeout(() => (el.style.display = 'none'), 6000);
}

// ── research_destination: live fan-out progress card ─────────────────────────
// While a turn is in flight (the send_message update blocks server-side through
// the whole research pass), poll the workflow's research_status and render a
// progress card: phase stages (plan → search → write) each with a
// spinner/check, plus the search plan with a spinner per parallel search that
// flips to ✓ as each activity completes.
let statusTimer = null;
const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const RSTAGES = [
  ['plan', 'Planning searches'],
  ['search', 'Researching the web'],
  ['write', 'Writing the guide'],
];
const RPHASE = { planning: 0, searching: 1, writing: 2 };
const isResearchPhase = (p) => p in RPHASE;

function renderProgress(s) {
  stopTypingRotation();  // the rich card takes over; kill the generic phrase rotation
  const t = $('chat').querySelector('.typing');
  if (t) t.remove();  // the rich card replaces the plain typing bubble
  let card = $('progress-card');
  if (!card) {
    card = document.createElement('div');
    card.id = 'progress-card';
    card.className = 'progress-card';
    card.innerHTML =
      '<div class="title"><span class="spinner"></span>Researching…</div><div class="stages">' +
      RSTAGES.map(([key]) => `<div class="stage" data-key="${key}"><span class="ic"></span><span class="label"></span></div>`).join('') +
      '</div><div class="plan-wrap" hidden><div class="plan-label">Search plan</div><ul class="plan-list"></ul></div>';
    $('chat').appendChild(card);
    card.scrollIntoView({ behavior: 'smooth' });
  }
  const active = RPHASE[s.phase] ?? 0;
  RSTAGES.forEach(([key, label], i) => {
    const row = card.querySelector(`.stage[data-key="${key}"]`);
    const state = i < active ? 'done' : i === active ? 'active' : 'pending';
    if (row.dataset.state !== state) {
      row.dataset.state = state;
      row.className = 'stage' + (state === 'done' ? ' done' : state === 'active' ? ' active' : '');
      const ic = row.querySelector('.ic');
      if (state === 'active') ic.innerHTML = '<span class="spinner"></span>';
      else ic.textContent = state === 'done' ? '✓' : '·';
    }
    const text = key === 'search' && s.searchesTotal
      ? `Researching the web (${s.searchesDone}/${s.searchesTotal})`
      : label;
    const labelEl = row.querySelector('.label');
    if (labelEl.textContent !== text) labelEl.textContent = text;
  });

  const wrap = card.querySelector('.plan-wrap');
  const planEl = card.querySelector('.plan-list');
  if (s.plan && s.plan.length) {
    wrap.hidden = false;
    if (planEl.children.length !== s.plan.length) {
      planEl.innerHTML = s.plan.map((p) =>
        '<li class="plan-item"><span class="ic"><span class="spin"></span></span>' +
        `<span class="body"><span class="q">${escapeHtml(p.query)}</span>` +
        (p.reason ? `<span class="why">${escapeHtml(p.reason)}</span>` : '') +
        '</span></li>'
      ).join('');
    }
    // searchesDone is a COUNT, not per-item; mark the first N complete. During
    // the searching phase the rest spin; before/after, they're pending/done.
    [...planEl.children].forEach((li, i) => {
      const state = i < s.searchesDone ? 'done' : s.phase === 'searching' ? 'active' : 'pending';
      const cls = 'plan-item ' + state;
      if (li.className !== cls) li.className = cls;
    });
  }
}

function removeProgress() {
  const card = $('progress-card');
  if (card) card.remove();
}

function startStatusPolling() {
  if (statusTimer || !conversationId) return;
  statusTimer = setInterval(async () => {
    // refresh the itinerary rail live so items pop in as the agent adds them
    refreshItinerary();
    try {
      const s = await call('GET', `/conversations/${conversationId}/research-status`);
      if (isResearchPhase(s.phase)) renderProgress(s);
    } catch { /* transient — keep polling */ }
  }, 700);
}

function stopStatusPolling() {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
  removeProgress();  // the guide takes over from here
}

// ── itinerary (workflow-durable; refreshed after every turn) ─────────────────
async function refreshItinerary() {
  if (!conversationId) return;
  try {
    const { items, total } = await call('GET', `/conversations/${conversationId}/itinerary`);
    renderItinerary(items, total);
  } catch { /* ignore transient errors */ }
}

let itinSig = null;  // last-rendered signature, so the live poll only rebuilds on change

function renderItinerary(items, total) {
  items = items || [];
  // Skip the rebuild when nothing changed — otherwise the 700ms live poll would
  // re-trigger the row fade-in animation and flicker.
  const sig = JSON.stringify([items.map((i) => i.itemId), total]);
  if (sig === itinSig) return;
  const prev = itinSig;
  const prevIds = prev ? new Set(JSON.parse(prev)[0]) : new Set();
  itinSig = sig;

  const n = items.length;
  $('itin-count').textContent = n ? `${n} item${n > 1 ? 's' : ''}` : 'empty';
  $('itin-total').textContent = `$${Number(total || 0).toFixed(2)}`;
  const list = $('itin-items');
  list.replaceChildren();
  const book = $('itin-book');
  if (!n) {
    book.disabled = true;  // nothing to book; leave the list blank
    return;
  }
  book.disabled = false;
  for (const it of items) {
    const row = document.createElement('div');
    row.className = 'itin-row';
    if (prevIds.has(it.itemId)) row.style.animation = 'none';  // only new rows fade in
    row.innerHTML =
      '<span class="it-main"><span class="it-kind"></span><span class="it-title"></span><span class="it-sub"></span></span>' +
      '<span class="it-price"></span>';
    row.querySelector('.it-kind').textContent = it.kind;
    row.querySelector('.it-title').textContent = it.title;
    row.querySelector('.it-sub').textContent = it.subtitle || '';
    row.querySelector('.it-price').textContent = `$${Number(it.price).toFixed(2)}`;
    list.append(row);
  }
}

// ── approval card (the HITL moment) ─────────────────────────────────────────
function showApprovalCard(pending) {
  const isInvoice = pending.action === 'create_invoice';
  const card = document.createElement('div');
  card.className = 'approval-card';
  card.innerHTML = `
    <div class="title"></div>
    <div class="desc"></div>
    <button class="pill approve">Confirm</button>
    <button class="reject">Cancel</button>`;
  const desc = card.querySelector('.desc');
  if (isInvoice) {
    // Mirror the original's CreateInvoice gate: tool name + args + Confirm.
    card.querySelector('.title').textContent = '🧾 Agent is ready to run: create_invoice';
    const a = pending.args || {};
    const args = { amount: a.amount, flight_details: a.flight_details };
    desc.innerHTML =
      '<div class="conf-args-label">Args</div>' +
      `<pre class="conf-args">${escapeHtml(JSON.stringify(args, null, 2))}</pre>` +
      '<div class="conf-note">Confirm to generate the invoice.</div>';
  } else {
    card.querySelector('.title').textContent = '⏸ Agent requests durable checkout';
    desc.innerHTML =
      `<div>${escapeHtml(pending.detail || `$${Number(pending.amount || 0).toFixed(2)}`)}</div>` +
      '<div class="conf-note">Confirm to start CheckoutWorkflow.</div>';
  }
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
    setBusy(true, approved ? 'running CheckoutWorkflow…' : 'cancelling…');
    await pollUntilSettled(baseline);
  } catch (e) {
    showError(e.message);
    card.querySelectorAll('button').forEach((b) => (b.disabled = false));
  }
}

// After an approval signal the turn resumes server-side; poll until a new
// assistant message lands (or another approval is requested).
async function pollUntilSettled(baselineAssistant) {
  for (let i = 0; i < 180; i++) {              // ~3 min — survive a full worker restart
    await new Promise((r) => setTimeout(r, 1000));
    let messages, pending;
    try {
      const [t, p] = await Promise.all([
        call('GET', `/conversations/${conversationId}/transcript`),
        call('GET', `/conversations/${conversationId}/pending-approval`),
      ]);
      messages = t.messages; pending = p.pending;
    } catch {
      continue;                               // workers still bouncing — keep the spinner, retry
    }
    if (pending) {
      renderTranscript(messages);
      setBusy(false);
      showApprovalCard(pending);
      return;
    }
    const assistants = messages.filter((m) => m.role === 'assistant');
    if (assistants.length > baselineAssistant) {
      // Append only the new reply — don't nuke+rebuild the transcript (that flashes
      // every bubble and yanks the scroll to the bottom).
      for (const m of assistants.slice(baselineAssistant)) addMsg('assistant', m.content);
      setBusy(false);
      refreshItinerary();
      return;
    }
  }
  setBusy(false);
  showError('The workers are taking a while to come back — refresh to pick up where it left off.');
}

// Resilient recovery: crashing the environment kills the worker pods (the app
// pod / this gateway stay up). While the workers bounce, the in-flight update
// can't be served and the query polls below error — but the message is a durable
// Update, so Temporal retries the turn on the fresh workers and it still completes.
// Poll until it settles (a turn ends by appending an assistant reply, so we're done
// when the last entry isn't the user's message), tolerating query failures while the
// workers are down. Spinner stays up; no refresh needed.
async function waitForReply() {
  for (let i = 0; i < 180; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    let messages, pending;
    try {
      const [t, p] = await Promise.all([
        call('GET', `/conversations/${conversationId}/transcript`),
        call('GET', `/conversations/${conversationId}/pending-approval`),
      ]);
      messages = t.messages; pending = p.pending;
    } catch {
      continue;                               // still bouncing — keep the spinner, retry
    }
    if (pending) { renderTranscript(messages); setBusy(false); showApprovalCard(pending); refreshItinerary(); return; }
    if (messages.length && messages[messages.length - 1].role === 'assistant') {
      renderTranscript(messages); setBusy(false); refreshItinerary(); return;
    }
  }
  setBusy(false);
  showError('The workers are taking a while to come back — refresh to pick up where it left off.');
}

// ── lazily start the workflow on the first message ──────────────────────────
// No sign-in step: the traveller identity comes from the auth gate (cloud) or a
// default (local), resolved server-side. First send creates the conversation.
function setConversation(id) {
  conversationId = id;
  try { convStore.setItem(CONV_KEY, id); } catch { /* private mode / disabled */ }
  // clickable workflow ID → opens this conversation's workflow in the Temporal UI
  const link = document.createElement('a');
  link.href = `${window.TEMPORAL_UI_BASE}/workflows/${encodeURIComponent(id)}`;
  link.target = '_blank';
  link.rel = 'noopener';
  link.innerHTML = '<span class="label">workflowId:&nbsp;</span>';
  link.append(id);
  $('conv-id').replaceChildren(link);
}

function clearConversation() {
  conversationId = null;
  try { convStore.removeItem(CONV_KEY); } catch { /* ignore */ }
  $('conv-id').replaceChildren();
}

async function ensureConversation() {
  if (conversationId) return;
  const { conversationId: id } = await call('POST', '/conversations', {});
  setConversation(id);
}

// ── send a message (blocks until the turn settles — see contract) ───────────
async function runTurn(text) {
  addMsg('user', text);
  setBusy(true);
  try {
    await ensureConversation();
    startStatusPolling();  // narrate research phases while the update is in flight
    let r;
    try {
      r = await call('POST', `/conversations/${conversationId}/messages`, { text });
    } catch (err) {
      stopStatusPolling();
      // Transient (no status = connection dropped, or 5xx = pods bouncing): the
      // message is durable, so keep the spinner and wait for the turn to finish
      // when the environment comes back — instead of erroring and forcing a refresh.
      if (!err.status || err.status >= 500) {
        setBusy(true, 'Reconnecting…');
        await waitForReply();
        return;
      }
      throw err;  // a real 4xx (e.g. booking declined) → surface it below
    }
    stopStatusPolling();
    setBusy(false);
    if (r.reply) addMsg('assistant', r.reply);  // research guides arrive here too
    if (r.status === 'awaiting_approval') {
      const { pending } = await call('GET', `/conversations/${conversationId}/pending-approval`);
      if (pending) showApprovalCard(pending);
    }
    refreshItinerary();
  } catch (err) {
    stopStatusPolling();
    setBusy(false);
    showError(err.message);
  }
}

// ── composer: auto-growing textarea; Enter sends, Shift+Enter = newline ───────
const inputEl = $('input');
function autoGrowInput() {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 168) + 'px';
}
inputEl.addEventListener('input', autoGrowInput);

function submitComposer() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  autoGrowInput();  // shrink back to a single line
  runTurn(text);
}

$('composer').onsubmit = (e) => { e.preventDefault(); submitComposer(); };
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submitComposer();
  }
});

// ── demo controls drawer — houses the LLM kill-switch for THIS conversation ──
// Provider/model come from config.js (the gateway's env); the outage flag is
// per-conversation, so flipping it only affects your own session.
let llmDown = false;

function openControls() {
  $('controls-panel').classList.add('open');
  $('controls-backdrop').classList.add('open');
  $('controls-toggle').setAttribute('aria-expanded', 'true');
  $('controls-panel').setAttribute('aria-hidden', 'false');
  refreshOutage();
}
function closeControls() {
  $('controls-panel').classList.remove('open');
  $('controls-backdrop').classList.remove('open');
  $('controls-toggle').setAttribute('aria-expanded', 'false');
  $('controls-panel').setAttribute('aria-hidden', 'true');
}
$('controls-toggle').onclick = () =>
  ($('controls-panel').classList.contains('open') ? closeControls() : openControls());
$('controls-close').onclick = closeControls;
$('controls-backdrop').onclick = closeControls;
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeControls(); });

function controlsMessage(text, isError) {
  const el = $('controls-message');
  el.textContent = text || '';
  el.classList.toggle('error', !!isError);
}

// Reflect outage state: switch "on" = operational; the pill's dot goes amber when down.
function setOutage(down) {
  llmDown = !!down;
  $('control-outage').checked = !llmDown;
  $('controls-toggle').querySelector('.status-dot').classList.toggle('injecting', llmDown);
}

async function refreshOutage() {
  if (!conversationId) return;
  try {
    const { down } = await call('GET', `/conversations/${conversationId}/llm-status`);
    setOutage(down);
  } catch { /* ignore transient errors */ }
}

$('control-outage').onchange = async (e) => {
  const down = !e.target.checked;  // switch OFF = outage on
  try {
    await ensureConversation();  // the switch is scoped to a conversation, so start one
    await call('POST', `/conversations/${conversationId}/llm-status`, { down });
    setOutage(down);
    controlsMessage(down ? 'Simulated outage on — LLM calls are retrying.' : 'Provider restored.');
  } catch (err) { controlsMessage(err.message, true); refreshOutage(); }
};

// labels + keep the toggle in sync while the drawer is open
$('as-provider').textContent =
  { anthropic: 'Anthropic API', openai: 'OpenAI API' }[window.LLM_PROVIDER] || 'LLM API';
$('as-model').textContent = window.LLM_MODEL || 'claude';

// ── runtime components: local shows the `make` commands; cloud swaps in the
// "Crash workers" / "Scale down workers" buttons that proxy to the
// crashable-workspace controller. ──
const isCloudHosted = (window.DEMO_HOSTING || 'local') === 'cloud';
const isCrashable = window.IS_CRASHABLE === true;
$('controls-local').hidden = isCloudHosted;
$('controls-cloud').hidden = !isCloudHosted;
if (isCloudHosted && window.CATALOG_PROVISION_URL) {
  const link = $('catalog-link');
  if (link) link.href = window.CATALOG_PROVISION_URL;
}

function setStatus(id, text, isError) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('error', !!isError);
}
const crashStatus = (text, isError) => setStatus('crash-worker-status', text, isError);
const scaleStatus = (text, isError) => setStatus('scale-worker-status', text, isError);

const crashBtn = $('control-crash-worker');
// Only a crashable clone can crash itself (an always-on cloud deploy can't).
// When it can't, disable the button and point at the catalog card below.
if (crashBtn && isCloudHosted && !isCrashable) {
  crashBtn.disabled = true;
  crashStatus('This is a shared instance — spin up your own ephemeral workspace below to crash workers.');
}
if (crashBtn && isCrashable) {
  crashBtn.onclick = async () => {
    crashBtn.disabled = true;
    crashStatus('Crashing worker pods…');
    try {
      const r = await call('POST', '/demo-controls/crash-worker');
      const where = r.host ? ` (${r.host})` : '';
      crashStatus(`Workers crashing${where} — Kubernetes restarts them and the workflow resumes on the exact next step.`);
    } catch (err) {
      crashStatus(err.message, true);
    } finally {
      crashBtn.disabled = false;
    }
  };
}

// Scale down workers: scales the deployment to 0 and leaves it there. Unlike
// Crash, there's no auto-recovery — workers return only when manually restored
// in the registry, so the status copy tells the operator that.
const scaleBtn = $('control-scale-workers');
if (scaleBtn && isCloudHosted && !isCrashable) {
  scaleBtn.disabled = true;
  scaleStatus('This is a shared instance — spin up your own ephemeral workspace below to scale workers.');
}
if (scaleBtn && isCrashable) {
  scaleBtn.onclick = async () => {
    scaleBtn.disabled = true;
    scaleStatus('Scaling workers to zero…');
    try {
      const r = await call('POST', '/demo-controls/scale-workers');
      const where = r.host ? ` (${r.host})` : '';
      scaleStatus(`Workers scaled to zero${where} — the workflow is paused and resumes once you restore workers in the registry.`);
    } catch (err) {
      scaleStatus(err.message, true);
    } finally {
      scaleBtn.disabled = false;
    }
  };
}

// ── New session: a refresh reattaches to the running workflow; this is the
// explicit "start clean" — end the current workflow and reset the UI to a fresh
// conversation. Sits next to the Demo-controls pill so it isn't tucked away. ──
function resetToFresh() {
  $('chat').querySelectorAll('.msg, .approval-card').forEach((el) => el.remove());
  assistantCount = 0;
  freshStart();                            // empty itinerary + greeting + focus
}

const newSessionBtn = $('new-session-top');
if (newSessionBtn) {
  newSessionBtn.onclick = async () => {
    if (!confirm('Start a new session? This ends the current workflow.')) return;
    newSessionBtn.disabled = true;
    try {
      // Best-effort cleanup: end the previous workflow before starting fresh.
      if (conversationId) await call('POST', `/conversations/${conversationId}/terminate`).catch(() => {});
      clearConversation();                 // forget the id → next send starts a fresh workflow
      resetToFresh();
      closeControls();                     // in case the drawer was open
    } catch (err) {
      showError(err.message);
    } finally {
      newSessionBtn.disabled = false;
    }
  };
}
setOutage(false);
setInterval(() => { if ($('controls-panel').classList.contains('open')) refreshOutage(); }, 5000);

// ── itinerary rail (left) — the Book button books the trip ───────────────────
$('itin-book').onclick = () => runTurn('I’d like to book this trip.');

// ── on load: reattach to a surviving workflow, else start fresh ──────────────
function freshStart() {
  renderItinerary([], 0);                       // empty itinerary rail — no conversation yet
  addMsg('assistant', GREETING, { counted: false });  // client greeting; not in the transcript
  $('input').focus();
}

// Try to reattach to a stored conversation. Returns true only if it's a live
// workflow whose durable state we replayed; false (and forgets the id) if it's
// gone. Transient errors keep the id so a later reload can retry.
async function rehydrate(id) {
  // Only reattach to a workflow that's still RUNNING. Crashable subdomains are
  // deterministic and reused across workspace incarnations, so a stored id can
  // point at a workflow a previous incarnation terminated — its transcript still
  // resolves within retention, but the next turn would 404. Check status first.
  let res;
  try {
    res = await fetch(API + `/conversations/${id}/status`);
  } catch {
    return false;                               // network blip — keep the id, retry next load
  }
  if (res.status === 404) { clearConversation(); return false; }  // never existed → forget it
  if (!res.ok) return false;                    // transient server error — keep the id
  const { running } = await res.json();
  if (!running) { clearConversation(); return false; }  // closed → don't reattach; start clean

  const tr = await fetch(API + `/conversations/${id}/transcript`);
  if (!tr.ok) { if (tr.status === 404) clearConversation(); return false; }
  const { messages } = await tr.json();

  setConversation(id);                          // re-adopt the id (and re-render the workflow link)
  renderTranscript(messages);                   // clears + replays the durable transcript
  if (!messages.length) addMsg('assistant', GREETING, { counted: false });

  // Restore the rest of the durable view (best-effort; a missing piece just no-ops).
  const [itin, pend, llm] = await Promise.all([
    call('GET', `/conversations/${id}/itinerary`).catch(() => null),
    call('GET', `/conversations/${id}/pending-approval`).catch(() => null),
    call('GET', `/conversations/${id}/llm-status`).catch(() => null),
  ]);
  renderItinerary(itin ? itin.items : [], itin ? itin.total : 0);
  if (llm) setOutage(llm.down);

  if (pend && pend.pending) {
    showApprovalCard(pend.pending);            // paused for approval — the card IS the state
  } else if (messages.length && messages[messages.length - 1].role === 'user') {
    // A turn was still running when we reattached: a turn only ends by appending
    // an assistant reply, so a trailing user message means the workflow — which
    // never stopped — is mid-turn. Resume the wait so the answer lands here.
    setBusy(true, 'the agent is still working…');
    pollUntilSettled(messages.filter((m) => m.role === 'assistant').length)
      .catch(() => setBusy(false));
  } else {
    $('input').focus();
  }
  return true;
}

async function boot() {
  let stored = null;
  try { stored = convStore.getItem(CONV_KEY); } catch { /* ignore */ }
  if (stored && await rehydrate(stored)) return;  // reattached to a live workflow
  freshStart();
}
boot();
