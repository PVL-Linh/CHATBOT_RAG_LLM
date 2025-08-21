// static/js/channels.js

/* ===== Short utils ===== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

function showToast(msg, ttl = 2000) {
  const el = document.createElement("div");
  el.textContent = msg;
  Object.assign(el.style, {
    position: "fixed",
    right: "16px",
    bottom: "16px",
    zIndex: 9999,
    background: "#222",
    color: "#fff",
    padding: "10px 14px",
    borderRadius: "10px",
    opacity: "0",
    transition: "opacity .2s",
  });
  document.body.appendChild(el);
  requestAnimationFrame(() => (el.style.opacity = "1"));
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 200);
  }, ttl);
}

const _debounce = (fn, ms = 250) => {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
};

/* ===== State ===== */
let CHANNELS = [];
let CURRENT_ID = null;
let toneCtrl, formatCtrl;

/* ===== Chips with AUTOSAVE ===== */
function Chips(inputEl, listEl, opts = {}) {
  let values = [];
  const split = (s) =>
    (s || "")
      .split(/[,\n;]+/)
      .map((x) => x.trim())
      .filter(Boolean);
  const autosaveField = opts.autosaveField; // 'tone' | 'formats'
  const ensureId = opts.ensureId || (async () => null);

  function render() {
    listEl.innerHTML = "";
    values.forEach((v, i) => {
      const el = document.createElement("span");
      el.className = "chip";
      el.innerHTML = `${v}<span class="x" data-i="${i}">×</span>`;
      listEl.appendChild(el);
    });
  }

  const _doSave = _debounce(async () => {
    if (!autosaveField) return;
    const id = await ensureId();
    if (!id) return;
    const payload = {};
    payload[autosaveField] = values.join(", ");
    try {
      await fetch(`/api/channels/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {}
  }, 250);

  function changed() {
    render();
    _doSave();
  }

  function add(v) {
    v = (v || "").trim();
    if (!v) return;
    if (!values.includes(v)) {
      values.push(v);
      changed();
    }
  }
  function set(arrOrString) {
    values = Array.isArray(arrOrString)
      ? arrOrString.slice()
      : split(arrOrString);
    render(); // set khi fill form -> KHÔNG autosave
  }
  function get() {
    return values.slice();
  }
  function commit() {
    const t = (inputEl.value || "").trim();
    if (t) {
      add(t);
      inputEl.value = "";
    }
  }

  inputEl.addEventListener("input", () => {
    const v = inputEl.value;
    if (/[,\n;]$/.test(v) || v.endsWith("  ")) {
      inputEl.value = v.replace(/[,\n;]+$/g, "");
      commit();
    }
  });
  inputEl.addEventListener("keydown", (e) => {
    if (["Enter", "Tab", ","].includes(e.key)) {
      e.preventDefault();
      commit();
    }
    if (e.key === "Backspace" && !inputEl.value && values.length) {
      values.pop();
      changed();
      e.preventDefault();
    }
  });
  inputEl.addEventListener("blur", commit);
  inputEl.addEventListener("paste", (e) => {
    const txt = (e.clipboardData || window.clipboardData).getData("text");
    const parts = split(txt);
    if (parts.length > 1) {
      e.preventDefault();
      parts.forEach(add);
    }
  });
  listEl.addEventListener("click", (e) => {
    const x = e.target.closest(".x");
    if (!x) return;
    values.splice(+x.dataset.i, 1);
    changed();
  });

  return { set, get, add, commit };
}

/* ===== Data I/O ===== */
async function loadList() {
  const r = await fetch("/api/channels");
  const d = await r.json();
  CHANNELS = d.items || [];
  renderList();
}
function renderList() {
  const root = $("#cards");
  root.innerHTML = "";
  CHANNELS.forEach((it) => {
    const el = document.createElement("div");
    el.className = "card";
    el.style =
      "padding:12px;border:1px solid #eee;border-radius:12px;background:#fff;";
    el.dataset.id = it.id;
    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:600;">${it.name || ""}</div>
          <small style="opacity:.7">${it.platform || ""}</small>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn-ghost btn-edit" type="button">Sửa</button>
          <button class="btn-ghost btn-del" type="button">Xoá</button>
        </div>
      </div>
      <div style="margin-top:8px;font-size:13px;line-height:1.4;">
        ${it.tone ? `<div><b>Tone:</b> ${it.tone}</div>` : ""}
        ${it.formats ? `<div><b>Formats:</b> ${it.formats}</div>` : ""}
        ${it.length ? `<div><b>Length:</b> ${it.length}</div>` : ""}
      </div>
    `;
    root.appendChild(el);
  });
}

/* ===== Helpers ===== */
function openEditor(title = "Tạo kênh mới") {
  $("#ed_title").textContent = title;
  $("#editor").style.display = "block";
  showList(false); // <-- ẩn danh sách
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function resetForm() {
  CURRENT_ID = null;
  $("#f_id").value = "";
  $("#f_name").value = "";
  $("#f_platform").value = "Social Media";
  $("#f_audience").value = "";
  $("#f_content_guide").value = "";
  $("#f_visual_guide").value = "";
  $("#f_hashtags").value = "";
  $("#f_cta").value = "";
  $("#f_length").value = "";
  $("#f_risk_notes").value = "";
  $("#f_special").value = "";
  toneCtrl?.set([]);
  formatCtrl?.set([]);
}
function fillForm(it) {
  CURRENT_ID = it.id || null;
  $("#f_id").value = it.id || "";
  $("#f_name").value = it.name || "";
  $("#f_platform").value = it.platform || "Social Media";
  $("#f_audience").value = it.audience || "";
  $("#f_content_guide").value = it.content_guide || "";
  $("#f_visual_guide").value = it.visual_guide || "";
  $("#f_hashtags").value = it.hashtags || "";
  $("#f_cta").value = it.cta || "";
  $("#f_length").value = it.length || "";
  $("#f_risk_notes").value = it.risk_notes || "";
  $("#f_special").value = it.special || "";
  toneCtrl?.set(it.tone || "");
  formatCtrl?.set(it.formats || "");
}
function collectAllFields() {
  toneCtrl?.commit();
  formatCtrl?.commit();
  return {
    name: $("#f_name").value.trim(),
    platform: $("#f_platform").value,
    audience: $("#f_audience").value,
    tone: (toneCtrl?.get() || []).join(", "),
    content_guide: $("#f_content_guide").value,
    visual_guide: $("#f_visual_guide").value,
    formats: (formatCtrl?.get() || []).join(", "),
    length: $("#f_length").value,
    hashtags: $("#f_hashtags").value,
    cta: $("#f_cta").value,
    risk_notes: $("#f_risk_notes").value,
    special: $("#f_special").value,
  };
}
async function ensureChannelId() {
  if (CURRENT_ID) return CURRENT_ID;
  const name = $("#f_name").value.trim();
  if (!name) {
    showToast("Hãy nhập Tên kênh trước khi thêm.");
    return null;
  }
  const payload = collectAllFields();
  try {
    const r = await fetch("/api/channels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const item = await r.json();
    if (item?.id) {
      CURRENT_ID = item.id;
      $("#f_id").value = item.id;
      return CURRENT_ID;
    }
  } catch (e) {
    console.error(e);
  }
  return null;
}

/* ===== Events ===== */
document.addEventListener("DOMContentLoaded", () => {
  // init chips (autosave)
  toneCtrl = Chips($("#tone_input"), $("#tone_chips"), {
    autosaveField: "tone",
    ensureId: ensureChannelId,
  });
  formatCtrl = Chips($("#format_input"), $("#format_chips"), {
    autosaveField: "formats",
    ensureId: ensureChannelId,
  });

  $("#btn_new").addEventListener("click", () => {
    resetForm();
    openEditor("Tạo kênh mới");
  });

  // nút Huỷ
  $("#ed_cancel").addEventListener("click", closeEditor);

  // nút Lưu
  $("#ed_save").addEventListener("click", async () => {
    const payload = collectAllFields();
    if (!payload.name) {
      showToast("Tên kênh là bắt buộc.");
      return;
    }
    try {
      if (CURRENT_ID) {
        await fetch(`/api/channels/${CURRENT_ID}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        const r = await fetch("/api/channels", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const item = await r.json();
        if (item?.id) CURRENT_ID = item.id;
      }
      showToast("Đã lưu.");
      await loadList();
      closeEditor(); // <-- hiện lại danh sách
    } catch (e) {
      alert("Không thể lưu kênh.");
    }
  });

  // delegation Sửa/Xoá
  $("#cards").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const card = e.target.closest(".card");
    const id = card?.dataset?.id;
    const item = (CHANNELS || []).find((x) => x.id === id);
    if (!item) return;

    if (btn.classList.contains("btn-edit")) {
      fillForm(item);
      openEditor("Chỉnh sửa: " + (item.name || "Kênh")); // <-- ẩn danh sách
    }
    if (btn.classList.contains("btn-del")) {
      if (!confirm("Xoá kênh này?")) return;
      await fetch(`/api/channels/${id}`, { method: "DELETE" });
      showToast("Đã xoá kênh.");
      await loadList();
    }
  });

  loadList();
});
// thêm hai helper
function showList(show = true) {
  const el = $("#list_card");
  if (el) el.style.display = show ? "" : "none";
}
function closeEditor() {
  $("#editor").style.display = "none";
  showList(true);
}
