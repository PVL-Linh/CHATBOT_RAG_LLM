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
    scroll: document.getElementById("chatScroll"),

    // History UI (auto-detect both panel and sidebar styles)
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
  function scrollToBottom(force = false) {
    const sc = els.scroll || document.getElementById("chatScroll");
    if (!sc) return;
    const threshold = 48; // px: coi như đã ở gần đáy
    const atBottom =
      sc.scrollHeight - sc.scrollTop - sc.clientHeight <= threshold;
    if (force || atBottom) {
      sc.scrollTo({ top: sc.scrollHeight, behavior: "smooth" });
    }
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

  // =========================
  // Local Storage Functions
  // =========================
  function loadSessions() {
    try {
      return JSON.parse(localStorage.getItem(SESS_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function saveSessions(list) {
    try {
      localStorage.setItem(SESS_KEY, JSON.stringify(list));
    } catch (_) { }
  }

  function loadMsgs(id) {
    try {
      return JSON.parse(localStorage.getItem(msgKey(id)) || "[]");
    } catch (_) {
      return [];
    }
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
        id,
        name: "Cuộc trò chuyện mới",
        createdAt: nowTS(),
        updatedAt: nowTS(),
      });
      saveSessions(sessions);
      saveMsgs(id, []);
    }
  }

  // =========================
  // Session Management Functions
  // =========================
  function exposeCurrentSessionId() {
    try {
      window.currentSessionId = currentSessionId;
    } catch (_) { }
  }

  function setSessionHistoryRef(arr) {
    sessionHistory = Array.isArray(arr) ? arr : [];
    try {
      window.sessionHistory = sessionHistory;
    } catch (_) { }
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
      id,
      name: "Cuộc trò chuyện mới",
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
    marked.setOptions({
      gfm: true,
      breaks: true,
      headerIds: false,
      mangle: false,
    });
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
        try {
          hljs.highlightElement(block);
        } catch (_) { }
      });
    }
    return wrapper;
  }

  // =========================
  // Chat UI Functions
  // =========================
  let currentTypingController = null;

  function addMessage(role, content, opts = {}) {
    const { persist = true, isNew = false, files = null } = opts;
    if (!content) return;
    if (els.greeting) els.greeting.style.display = "none";

    const li = document.createElement("li");
    li.className = "msg " + (role === "user" ? "user" : "assistant");

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const contentWrapper = document.createElement("div");
    bubble.appendChild(contentWrapper);

    li.appendChild(bubble);
    els.chatList.appendChild(li);
    scrollToBottom(true);

    // === Tin nhắn người dùng: hiện luôn + HIỂN THỊ FILE ĐÍNH KÈM ===
    if (role === "user") {
      const node = renderMarkdown(content);
      if (node.dataset.hasTable === "1") bubble.classList.add("is-table");
      contentWrapper.appendChild(node);

      // === HIỂN THỊ DANH SÁCH FILE ĐÍNH KÈM (nếu có) ===
      const filesToShow = files || window.lastUploadedFiles || [];
      if (filesToShow.length > 0) {
        // Hàng file nằm TRÊN bubble
        const header = document.createElement("div");
        header.className = "msg-file-header";

        filesToShow.forEach(file => {
          const name = file.name || file.filename || file.file || file.path || "";
          const ext = (name.split(".").pop() || "").toUpperCase();
          const isImage = ["JPG", "JPEG", "PNG", "GIF", "WEBP", "BMP"].includes(ext);

          // Tạo pill như ban đầu – giữ nguyên 100% thiết kế cũ
          const pill = document.createElement("div");
          pill.className = "file-pill msg-file-pill";
          pill.innerHTML = `
            <i data-lucide="${isImage ? "image" : "file-text"}" class="file-icon"></i>
            <span class="file-name">${htmlEscape(name)}</span>
          `;

          header.appendChild(pill);
        });

        // chèn header lên TRÊN bubble
        li.insertBefore(header, bubble);
        lucideRefresh();
      }

      if (persist) {
        sessionHistory.push({ role: "user", content, files: filesToShow });
        persistMessage("user", content);
      }
      return;
    }

    // === ASSISTANT ===
    // Nếu là tin nhắn cũ (load từ lịch sử, chuyển session, hydrate) → hiện luôn
    if (!opts.isNew) {
      const node = renderMarkdown(content);
      if (node.dataset.hasTable === "1") bubble.classList.add("is-table");
      contentWrapper.appendChild(node);

      if (opts.persist) {
        sessionHistory.push({ role, content });
        persistMessage(role, content);
      }

      // Highlight code nếu có
      if (window.hljs) {
        contentWrapper.querySelectorAll("pre code").forEach(block => {
          try { hljs.highlightElement(block); } catch { }
        });
      }
      return;
    }

    // === CHỈ KHI LÀ TIN NHẮN MỚI (isNew: true) → bật typewriter (HOẠT ĐỘNG DÙ CHUYỂN TAB) ===
    if (currentTypingController) {
      currentTypingController.abort();
    }
    currentTypingController = new AbortController();
    const signal = currentTypingController.signal;

    const fullNode = renderMarkdown(content);
    if (fullNode.dataset.hasTable === "1") bubble.classList.add("is-table");

    let textSoFar = "";
    let charIndex = 0;
    const fullText = content;

    // Tốc độ gõ như ChatGPT (đã tối ưu)
    const getDelay = (char) => {
      if (/[.,!?;]/.test(char)) return 50;
      if (/[\u4e00-\u9fff]/.test(char)) return 25;
      if (/[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]/.test(char)) return 25;
      if (/\s/.test(char)) return 8;
      return 11;
    };

    let lastTimestamp = performance.now();

    const typeNext = (now) => {
      if (signal.aborted) return;

      // Tính thời gian đã trôi qua kể từ lần cuối
      const delta = now - lastTimestamp;
      let accumulatedDelay = (typeNext.accumulated ||= 0) + delta;

      // Gõ hết các ký tự mà thời gian đã đủ
      while (accumulatedDelay >= getDelay(fullText[charIndex - 1] || " ")) {
        if (charIndex >= fullText.length) {
          // HOÀN THÀNH
          contentWrapper.innerHTML = fullNode.innerHTML;

          if (window.hljs) {
            contentWrapper.querySelectorAll("pre code").forEach(block => {
              try { hljs.highlightElement(block); } catch { }
            });
          }

          if (opts.persist) {
            sessionHistory.push({ role: "assistant", content });
            persistMessage("assistant", content);
          }

          currentTypingController = null;
          removeTyping();
          typeNext.accumulated = 0;
          return;
        }

        textSoFar += fullText[charIndex];
        charIndex++;

        const nextDelay = getDelay(fullText[charIndex - 1]);
        accumulatedDelay -= nextDelay;
      }

      // Cập nhật UI với nội dung hiện tại + con trỏ nháy
      const temp = renderMarkdown(textSoFar + "<span class='typing-cursor'>|</span>");
      contentWrapper.innerHTML = temp.innerHTML;
      scrollToBottom();

      // Lưu lại thời gian và delay còn lại
      lastTimestamp = now;
      typeNext.accumulated = accumulatedDelay;

      // Vòng lặp tiếp theo (luôn chạy dù tab bị ẩn)
      requestAnimationFrame(typeNext);
    };

    // Bắt đầu sau 30ms để mượt
    setTimeout(() => {
      if (!signal.aborted) {
        lastTimestamp = performance.now();
        requestAnimationFrame(typeNext);
      }
    }, 10); // delay nhẹ trước khi bắt đầu gõ
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
  }

  // =========================
  // History Container Functions
  // =========================
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
    } catch {
      return null;
    }
  }

  function loadLocalSessions() {
    try {
      return loadSessions().map((s) => ({
        id: s.id,
        title: s.name || "Cuộc trò chuyện",
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
      els.list
        .querySelectorAll(".chat-item.active, .hp-item.active")
        .forEach((n) => n.classList.remove("active"));

      if (!currentSessionId) return;
      const id =
        window.CSS && CSS.escape
          ? CSS.escape(String(currentSessionId))
          : String(currentSessionId);

      // tìm item theo data-id
      const node = els.list.querySelector(
        `.chat-item[data-id="${id}"], .hp-item[data-id="${id}"]`
      );
      if (node) {
        node.classList.add("active");
        node.scrollIntoView({ block: "nearest" });
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

    // Sidebar item
    const wrap = document.createElement("div");
    wrap.className = "chat-item p-3 p-md-4";
    wrap.setAttribute("data-id", String(s.id));
    wrap.innerHTML = `
        <div class="chat-content gap-2 gap-md-3">
          <div class="chat-avatar"><i data-lucide="user"></i></div>
          <div class="chat-text">
            <div class="chat-title">${htmlEscape(
      s.title || "Cuộc trò chuyện"
    )}</div>
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

  // =========================
  // Session Actions
  // =========================
  function inlineRename(id, currentTitle) {
    const newName = prompt(
      "Đặt tên đoạn chat:",
      currentTitle || "Cuộc trò chuyện"
    );
    if (!newName || !newName.trim()) return;
    commitRename(id, newName.trim());
  }

  async function commitRename(id, newTitle) {
    try {
      await fetch("/api/history/rename_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, title: newTitle }),
      });
    } catch { }

    // Update local mirrors
    updateLocalSession(id, (s) => {
      s.name = newTitle;
    });
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
        body: JSON.stringify({ session_id: id }),
      });
      const d = await r.json().catch(() => ({}));
      serverOk = r.ok && d.ok;
    } catch {
      /* bỏ qua */
    }

    // 2) Xóa bản local (session list + messages)
    clearLocal(id);

    // 3) Nếu đang xóa CHÍNH phiên làm việc hiện tại → chọn phiên gần nhất và chuyển sang
    const deletingCurrent =
      currentSessionId && String(currentSessionId) === String(id);
    if (deletingCurrent) {
      // Lấy danh sách còn lại (ưu tiên server, fallback local), loại id vừa xóa
      let candidateId = null;
      try {
        const list = await getSessions(); // {id, title, preview, last_ts}
        const filtered = (list || []).filter(
          (s) => String(s.id) !== String(id)
        );
        // Sắp theo thời gian giảm dần và chọn cái "gần nhất" (mới nhất còn lại)
        filtered.sort(
          (a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0)
        );
        if (filtered.length) candidateId = filtered[0].id;
      } catch {
        /* bỏ qua */
      }

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
        try {
          await createNewSession();
        } catch { }
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
        body: JSON.stringify({ title: "Cuộc trò chuyện" }),
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
      const r = await fetch(
        `/api/history/by_session?session_id=${encodeURIComponent(sessionId)}`
      );
      if (r.ok) {
        const data = await r.json();
        const items = data.items || [];

        // Clean session switch
        if (els.chatList) els.chatList.innerHTML = "";
        if (els.greeting)
          els.greeting.style.display = items.length ? "none" : "flex";

        // Set new current session
        adoptServerSid(data.session_id || sessionId);

        // Load messages for this session only
        items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
        setSessionHistoryRef(
          items.map(({ role, content }) => ({ role, content }))
        );

        // Save to local storage
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
          msgs.forEach((m) =>
            addMessage(m.role, m.content, { persist: false })
          );
          setSessionHistoryRef(
            msgs.map((m) => ({ role: m.role, content: m.content }))
          );
        }
      }
    } catch { }
  }

  function showMessages(messages) {
    if (!els.chatList) return;
    els.chatList.innerHTML = "";
    if (els.greeting)
      els.greeting.style.display = messages.length ? "none" : "flex";

    let i = 0;
    (function pump() {
      const end = Math.min(i + MSG_CHUNK, messages.length);
      for (; i < end; i++) {
        const m = messages[i];
        addMessage(m.role, m.content, { persist: false });
      }
      if (i < messages.length) setTimeout(pump, 0);
    })();
    scrollToBottom(true);
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
      const filtered = loadSessions().filter(
        (s) => String(s.id) !== String(id)
      );
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
      const res = await fetch(`/api/history/current_session`, {
        method: "GET",
      });
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
          }
        }
      } catch (_) { }
    }
  }
  // =========================
  // Upload file tạm cho doc_qa
  // =========================
  async function uploadSelectedFiles() {
    // Không có file thì coi như OK, bỏ qua
    if (!selectedFiles || !selectedFiles.length) {
      return { ok: true, uploaded: false };
    }

    const formData = new FormData();
    selectedFiles.forEach(file => {
      formData.append("file", file); // backend: request.files.getlist("file")
    });

    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });

    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      // ignore parse error, sẽ ném ở dưới
    }

    if (!res.ok || !data || data.ok === false) {
      const msg =
        (data && (data.message || data.error)) ||
        "Upload file thất bại. Vui lòng thử lại.";
      throw new Error("Upload file thất bại: " + msg);
    }

    // Upload OK → clear danh sách file đã chọn trên UI
    selectedFiles = [];
    renderFilePills();
    window.lastUploadedFiles = data.files || data.saved_files || [];
    return {
      ok: true,
      uploaded: true,
      data,
    };
  }

  // =========================
  // Chat Form Handler (ĐÃ FIX: KHÓA HOÀN TOÀN KHI ĐANG GỬI)
  // =========================
  if (els.chatForm) {
    let isSubmitting = false; // <-- Cờ trạng thái quan trọng

    const setSubmitting = (state) => {
      isSubmitting = state;
      els.sendBtn.disabled = state;
      els.chatForm.style.opacity = state ? "0.6" : "1";
      els.chatInput.style.pointerEvents = state ? "none" : "auto";
      if (state) {
        els.sendBtn.classList.add("disabled");
      } else {
        els.sendBtn.classList.remove("disabled");
      }
    };

    els.chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (isSubmitting) return;

      const text = (els.chatInput?.value || "").trim();
      if (!text) return;

      // chụp lại danh sách file đang chọn để hiển thị trên bubble
      const attachedForBubble = [...(selectedFiles || [])];

      // 1. Khóa ngay lập tức
      setSubmitting(true);

      // 2. Thêm tin nhắn người dùng
      addMessage("user", text, {
        persist: true,
        files: attachedForBubble,
      });
      window.lastUploadedFiles = [];
      els.chatInput.value = "";
      els.chatInput.style.height = "auto";
      scrollToBottom(true);

      // 3. Hiển thị typing
      addTyping();

      try {
        // 3a. Nếu có file được chọn → upload trước
        if (selectedFiles && selectedFiles.length > 0) {
          await uploadSelectedFiles(); // sẽ throw Error nếu fail
        }

        // 3b. Gọi API chat (doc_qa / db / rag tuỳ server quyết định)
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            session_id: currentSessionId || "",
          }),
        });
        const data = await res.json();

        // Nhận session_id từ server nếu có
        if (data.session_id) adoptServerSid(data.session_id);

        removeTyping();

        if (!data.ok) {
          addMessage("assistant", `Lỗi: ${data.error || "Không rõ"}`);
          return;
        }

        const answer = data.answer || "";
        addMessage("assistant", answer, { isNew: true });

        // Hiển thị timing nếu có
        if (data.timing && els.timingEl) {
          const t = data.timing;
          // (chỗ .to(2) hình như typo, nên là .toFixed(2))
          els.timingEl.textContent =
            `Tổng: ${(+t.total).toFixed(2)}s | ` +
            `Embedding: ${(+t.embedding).toFixed(2)}s | ` +
            `Tìm kiếm: ${(+t.search).toFixed(2)}s | ` +
            `LLM: ${(+t.llm).toFixed(2)}s`;
        }
      } catch (err) {
        removeTyping();
        const msg = err && err.message ? err.message : String(err);
        // Nếu lỗi do uploadSelectedFiles ném ra → msg đã có tiền tố "Upload file thất bại"
        addMessage("assistant", msg.startsWith("Upload file") ? msg : `Lỗi kết nối: ${msg}`);
        console.error(err);
      } finally {
        // 4. Bỏ khóa dù thành công hay thất bại
        setSubmitting(false);
      }
    });

    // Auto resize textarea
    els.chatInput?.addEventListener("input", () => {
      if (isSubmitting) return;
      els.chatInput.style.height = "auto";
      els.chatInput.style.height = els.chatInput.scrollHeight + "px";
    });

    // Enter để gửi, Shift+Enter để xuống dòng
    els.chatInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !isSubmitting) {
        e.preventDefault();
        els.chatForm.dispatchEvent(new Event("submit"));
      }
    });
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
  const fileInput = document.getElementById('fileInput');
  const filePreviewContainer = document.getElementById('filePreviewContainer');
  const filePreview = document.getElementById('filePreview');
  let selectedFiles = []; // Lưu danh sách file để gửi đi

  fileInput.addEventListener('change', function () {
    const newFiles = Array.from(this.files);

    // Thêm file mới vào danh sách (tránh trùng)
    newFiles.forEach(file => {
      if (!selectedFiles.some(f => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified)) {
        selectedFiles.push(file);
      }
    });

    renderFilePills();
    this.value = ''; // reset input để có thể chọn lại cùng file
  });

  function renderFilePills() {
    filePreview.innerHTML = '';

    if (selectedFiles.length === 0) {
      filePreviewContainer.style.display = 'none';
      return;
    }

    filePreviewContainer.style.display = 'flex';
    filePreviewContainer.style.display = 'block';

    selectedFiles.forEach((file, index) => {
      const pill = document.createElement('div');
      pill.className = 'file-pill';

      const ext = file.name.split('.').pop().toUpperCase();
      const isImage = ['JPG', 'JPEG', 'PNG', 'GIF', 'WEBP'].includes(ext);

      pill.innerHTML = `
      <i data-lucide="${isImage ? 'image' : 'file-text'}"></i>
      <span class="file-name" title="${file.name}">${file.name}</span>
      <button type="button" class="remove-file" data-index="${index}">×</button>
    `;

      // Xử lý xóa file
      pill.querySelector('.remove-file').addEventListener('click', () => {
        selectedFiles.splice(index, 1);
        renderFilePills();
      });

      filePreview.appendChild(pill);
    });

    lucide.createIcons();
  }
  // ======== CHỐNG BACK VÀO LẠI CHAT – PHIÊN BẢN HOÀN HẢO ========
  document.addEventListener('DOMContentLoaded', () => {
    // Chỉ đẩy thêm 1 lớp bảo vệ nữa (đã có 3 lớp từ post_login rồi)
    history.pushState(null, '', '/login');

    // Chỉ kích hoạt ép về login khi người dùng THỰC SỰ bấm Back
    // (không kích hoạt ngay khi load trang)
    const handleBack = () => {
      // Nếu đang ở trang chat và bấm Back → ép về login
      if (window.location.pathname === '/' || window.location.pathname === '/chat') {
        window.location.replace('/login');
      }
    };

    window.addEventListener('popstate', handleBack);

    // Cleanup (tốt hơn)
    window.addEventListener('beforeunload', () => {
      window.removeEventListener('popstate', handleBack);
    });
  });
})();
