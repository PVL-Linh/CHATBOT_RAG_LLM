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
    const bDel = document.createElement("button");
    bDel.className = "btn-ghost";
    bDel.textContent = "🗑️";
    actions.append(bCopy, bDel);
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
      if (e.target === bCopy || e.target === bDel) return;
      wrap.classList.toggle("open");
      if (wrap.classList.contains("open")) ensure();
    });
    bCopy.addEventListener("click", (e) => {
      e.stopPropagation();
      ensure();
      copyFrom(md);
      showToast("Đã sao chép.");
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
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('#pl_goals input[name="pl_goal"]').forEach((i) => {
    i.addEventListener("change", syncGoalActive);
  });
  syncGoalActive();
});

/* (tuỳ chọn) đồng bộ chiều cao 4 card – tránh “mục tiêu” cao thấp khác nhau */
function equalizeGoalHeights() {
  const cards = document.querySelectorAll("#pl_goals .goal-card");
  if (!cards.length) return;
  cards.forEach((c) => (c.style.height = "auto"));
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
    });
  }

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
});
/* ===== Equal height cho 4 ô mục tiêu (theo box cao nhất) ===== */
function equalizeGoalHeights() {
  const cards = document.querySelectorAll("#pl_goals .goal-card");
  if (!cards.length) return;
  // reset để đo chính xác
  cards.forEach((c) => (c.style.height = "auto"));
  // lấy chiều cao lớn nhất
  const maxH = Math.max(...[...cards].map((c) => c.offsetHeight));
  // gán lại cho tất cả
  cards.forEach((c) => (c.style.height = maxH + "px"));
}

// chạy khi DOM sẵn sàng, khi resize và khi nội dung trong card thay đổi
document.addEventListener("DOMContentLoaded", () => {
  equalizeGoalHeights();

  // khi chọn/uncheck mục tiêu -> có viền/box-shadow -> có thể làm cao hơn
  document.querySelectorAll('#pl_goals input[name="pl_goal"]').forEach((i) => {
    i.addEventListener("change", equalizeGoalHeights);
  });

  // khi đổi font/viewport
  const debounce = (fn, ms = 120) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };
  window.addEventListener("resize", debounce(equalizeGoalHeights));

  // quan sát mọi thay đổi kích thước trong 4 thẻ (an toàn hơn)
  const ro = new ResizeObserver(debounce(equalizeGoalHeights, 60));
  document
    .querySelectorAll("#pl_goals .goal-card")
    .forEach((c) => ro.observe(c));
});
