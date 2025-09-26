// Complete Chat System - Fixed Session Management
(() => {
  "use strict";

  // =========================
  // Configuration
  // =========================
  const MAX_SESSIONS = 200;
  const SESSIONS_CHUNK = 20;
  const MSG_CHUNK = 10;
  const MAX_LOCAL_MSGS = 200;

  // =========================
  // Element Detection
  // =========================
  const els = {
    // Chat UI
    chatList: document.getElementById("chatList"),
    greeting: document.getElementById("greeting"),
    chatForm: document.getElementById("chatForm"),
    chatInput: document.getElementById("chatInput"),
    sendBtn: document.getElementById("sendBtn"),
    timingEl: document.getElementById("timing"),

    // History UI (auto-detect both panel and sidebar styles)
    openBtn: document.getElementById("historyBtn") || document.getElementById("historyToggle"),
    newBtn: document.getElementById("newChatBtn") || document.getElementById("newSession") || document.getElementById("newSessionTop"),
    overlay: document.getElementById("overlay") || document.getElementById("sidebarOverlay"),
    panel: document.getElementById("historyPanel") || document.getElementById("chatSidebar"),
    closeBtn: document.getElementById("closeHistory") || document.getElementById("closeSidebar"),
    list: document.getElementById("historyList") || document.getElementById("chatHistory") ||
      document.querySelector(".history-list, [data-role='history-list'], .chat-list, [data-role='chat-history']"),
    search: document.getElementById("searchInput")
  };

  // =========================
  // Storage & Session Management
  // =========================
  let sessionHistory = [];
  const USER = (window.TXM_USER || "anonymous").trim();
  const SESS_KEY = `txm_sessions_${USER}`;
  const MSG_KEY_PREFIX = `txm_msgs_${USER}_`;
  const CURR_KEY = `txm_current_session_${USER}`;
  const LSCHEMA_KEY = `txm_schema_v_${USER}`;
  const LSCHEMA_VERSION = 2;

  let currentSessionId = null;
  let renderCtrl = null;
  let sessionsCache = [];

  // =========================
  // Utility Functions
  // =========================
  function nowTS() { return new Date().toISOString(); }
  function genId() { return Math.random().toString(36).slice(2, 10); }
  function msgKey(id) { return MSG_KEY_PREFIX + id; }

  function htmlEscape(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function lucideRefresh() {
    try { if (window.lucide) window.lucide.createIcons(); } catch { }
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
    (window.requestIdleCallback ? requestIdleCallback(cb, { timeout }) : setTimeout(cb, 0));

  // =========================
  // Local Storage Functions
  // =========================
  function loadSessions() {
    try { return JSON.parse(localStorage.getItem(SESS_KEY) || "[]"); }
    catch (_) { return []; }
  }

  function saveSessions(list) {
    try { localStorage.setItem(SESS_KEY, JSON.stringify(list)); }
    catch (_) { }
  }

  function loadMsgs(id) {
    try { return JSON.parse(localStorage.getItem(msgKey(id)) || "[]"); }
    catch (_) { return []; }
  }

  function saveMsgs(id, msgs) {
    try {
      if (msgs.length > MAX_LOCAL_MSGS) msgs = msgs.slice(-MAX_LOCAL_MSGS);
      localStorage.setItem(msgKey(id), JSON.stringify(msgs));
    } catch (_) { }
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
        if (k === SESS_KEY || k === CURR_KEY || k.startsWith(MSG_KEY_PREFIX)) {
          localStorage.removeItem(k);
        }
      });
    } catch (_) { }
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
        id, name: "Cuộc trò chuyện mới",
        createdAt: nowTS(), updatedAt: nowTS(),
      });
      saveSessions(sessions);
      saveMsgs(id, []);
    }
  }

  // =========================
  // Session Management Functions
  // =========================
  function exposeCurrentSessionId() {
    try { window.currentSessionId = currentSessionId; } catch (_) { }
  }

  function setSessionHistoryRef(arr) {
    sessionHistory = Array.isArray(arr) ? arr : [];
    try { window.sessionHistory = sessionHistory; } catch (_) { }
  }

  // FIXED: Proper session adoption without message merging
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

    // FIXED: Don't merge sessions - just switch
    currentSessionId = newSid;
    localStorage.setItem(CURR_KEY, newSid);
    ensureLocalSessionEntry(newSid);
    exposeCurrentSessionId();
    useIdle(markActiveSessionInList);
  }

  async function createServerSession(title) {
    try {
      const res = await fetch("/api/history/new_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(title ? { title } : {}),
      });
      const data = await res.json();
      if (data && data.session_id) {
        adoptServerSid(data.session_id);
        return data.session_id;
      }
    } catch (e) {
      console.warn("Server session creation failed:", e);
    }
    throw new Error("Không tạo được session_id từ server");
  }

  function ensureSession(createIfMissing = false) {
    if (currentSessionId) return currentSessionId;
    if (!createIfMissing) return null;
    const id = genId();
    const sessions = loadSessions();
    sessions.unshift({
      id, name: "Cuộc trò chuyện mới",
      createdAt: nowTS(), updatedAt: nowTS(),
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
    if (s.name === "Cuộc trò chuyện mới") {
      s.name = (msg || "Untitled").slice(0, 30);
    }
    s.updatedAt = nowTS();
    saveSessions(sessions);
  }

  // FIXED: Proper message persistence with session isolation
  function persistMessage(role, content) {
    if (!content) return;

    if (!currentSessionId && role === "user") {
      ensureSession(true);
    }

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

    if (containerIsOpen()) {
      useIdle(startRenderSessions);
    }
  }

  // =========================
  // Markdown Rendering
  // =========================
  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
  }

  function renderMarkdown(md) {
    const raw = (window.marked ? marked.parse(md || "") : md || "").toString();
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
    wrapper.dataset.hasTable = tables.length ? "1" : "0";

    if (window.hljs) {
      wrapper.querySelectorAll("pre code").forEach((block) => {
        try { hljs.highlightElement(block); } catch (_) { }
      });
    }
    return wrapper;
  }

  // =========================
  // Chat UI Functions
  // =========================
  function addMessage(role, content, opts = { persist: true }) {
    if (!content) return;
    if (els.greeting) els.greeting.style.display = "none";

    const li = document.createElement("li");
    li.className = "msg " + (role === "user" ? "user" : "assistant");

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const node = renderMarkdown(content);
    if (node.dataset.hasTable === "1") bubble.classList.add("is-table");
    bubble.appendChild(node);

    li.appendChild(bubble);
    if (els.chatList) {
      els.chatList.appendChild(li);
      els.chatList.scrollTop = els.chatList.scrollHeight;
    }

    if (opts.persist) {
      sessionHistory.push({ role, content });
      persistMessage(role, content);
      try { window.sessionHistory = sessionHistory; } catch (_) { }
    }
  }

  function addTyping() {
    if (!els.chatList) return;
    const li = document.createElement("li");
    li.id = "typingRow";
    li.className = "msg assistant";
    li.innerHTML = `<div class="bubble"><span class="dots">Vui lòng chờ...</span></div>`;
    els.chatList.appendChild(li);
    els.chatList.scrollTop = els.chatList.scrollHeight;
  }

  function removeTyping() {
    const t = document.getElementById("typingRow");
    if (t) t.remove();
  }

  function resetUIToEmpty() {
    setSessionHistoryRef([]);
    if (els.chatList) els.chatList.innerHTML = "";
    if (els.greeting) els.greeting.style.display = "flex";
    if (els.timingEl) els.timingEl.textContent = "";
  }

  // =========================
  // History Container Functions
  // =========================
  function syncHistoryWidth() {
    if (!els.panel) return;
    const w = els.panel.getBoundingClientRect().width || 0;
    const effective = Math.min(w, 400);
    document.documentElement.style.setProperty('--history-w', effective + 'px');

    const btnW = Math.max(
      (els.openBtn && els.openBtn.offsetWidth) || 0,
      (els.newBtn && els.newBtn.offsetWidth) || 0
    ) || 56;
    document.documentElement.style.setProperty('--float-btn-w', btnW + 'px');
  }

  function openContainer() {
    if (!els.panel || !els.overlay) return;
    if (containerIsOpen()) return;
    els.panel.setAttribute("aria-hidden", "false");
    els.panel.classList.add(isSidebarMode() ? "active" : "open");
    els.overlay.classList.add(isSidebarMode() ? "active" : "open");

    document.body.classList.add('sidebar-open');
    syncHistoryWidth();
    window.addEventListener('resize', syncHistoryWidth, { passive: true });

    lockScroll(true);
    useIdle(startRenderSessions);
  }

  function closeContainer() {
    if (!els.panel || !els.overlay) return;
    els.panel.setAttribute("aria-hidden", "true");
    els.panel.classList.remove(isSidebarMode() ? "active" : "open");
    els.overlay.classList.remove(isSidebarMode() ? "active" : "open");

    document.body.classList.remove('sidebar-open');
    window.removeEventListener('resize', syncHistoryWidth);
    document.documentElement.style.setProperty('--history-w', '0px');

    lockScroll(false);
    cancelHistoryRender();
  }

  function cancelHistoryRender() {
    if (renderCtrl) { renderCtrl.abort(); renderCtrl = null; }
  }

  // =========================
  // Data Sources (Server + Local)
  // =========================
  async function fetchSessionsServer() {
    try {
      const r = await fetch(`/api/history/sessions?limit=${MAX_SESSIONS}`);
      if (!r.ok) throw new Error("server off");
      const d = await r.json();
      const arr = (d.sessions || []).map((s) => ({
        id: s.id,
        title: s.title || "Cuộc trò chuyện",
        preview: s.preview || s.last_msg || "",
        last_ts: s.last_ts || s.first_ts || "",
      }));
      return arr;
    } catch { return null; }
  }

  function loadLocalSessions() {
    try {
      return loadSessions().map((s) => ({
        id: s.id,
        title: s.name || "Cuộc trò chuyện",
        preview: s.preview || "",
        last_ts: s.updatedAt || s.createdAt || "",
      }));
    } catch { return []; }
  }

  async function getSessions() {
    const server = await fetchSessionsServer();
    if (server) return server;
    return loadLocalSessions();
  }

  // =========================
  // History Rendering
  // =========================
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

    const start = performance.now();
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
        const took = Math.round(performance.now() - start);
        console.debug(`[history] rendered ${list.length} items in ~${took}ms`);
      }
    })();
  }
  function markActiveSessionInList() {
    if (!els.list) return;
    try {
      // gỡ cờ cũ
      els.list.querySelectorAll('.chat-item.active, .hp-item.active')
        .forEach(n => n.classList.remove('active'));

      if (!currentSessionId) return;
      const id = (window.CSS && CSS.escape) ? CSS.escape(String(currentSessionId)) : String(currentSessionId);

      // tìm item theo data-id
      const node = els.list.querySelector(`.chat-item[data-id="${id}"], .hp-item[data-id="${id}"]`);
      if (node) {
        node.classList.add('active');
        node.scrollIntoView({ block: 'nearest' });
      }
    } catch (_) { }
  }

  function renderItemNode(s) {
    if (!isSidebarMode()) {
      // Panel item
      const li = document.createElement("li");
      li.className = "hp-item";
      li.setAttribute("data-id", String(s.id));
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
          <div class="name">${htmlEscape(s.title || "Cuộc trò chuyện")}</div>
          <div class="meta">${s.last_ts ? new Date(s.last_ts).toLocaleString() : ""}</div>`;
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
        e.preventDefault(); e.stopPropagation();
        inlineRename(s.id, s.title);
      });
      acts.querySelector(".act-delete").addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        onDelete(s.id);
      });
      return li;
    }

    // Sidebar item
    const wrap = document.createElement("div");
    wrap.className = "chat-item p-3 p-md-4";
    wrap.setAttribute("data-id", String(s.id));
    wrap.innerHTML = `
        <div class="chat-content gap-2 gap-md-3">
          <div class="chat-avatar"><i data-lucide="user"></i></div>
          <div class="chat-text">
            <div class="chat-title">${htmlEscape(s.title || "Cuộc trò chuyện")}</div>
            <div class="chat-preview">${htmlEscape(s.preview || "")}</div>
            <div class="chat-time">${formatTime(s.last_ts)}</div>
          </div>
        </div>
        <div class="chat-actions">
          <button class="action-btn" data-action="rename" title="Đổi tên"><i data-lucide="edit-3"></i></button>
          <button class="action-btn delete" data-action="delete" title="Xóa"><i data-lucide="trash-2"></i></button>
        </div>
      `;
    wrap.addEventListener("click", (e) => {
      if (e.target.closest(".chat-actions")) return;
      openSessionAndRender(s.id);
    });
    wrap.querySelector('[data-action="rename"]').addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      inlineRename(s.id, s.title);
    });
    wrap.querySelector('[data-action="delete"]').addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
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
    if (days === 0) return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    if (days === 1) return "Hôm qua";
    if (days < 7) return `${days} ngày trước`;
    return date.toLocaleDateString("vi-VN");
  }

  // =========================
  // Session Actions
  // =========================
  function inlineRename(id, currentTitle) {
    const newName = prompt("Đặt tên đoạn chat:", currentTitle || "Cuộc trò chuyện");
    if (!newName || !newName.trim()) return;
    commitRename(id, newName.trim());
  }

  async function commitRename(id, newTitle) {
    try {
      await fetch("/api/history/rename_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, title: newTitle })
      });
    } catch { }

    // Update local mirrors
    updateLocalSession(id, (s) => { s.name = newTitle; });
    await startRenderSessions();
  }

  async function onDelete(id) {
    if (!confirm("Bạn có chắc chắn muốn xóa cuộc trò chuyện này?")) return;

    // 1) Gọi server xóa (nếu có)
    let serverOk = false;
    try {
      const r = await fetch("/api/history/delete_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id })
      });
      const d = await r.json().catch(() => ({}));
      serverOk = r.ok && d.ok;
    } catch { /* bỏ qua */ }

    // 2) Xóa bản local (session list + messages)
    clearLocal(id);

    // 3) Nếu đang xóa CHÍNH phiên làm việc hiện tại → chọn phiên gần nhất và chuyển sang
    const deletingCurrent = currentSessionId && String(currentSessionId) === String(id);
    if (deletingCurrent) {
      // Lấy danh sách còn lại (ưu tiên server, fallback local), loại id vừa xóa
      let candidateId = null;
      try {
        const list = await getSessions(); // {id, title, preview, last_ts}
        const filtered = (list || []).filter(s => String(s.id) !== String(id));
        // Sắp theo thời gian giảm dần và chọn cái "gần nhất" (mới nhất còn lại)
        filtered.sort((a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0));
        if (filtered.length) candidateId = filtered[0].id;
      } catch { /* bỏ qua */ }

      // Reset trạng thái current trước khi chuyển
      localStorage.removeItem(CURR_KEY);
      currentSessionId = null;
      exposeCurrentSessionId();

      // Làm sạch UI hiện tại
      resetUIToEmpty();

      if (candidateId) {
        // Mở phiên gần nhất còn lại
        await openSessionAndRender(candidateId);
      } else {
        // Không còn phiên nào -> tạo phiên mới
        try { await createNewSession(); } catch { }
      }
    }

    // 4) Cập nhật lại list ở thanh lịch sử
    await startRenderSessions();

    if (!serverOk) console.warn("Server delete failed; cleared locally only.");
  }


  async function createNewSession() {
    // Try server first
    try {
      const res = await createServerSession("Cuộc trò chuyện mới");
      resetUIToEmpty();
      await startRenderSessions();
      closeContainer();
      return;
    } catch { }

    // Try API directly
    try {
      const r = await fetch("/api/history/new_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "Cuộc trò chuyện" })
      });
      if (r.ok) {
        const d = await r.json();
        const sid = d?.session_id || d?.id;
        if (sid) {
          adoptServerSid(sid);
          resetUIToEmpty();
          await startRenderSessions();
          closeContainer();
          return;
        }
      }
    } catch { }

    // Local fallback
    ensureSession(true);
    resetUIToEmpty();
    await startRenderSessions();
    closeContainer();
  }

  // FIXED: Open session with proper session switching
  async function openSessionAndRender(sessionId) {
    if (!sessionId) return;

    try {
      const r = await fetch(`/api/history/by_session?session_id=${encodeURIComponent(sessionId)}`);
      if (r.ok) {
        const data = await r.json();
        const items = data.items || [];

        // Clean session switch
        if (els.chatList) els.chatList.innerHTML = "";
        if (els.greeting) els.greeting.style.display = items.length ? "none" : "flex";

        // Set new current session
        adoptServerSid(data.session_id || sessionId);

        // Load messages for this session only
        items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
        setSessionHistoryRef(items.map(({ role, content }) => ({ role, content })));

        // Save to local storage
        if (currentSessionId) {
          const msgs = items.map((m) => ({
            role: m.role,
            content: m.content,
            at: m.ts || nowTS()
          }));
          saveMsgs(currentSessionId, msgs);

          const firstUser = items.find((x) => x.role === "user");
          if (firstUser) setSessionTitleFromFirstUser(firstUser.content);
        }

        closeContainer();
        return;
      }
    } catch { }

    // Local fallback
    openLocalSession(sessionId);
    closeContainer();
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
          msgs.forEach((m) => addMessage(m.role, m.content, { persist: false }));
          setSessionHistoryRef(msgs.map(m => ({ role: m.role, content: m.content })));
        }
      }
    } catch { }
  }



  // =========================
  // Local Storage Helpers
  // =========================
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
      const filtered = loadSessions().filter((s) => String(s.id) !== String(id));
      saveSessions(filtered);
    } catch { }
    try {
      localStorage.removeItem(MSG_KEY_PREFIX + id);
    } catch { }
  }

  // =========================
  // Server Communication
  // =========================
  // FIXED: Get current session specifically
  async function hydrateFromServer() {
    try {
      const res = await fetch(`/api/history/current_session`, { method: "GET" });
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
      if (els.greeting) els.greeting.style.display = items.length ? "none" : "flex";

      items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
      setSessionHistoryRef(items.map(({ role, content }) => ({ role, content })));

      if (currentSessionId) {
        const msgs = items.map((m) => ({
          role: m.role,
          content: m.content,
          at: m.ts || nowTS()
        }));
        saveMsgs(currentSessionId, msgs);

        const firstUser = items.find((x) => x.role === "user");
        if (firstUser) setSessionTitleFromFirstUser(firstUser.content);
      }
    } catch (e) {
      console.warn("hydrateFromServer() failed:", e);
    }
  }

  async function bootstrapFromLocalThenServer() {
    await hydrateFromServer();

    const hasUI = els.chatList && els.chatList.children && els.chatList.children.length > 0;
    if (!hasUI) {
      try {
        currentSessionId = localStorage.getItem(CURR_KEY) || null;
        exposeCurrentSessionId();
        if (currentSessionId && els.chatList) {
          const msgs = loadMsgs(currentSessionId);
          if (msgs.length) {
            if (els.greeting) els.greeting.style.display = "none";
            els.chatList.innerHTML = "";
            msgs.forEach((m) => addMessage(m.role, m.content, { persist: false }));
            setSessionHistoryRef(msgs.map((m) => ({ role: m.role, content: m.content })));
          }
        }
      } catch (_) { }
    }
  }

  // =========================
  // Chat Form Handler
  // =========================
  if (els.chatForm) {
    els.chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = (els.chatInput?.value || "").trim();
      if (!text) return;

      addMessage("user", text);
      els.chatInput.value = "";
      els.chatInput.style.height = "auto";

      if (els.sendBtn) els.sendBtn.disabled = true;
      addTyping();

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: currentSessionId || "" }),
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

        if (data.timing && els.timingEl) {
          const t = data.timing;
          const total = Number(t.total ?? 0);
          const emb = Number(t.embedding ?? 0);
          const search = Number(t.search ?? 0);
          const llm = Number(t.llm ?? 0);
          els.timingEl.textContent =
            `Tổng: ${total.toFixed(2)}s | Embedding: ${emb.toFixed(2)}s | ` +
            `Tìm kiếm: ${search.toFixed(2)}s | LLM: ${llm.toFixed(2)}s`;
        }
      } catch (err) {
        removeTyping();
        if (els.sendBtn) els.sendBtn.disabled = false;
        addMessage("assistant", `❌ Lỗi kết nối: ${err}`);
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

    // Set session title from first user message
    els.chatForm.addEventListener("submit", () => {
      const text = (els.chatInput?.value || "").trim();
      if (text) {
        if (!currentSessionId) ensureSession(true);
        setSessionTitleFromFirstUser(text);
      }
    }, true);
  }

  // =========================
  // Event Listeners
  // =========================
  // History panel toggle
  if (els.openBtn) {
    els.openBtn.addEventListener("click", () => {
      containerIsOpen() ? closeContainer() : openContainer();
    });
  }

  // Close handlers
  if (els.overlay) els.overlay.addEventListener("click", closeContainer);
  if (els.closeBtn) els.closeBtn.addEventListener("click", closeContainer);
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeContainer();
  });

  // Search filter
  if (els.search) {
    els.search.addEventListener("input", () => {
      renderList(filterSessions(sessionsCache));
    });
  }

  // New session button
  if (els.newBtn) els.newBtn.addEventListener("click", createNewSession);

  // =========================
  // Global Exports
  // =========================
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

    // Public API for external access
    window.ChatPage = window.ChatPage || {};
    window.ChatPage.History = {
      open: openContainer,
      close: closeContainer,
      render: startRenderSessions,
      create: createNewSession,
    };
  } catch (_) { }

  // =========================
  // Initialization
  // =========================
  document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) lucide.createIcons();
    ensureLocalSchema();

    // Load current session from localStorage if exists
    try {
      currentSessionId = localStorage.getItem(CURR_KEY) || null;
      exposeCurrentSessionId();
    } catch (_) { }

    // Bootstrap from server, fallback to local
    bootstrapFromLocalThenServer();

    // Auto-render history if container is visible
    useIdle(startRenderSessions);
  });

})();