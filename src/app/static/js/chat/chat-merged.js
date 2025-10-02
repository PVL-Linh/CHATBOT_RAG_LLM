(() => {
  "use strict";

  // =====================
  // Elements
  // =====================
  const chatList = document.getElementById("chatList");
  const greeting  = document.getElementById("greeting");
  const chatForm  = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const sendBtn   = document.getElementById("sendBtn");
  const timingEl  = document.getElementById("timing");
  const newChatBtn = document.getElementById("newChatBtn"); // (nếu có)

  const historyBtn =
    document.getElementById("historyBtn") ||
    document.getElementById("newChatBtn");
  const historyPanel   = document.getElementById("historyPanel");
  const historyList    = document.getElementById("historyList");
  const newSessionBtn  = document.getElementById("newSession");
  const closeHistory   = document.getElementById("closeHistory");
  const overlayEl      = document.getElementById("overlay");
  const newSessionTopBtn = document.getElementById("newSessionTop");

  // =====================
  // Markdown render
  // =====================
  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
  }

  function renderMarkdown(md) {
    const raw   = (window.marked ? marked.parse(md || "") : md || "").toString();
    const clean = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;

    const wrapper = document.createElement("div");
    wrapper.innerHTML = clean;

    // wrap tables for horizontal scroll
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
        try { hljs.highlightElement(block); } catch(_) {}
      });
    }
    return wrapper;
  }

  // =====================
  // Local Storage (per-user) + Schema versioning
  // =====================
  let sessionHistory = [];
  const MAX_LOCAL_MSGS = 200;

  const USER = (window.TXM_USER || "anonymous").trim();
  const SESS_KEY     = `txm_sessions_${USER}`;
  const MSG_KEY_PREFIX = `txm_msgs_${USER}_`;
  const CURR_KEY     = `txm_current_session_${USER}`;

  const LSCHEMA_KEY = `txm_schema_v_${USER}`;
  const LSCHEMA_VERSION = 2;

  try {
    const OLD_KEY = "txm_current_session";
    if (localStorage.getItem(OLD_KEY) && !localStorage.getItem(CURR_KEY)) {
      localStorage.removeItem(OLD_KEY);
    }
  } catch(_) {}

  let currentSessionId = localStorage.getItem(CURR_KEY) || null;

  function nowTS() { return new Date().toISOString(); }
  function genId()  { return Math.random().toString(36).slice(2, 10); }
  function msgKey(id) { return MSG_KEY_PREFIX + id; }

  function loadSessions() {
    try { return JSON.parse(localStorage.getItem(SESS_KEY) || "[]"); }
    catch(_) { return []; }
  }
  function saveSessions(list) {
    try { localStorage.setItem(SESS_KEY, JSON.stringify(list)); }
    catch(_) {}
  }
  function loadMsgs(id) {
    try { return JSON.parse(localStorage.getItem(msgKey(id)) || "[]"); }
    catch(_) { return []; }
  }
  function saveMsgs(id, msgs) {
    try {
      if (msgs.length > MAX_LOCAL_MSGS) msgs = msgs.slice(-MAX_LOCAL_MSGS);
      localStorage.setItem(msgKey(id), JSON.stringify(msgs));
    } catch(_) {}
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
    } catch(_) {}
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

  function exposeCurrentSessionId() {
    try { window.currentSessionId = currentSessionId; } catch(_) {}
  }
  function setSessionHistoryRef(arr) {
    sessionHistory = Array.isArray(arr) ? arr : [];
    try { window.sessionHistory = sessionHistory; } catch(_) {}
  }

  function adoptServerSid(newSid) {
    if (!newSid) return;

    if (!currentSessionId) {
      currentSessionId = newSid;
      localStorage.setItem(CURR_KEY, newSid);
      ensureLocalSessionEntry(newSid);
      exposeCurrentSessionId();
      return;
    }
    if (currentSessionId === newSid) return;

    const oldId = currentSessionId;
    const msgs  = loadMsgs(oldId);
    localStorage.removeItem(msgKey(oldId));
    saveMsgs(newSid, msgs);

    const sessions = loadSessions();
    const s = sessions.find((x) => x.id === oldId);
    if (s) {
      s.id = newSid;
      s.updatedAt = nowTS();
    } else {
      sessions.unshift({
        id: newSid, name: "Cuộc trò chuyện mới",
        createdAt: nowTS(), updatedAt: nowTS(),
      });
    }
    saveSessions(sessions);

    currentSessionId = newSid;
    localStorage.setItem(CURR_KEY, newSid);
    exposeCurrentSessionId();
  }

  async function createServerSession(title) {
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
    const sessions = loadSessions();
    const s = sessions.find((x) => x.id === currentSessionId);
    if (!s) return;
    if (s.name === "Cuộc trò chuyện mới") {
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

    // Nếu panel lịch sử đang mở trong chat-merged → auto refresh list
    if (document.body.classList.contains("history-open") && window.ChatPage?.History?.render) {
      window.ChatPage.History.render();
    }
  }

  // =====================
  // Chat UI helpers
  // =====================
  function addMessage(role, content, opts = { persist: true }) {
    if (!content) return;
    if (greeting) greeting.style.display = "none";

    const li = document.createElement("li");
    li.className = "msg " + (role === "user" ? "user" : "assistant");

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const node = renderMarkdown(content);
    if (node.dataset.hasTable === "1") bubble.classList.add("is-table");
    bubble.appendChild(node);

    li.appendChild(bubble);
    if (chatList) {
      chatList.appendChild(li);
      chatList.scrollTop = chatList.scrollHeight;
    }

    if (opts.persist) {
      sessionHistory.push({ role, content });
      persistMessage(role, content);
      // giữ sync tham chiếu ra window
      try { window.sessionHistory = sessionHistory; } catch(_) {}
    }
  }

  // Expose sớm để chat-merged.js có thể gọi được
  try { window.addMessage = addMessage; } catch(_) {}

  function addTyping() {
    if (!chatList) return;
    const li = document.createElement("li");
    li.id = "typingRow";
    li.className = "msg assistant";
    li.innerHTML = `<div class="bubble"><span class="dots">Vui lòng chờ...</span></div>`;
    chatList.appendChild(li);
    chatList.scrollTop = chatList.scrollHeight;
  }
  function removeTyping() {
    const t = document.getElementById("typingRow");
    if (t) t.remove();
  }

  // =====================
  // Send form
  // =====================
  if (chatForm) {
    chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = (chatInput?.value || "").trim();
      if (!text) return;

      addMessage("user", text);
      chatInput.value = "";
      chatInput.style.height = "auto";

      if (sendBtn) sendBtn.disabled = true;
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
        if (sendBtn) sendBtn.disabled = false;

        if (!data.ok) {
          addMessage("assistant", `⚠️ Lỗi: ${data.error || "Không rõ"}`);
          return;
        }

        const answer = data.answer || "";
        addMessage("assistant", answer);

        if (data.timing && timingEl) {
          const t = data.timing;
          const total  = Number(t.total ?? 0);
          const emb    = Number(t.embedding ?? 0);
          const search = Number(t.search ?? 0);
          const llm    = Number(t.llm ?? 0);
          timingEl.textContent =
            `Tổng: ${total.toFixed(2)}s | Embedding: ${emb.toFixed(2)}s | ` +
            `Tìm kiếm: ${search.toFixed(2)}s | LLM: ${llm.toFixed(2)}s`;
        }
      } catch (err) {
        removeTyping();
        if (sendBtn) sendBtn.disabled = false;
        addMessage("assistant", `❌ Lỗi kết nối: ${err}`);
      }
    });

    chatInput?.addEventListener("input", () => {
      chatInput.style.height = "auto";
      chatInput.style.height = chatInput.scrollHeight + "px";
    });

    chatInput?.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    });
  }

  if (chatForm && chatInput) {
    chatForm.addEventListener("submit", () => {
      const text = (chatInput?.value || "").trim();
      if (text) {
        if (!currentSessionId) ensureSession(true);
        setSessionTitleFromFirstUser(text);
      }
    }, true);
  }

  // =====================
  // New chat
  // =====================
  function resetUIToEmpty() {
    setSessionHistoryRef([]);
    if (chatList) chatList.innerHTML = "";
    if (greeting) greeting.style.display = "flex";
    if (timingEl) timingEl.textContent = "";
  }

  async function handleCreateNewSession() {
    try { await createServerSession("Cuộc trò chuyện mới"); } catch(e) { console.warn(e); }
    resetUIToEmpty();
    // refresh list nếu panel lịch sử đang mở
    if (window.ChatPage?.History?.render) window.ChatPage.History.render();
  }

  if (newChatBtn)        newChatBtn.addEventListener("click", handleCreateNewSession);
  if (newSessionTopBtn)  newSessionTopBtn.addEventListener("click", handleCreateNewSession);
  if (newSessionBtn)     newSessionBtn.addEventListener("click", handleCreateNewSession);

  // =====================
  // History drawer (SERVER-backed)
  // *Tắt UI riêng nếu đã dùng chat-merged.js*
  // =====================
  const historyUiDisabled = !!window.ChatPage?.History; // khi chat-merged khởi tạo sẽ set ChatPage.History
  function showHistory() {
    if (historyUiDisabled) { window.ChatPage?.History?.open?.(); return; }
    if (!historyPanel || !overlayEl) return;
    document.body.classList.add("history-open");
    renderHistoryPanel();
    if (window.lucide) lucide.createIcons();
  }
  function hideHistory() {
    if (historyUiDisabled) { window.ChatPage?.History?.close?.(); return; }
    document.body.classList.remove("history-open");
  }

  if (!historyUiDisabled && historyBtn && historyPanel) {
    historyBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      const open = document.body.classList.contains("history-open");
      open ? hideHistory() : showHistory();
    }, true);
  }
  if (!historyUiDisabled) {
    overlayEl?.addEventListener("click", hideHistory);
    closeHistory?.addEventListener("click", hideHistory);
  }

  async function renderHistoryPanel() {
    if (historyUiDisabled) { window.ChatPage?.History?.render?.(); return; }
    if (!historyList) return;

    let sessions = [];
    try {
      const r = await fetch("/api/history/sessions");
      const d = await r.json();
      sessions = (d.sessions || []).map((s) => ({
        id: s.id,
        name: s.title || "Cuộc trò chuyện",
        last_ts: s.last_ts || s.first_ts || "",
        count: s.count || 0,
      }));
      sessions.sort((a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0));
    } catch (e) {
      console.warn("renderHistoryPanel(): server sessions failed, fallback local", e);
      sessions = loadSessions().map((s) => ({
        id: s.id,
        name: s.name,
        last_ts: s.updatedAt || s.createdAt,
        count: (loadMsgs(s.id) || []).length,
      }));
      sessions.sort((a, b) => new Date(b.last_ts || 0) - new Date(a.last_ts || 0));
    }

    historyList.innerHTML = "";
    sessions.forEach((s) => {
      const li = document.createElement("li");
      li.className = "hp-item";

      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
        <div class="name">${window.DOMPurify ? DOMPurify.sanitize(s.name) : s.name}</div>
        <div class="meta">${s.last_ts ? new Date(s.last_ts).toLocaleString() : ""}</div>
      `;

      const acts = document.createElement("div");
      acts.className = "acts";
      acts.innerHTML = `
        <button class="icon-btn act-rename" title="Đổi tên"><i data-lucide="pencil"></i></button>
        <button class="icon-btn act-delete" title="Xóa"><i data-lucide="trash-2"></i></button>
      `;

      li.appendChild(row);
      li.appendChild(acts);

      // Open session (server)
      li.addEventListener("click", async (e) => {
        if (e.target.closest(".acts")) return;
        try {
          const r = await fetch(`/api/history/by_session?session_id=${encodeURIComponent(s.id)}`);
          const data = await r.json();

          if (data && data.session_id) adoptServerSid(data.session_id);

          const items = data.items || [];
          if (chatList) chatList.innerHTML = "";
          if (greeting) greeting.style.display = items.length ? "none" : "flex";
          items.forEach((m) => addMessage(m.role, m.content, { persist: false }));

          setSessionHistoryRef(items.map(({ role, content }) => ({ role, content })));
          saveMsgs(currentSessionId, sessionHistory.map((x) => ({ ...x, at: nowTS() })));
          hideHistory();
        } catch (err) {
          console.error("Open session failed:", err);
        }
      });

      // Rename
      acts.querySelector(".act-rename").addEventListener("click", async (e) => {
        e.preventDefault(); e.stopImmediatePropagation();
        const newName = prompt("Đặt tên đoạn chat:", s.name || "");
        if (!newName || !newName.trim()) return;
        try {
          await fetch("/api/history/rename_session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: s.id, title: newName.trim() }),
          });
        } catch(_) {}
        renderHistoryPanel();
      });

      // Delete
      acts.querySelector(".act-delete").addEventListener("click", async (e) => {
        e.preventDefault(); e.stopImmediatePropagation();
        if (!confirm("Xóa phiên này khỏi máy chủ? (Toàn bộ tin nhắn trong phiên sẽ bị xóa)")) return;

        try {
          const r = await fetch("/api/history/delete_session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: s.id }),
          });
          const d = await r.json();
          if (!r.ok || !d.ok) {
            alert("Xóa không thành công trên server.");
            return;
          }

          // remove local cache for this session
          localStorage.removeItem(MSG_KEY_PREFIX + s.id);
          const loc = loadSessions().filter((x) => x.id !== s.id);
          saveSessions(loc);

          // if current session is deleted → reset UI + create a new server session
          if (currentSessionId === s.id) {
            localStorage.removeItem(CURR_KEY);
            currentSessionId = null;
            exposeCurrentSessionId();

            if (chatList) chatList.innerHTML = "";
            if (greeting) greeting.style.display = "flex";
            setSessionHistoryRef([]);

            try { await createServerSession("Cuộc trò chuyện mới"); } catch(_) {}
          }

          renderHistoryPanel();
        } catch (err) {
          console.error("Delete session failed:", err);
          alert("Lỗi kết nối khi xóa phiên.");
        }
      });

      historyList.appendChild(li);
    });

    if (window.lucide) lucide.createIcons();
  }

  // =====================
  // Server hydrate (SERVER-WINS, 1 phiên duy nhất)
  // =====================
  async function hydrateFromServer() {
    try {
      const res = await fetch(`/api/history/by_session`, { method: "GET" });
      const data = await res.json();

      const items = data.items || [];
      const sid   = data.session_id || null;

      // server empty but local has old data → purge local to avoid mixing
      if (!items.length && anyLocalMessagesExist()) {
        clearAllLocalForUser();
        if (chatList) chatList.innerHTML = "";
        if (greeting) greeting.style.display = "flex";
        currentSessionId = null;
        exposeCurrentSessionId();
        localStorage.removeItem(CURR_KEY);
      }

      if (sid) adoptServerSid(sid);

      if (chatList) chatList.innerHTML = "";
      if (greeting) greeting.style.display = items.length ? "none" : "flex";

      items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
      setSessionHistoryRef(items.map(({ role, content }) => ({ role, content })));

      if (currentSessionId) {
        const msgs = items.map((m) => ({ role: m.role, content: m.content, at: m.ts || nowTS() }));
        saveMsgs(currentSessionId, msgs);
        ensureLocalSessionEntry(currentSessionId);
        const firstUser = items.find((x) => x.role === "user");
        if (firstUser) setSessionTitleFromFirstUser(firstUser.content);
      }
    } catch (e) {
      console.warn("hydrateFromServer() failed:", e);
    }
  }

  // =====================
  // Boot (SERVER FIRST → fallback local)
  // =====================
  async function bootstrapFromLocalThenServer() {
    await hydrateFromServer();

    const hasUI = chatList && chatList.children && chatList.children.length > 0;
    if (!hasUI) {
      try {
        currentSessionId = localStorage.getItem(CURR_KEY) || null;
        exposeCurrentSessionId();
        if (currentSessionId && chatList) {
          const msgs = loadMsgs(currentSessionId);
          if (msgs.length) {
            if (greeting) greeting.style.display = "none";
            chatList.innerHTML = "";
            msgs.forEach((m) => addMessage(m.role, m.content, { persist: false }));
            setSessionHistoryRef(msgs.map((m) => ({ role: m.role, content: m.content })));
          }
        }
      } catch(_) {}
    }
  }

  // =====================
  // Expose helpers cho chat-merged.js
  // =====================
  try {
    window.persistMessage      = persistMessage;
    window.saveMsgs            = saveMsgs;
    window.loadSessions        = loadSessions;
    window.saveSessions        = saveSessions;
    window.adoptServerSid      = adoptServerSid;
    window.createServerSession = createServerSession;
    window.nowTS               = nowTS;
    window.CURR_KEY            = CURR_KEY;
    window.MSG_KEY_PREF        = MSG_KEY_PREFIX;
    window.sessionHistory      = sessionHistory;
    window.currentSessionId    = currentSessionId;
  } catch(_) {}

  // =====================
  // Init
  // =====================
  document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) lucide.createIcons();
    ensureLocalSchema();
    bootstrapFromLocalThenServer();
  });
})();
