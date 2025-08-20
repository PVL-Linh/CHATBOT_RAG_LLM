// =====================
// Init icons & bootstrap
// =====================
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) lucide.createIcons();
  bootstrapFromLocalThenServer(); // khởi động
});

// =====================
// Elements
// =====================
const chatList = document.getElementById("chatList");
const greeting = document.getElementById("greeting");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const timingEl = document.getElementById("timing");
const newChatBtn = document.getElementById("newChatBtn"); // (nếu có)

const historyBtn =
  document.getElementById("historyBtn") ||
  document.getElementById("newChatBtn"); // fallback nếu chưa đổi id
const historyPanel = document.getElementById("historyPanel");
const historyList = document.getElementById("historyList");
const newSessionBtn = document.getElementById("newSession");
const closeHistory = document.getElementById("closeHistory");
const overlayEl = document.getElementById("overlay");
const newSessionTopBtn = document.getElementById("newSessionTop");

// =====================
// Client-side session state
// =====================
let sessionHistory = []; // buffer cho UI hiện tại
const MAX_LOCAL_MSGS = 200;

// =====================
// Markdown render
// =====================
function renderMarkdown(md) {
  const raw = marked.parse(md || "");
  const clean = DOMPurify.sanitize(raw);
  const wrapper = document.createElement("div");
  wrapper.innerHTML = clean;
  wrapper.querySelectorAll("pre code").forEach((block) => {
    try {
      hljs.highlightElement(block);
    } catch (_) {}
  });
  return wrapper;
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
  bubble.appendChild(renderMarkdown(content));

  li.appendChild(bubble);
  if (chatList) {
    chatList.appendChild(li);
    chatList.scrollTop = chatList.scrollHeight;
  }

  if (opts.persist) {
    sessionHistory.push({ role, content });
    persistMessage(role, content);
  }
}

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
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
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
        timingEl.textContent =
          `Tổng: ${t.total.toFixed(2)}s | Embedding: ${t.embedding.toFixed(
            2
          )}s | ` +
          `Tìm kiếm: ${t.search.toFixed(2)}s | LLM: ${t.llm.toFixed(2)}s`;
      }
    } catch (err) {
      removeTyping();
      if (sendBtn) sendBtn.disabled = false;
      addMessage("assistant", `❌ Lỗi kết nối: ${err}`);
    }
  });

  // Auto-grow textarea
  chatInput?.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = chatInput.scrollHeight + "px";
  });

  // Enter để gửi (không Shift)
  chatInput?.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });
}

// =====================
// New chat (xóa UI hiện tại – không ảnh hưởng server session)
// =====================
if (newChatBtn) {
  newChatBtn.addEventListener("click", () => {
    sessionHistory = [];
    if (chatList) chatList.innerHTML = "";
    if (greeting) greeting.style.display = "flex";
    if (timingEl) timingEl.textContent = "";
  });
}

// =====================
// Chat History drawer (localStorage)
// =====================
const USER = (window.TXM_USER || "anonymous").trim();
const SESS_KEY = `txm_sessions_${USER}`;
const MSG_KEY_PREFIX = `txm_msgs_${USER}_`;
const CURR_KEY = `txm_current_session_${USER}`;

try {
  const OLD_KEY = "txm_current_session";
  if (localStorage.getItem(OLD_KEY) && !localStorage.getItem(CURR_KEY)) {
    localStorage.removeItem(OLD_KEY);
  }
} catch (_) {}

let currentSessionId = localStorage.getItem(CURR_KEY) || null;

function nowTS() {
  return new Date().toISOString();
}
function genId() {
  return Math.random().toString(36).slice(2, 10);
}
function msgKey(id) {
  return MSG_KEY_PREFIX + id;
}

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
  } catch (_) {}
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
  } catch (_) {}
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

// Drawer show/hide
function showHistory() {
  if (!historyPanel || !overlayEl) return;
  document.body.classList.add("history-open");
  renderHistoryPanel();
  if (window.lucide) lucide.createIcons();
}
function hideHistory() {
  document.body.classList.remove("history-open");
}

if (historyBtn && historyPanel) {
  historyBtn.addEventListener(
    "click",
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      const open = document.body.classList.contains("history-open");
      open ? hideHistory() : showHistory();
    },
    true
  );
}
overlayEl?.addEventListener("click", hideHistory);
closeHistory?.addEventListener("click", hideHistory);

newSessionBtn?.addEventListener("click", () => {
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
  saveMsgs(id, []);
  if (chatList) chatList.innerHTML = "";
  if (greeting) greeting.style.display = "flex";
  sessionHistory = [];
  hideHistory();
});

// Persist 1 tin nhắn vào local session
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

  if (document.body.classList.contains("history-open")) renderHistoryPanel();
}

// Hook đặt tiêu đề từ câu đầu user
if (chatForm && chatInput) {
  chatForm.addEventListener(
    "submit",
    () => {
      const text = (chatInput?.value || "").trim();
      if (text) {
        if (!currentSessionId) ensureSession(true);
        setSessionTitleFromFirstUser(text);
      }
    },
    true
  );
}

// Vẽ panel lịch sử
function renderHistoryPanel() {
  if (!historyList) return;

  const sessions = loadSessions()
    .map((s) => {
      const msgs = loadMsgs(s.id);
      const lastAt =
        msgs && msgs.length
          ? msgs[msgs.length - 1].at
          : s.updatedAt || s.createdAt;
      return { ...s, __lastAt: lastAt };
    })
    .sort((a, b) => new Date(b.__lastAt || 0) - new Date(a.__lastAt || 0));

  historyList.innerHTML = "";
  sessions.forEach((s) => {
    const li = document.createElement("li");
    li.className = "hp-item";

    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div class="name">${DOMPurify.sanitize(s.name)}</div>
      <div class="meta">${new Date(
        s.__lastAt || s.updatedAt || s.createdAt
      ).toLocaleString()}</div>
    `;

    const acts = document.createElement("div");
    acts.className = "acts";
    acts.innerHTML = `
      <button class="icon-btn act-rename" title="Đổi tên"><i data-lucide="pencil"></i></button>
      <button class="icon-btn act-delete" title="Xóa"><i data-lucide="trash-2"></i></button>
    `;

    li.appendChild(row);
    li.appendChild(acts);

    // Mở đoạn chat
    li.addEventListener("click", (e) => {
      if (e.target.closest(".acts")) return;
      currentSessionId = s.id;
      localStorage.setItem(CURR_KEY, s.id); // dùng CURR_KEY thống nhất

      if (chatList) chatList.innerHTML = "";
      const msgs = loadMsgs(s.id);
      if (greeting) greeting.style.display = msgs.length ? "none" : "flex";
      if (chatList)
        msgs.forEach((m) => addMessage(m.role, m.content, { persist: false }));

      sessionHistory = msgs.map((m) => ({ role: m.role, content: m.content }));
      hideHistory();
    });

    // Đổi tên
    acts.querySelector(".act-rename").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      const sessions2 = loadSessions();
      const item = sessions2.find((x) => x.id === s.id);
      const newName = prompt("Đặt tên đoạn chat:", item?.name || "");
      if (newName && newName.trim()) {
        item.name = newName.trim();
        item.updatedAt = nowTS();
        saveSessions(sessions2);
        renderHistoryPanel();
        if (window.lucide) lucide.createIcons();
      }
    });

    // Xóa
    acts.querySelector(".act-delete").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (!confirm("Xóa đoạn chat này?")) return;

      localStorage.removeItem(msgKey(s.id));
      const sessions3 = loadSessions().filter((x) => x.id !== s.id);
      saveSessions(sessions3);

      if (currentSessionId === s.id) {
        localStorage.removeItem(CURR_KEY);
        currentSessionId = null;
        if (chatList) chatList.innerHTML = "";
        if (greeting) greeting.style.display = "flex";
        sessionHistory = [];
      }

      renderHistoryPanel();
      if (window.lucide) lucide.createIcons();
    });

    historyList.appendChild(li);
  });

  if (window.lucide) lucide.createIcons();
}

// =====================
// Server hydrate
// =====================
async function hydrateFromServer(limit = 100) {
  try {
    const res = await fetch(`/api/history?limit=${limit}`, { method: "GET" });
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) return;

    const hasUI = chatList && chatList.children && chatList.children.length > 0;
    if (hasUI) return; // tránh render đè nếu đã có local

    if (greeting) greeting.style.display = "none";
    if (chatList) chatList.innerHTML = "";

    // server đã sort tăng dần → render tuần tự
    items.forEach((m) => addMessage(m.role, m.content, { persist: false }));
    sessionHistory = items.map(({ role, content }) => ({ role, content }));

    // (Tuỳ chọn) tạo 1 phiên local từ dữ liệu server để có trong drawer
    if (!currentSessionId) {
      ensureSession(true);
      const msgs = items.map(({ role, content }) => ({
        role,
        content,
        at: new Date().toISOString(),
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
  // 1) khôi phục từ localStorage (nếu có)
  try {
    currentSessionId = localStorage.getItem(CURR_KEY) || null;
    if (currentSessionId && chatList) {
      const msgs = loadMsgs(currentSessionId);
      if (msgs.length) {
        if (greeting) greeting.style.display = "none";
        chatList.innerHTML = "";
        msgs.forEach((m) => addMessage(m.role, m.content, { persist: false }));
        sessionHistory = msgs.map((m) => ({
          role: m.role,
          content: m.content,
        }));
      }
    }
  } catch (_) {}

  // 2) nếu UI vẫn trống → hydrate từ server CSV
  const hasUI = chatList && chatList.children && chatList.children.length > 0;
  if (!hasUI) {
    await hydrateFromServer(100);
  }
}

// =====================
// Rebind tạo session mới ở top
// =====================
if (newSessionTopBtn) {
  newSessionTopBtn.addEventListener("click", () => {
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
    saveMsgs(id, []);
    if (chatList) chatList.innerHTML = "";
    if (greeting) greeting.style.display = "flex";
    sessionHistory = [];
    hideHistory();
  });
}
