// static/js/hr/human.js
(() => {
  "use strict";

  /* =========================
     Configuration
     ========================= */
  const MAX_SESSIONS = 200;
  const SESSIONS_CHUNK = 20;
  const MSG_CHUNK = 10;
  const MAX_LOCAL_MSGS = 200;

  // ---- IMPORTANT: đúng prefix /api/history/hr/*
  const API = {
    chat: "/api/hr/chat",
    chatStream: "/api/hr/chat/stream",
    history: {
      newSession: "/api/history/hr/new_session",
      rename: "/api/history/hr/rename_session",
      delete: "/api/history/hr/delete_session",
      bySession: (id) =>
        `/api/history/hr/by_session?session_id=${encodeURIComponent(id)}`,
      sessions: (limit) =>
        `/api/history/hr/sessions?limit=${Number(limit) || 200}`,
      current: "/api/history/hr/current_session",
    },
  };

  /* =========================
     Element Detection
     ========================= */
  const els = {
    chatList: document.getElementById("chatList"),
    greeting: document.getElementById("greeting"),
    chatForm: document.getElementById("chatForm"),
    chatInput: document.getElementById("chatInput"),
    sendBtn: document.getElementById("sendBtn"),
    timingEl: document.getElementById("timing"),

    // History UI (panel hoặc sidebar)
    openBtn:
      document.getElementById("historyBtn") ||
      document.getElementById("historyToggle"),
    newBtn:
      document.getElementById("newChatBtn") ||
      document.getElementById("newSession") ||
      document.getElementById("newSessionTop"),
    overlay:
      document.getElementById("overlay") ||
      document.getElementById("sidebarOverlay"),
    panel:
      document.getElementById("historyPanel") ||
      document.getElementById("chatSidebar"),
    closeBtn:
      document.getElementById("closeHistory") ||
      document.getElementById("closeSidebar"),
    list:
      document.getElementById("historyList") ||
      document.getElementById("chatHistory") ||
      document.querySelector(
        ".history-list, [data-role='history-list'], .chat-list, [data-role='chat-history']"
      ),
    search: document.getElementById("searchInput"),
    scroll: document.getElementById("chatScroll"),
  };

  /* =========================
     Storage & Session Management
     ========================= */
  // ---- Namespace riêng cho HR để không va chạm với Chat chung
  const APP_SCOPE = "hr";
  const USER = (window.TXM_USER || "anonymous").trim();

  const SESS_KEY = `txm_${APP_SCOPE}_sessions_${USER}`;
  const MSG_KEY_PREFIX = `txm_${APP_SCOPE}_msgs_${USER}_`;
  const CURR_KEY = `txm_${APP_SCOPE}_current_session_${USER}`;
  const LSCHEMA_KEY = `txm_${APP_SCOPE}_schema_v_${USER}`;
  const LSCHEMA_VERSION = 3; // bump để migrate key cũ

  let currentSessionId = null;
  let renderCtrl = null;
  let sessionsCache = [];
  let sessionHistory = [];

  /* =========================
     Utilities
     ========================= */
  function nowTS() {
    return new Date().toISOString();
  }
  function genId() {
    return Math.random().toString(36).slice(2, 10);
  }
  function msgKey(id) {
    return MSG_KEY_PREFIX + id;
  }
  function htmlEscape(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }
  function _esc(s) {
    return String(s || "").replace(
      /[&<>]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])
    );
  }
  function lucideRefresh() {
    try {
      if (window.lucide) window.lucide.createIcons();
    } catch { }
  }
  function lockScroll(on) {
    document.body.style.overflow = on ? "hidden" : "";
  }
  function isSidebarMode() {
    return !!document.getElementById("chatSidebar");
  }
  function containerIsOpen() {
    const node = els.panel;
    if (!node) return false;
    return node.classList.contains(isSidebarMode() ? "active" : "open");
  }
  const useIdle = (cb, timeout = 500) =>
    window.requestIdleCallback
      ? requestIdleCallback(cb, { timeout })
      : setTimeout(cb, 0);

  function scrollToBottom(force = false) {
    const sc = els.scroll || document.getElementById("chatScroll");
    if (!sc) return;
    const threshold = 48;
    const atBottom =
      sc.scrollHeight - sc.scrollTop - sc.clientHeight <= threshold;
    if (force || atBottom) {
      sc.scrollTo({ top: sc.scrollHeight, behavior: "smooth" });
    }
  }

  /* =========================
     Local Storage helpers
     ========================= */
  function loadSessions() {
    try {
      return JSON.parse(localStorage.getItem(SESS_KEY) || "[]");
    } catch {
      return [];
    }
  }
  function saveSessions(list) {
    try {
      localStorage.setItem(SESS_KEY, JSON.stringify(list));
    } catch { }
  }
  function loadMsgs(id) {
    try {
      return JSON.parse(localStorage.getItem(msgKey(id)) || "[]");
    } catch {
      return [];
    }
  }
  function saveMsgs(id, msgs) {
    try {
      if (msgs.length > MAX_LOCAL_MSGS) msgs = msgs.slice(-MAX_LOCAL_MSGS);
      localStorage.setItem(msgKey(id), JSON.stringify(msgs));
    } catch { }
  }
  function anyLocalMessagesExist() {
    const sessions = loadSessions();
    for (const s of sessions) {
      const msgs = loadMsgs(s.id);
      if (msgs && msgs.length) return true;
    }
    return false;
  }
  function clearAllLocalForUser() {
    try {
      const keys = Object.keys(localStorage);
      keys.forEach((k) => {
        if (
          k === SESS_KEY ||
          k === CURR_KEY ||
          k.startsWith(MSG_KEY_PREFIX) ||
          k === LSCHEMA_KEY
        ) {
          localStorage.removeItem(k);
        }
      });
    } catch { }
  }
  function ensureLocalSchema() {
    const v = Number(localStorage.getItem(LSCHEMA_KEY) || 0);
    if (v < LSCHEMA_VERSION) {
      clearAllLocalForUser();
      localStorage.setItem(LSCHEMA_KEY, String(LSCHEMA_VERSION));
    }
  }
  function ensureLocalSessionEntry(id) {
    const sessions = loadSessions();
    if (!sessions.find((x) => x.id === id)) {
      sessions.unshift({
        id,
        name: "Cuộc trò chuyện HR",
        createdAt: nowTS(),
        updatedAt: nowTS(),
      });
      saveSessions(sessions);
      saveMsgs(id, []);
    }
  }

  /* =========================
     Session Management
     ========================= */
  function exposeCurrentSessionId() {
    try {
      window.currentSessionId = currentSessionId;
    } catch { }
  }
  function setSessionHistoryRef(arr) {
    sessionHistory = Array.isArray(arr) ? arr : [];
    try {
      window.sessionHistory = sessionHistory;
    } catch { }
  }

  function adoptServerSid(newSid) {
    if (!newSid) return;
    if (!currentSessionId) {
      currentSessionId = newSid;
      localStorage.setItem(CURR_KEY, newSid);
      ensureLocalSessionEntry(newSid);
      exposeCurrentSessionId();
      useIdle(markActiveSessionInList);
      return;
    }
    if (currentSessionId === newSid) return;
    currentSessionId = newSid;
    localStorage.setItem(CURR_KEY, newSid);
    ensureLocalSessionEntry(newSid);
    exposeCurrentSessionId();
    useIdle(markActiveSessionInList);
  }

  async function createServerSession(title) {
    const payload = title ? { title } : {};
    const res = await fetch(API.history.newSession, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data && data.session_id) {
      adoptServerSid(data.session_id);
      return data.session_id;
    }
    throw new Error("Không tạo được session_id từ server");
  }

  function ensureSession(createIfMissing = false) {
    if (currentSessionId) return currentSessionId;
    if (!createIfMissing) return null;
    const id = genId();
    const sessions = loadSessions();
    sessions.unshift({
      id,
      name: "Cuộc trò chuyện HR",
      createdAt: nowTS(),
      updatedAt: nowTS(),
    });
    saveSessions(sessions);
    localStorage.setItem(CURR_KEY, id);
    currentSessionId = id;
    exposeCurrentSessionId();
    saveMsgs(id, []);
    return id;
  }

  function setSessionTitleFromFirstUser(msg) {
    if (!currentSessionId) return;
    const sessions = loadSessions();
    const s = sessions.find((x) => x.id === currentSessionId);
    if (!s) return;
    if (s.name === "Cuộc trò chuyện HR") {
      s.name = (msg || "Untitled").slice(0, 30);
    }
    s.updatedAt = nowTS();
    saveSessions(sessions);
  }

  function persistMessage(role, content) {
    if (!content) return;
    if (!currentSessionId && role === "user") ensureSession(true);
    if (!currentSessionId) return;
    const msgs = loadMsgs(currentSessionId);
    const last = msgs[msgs.length - 1];
    if (last && last.role === role && last.content === content) return;
    msgs.push({ role, content, at: nowTS() });
    saveMsgs(currentSessionId, msgs);
    const sessions = loadSessions();
    const s = sessions.find((x) => x.id === currentSessionId);
    if (s) {
      s.updatedAt = nowTS();
      saveSessions(sessions);
    }
    if (containerIsOpen()) useIdle(startRenderSessions);
  }

  /* =========================
     TREE render helpers (giữ nguyên như bản của bạn)
     ========================= */
  const CONNECTED_DRAW_FROM_LEVEL = 2;
  const CONNECTED_KEEP_NUM = false;

  function _normSpaces(s) {
    return (s || "")
      .replace(/\uFEFF/g, "")
      .replace(
        /[\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000\u200B\u200C\u200D]/g,
        " "
      );
  }
  function _preTreeLine(s) {
    let t = _normSpaces(s).trimEnd();
    t = t.replace(/^\s*>+\s*/, "");
    t = t.replace(/^\s*(?:[*+-]\s+)/, "");
    t = t.replace(/^\s*(?:\*\*|__|\*|_)\s*/, "");
    t = t.replace(/\s*(?:\*\*|__|\*|_)\s*$/, "");
    return t;
  }
  const RX_TREE_LINE =
    /^\s*[│┃║ \t]*(?:[├┝┞┟┠┡┢┣└┕┖┗]\s*[─━┄┅┈┉]+\s*)?\s*\(?([0-9]+(?:\.[0-9]+)*)\)?(?:[.)-])?\s+(.*)$/;
  function _stripLeadingNumberToken(text) {
    return String(text || "").replace(/^\s*[0-9]+(?:\.[0-9]+)*\s+/, "");
  }
  function _parseTreeLine(raw) {
    const s = _preTreeLine(raw);
    if (!s.trim()) return { kind: "blank", raw: "" };
    const m = s.match(RX_TREE_LINE);
    if (!m) return { kind: "raw", raw: s };
    const token = (m[1] || "").trim();
    const label = (m[2] || "").trim();
    if (!label) return { kind: "raw", raw: s };
    const parts = token.split(".");
    const depth = parts.length;
    return {
      kind: "node",
      depth,
      parts,
      token,
      label,
      text: `${token} ${label}`,
    };
  }
  function _hasNextSibling(idx, items) {
    const curr = items[idx];
    const d = curr.depth;
    const parentKey = curr.parts.slice(0, d - 1).join(".");
    for (let j = idx + 1; j < items.length; j++) {
      const it = items[j];
      if (it.kind !== "node") continue;
      if (it.depth < d) return false;
      if (it.depth === d && it.parts.slice(0, d - 1).join(".") === parentKey)
        return true;
    }
    return false;
  }
  function _buildConnectedTree(items, opt = {}) {
    const keepNumbers = opt.keepNumbers ?? CONNECTED_KEEP_NUM;
    const boldUpTo = opt.boldUpTo ?? 2;
    const nodes = items.filter((x) => x.kind === "node");
    if (!nodes.length)
      return items.map((x) => (x.kind === "raw" ? _esc(x.raw) : "")).join("\n");
    const out = [];
    const open = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind !== "node") {
        out.push(it.kind === "blank" ? "" : _esc(it.raw));
        continue;
      }
      const d = it.depth;
      for (let k = open.length - 1; k > d; k--) open[k] = false;
      const last = !_hasNextSibling(i, items);
      const rawLabel = keepNumbers
        ? it.text || ""
        : _stripLeadingNumberToken(it.text || "");
      const labelHTML =
        d <= boldUpTo ? `<strong>${_esc(rawLabel)}</strong>` : _esc(rawLabel);
      if (d < CONNECTED_DRAW_FROM_LEVEL) {
        for (let k = open.length - 1; k >= CONNECTED_DRAW_FROM_LEVEL; k--)
          open[k] = false;
        out.push(labelHTML);
        continue;
      }
      let prefix = "";
      for (let k = CONNECTED_DRAW_FROM_LEVEL; k < d; k++) {
        prefix += open[k] ? "│  " : "   ";
      }
      prefix += last ? "└─ " : "├─ ";
      open[d] = !last;
      out.push(`${_esc(prefix)}${labelHTML}`);
    }
    return out.join("\n");
  }
  function _splitBlocks(md) {
    const lines = _normSpaces(md).replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
      if (/^\s*```tree\s*$/i.test(lines[i])) {
        const start = ++i;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) i++;
        const raw = lines.slice(start, i);
        const parsed = raw.map(_parseTreeLine);
        blocks.push({
          type: "tree",
          content: _buildConnectedTree(parsed, {
            keepNumbers: false,
            boldUpTo: 2,
          }),
        });
        if (i < lines.length && /^\s*```\s*$/.test(lines[i])) i++;
        continue;
      }
      const start = i;
      let cnt = 0;
      while (
        i < lines.length &&
        RX_TREE_LINE.test(_preTreeLine(lines[i]).trimEnd())
      ) {
        cnt++;
        i++;
      }
      if (cnt >= 2) {
        const rawBlock = lines.slice(start, i);
        const parsed = rawBlock.map(_parseTreeLine);
        blocks.push({
          type: "tree",
          content: _buildConnectedTree(parsed, {
            keepNumbers: false,
            boldUpTo: 2,
          }),
        });
        continue;
      }
      let j = i;
      const buf = [];
      while (j < lines.length) {
        if (/^\s*```tree\s*$/i.test(lines[j])) break;
        if (RX_TREE_LINE.test(_preTreeLine(lines[j]).trimEnd())) {
          let k = j,
            c = 0;
          while (
            k < lines.length &&
            RX_TREE_LINE.test(_preTreeLine(lines[k]).trimEnd())
          ) {
            c++;
            k++;
          }
          if (c >= 2) break;
        }
        buf.push(lines[j]);
        j++;
      }
      blocks.push({ type: "md", content: buf.join("\n") });
      i = j;
    }
    return blocks;
  }
  function _renderBlock(block) {
    if (block.type === "tree") {
      const pre = document.createElement("pre");
      pre.className = "txm-tree";
      pre.innerHTML = block.content;
      pre.dataset.isTree = "1";
      return pre;
    }
    const raw = (
      window.marked ? marked.parse(block.content || "") : block.content || ""
    ).toString();
    const clean = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
    const wrapper = document.createElement("div");
    wrapper.innerHTML = clean;
    const tables = wrapper.querySelectorAll("table");
    tables.forEach((t) => {
      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      t.parentNode.insertBefore(wrap, t);
      wrap.appendChild(t);
    });
    if (tables.length) wrapper.dataset.hasTable = "1";
    if (window.hljs) {
      wrapper.querySelectorAll("pre code").forEach((b) => {
        try {
          hljs.highlightElement(b);
        } catch { }
      });
    }
    return wrapper;
  }

  /* =========================
     Markdown Rendering
     ========================= */
  if (window.marked) {
    marked.setOptions({
      gfm: true,
      breaks: true,
      headerIds: false,
      mangle: false,
    });
  }
  function renderMarkdown(md) {
    const blocks = _splitBlocks(md || "");
    const host = document.createElement("div");
    let hasTable = false,
      hasTree = false;
    for (const b of blocks) {
      const node = _renderBlock(b);
      if (node.dataset?.hasTable === "1") hasTable = true;
      if (node.dataset?.isTree === "1") hasTree = true;
      host.appendChild(node);
    }
    if (hasTable) host.dataset.hasTable = "1";
    if (hasTree) host.dataset.isTree = "1";
    return host;
  }

  /* =========================
     Chat UI
     ========================= */
  function addMessage(role, content, opts = { persist: true }) {
    if (!content) return;
    if (els.greeting) els.greeting.style.display = "none";
    const li = document.createElement("li");
    li.className = "msg " + (role === "user" ? "user" : "assistant");
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    const node = renderMarkdown(content);
    if (node.dataset && node.dataset.hasTable === "1")
      bubble.classList.add("is-table");
    if (node.dataset && node.dataset.isTree === "1")
      bubble.classList.add("is-tree");
    bubble.appendChild(node);
    li.appendChild(bubble);
    if (els.chatList) {
      els.chatList.appendChild(li);
    }
    scrollToBottom(true);

    if (opts.persist) {
      sessionHistory.push({ role, content });
      persistMessage(role, content);
      try {
        window.sessionHistory = sessionHistory;
      } catch { }
    }
  }

  function addTyping() {
    if (!els.chatList) return;
    if (document.getElementById("typingRow")) return;

    const li = document.createElement("li");
    li.id = "typingRow";
    li.className = "msg assistant";
    li.innerHTML = `
    <div class="bubble" aria-live="polite" aria-label="Đang soạn">
      <span class="typing-neo">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </span>
    </div>`;
    els.chatList.appendChild(li);
    scrollToBottom(true);
  }

  function removeTyping() {
    const t = document.getElementById("typingRow");
    if (t) t.remove();
    scrollToBottom(true);
  }

  function resetUIToEmpty() {
    setSessionHistoryRef([]);
    if (els.chatList) els.chatList.innerHTML = "";
    if (els.greeting) els.greeting.style.display = "flex";
    if (els.timingEl) els.timingEl.textContent = "";
    scrollToBottom(true);
  }

  /* =========================
     History Container
     ========================= */
  function syncHistoryWidth() {
    if (!els.panel) return;
    const w = els.panel.getBoundingClientRect().width || 0;
    const effective = Math.min(w, 400);
    document.documentElement.style.setProperty("--history-w", effective + "px");
    const btnW =
      Math.max(
        (els.openBtn && els.openBtn.offsetWidth) || 0,
        (els.newBtn && els.newBtn.offsetWidth) || 0
      ) || 56;
    document.documentElement.style.setProperty("--float-btn-w", btnW + "px");
  }
  function openContainer() {
    if (!els.panel || !els.overlay) return;
    if (containerIsOpen()) return;
    els.panel.setAttribute("aria-hidden", "false");
    els.panel.classList.add(isSidebarMode() ? "active" : "open");
    els.overlay.classList.add(isSidebarMode() ? "active" : "open");
    document.body.classList.add("sidebar-open");
    syncHistoryWidth();
    window.addEventListener("resize", syncHistoryWidth, { passive: true });
    lockScroll(true);
    useIdle(startRenderSessions);
  }
  function closeContainer() {
    if (!els.panel || !els.overlay) return;
    els.panel.setAttribute("aria-hidden", "true");
    els.panel.classList.remove(isSidebarMode() ? "active" : "open");
    els.overlay.classList.remove(isSidebarMode() ? "active" : "open");
    document.body.classList.remove("sidebar-open");
    window.removeEventListener("resize", syncHistoryWidth);
    document.documentElement.style.setProperty("--history-w", "0px");
    lockScroll(false);
    cancelHistoryRender();
  }
  function cancelHistoryRender() {
    if (renderCtrl) {
      renderCtrl.abort();
      renderCtrl = null;
    }
  }

  /* =========================
     Data Sources
     ========================= */
  async function fetchSessionsServer() {
    try {
      const r = await fetch(API.history.sessions(MAX_SESSIONS));
      if (!r.ok) throw new Error("server off");
      const d = await r.json();
      const arr = (d.sessions || []).map((s) => ({
        id: s.id,
        title: s.title || "Cuộc trò chuyện HR",
        preview: s.preview || s.last_msg || "",
        last_ts: s.last_ts || s.first_ts || "",
      }));
      return arr;
    } catch {
      return null;
    }
  }
  function loadLocalSessionsUI() {
    try {
      return loadSessions().map((s) => ({
        id: s.id,
        title: s.name || "Cuộc trò chuyện HR",
        preview: s.preview || "",
        last_ts: s.updatedAt || s.createdAt || "",
      }));
    } catch {
      return [];
    }
  }
  async function getSessions() {
    const server = await fetchSessionsServer();
    if (server) return server;
    return loadLocalSessionsUI();
  }

  /* =========================
     History Rendering
     ========================= */
  async function startRenderSessions() {
    cancelHistoryRender();
    renderCtrl = new AbortController();
    try {
      const list = await getSessions();
      list.sort((a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0));
      sessionsCache = list.slice(0, MAX_SESSIONS);
      renderList(filterSessions(sessionsCache), renderCtrl.signal);
    } catch (e) {
      if (e?.name !== "AbortError") console.error("render sessions failed:", e);
    } finally {
      renderCtrl = null;
    }
  }
  function filterSessions(list) {
    const q = (els.search?.value || "").trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (s) =>
        (s.title || "").toLowerCase().includes(q) ||
        (s.preview || "").toLowerCase().includes(q)
    );
  }
  function renderList(list, signal) {
    const host = els.list;
    if (!host) return;
    host.innerHTML = "";
    let i = 0;
    (function pump() {
      if (signal?.aborted) return;
      const frag = document.createDocumentFragment();
      for (let n = 0; n < SESSIONS_CHUNK && i < list.length; n++, i++) {
        const s = list[i];
        frag.appendChild(renderItemNode(s));
      }
      host.appendChild(frag);
      if (i < list.length) {
        setTimeout(pump, 0);
      } else {
        lucideRefresh();
        markActiveSessionInList();
        scrollToBottom(false);
      }
    })();
  }
  function markActiveSessionInList() {
    if (!els.list) return;
    try {
      els.list
        .querySelectorAll(".chat-item.active, .hp-item.active")
        .forEach((n) => n.classList.remove("active"));
      if (!currentSessionId) return;
      const id =
        window.CSS && CSS.escape
          ? CSS.escape(String(currentSessionId))
          : String(currentSessionId);
      const node = els.list.querySelector(
        `.chat-item[data-id="${id}"], .hp-item[data-id="${id}"]`
      );
      if (node) {
        node.classList.add("active");
        node.scrollIntoView({ block: "nearest" });
      }
    } catch { }
  }
  function renderItemNode(s) {
    if (!isSidebarMode()) {
      const li = document.createElement("li");
      li.className = "hp-item";
      li.setAttribute("data-id", String(s.id));
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
        <div class="name">${htmlEscape(s.title || "Cuộc trò chuyện HR")}</div>
        <div class="meta">${s.last_ts ? new Date(s.last_ts).toLocaleString() : ""
        }</div>`;
      const acts = document.createElement("div");
      acts.className = "acts";
      acts.innerHTML = `
        <button class="icon-btn act-rename" title="Đổi tên"><i data-lucide="pencil"></i></button>
        <button class="icon-btn act-delete" title="Xóa"><i data-lucide="trash-2"></i></button>`;
      li.append(row, acts);
      li.addEventListener("click", (e) => {
        if (e.target.closest(".acts")) return;
        openSessionAndRender(s.id);
      });
      acts.querySelector(".act-rename").addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        inlineRename(s.id, s.title);
      });
      acts.querySelector(".act-delete").addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        onDelete(s.id);
      });
      return li;
    }

    const wrap = document.createElement("div");
    wrap.className = "chat-item p-3 p-md-4";
    wrap.setAttribute("data-id", String(s.id));
    wrap.innerHTML = `
      <div class="chat-content gap-2 gap-md-3">
        <div class="chat-avatar"><i data-lucide="user"></i></div>
        <div class="chat-text">
          <div class="chat-title">${htmlEscape(
      s.title || "Cuộc trò chuyện HR"
    )}</div>
          <div class="chat-preview">${htmlEscape(s.preview || "")}</div>
          <div class="chat-time">${formatTime(s.last_ts)}</div>
        </div>
      </div>
      <div class="chat-actions">
        <button class="action-btn" data-action="rename" title="Đổi tên"><i data-lucide="edit-3"></i></button>
        <button class="action-btn delete" data-action="delete" title="Xóa"><i data-lucide="trash-2"></i></button>
      </div>`;
    wrap.addEventListener("click", (e) => {
      if (e.target.closest(".chat-actions")) return;
      openSessionAndRender(s.id);
    });
    wrap
      .querySelector('[data-action="rename"]')
      .addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        inlineRename(s.id, s.title);
      });
    wrap
      .querySelector('[data-action="delete"]')
      .addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        onDelete(s.id);
      });
    return wrap;
  }
  function formatTime(ts) {
    if (!ts) return "";
    const date = new Date(ts);
    if (isNaN(+date)) return "";
    const now = new Date();
    const diff = now - date;
    const days = Math.floor(diff / 86400000);
    if (days === 0)
      return date.toLocaleTimeString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
      });
    if (days === 1) return "Hôm qua";
    if (days < 7) return `${days} ngày trước`;
    return date.toLocaleDateString("vi-VN");
  }

  /* =========================
     Session Actions
     ========================= */
  function inlineRename(id, currentTitle) {
    const newName = prompt(
      "Đặt tên đoạn chat:",
      currentTitle || "Cuộc trò chuyện HR"
    );
    if (!newName || !newName.trim()) return;
    commitRename(id, newName.trim());
  }
  async function commitRename(id, newTitle) {
    try {
      await fetch(API.history.rename, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, title: newTitle }),
      });
    } catch { }
    updateLocalSession(id, (s) => {
      s.name = newTitle;
    });
    await startRenderSessions();
  }
  async function onDelete(id) {
    if (!confirm("Bạn có chắc chắn muốn xóa cuộc trò chuyện này?")) return;
    let serverOk = false;
    try {
      const r = await fetch(API.history.delete, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id }),
      });
      const d = await r.json().catch(() => ({}));
      serverOk = r.ok && d.ok;
    } catch { }
    clearLocal(id);

    const deletingCurrent =
      currentSessionId && String(currentSessionId) === String(id);
    if (deletingCurrent) {
      let candidateId = null;
      try {
        const list = await getSessions();
        const filtered = (list || []).filter(
          (s) => String(s.id) !== String(id)
        );
        filtered.sort(
          (a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0)
        );
        if (filtered.length) candidateId = filtered[0].id;
      } catch { }
      localStorage.removeItem(CURR_KEY);
      currentSessionId = null;
      exposeCurrentSessionId();
      resetUIToEmpty();
      if (candidateId) {
        await openSessionAndRender(candidateId);
      } else {
        try {
          await createNewSession();
        } catch { }
      }
    }
    await startRenderSessions();
    if (!serverOk) console.warn("Server delete failed; cleared locally only.");
  }
  async function createNewSession() {
    try {
      await createServerSession("Cuộc trò chuyện HR");
      resetUIToEmpty();
      await startRenderSessions();
      closeContainer();
      return;
    } catch { }
    // fallback local only
    ensureSession(true);
    resetUIToEmpty();
    await startRenderSessions();
    closeContainer();
  }

  async function openSessionAndRender(sessionId) {
    if (!sessionId) return;
    try {
      const r = await fetch(API.history.bySession(sessionId));
      if (r.ok) {
        const data = await r.json();
        const items = data.items || [];
        if (els.chatList) els.chatList.innerHTML = "";
        if (els.greeting)
          els.greeting.style.display = items.length ? "none" : "flex";
        adoptServerSid(data.session_id || sessionId);
        items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
        setSessionHistoryRef(
          items.map(({ role, content }) => ({ role, content }))
        );
        if (currentSessionId) {
          const msgs = items.map((m) => ({
            role: m.role,
            content: m.content,
            at: m.ts || nowTS(),
          }));
          saveMsgs(currentSessionId, msgs);
          const firstUser = items.find((x) => x.role === "user");
          if (firstUser) setSessionTitleFromFirstUser(firstUser.content);
        }
        closeContainer();
        scrollToBottom(true);
        return;
      }
    } catch { }
    // fallback local
    openLocalSession(sessionId);
    closeContainer();
    scrollToBottom(true);
  }
  function openLocalSession(id) {
    try {
      const all = loadSessions();
      const s = all.find((x) => String(x.id) === String(id));
      if (s) {
        const msgs = loadMsgs(s.id);
        if (msgs.length) {
          if (els.chatList) els.chatList.innerHTML = "";
          if (els.greeting) els.greeting.style.display = "none";
          currentSessionId = id;
          localStorage.setItem(CURR_KEY, id);
          exposeCurrentSessionId();
          useIdle(markActiveSessionInList);
          msgs.forEach((m) =>
            addMessage(m.role, m.content, { persist: false })
          );
          setSessionHistoryRef(
            msgs.map((m) => ({ role: m.role, content: m.content }))
          );
          scrollToBottom(true);
        }
      }
    } catch { }
  }

  function updateLocalSession(id, mutator) {
    try {
      const arr = loadSessions();
      const idx = arr.findIndex((s) => String(s.id) === String(id));
      if (idx >= 0) {
        mutator(arr[idx]);
        saveSessions(arr);
      }
    } catch { }
  }
  function clearLocal(id) {
    try {
      const filtered = loadSessions().filter(
        (s) => String(s.id) !== String(id)
      );
      saveSessions(filtered);
    } catch { }
    try {
      localStorage.removeItem(MSG_KEY_PREFIX + id);
    } catch { }
  }

  /* =========================
     Server Communication
     ========================= */
  async function hydrateFromServer() {
    try {
      const res = await fetch(API.history.current, { method: "GET" });
      const data = await res.json();
      const items = data.items || [];
      const sid = data.session_id || null;

      if (!sid && !items.length && anyLocalMessagesExist()) {
        clearAllLocalForUser();
        if (els.chatList) els.chatList.innerHTML = "";
        if (els.greeting) els.greeting.style.display = "flex";
        currentSessionId = null;
        exposeCurrentSessionId();
        localStorage.removeItem(CURR_KEY);
        return;
      }

      if (sid) adoptServerSid(sid);

      if (els.chatList) els.chatList.innerHTML = "";
      if (els.greeting)
        els.greeting.style.display = items.length ? "none" : "flex";
      items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
      setSessionHistoryRef(
        items.map(({ role, content }) => ({ role, content }))
      );

      if (currentSessionId) {
        const msgs = items.map((m) => ({
          role: m.role,
          content: m.content,
          at: m.ts || nowTS(),
        }));
        saveMsgs(currentSessionId, msgs);
        const firstUser = items.find((x) => x.role === "user");
        if (firstUser) setSessionTitleFromFirstUser(firstUser.content);
      }
      scrollToBottom(true);
    } catch (e) {
      console.warn("hydrateFromServer() failed:", e);
    }
  }

  async function bootstrapFromLocalThenServer() {
    await hydrateFromServer();
    const hasUI =
      els.chatList && els.chatList.children && els.chatList.children.length > 0;
    if (!hasUI) {
      try {
        currentSessionId = localStorage.getItem(CURR_KEY) || null;
        exposeCurrentSessionId();
        if (currentSessionId && els.chatList) {
          const msgs = loadMsgs(currentSessionId);
          if (msgs.length) {
            if (els.greeting) els.greeting.style.display = "none";
            els.chatList.innerHTML = "";
            msgs.forEach((m) =>
              addMessage(m.role, m.content, { persist: false })
            );
            setSessionHistoryRef(
              msgs.map((m) => ({ role: m.role, content: m.content }))
            );
            scrollToBottom(true);
          }
        }
      } catch { }
    }
  }

  /* =========================
     Chat Form Handler
     ========================= */
  if (els.chatForm) {
    els.chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = (els.chatInput?.value || "").trim();
      if (!text) return;

      addMessage("user", text);
      scrollToBottom(true);

      els.chatInput.value = "";
      els.chatInput.style.height = "auto";

      if (els.sendBtn) els.sendBtn.disabled = true;
      addTyping();

      try {
        const res = await fetch(API.chat, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            session_id: currentSessionId || "",
          }),
        });
        const data = await res.json();
        if (data.session_id) adoptServerSid(data.session_id);

        removeTyping();
        if (els.sendBtn) els.sendBtn.disabled = false;

        if (!data.ok) {
          addMessage("assistant", `⚠️ Lỗi: ${data.error || "Không rõ"}`);
          return;
        }

        const answer = data.answer || "";
        addMessage("assistant", answer);
        scrollToBottom(true);

        if (data.timing && els.timingEl) {
          const t = data.timing;
          const total = Number(t.total ?? 0);
          const emb = Number(t.embedding ?? 0);
          const search = Number(t.search ?? 0);
          const llm = Number(t.llm ?? 0);
          els.timingEl.textContent = `Tổng: ${total.toFixed(
            2
          )}s | Embedding: ${emb.toFixed(2)}s | Tìm kiếm: ${search.toFixed(
            2
          )}s | LLM: ${llm.toFixed(2)}s`;
        }
      } catch (err) {
        removeTyping();
        if (els.sendBtn) els.sendBtn.disabled = false;
        addMessage("assistant", `❌ Lỗi kết nối: ${err}`);
        scrollToBottom(true);
      }
    });

    els.chatInput?.addEventListener("input", () => {
      els.chatInput.style.height = "auto";
      els.chatInput.style.height = els.chatInput.scrollHeight + "px";
    });

    els.chatInput?.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        els.chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    });

    els.chatForm.addEventListener(
      "submit",
      () => {
        const text = (els.chatInput?.value || "").trim();
        if (text) {
          if (!currentSessionId) ensureSession(true);
          setSessionTitleFromFirstUser(text);
        }
      },
      true
    );
  }

  /* =========================
     Events & Exports
     ========================= */
  if (els.openBtn)
    els.openBtn.addEventListener("click", () => {
      containerIsOpen() ? closeContainer() : openContainer();
    });
  if (els.overlay) els.overlay.addEventListener("click", closeContainer);
  if (els.closeBtn) els.closeBtn.addEventListener("click", closeContainer);
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeContainer();
  });
  if (els.search)
    els.search.addEventListener("input", () => {
      renderList(filterSessions(sessionsCache));
    });
  if (els.newBtn) els.newBtn.addEventListener("click", createNewSession);

  try {
    window.addMessage = addMessage;
    window.persistMessage = persistMessage;
    window.saveMsgs = saveMsgs;
    window.loadSessions = loadSessions;
    window.saveSessions = saveSessions;
    window.adoptServerSid = adoptServerSid;
    window.createServerSession = createServerSession;
    window.nowTS = nowTS;
    window.CURR_KEY = CURR_KEY;
    window.MSG_KEY_PREF = MSG_KEY_PREFIX;
    window.sessionHistory = sessionHistory;
    window.currentSessionId = currentSessionId;
    window.openSessionAndRender = openSessionAndRender;

    window.ChatPage = window.ChatPage || {};
    window.ChatPage.History = {
      open: openContainer,
      close: closeContainer,
      render: startRenderSessions,
      create: createNewSession,
    };
  } catch { }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) lucide.createIcons();
    ensureLocalSchema();
    try {
      currentSessionId = localStorage.getItem(CURR_KEY) || null;
      exposeCurrentSessionId();
    } catch { }
    bootstrapFromLocalThenServer();
    useIdle(startRenderSessions);
    scrollToBottom(true);
  });
})();
