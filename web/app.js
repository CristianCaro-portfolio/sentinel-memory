// sentinel-memory analyst console
// Vanilla JS, no framework. Calls the FastAPI service mounted at the same origin.

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  analystId: "cristian",
  role: null,
  sessionId: null,
  prefs: {},
  alerts: [],
  selectedAlertId: null,
};

// ---------- API client ----------------------------------------------------

const API = "";

async function api(method, path, body) {
  const headers = { "X-Analyst-Id": state.analystId };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch (_) {}
    const err = new Error(`${res.status} ${detail}`);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------- toast ----------------------------------------------------------

let toastTimer = null;
function toast(msg, kind = "info") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4200);
}

// ---------- tabs -----------------------------------------------------------

function switchTab(name) {
  $$(".tab").forEach(b => b.classList.toggle("is-active", b.dataset.tab === name));
  $$("[data-panel]").forEach(p => p.classList.toggle("hidden", p.dataset.panel !== name));
  if (name === "alerts") loadAlerts();
  if (name === "audit") loadAudit();
  if (name === "prefs") loadPrefs();
}

$$(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

// ---------- identity / role -----------------------------------------------

async function refreshIdentity() {
  state.analystId = $("#analyst-id").value.trim() || "cristian";
  try {
    const r = await api("GET", `/analyst/${encodeURIComponent(state.analystId)}/preferences`);
    state.prefs = {};
    const list = Array.isArray(r.preferences) ? r.preferences : [];
    list.forEach(p => state.prefs[p.key] = p.value);
    state.role = (state.prefs.role) || "(no role in LTM)";
    $("#role-badge").textContent = String(state.role);
  } catch (e) {
    state.role = "?";
    $("#role-badge").textContent = "?";
    toast(`could not load preferences: ${e.message}`, "warn");
  }
}

$("#analyst-id").addEventListener("change", refreshIdentity);
$("#refresh-role").addEventListener("click", () => refreshIdentity().then(() => toast("identity refreshed", "success")));

// ---------- chat -----------------------------------------------------------

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function renderTurn(turn) {
  const thread = $("#chat-thread");
  const wrap = document.createElement("div");
  wrap.className = `turn ${turn.role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = turn.role === "user" ? "ME" : "AI";
  wrap.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = turn.content;
  wrap.appendChild(bubble);

  if (turn.role === "assistant" && turn.citations) {
    const cites = document.createElement("div");
    cites.className = "citations";
    const all = [
      ...(turn.citations.playbooks || []).map(c => ({ ...c, kind: "playbook_chunk", id: c.id || c.chunk_id, label: c.title })),
      ...(turn.citations.alerts    || []).map(c => ({ ...c, kind: "alert", id: c.id || c.alert_id, label: c.summary || c.raw_text })),
    ];
    for (const c of all) {
      const div = document.createElement("div");
      div.className = "citation";
      const finalScore = (c.final_score ?? c.distance);
      const n = c.n_ratings ?? 0;
      div.innerHTML = `
        <span class="cite-text" title="${escapeHtml(c.label)}">
          <strong>${c.kind === "playbook_chunk" ? "📘" : "🚨"}</strong>
          ${escapeHtml(c.label || c.id)}
        </span>
        <span class="cite-meta">score=${Number(finalScore).toFixed(3)} · n=${n}</span>
        <div class="actions">
          <button class="up"   title="+1">▲</button>
          <button class="down" title="−1">▼</button>
        </div>
      `;
      const [up, down] = div.querySelectorAll("button");
      up.onclick   = () => sendFeedback(c.kind, c.id, +1, turn.session_id, turn.turn_id);
      down.onclick = () => sendFeedback(c.kind, c.id, -1, turn.session_id, turn.turn_id);
      cites.appendChild(div);
    }
    if (all.length) bubble.appendChild(cites);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `latency ${turn.latency_ms ?? "?"} ms · session ${turn.session_id?.slice(0, 8) || ""}`;
    bubble.appendChild(meta);
  }

  thread.appendChild(wrap);
  thread.scrollTop = thread.scrollHeight;
}

async function sendChat(message) {
  if (!message) return;
  renderTurn({ role: "user", content: message });

  const payload = { analyst_id: state.analystId, message };
  if (state.sessionId) payload.session_id = state.sessionId;

  try {
    const t0 = performance.now();
    const r = await api("POST", "/chat", payload);
    const dt = Math.round(performance.now() - t0);
    state.sessionId = r.session_id;
    $("#chat-session").textContent = r.session_id.slice(0, 8);
    renderTurn({
      role: "assistant",
      content: r.reply,
      citations: r.citations,
      session_id: r.session_id,
      turn_id: r.turn_id,
      latency_ms: r.latency_ms ?? dt,
    });
  } catch (e) {
    renderTurn({ role: "assistant", content: `⚠ ${e.message}` });
    toast(e.message, "error");
  }
}

async function sendFeedback(kind, id, rating, sessionId, turnId) {
  try {
    await api("POST", "/feedback", {
      analyst_id: state.analystId,
      target_kind: kind,
      target_id: id,
      rating,
      session_id: sessionId,
      turn_id: turnId,
      note: "from analyst console",
    });
    toast(`feedback recorded (${rating > 0 ? "+1" : "-1"})`, "success");
  } catch (e) {
    toast(`feedback failed: ${e.message}`, "error");
  }
}

$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  sendChat(msg);
});

$("#chat-input").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    $("#chat-form").requestSubmit();
  }
});

$("#chat-new").addEventListener("click", () => {
  state.sessionId = null;
  $("#chat-session").textContent = "—";
  $("#chat-thread").innerHTML = "";
  toast("new session started", "success");
});

// ---------- search: playbooks ---------------------------------------------

$("#search-pb-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#search-pb-q").value.trim();
  if (!q) return;
  const limit = parseInt($("#search-pb-limit").value || "5", 10);
  await runPlaybookSearch(q, limit);
});

async function runPlaybookSearch(query, limit) {
  const container = $("#search-pb-results");
  container.innerHTML = `<p class="muted small">searching…</p>`;
  try {
    const r = await api("POST", "/search/playbooks", { query, limit });
    if (!r.results.length) {
      container.innerHTML = `<p class="muted small">no results.</p>`;
      return;
    }
    container.innerHTML = "";
    for (const row of r.results) {
      const el = renderResultRow({
        title: row.title,
        text:  row.content,
        meta:  `dist=${Number(row.distance).toFixed(3)} · final=${Number(row.final_score).toFixed(3)} · n=${row.n_ratings}`,
        onUp:   () => sendFeedback("playbook_chunk", row.chunk_id, +1),
        onDown: () => sendFeedback("playbook_chunk", row.chunk_id, -1, null, null).then(() => runPlaybookSearch(query, limit)),
      });
      container.appendChild(el);
    }
  } catch (e) {
    container.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

// ---------- search: alerts ------------------------------------------------

$("#search-al-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#search-al-q").value.trim();
  if (!q) return;
  const limit = parseInt($("#search-al-limit").value || "5", 10);
  const sevs = $$("#search-al-form input[type=checkbox]:checked").map(i => i.value);
  await runAlertSearch(q, sevs, limit);
});

async function runAlertSearch(query, severities, limit) {
  const container = $("#search-al-results");
  container.innerHTML = `<p class="muted small">searching…</p>`;
  try {
    const body = { query, limit };
    if (severities.length) body.severities = severities;
    const r = await api("POST", "/search/similar-incidents", body);
    if (!r.results.length) {
      container.innerHTML = `<p class="muted small">no results.</p>`;
      return;
    }
    container.innerHTML = "";
    for (const row of r.results) {
      const sev = sevBadge(row.severity);
      const el = renderResultRow({
        titleHtml: `${sev} <span class="muted small mono">${row.source_ip || "—"}</span>`,
        text:  row.raw_text,
        meta:  `dist=${Number(row.distance).toFixed(3)} · final=${Number(row.final_score).toFixed(3)} · n=${row.n_ratings}`,
        onUp:   () => sendFeedback("alert", row.alert_id, +1),
        onDown: () => sendFeedback("alert", row.alert_id, -1, null, null).then(() => runAlertSearch(query, severities, limit)),
      });
      container.appendChild(el);
    }
  } catch (e) {
    container.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

function sevBadge(sev) {
  return `<span class="sev sev-${escapeHtml(sev)}">${escapeHtml(sev)}</span>`;
}

function renderResultRow({ title, titleHtml, text, meta, onUp, onDown }) {
  const div = document.createElement("div");
  div.className = "row-item";
  div.innerHTML = `
    <div class="head">
      <div class="title">${titleHtml || escapeHtml(title || "")}</div>
      <div class="actions">
        <button class="up" title="+1">▲</button>
        <button class="down" title="−1">▼</button>
      </div>
    </div>
    <div class="text">${escapeHtml(text || "")}</div>
    <div class="meta">${escapeHtml(meta || "")}</div>
  `;
  const [up, down] = div.querySelectorAll("button");
  up.onclick = onUp;
  down.onclick = onDown;
  return div;
}

// ---------- alerts: list + timeline ---------------------------------------

async function loadAlerts() {
  const container = $("#alerts-list");
  container.innerHTML = `<p class="muted small">loading…</p>`;
  try {
    const r = await api("POST", "/search/similar-incidents", { query: "alert", limit: 50 });
    state.alerts = r.results;
    container.innerHTML = "";
    if (!r.results.length) {
      container.innerHTML = `<p class="muted small">no alerts.</p>`;
      return;
    }
    for (const a of r.results) {
      const div = document.createElement("div");
      div.className = "row-item";
      div.dataset.alertId = a.alert_id;
      div.innerHTML = `
        <div class="head">
          <div class="title">${sevBadge(a.severity)} <span class="muted small mono">${escapeHtml(a.source_ip || "—")}</span></div>
          <span class="meta">${escapeHtml(a.alert_id.slice(0, 8))}</span>
        </div>
        <div class="text">${escapeHtml(a.raw_text)}</div>
      `;
      div.addEventListener("click", () => selectAlert(a.alert_id));
      container.appendChild(div);
    }
  } catch (e) {
    container.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

async function selectAlert(alertId) {
  state.selectedAlertId = alertId;
  $$("#alerts-list .row-item").forEach(el => {
    el.classList.toggle("is-selected", el.dataset.alertId === alertId);
  });
  $("#alert-detail-id").textContent = alertId;
  const body = $("#alert-detail-body");
  body.innerHTML = `<p class="muted small">loading timeline…</p>`;
  try {
    const r = await api("GET", `/alerts/${alertId}/history`);
    const timeline = document.createElement("div");
    timeline.className = "timeline";
    const ordered = [...(r.history || [])].sort((a, b) =>
      (b.valid_from || "").localeCompare(a.valid_from || "")
    );
    if (!ordered.length) {
      body.innerHTML = `<p class="muted small">no history yet.</p>`;
      return;
    }
    for (const v of ordered) {
      const div = document.createElement("div");
      const src = v.source || v.source_table || "";
      div.className = `timeline-item${src === "current" ? " current" : ""}`;
      const validTo = v.valid_to ? new Date(v.valid_to).toISOString() : "now";
      div.innerHTML = `
        <div class="body">
          ${sevBadge(v.severity || "low")} <strong>${escapeHtml(v.status || "")}</strong>
        </div>
        <div class="meta">
          ${escapeHtml(src)} · ${escapeHtml(v.valid_from || "")} → ${escapeHtml(validTo)}
        </div>
      `;
      timeline.appendChild(div);
    }
    body.innerHTML = "";
    body.appendChild(timeline);
  } catch (e) {
    body.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

// ---------- new-alert modal -----------------------------------------------

$("#alert-new").addEventListener("click", () => $("#new-alert-dlg").showModal());
$("#new-alert-dlg [data-dlg-close]").addEventListener("click", () => $("#new-alert-dlg").close());
$("#new-alert-form").addEventListener("submit", async (e) => {
  const fd = new FormData(e.target);
  try {
    const a = await api("POST", "/alerts", {
      source_ip: fd.get("source_ip"),
      severity: fd.get("severity"),
      category: fd.get("category") || null,
      raw_text: fd.get("raw_text"),
    });
    $("#new-alert-dlg").close();
    toast(`alert created · ${a.alert_id.slice(0, 8)} (worker will embed it shortly)`, "success");
    setTimeout(loadAlerts, 1500);
  } catch (err) {
    toast(`create failed: ${err.message}`, "error");
  }
});

// ---------- audit ----------------------------------------------------------

async function loadAudit() {
  const container = $("#audit-table");
  container.innerHTML = `<p class="muted small">loading…</p>`;
  try {
    const r = await api("GET", "/audit?limit=50");
    container.innerHTML = "";
    const head = document.createElement("div");
    head.className = "audit-row head";
    head.innerHTML = `
      <span>time</span><span>principal</span><span>operation</span>
      <span>query</span><span class="lat">latency</span><span>ok</span>
    `;
    container.appendChild(head);
    for (const ev of (r.events || [])) {
      const row = document.createElement("div");
      row.className = "audit-row";
      const ids = (ev.retrieved_ids || []).length;
      const qtext = ev.query || ev.query_text || "";
      row.innerHTML = `
        <span data-label="time">${escapeHtml((ev.occurred_at || "").replace("T", " ").slice(0, 19))}</span>
        <span data-label="principal">${escapeHtml(ev.principal || "")}</span>
        <span data-label="op" class="op">${escapeHtml(ev.operation || "")}</span>
        <span data-label="query">${escapeHtml(qtext.slice(0, 80))} <span class="muted">· ${ids} ids</span></span>
        <span data-label="lat" class="lat">${ev.latency_ms ?? "—"} ms</span>
        <span data-label="ok" class="${ev.granted ? "granted-y" : "granted-n"}">${ev.granted ? "✓" : "✗"}</span>
      `;
      container.appendChild(row);
    }
  } catch (e) {
    container.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

$("#audit-refresh").addEventListener("click", loadAudit);

// ---------- preferences ---------------------------------------------------

async function loadPrefs() {
  const container = $("#prefs-list");
  container.innerHTML = `<p class="muted small">loading…</p>`;
  try {
    const r = await api("GET", `/analyst/${encodeURIComponent(state.analystId)}/preferences`);
    if (!r.preferences.length) {
      container.innerHTML = `<p class="muted small">no preferences yet.</p>`;
      return;
    }
    container.innerHTML = "";
    for (const p of r.preferences) {
      const div = document.createElement("div");
      div.className = "row-item";
      div.innerHTML = `
        <div class="head">
          <div class="title">${escapeHtml(p.key)}</div>
          <span class="meta">importance=${Number(p.importance).toFixed(2)}</span>
        </div>
        <div class="text mono small">${escapeHtml(JSON.stringify(p.value))}</div>
        <div class="meta">last touched ${escapeHtml(p.last_touched || "")}</div>
      `;
      container.appendChild(div);
    }
  } catch (e) {
    container.innerHTML = `<p class="muted small">error: ${escapeHtml(e.message)}</p>`;
  }
}

$("#prefs-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const key = $("#pref-key").value.trim();
  const rawValue = $("#pref-value").value.trim();
  const importance = parseFloat($("#pref-importance").value || "0.5");
  if (!key || !rawValue) {
    toast("key and value are required", "warn");
    return;
  }
  let value;
  try { value = JSON.parse(rawValue); }
  catch (_) { toast("value must be valid JSON", "error"); return; }
  try {
    await api("POST", `/analyst/${encodeURIComponent(state.analystId)}/preferences`, {
      key, value, importance,
    });
    toast(`saved ${key}`, "success");
    loadPrefs();
    refreshIdentity();
  } catch (err) {
    toast(`save failed: ${err.message}`, "error");
  }
});

// ---------- boot -----------------------------------------------------------

refreshIdentity();
