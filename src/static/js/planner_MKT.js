/* --- helpers gọn: render MD, tab, loader, copy, toast, saved list --- */
function mdRenderTo(el, text) {
  const html = DOMPurify.sanitize(marked.parse(text || ""));
  el.innerHTML = html;
  el.querySelectorAll("pre code").forEach((b) => hljs.highlightElement(b));
}
function attachTabs() {
  document.querySelectorAll(".tabs").forEach((t) => {
    const scope = t.dataset.scope;
    const panels = t.parentElement.querySelectorAll(".tab-panel");
    t.querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => {
        t.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));
        b.classList.add("active");
        t.parentElement
          .querySelector(`#${scope}_${b.dataset.tab}`)
          .classList.add("active");
      })
    );
  });
}
async function withLoader(card, fn) {
  const L = card?.querySelector?.(".local-loader");
  L && L.classList.remove("hidden");
  try {
    return await fn();
  } finally {
    L && L.classList.add("hidden");
  }
}
function copyFrom(el) {
  const t = document.createElement("textarea");
  t.value = el?.innerText || el?.textContent || "";
  document.body.appendChild(t);
  t.select();
  document.execCommand("copy");
  document.body.removeChild(t);
}

/* --- Download .txt (UTF-8 BOM) + slug --- */
function downloadTxt(filename, text) {
  const blob = new Blob(["\uFEFF" + (text || "")], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
function slug(s) {
  return (
    (s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "content"
  );
}

function showToast(msg, ttl = 2200) {
  const root = document.getElementById("marketing") || document.body;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  root.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 180);
  }, ttl);
}
async function loadSaved(type, targetId) {
  const r = await fetch(`/api/saves?type=${encodeURIComponent(type)}`);
  const d = await r.json();
  const list = document.getElementById(targetId);
  if (!list) return;
  list.innerHTML = "";
  (d.items || []).forEach((it) => {
    const wrap = document.createElement("div");
    wrap.className = "item";
    const header = document.createElement("div");
    header.className = "item-header";
    const title = document.createElement("div");
    title.className = "item-title";
    title.textContent = it.input?.summary || "Nội dung đã lưu";
    const actions = document.createElement("div");
    actions.className = "item-actions";
    const bCopy = document.createElement("button");
    bCopy.className = "btn-ghost";
    bCopy.textContent = "📋";
    const bDown = document.createElement("button");
    bDown.className = "btn-ghost";
    bDown.textContent = "📥";
    const bDel = document.createElement("button");
    bDel.className = "btn-ghost";
    bDel.textContent = "🗑️";
    actions.append(bCopy, bDown, bDel);
    header.append(title, actions);

    const body = document.createElement("div");
    body.className = "item-body";
    const md = document.createElement("div");
    md.className = "markdown result-scroll";
    body.appendChild(md);
    let rendered = false;
    const ensure = () => {
      if (!rendered) {
        mdRenderTo(md, it.text || "");
        rendered = true;
      }
    };

    header.addEventListener("click", (e) => {
      if (e.target === bCopy || e.target === bDel || e.target === bDown) return;
      wrap.classList.toggle("open");
      if (wrap.classList.contains("open")) ensure();
    });
    bCopy.addEventListener("click", (e) => {
      e.stopPropagation();
      ensure();
      copyFrom(md);
      showToast("Đã sao chép.");
    });
    bDown.addEventListener("click", (e) => {
      e.stopPropagation();
      const sum = it.input?.summary || "planner";
      const ts = it.ts ? new Date(it.ts) : new Date();
      const stamp = ts.toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`planner_${slug(sum)}_${stamp}.txt`, it.text || "");
    });
    bDel.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Xóa mục đã lưu?")) return;
      await fetch("/api/saves/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "planner", ts: it.ts }),
      });
      await loadSaved("planner", targetId);
    });

    wrap.append(header, body);
    list.appendChild(wrap);
  });
}

/* helpers */
function getCheckedValues(selector, limit = null) {
  const arr = [...document.querySelectorAll(selector)]
    .filter((i) => i.checked)
    .map((i) => i.value);
  return limit ? arr.slice(0, limit) : arr;
}
function getSelectedGoal() {
  return document.querySelector('input[name="pl_goal"]:checked')?.value || "";
}

/* fallback cho :has() – đồng bộ màu chọn */
function syncGoalActive() {
  document.querySelectorAll("#pl_goals .goal-card").forEach((card) => {
    const checked = card.querySelector('input[name="pl_goal"]')?.checked;
    card.classList.toggle("is-active", !!checked);
  });
}

/* ===== Equal height cho 4 ô mục tiêu (theo box cao nhất) ===== */
function equalizeGoalHeights() {
  const cards = document.querySelectorAll("#pl_goals .goal-card");
  if (!cards.length) return;
  cards.forEach((c) => (c.style.height = "auto")); // reset
  const maxH = Math.max(...[...cards].map((c) => c.offsetHeight));
  cards.forEach((c) => (c.style.height = maxH + "px"));
}

const debounce = (fn, ms = 120) => {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
};

/* ==================== NEW: Channels integration ==================== */
async function loadPlannerChannels() {
  try {
    const r = await fetch("/api/channels");
    const d = await r.json();
    const sel = document.getElementById("pl_channel");
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">Chọn kênh..</option>';
    (d.items || []).forEach((it) => {
      const opt = document.createElement("option");
      opt.value = it.name;
      opt.textContent = it.name;
      sel.appendChild(opt);
    });
    if (cur) sel.value = cur;
  } catch (e) {
    console.error("loadPlannerChannels:", e);
  }
}

/** Tạo (hoặc lấy) khối preview prompt dưới form bên trái */
function ensurePromptPreviewBox() {
  let wrap = document.getElementById("pl_prompt_preview_wrap");
  if (wrap) return wrap;
  const formCard = document.getElementById("pl_form_card");
  if (!formCard) return null;
  wrap = document.createElement("div");
  wrap.id = "pl_prompt_preview_wrap";
  wrap.className = "card";
  wrap.innerHTML = `
    <div style="display:flex; align-items:center; gap:8px; margin-top:10px;">
      <strong>Preview Prompt</strong>
      <button id="pl_copy_prompt" class="btn-ghost" type="button">📋 Sao chép</button>
    </div>
    <pre id="pl_prompt_preview" class="markdown" style="max-height:260px; overflow:auto; white-space:pre-wrap;"></pre>
  `;
  formCard.appendChild(wrap);
  document.getElementById("pl_copy_prompt")?.addEventListener("click", () => {
    const txt = document.getElementById("pl_prompt_preview")?.textContent || "";
    if (!txt.trim()) return;
    navigator.clipboard.writeText(txt);
    showToast("Đã sao chép prompt.");
  });
  return wrap;
}

/** Gọi Gemini để sinh prompt theo kênh đã chọn và hiện preview */
async function fetchPromptForChannel() {
  const sel = document.getElementById("pl_channel");
  const langSel = document.getElementById("pl_lang");
  const wrap = ensurePromptPreviewBox();
  const out = document.getElementById("pl_prompt_preview");
  if (!sel || !out || !wrap) return;

  const channel = sel.value || "";
  if (!channel) {
    out.textContent = "";
    return;
  }

  const tones = getCheckedValues("#pl_tones input[type=checkbox]", 2);
  await withLoader(wrap, async () => {
    try {
      const r = await fetch("/api/channels/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel,
          lang: langSel?.value || "Tiếng Việt",
          tones,
        }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      out.textContent = d.generated || "";
    } catch (e) {
      out.textContent = "Không thể tạo prompt: " + e.message;
    }
  });
}

/* ==================== DOM Ready ==================== */
document.addEventListener("DOMContentLoaded", () => {
  attachTabs();
  loadSaved("planner", "pl_saved_list");

  // highlight card khi chọn mục tiêu (fallback cho :has)
  document.querySelectorAll('#pl_goals input[name="pl_goal"]').forEach((i) => {
    i.addEventListener("change", () => {
      syncGoalActive();
      equalizeGoalHeights();
    });
  });
  syncGoalActive();
  equalizeGoalHeights();
  window.addEventListener("resize", debounce(equalizeGoalHeights));

  // limit tones to 2
  const toneWrap = document.getElementById("pl_tones");
  if (toneWrap) {
    toneWrap.addEventListener("change", () => {
      const cbs = [...toneWrap.querySelectorAll('input[type="checkbox"]')];
      const checked = cbs.filter((c) => c.checked);
      if (checked.length > 2) {
        checked.pop().checked = false;
        showToast("Chỉ chọn tối đa 2 giọng điệu.");
      }
      const ch = document.getElementById("pl_channel")?.value;
      if (ch) fetchPromptForChannel();
    });
  }

  // Channels: nạp dropdown + bind preview khi đổi kênh/ngôn ngữ
  loadPlannerChannels().then(() => {
    const selCh = document.getElementById("pl_channel");
    selCh && selCh.addEventListener("change", fetchPromptForChannel);
  });
  const selLang = document.getElementById("pl_lang");
  selLang &&
    selLang.addEventListener("change", () => {
      const ch = document.getElementById("pl_channel")?.value;
      if (ch) fetchPromptForChannel();
    });

  // Generate
  document.getElementById("pl_generate")?.addEventListener("click", () =>
    withLoader(document.getElementById("pl_form_card"), async () => {
      const goal = getSelectedGoal();
      if (!goal) {
        showToast("Hãy chọn 1 mục tiêu truyền thông.");
        return;
      }

      const payload = {
        goal, // backend mới
        objectives: [goal], // tương thích backend cũ (mảng)
        stage: document.getElementById("pl_stage").value,
        channel: document.getElementById("pl_channel").value,
        format: document.getElementById("pl_format").value,
        length: document.getElementById("pl_length").value,
        tones: getCheckedValues("#pl_tones input[type=checkbox]", 2),
        keywords: document.getElementById("pl_keywords").value.trim(),
        offer: document.getElementById("pl_offer").value.trim(),
        cta: document.getElementById("pl_cta").value.trim(),
        lang: document.getElementById("pl_lang").value,
      };

      const r = await fetch("/api/planner/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        alert("Lỗi tạo nội dung.");
        return;
      }

      const d = await r.json();
      const out = document.getElementById("pl_out");
      if (!out) return;
      out.dataset.md = d.text || "";
      mdRenderTo(out, d.text || "");
      document
        .querySelector('.tabs[data-scope="pl"] .tab[data-tab="result"]')
        ?.click();
    })
  );

  // Copy
  document
    .getElementById("pl_copy")
    ?.addEventListener("click", () =>
      copyFrom(document.getElementById("pl_out"))
    );

  // Save
  document.getElementById("pl_save")?.addEventListener("click", async () => {
    const outEl = document.getElementById("pl_out");
    const text = (outEl?.dataset?.md || "").trim();
    if (!text) {
      alert("Chưa có nội dung để lưu.");
      return;
    }

    const sum =
      "Planner – " +
      (document.getElementById("pl_channel").value || "Kênh?") +
      " / " +
      (document.getElementById("pl_format").value || "Định dạng?") +
      " / " +
      (getSelectedGoal() || "Mục tiêu?");

    await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "planner", text, input: { summary: sum } }),
    });
    showToast("Đã lưu (Planner).");
    await loadSaved("planner", "pl_saved_list");
    document
      .querySelector('.tabs[data-scope="pl"] .tab[data-tab="saved"]')
      ?.click();
  });

  // Download .txt (Planner)
  document.getElementById("pl_download")?.addEventListener("click", () => {
    const outEl = document.getElementById("pl_out");
    const text = (outEl?.dataset?.md || outEl?.textContent || "").trim();
    if (!text) {
      alert("Chưa có nội dung để tải.");
      return;
    }
    const sum =
      "Planner – " +
      (document.getElementById("pl_channel").value || "Kenh") +
      " / " +
      (document.getElementById("pl_format").value || "Dinh-dang") +
      " / " +
      (getSelectedGoal() || "Muc-tieu");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadTxt(`planner_${slug(sum)}_${stamp}.txt`, text);
    showToast("Đang tải file .txt…");
  });
});
async function loadChannels() {
  const res = await fetch("/api/channels"); // phải là endpoint này
  if (!res.ok) return;
  const data = await res.json();
  const sel = document.getElementById("pl_channel");
  sel.innerHTML = '<option value="">Chọn kênh..</option>';
  for (const ch of data.items || []) {
    const id = ch.id || ch.name;
    const name = ch.name || ch.title || id;
    sel.insertAdjacentHTML(
      "beforeend",
      `<option value="${id}">${name}</option>`
    );
  }
}
document.addEventListener("DOMContentLoaded", loadChannels);
