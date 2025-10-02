// /* --- helpers gọn: render MD, tab, loader, copy, toast, saved list --- */
// function mdRenderTo(el, text) {
//   const html = DOMPurify.sanitize(marked.parse(text || ""));
//   el.innerHTML = html;
//   el.querySelectorAll("pre code").forEach((b) => hljs.highlightElement(b));
// }

// function attachTabs() {
//   document.querySelectorAll(".tabs").forEach((t) => {
//     const scope = t.dataset.scope;
//     const panels = t.parentElement.querySelectorAll(".tab-panel");
//     t.querySelectorAll(".tab").forEach((b) =>
//       b.addEventListener("click", () => {
//         t.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
//         panels.forEach((p) => p.classList.remove("active"));
//         b.classList.add("active");
//         t.parentElement
//           .querySelector(`#${scope}_${b.dataset.tab}`)
//           .classList.add("active");
//       })
//     );
//   });
// }

// async function withLoader(card, fn) {
//   const L = card?.querySelector?.(".local-loader");
//   L && L.classList.remove("hidden");
//   try {
//     return await fn();
//   } finally {
//     L && L.classList.add("hidden");
//   }
// }

// function copyFrom(el) {
//   const t = document.createElement("textarea");
//   t.value = el?.innerText || el?.textContent || "";
//   document.body.appendChild(t);
//   t.select();
//   document.execCommand("copy");
//   document.body.removeChild(t);
// }

// /* --- Download .txt (UTF-8 BOM) + slug --- */
// function downloadTxt(filename, text) {
//   const blob = new Blob(["\uFEFF" + (text || "")], {
//     type: "text/plain;charset=utf-8",
//   });
//   const url = URL.createObjectURL(blob);
//   const a = document.createElement("a");
//   a.href = url;
//   a.download = filename;
//   document.body.appendChild(a);
//   a.click();
//   a.remove();
//   URL.revokeObjectURL(url);
// }

// function slug(s) {
//   return (
//     (s || "")
//       .toLowerCase()
//       .normalize("NFD")
//       .replace(/[\u0300-\u036f]/g, "")
//       .replace(/[^a-z0-9]+/g, "-")
//       .replace(/^-+|-+$/g, "")
//       .slice(0, 60) || "content"
//   );
// }

// function showToast(msg, ttl = 2200) {
//   const root = document.getElementById("marketing") || document.body;
//   const el = document.createElement("div");
//   el.className = "toast";
//   el.textContent = msg;
//   root.appendChild(el);
//   requestAnimationFrame(() => el.classList.add("show"));
//   setTimeout(() => {
//     el.classList.remove("show");
//     setTimeout(() => el.remove(), 180);
//   }, ttl);
// }

// async function loadSaved(type, targetId) {
//   const r = await fetch(`/api/saves?type=${encodeURIComponent(type)}`);
//   const d = await r.json();
//   const list = document.getElementById(targetId);
//   if (!list) return;
//   list.innerHTML = "";
//   (d.items || []).forEach((it) => {
//     const wrap = document.createElement("div");
//     wrap.className = "item";
//     const header = document.createElement("div");
//     header.className = "item-header";
//     const title = document.createElement("div");
//     title.className = "item-title";
//     title.textContent = it.input?.summary || "Nội dung đã lưu";
//     const actions = document.createElement("div");
//     actions.className = "item-actions";
//     const bCopy = document.createElement("button");
//     bCopy.className = "btn-ghost";
//     bCopy.textContent = "📋";
//     const bDown = document.createElement("button");
//     bDown.className = "btn-ghost";
//     bDown.textContent = "📥";
//     const bDel = document.createElement("button");
//     bDel.className = "btn-ghost";
//     bDel.textContent = "🗑️";
//     actions.append(bCopy, bDown, bDel);
//     header.append(title, actions);

//     const body = document.createElement("div");
//     body.className = "item-body";
//     const md = document.createElement("div");
//     md.className = "markdown result-scroll";
//     body.appendChild(md);
//     let rendered = false;
//     const ensure = () => {
//       if (!rendered) {
//         mdRenderTo(md, it.text || "");
//         rendered = true;
//       }
//     };

//     header.addEventListener("click", (e) => {
//       if (e.target === bCopy || e.target === bDel || e.target === bDown) return;
//       wrap.classList.toggle("open");
//       if (wrap.classList.contains("open")) ensure();
//     });
//     bCopy.addEventListener("click", (e) => {
//       e.stopPropagation();
//       ensure();
//       copyFrom(md);
//       showToast("Đã sao chép.");
//     });
//     bDown.addEventListener("click", (e) => {
//       e.stopPropagation();
//       const sum = it.input?.summary || "planner";
//       const ts = it.ts ? new Date(it.ts) : new Date();
//       const stamp = ts.toISOString().replace(/[:.]/g, "-").slice(0, 19);
//       downloadTxt(`planner_${slug(sum)}_${stamp}.txt`, it.text || "");
//     });
//     bDel.addEventListener("click", async (e) => {
//       e.stopPropagation();
//       if (!confirm("Xóa mục đã lưu?")) return;
//       await fetch("/api/saves/delete", {
//         method: "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({ type: "planner", ts: it.ts }),
//       });
//       await loadSaved("planner", targetId);
//     });

//     wrap.append(header, body);
//     list.appendChild(wrap);
//   });
// }

// /* helpers */
// function getCheckedValues(selector, limit = null) {
//   const arr = [...document.querySelectorAll(selector)]
//     .filter((i) => i.checked)
//     .map((i) => i.value);
//   return limit ? arr.slice(0, limit) : arr;
// }

// function getSelectedGoal() {
//   return document.querySelector('input[name="pl_goal"]:checked')?.value || "";
// }

// /* fallback cho :has() – đồng bộ màu chọn */
// function syncGoalActive() {
//   document.querySelectorAll("#pl_goals .goal-card").forEach((card) => {
//     const checked = card.querySelector('input[name="pl_goal"]')?.checked;
//     card.classList.toggle("is-active", !!checked);
//   });
// }

// /* ===== Equal height cho 4 ô mục tiêu (theo box cao nhất) ===== */
// function equalizeGoalHeights() {
//   const cards = document.querySelectorAll("#pl_goals .goal-card");
//   if (!cards.length) return;
//   cards.forEach((c) => (c.style.height = "auto")); // reset
//   const maxH = Math.max(...[...cards].map((c) => c.offsetHeight));
//   cards.forEach((c) => (c.style.height = maxH + "px"));
// }

// const debounce = (fn, ms = 120) => {
//   let t;
//   return (...a) => {
//     clearTimeout(t);
//     t = setTimeout(() => fn(...a), ms);
//   };
// };

// /* ==================== NEW: Channels integration ==================== */
// async function loadPlannerChannels() {
//   try {
//     const r = await fetch(window.CHANNELS_API || "/marketing/api/channels");
//     const d = await r.json();
//     const sel = document.getElementById("pl_channel");
//     if (!sel) return;
//     const cur = sel.value;
//     sel.innerHTML = '<option value="">Chọn kênh..</option>';
//     (d.items || []).forEach((it) => {
//       const opt = document.createElement("option");
//       opt.value = it.name;
//       opt.textContent = it.name;
//       sel.appendChild(opt);
//     });
//     if (cur) sel.value = cur;
//   } catch (e) {
//     console.error("loadPlannerChannels:", e);
//   }
// }

// /* ==================== FIXED: Clean AI Response ==================== */
// function cleanPlannerResponse(text) {
//   if (!text) return "";
//   let s = (text || "").trim();

//   // 0) Cắt YAML front-matter nếu có
//   s = s.replace(/^\s*---[\s\S]*?---\s*/m, "");

//   // 1) Phân tách dòng để xử lý "preamble"
//   const lines = s.split(/\r?\n/);
//   let i = 0;

//   // 1a) Bỏ các heading đầu (H1/H2/...) nếu có
//   while (i < lines.length && /^#{1,6}\s/.test(lines[i].trim())) i++;

//   // 1b) Bỏ dòng trống ngay sau heading
//   while (i < lines.length && !lines[i].trim()) i++;

//   // 1c) Bỏ block metadata đầu bài (VN + EN)
//   const metaHeadRe =
//     /^(?:\*\*)?(?:Mục tiêu|Giai đoạn|Kênh|Định dạng|Độ dài|Giọng ?điệu|Từ ?kho[áa]|Từ khoá chiến lược|Khuyến mãi|Ưu đãi|Kêu gọi hành động|CTA|Ngôn ngữ|Goal|Stage|Channel|Format|Content length|Tone|Keywords|Promotion|Offer|Call(?:-| )?to(?:-| )?Action|Language)(?:\*\*)?\s*:/i;

//   let metaFound = false;
//   let j = i;
//   while (j < lines.length) {
//     const t = lines[j].trim();
//     if (!t) {
//       j++;
//       continue;
//     } // cho phép lẫn dòng trống trong block meta
//     if (metaHeadRe.test(t)) {
//       metaFound = true;
//       j++;
//       continue;
//     }
//     break; // gặp dòng không phải meta => kết thúc block meta
//   }
//   if (metaFound) i = j; // cắt bỏ preamble (heading + meta)

//   // 2) Phần còn lại là nội dung
//   s = lines.slice(i).join("\n").trim();

//   // 3) Xóa mọi dòng metadata còn sót ở BẤT KỲ đâu (phòng model in lẫn trong nội dung)
//   const stripAllParamsRe =
//     /^(?:\s*(?:\*\*)?(?:Mục tiêu|Giai đoạn|Kênh|Định dạng|Độ dài|Giọng ?điệu|Từ ?kho[áa]|Từ khoá chiến lược|Khuyến mãi|Ưu đãi|Kêu gọi hành động|CTA|Ngôn ngữ|Goal|Stage|Channel|Format|Content length|Tone|Keywords|Promotion|Offer|Call(?:-| )?to(?:-| )?Action|Language)(?:\*\*)?\s*[:\-].*)$/gim;
//   s = s.replace(stripAllParamsRe, "");

//   // 4) Thu gọn khoảng trắng
//   s = s.replace(/\n{3,}/g, "\n\n").trim();

//   return s;
// }

// /* ==================== DOM Ready ==================== */
// document.addEventListener("DOMContentLoaded", () => {
//   attachTabs();
//   loadSaved("planner", "pl_saved_list");

//   // highlight card khi chọn mục tiêu (fallback cho :has)
//   document.querySelectorAll('#pl_goals input[name="pl_goal"]').forEach((i) => {
//     i.addEventListener("change", () => {
//       syncGoalActive();
//       equalizeGoalHeights();
//     });
//   });
//   syncGoalActive();
//   equalizeGoalHeights();
//   window.addEventListener("resize", debounce(equalizeGoalHeights));

//   // limit tones to 2
//   const toneWrap = document.getElementById("pl_tones");
//   if (toneWrap) {
//     toneWrap.addEventListener("change", () => {
//       const cbs = [...toneWrap.querySelectorAll('input[type="checkbox"]')];
//       const checked = cbs.filter((c) => c.checked);
//       if (checked.length > 2) {
//         checked.pop().checked = false;
//         showToast("Chỉ chọn tối đa 2 giọng điệu.");
//       }
//     });
//   }

//   // Channels: nạp dropdown
//   loadPlannerChannels();

//   // ==================== FIXED: Generate với content cleaning ====================
//   document.getElementById("pl_generate")?.addEventListener("click", () =>
//     withLoader(document.getElementById("pl_form_card"), async () => {
//       const goal = getSelectedGoal();
//       if (!goal) {
//         showToast("Hãy chọn 1 mục tiêu truyền thông.");
//         return;
//       }

//       const payload = {
//         goal, // backend mới
//         objectives: [goal], // tương thích backend cũ (mảng)
//         stage: document.getElementById("pl_stage").value,
//         channel: document.getElementById("pl_channel").value,
//         format: document.getElementById("pl_format").value,
//         length: document.getElementById("pl_length").value,
//         tones: getCheckedValues("#pl_tones input[type=checkbox]", 2),
//         keywords: document.getElementById("pl_keywords").value.trim(),
//         offer: document.getElementById("pl_offer").value.trim(),
//         cta: document.getElementById("pl_cta").value.trim(),
//         lang: document.getElementById("pl_lang").value,
//       };

//       try {
//         const r = await fetch(
//           window.PLANNER_API || "/marketing/api/planner/generate",
//           {
//             method: "POST",
//             headers: { "Content-Type": "application/json" },
//             body: JSON.stringify(payload),
//           }
//         );

//         if (!r.ok) {
//           throw new Error(`HTTP ${r.status}: ${r.statusText}`);
//         }

//         const d = await r.json();
//         if (d.error) {
//           throw new Error(d.error);
//         }

//         const out = document.getElementById("pl_out");
//         if (!out) return;

//         // ========== CLEAN CONTENT HERE ==========
//         const rawContent = d.text || "";
//         let cleanedContent = cleanPlannerResponse(rawContent);
//         if (!cleanedContent || cleanedContent.replace(/\s/g, "").length < 30) {
//           cleanedContent = rawContent.trim();
//         }

//         // Lưu cả raw và cleaned content
//         out.dataset.mdRaw = rawContent; // raw cho debug
//         out.dataset.md = cleanedContent; // cleaned cho display

//         // Render cleaned content
//         mdRenderTo(out, cleanedContent);

//         // Switch to result tab
//         document
//           .querySelector('.tabs[data-scope="pl"] .tab[data-tab="result"]')
//           ?.click();

//         showToast("Đã tạo nội dung thành công!");
//       } catch (error) {
//         console.error("Generate error:", error);
//         showToast("Lỗi tạo nội dung: " + error.message);
//       }
//     })
//   );

//   // Copy - sử dụng cleaned content
//   document.getElementById("pl_copy")?.addEventListener("click", () => {
//     const outEl = document.getElementById("pl_out");
//     const cleanedText = outEl?.dataset?.md || outEl?.textContent || "";

//     if (!cleanedText.trim()) {
//       showToast("Chưa có nội dung để sao chép.");
//       return;
//     }

//     // Copy using modern clipboard API if available
//     if (navigator.clipboard && window.isSecureContext) {
//       navigator.clipboard
//         .writeText(cleanedText)
//         .then(() => {
//           showToast("Đã sao chép nội dung.");
//         })
//         .catch(() => {
//           // Fallback to old method
//           copyFrom(outEl);
//           showToast("Đã sao chép nội dung.");
//         });
//     } else {
//       copyFrom(outEl);
//       showToast("Đã sao chép nội dung.");
//     }
//   });

//   // Save - sử dụng cleaned content
//   document.getElementById("pl_save")?.addEventListener("click", async () => {
//     const outEl = document.getElementById("pl_out");
//     const text = (outEl?.dataset?.md || "").trim();

//     if (!text) {
//       showToast("Chưa có nội dung để lưu.");
//       return;
//     }

//     const sum =
//       "Planner – " +
//       (document.getElementById("pl_channel").value || "Kênh?") +
//       " / " +
//       (document.getElementById("pl_format").value || "Định dạng?") +
//       " / " +
//       (getSelectedGoal() || "Mục tiêu?");

//     try {
//       const response = await fetch("/api/save", {
//         method: "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({
//           type: "planner",
//           text,
//           input: { summary: sum },
//         }),
//       });

//       if (!response.ok) {
//         throw new Error(`HTTP ${response.status}`);
//       }

//       showToast("Đã lưu (Planner).");
//       await loadSaved("planner", "pl_saved_list");
//       document
//         .querySelector('.tabs[data-scope="pl"] .tab[data-tab="saved"]')
//         ?.click();
//     } catch (error) {
//       console.error("Save error:", error);
//       showToast("Lỗi khi lưu: " + error.message);
//     }
//   });

//   // Download .txt (Planner) - sử dụng cleaned content
//   document.getElementById("pl_download")?.addEventListener("click", () => {
//     const outEl = document.getElementById("pl_out");
//     const text = (outEl?.dataset?.md || outEl?.textContent || "").trim();

//     if (!text) {
//       showToast("Chưa có nội dung để tải.");
//       return;
//     }

//     const sum =
//       "Planner – " +
//       (document.getElementById("pl_channel").value || "Kenh") +
//       " / " +
//       (document.getElementById("pl_format").value || "Dinh-dang") +
//       " / " +
//       (getSelectedGoal() || "Muc-tieu");

//     const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
//     downloadTxt(`planner_${slug(sum)}_${stamp}.txt`, text);
//     showToast("Đang tải file .txt…");
//   });
// });

// // Load channels function (backup)
// async function loadChannels() {
//   try {
//     const res = await fetch(window.CHANNELS_API || "/marketing/api/channels");
//     if (!res.ok) return;
//     const data = await res.json();
//     const sel = document.getElementById("pl_channel");
//     if (!sel) return;

//     sel.innerHTML = '<option value="">Chọn kênh..</option>';
//     for (const ch of data.items || []) {
//       const id = ch.id || ch.name;
//       const name = ch.name || ch.title || id;
//       sel.insertAdjacentHTML(
//         "beforeend",
//         `<option value="${id}">${name}</option>`
//       );
//     }
//   } catch (error) {
//     console.error("Load channels error:", error);
//   }
// }

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

/* ==================== FIXED: Clean AI Response ==================== */
function cleanPlannerResponse(text) {
  if (!text) return "";
  let s = (text || "").trim();

  // 0) Cắt YAML front-matter nếu có
  s = s.replace(/^\s*---[\s\S]*?---\s*/m, "");

  // 1) Phân tách dòng để xử lý "preamble"
  const lines = s.split(/\r?\n/);
  let i = 0;

  // 1a) Bỏ các heading đầu (H1/H2/...) nếu có
  while (i < lines.length && /^#{1,6}\s/.test(lines[i].trim())) i++;

  // 1b) Bỏ dòng trống ngay sau heading
  while (i < lines.length && !lines[i].trim()) i++;

  // 1c) Bỏ block metadata đầu bài (VN + EN)
  const metaHeadRe =
    /^(?:\*\*)?(?:Mục tiêu|Giai đoạn|Kênh|Định dạng|Độ dài|Giọng ?điệu|Từ ?kho[áa]|Từ khoá chiến lược|Khuyến mãi|Ưu đãi|Kêu gọi hành động|CTA|Ngôn ngữ|Goal|Stage|Channel|Format|Content length|Tone|Keywords|Promotion|Offer|Call(?:-| )?to(?:-| )?Action|Language)(?:\*\*)?\s*:/i;

  let metaFound = false;
  let j = i;
  while (j < lines.length) {
    const t = lines[j].trim();
    if (!t) {
      j++;
      continue;
    } // cho phép lẫn dòng trống trong block meta
    if (metaHeadRe.test(t)) {
      metaFound = true;
      j++;
      continue;
    }
    break; // gặp dòng không phải meta => kết thúc block meta
  }
  if (metaFound) i = j; // cắt bỏ preamble (heading + meta)

  // 2) Phần còn lại là nội dung
  s = lines.slice(i).join("\n").trim();

  // 3) Xóa mọi dòng metadata còn sót ở BẤT KỲ đâu (phòng model in lẫn trong nội dung)
  const stripAllParamsRe =
    /^(?:\s*(?:\*\*)?(?:Mục tiêu|Giai đoạn|Kênh|Định dạng|Độ dài|Giọng ?điệu|Từ ?kho[áa]|Từ khoá chiến lược|Khuyến mãi|Ưu đãi|Kêu gọi hành động|CTA|Ngôn ngữ|Goal|Stage|Channel|Format|Content length|Tone|Keywords|Promotion|Offer|Call(?:-| )?to(?:-| )?Action|Language)(?:\*\*)?\s*[:\-].*)$/gim;
  s = s.replace(stripAllParamsRe, "");

  // 4) Thu gọn khoảng trắng
  s = s.replace(/\n{3,}/g, "\n\n").trim();

  return s;
}

/* ==================== Map độ dài -> target_words ==================== */
function mapLengthToTarget(line) {
  const s = (line || "").toLowerCase();
  if (s.includes("ngắn") || s.includes("150")) return { target: 150, tol: 4 };
  if (s.includes("trung") || s.includes("300") || s.includes("500"))
    return { target: 400, tol: 6 };
  if (s.includes("dài") || s.includes("800")) return { target: 900, tol: 6 };
  if (s.includes("seo") || s.includes("2000")) return { target: 2000, tol: 6 };
  return { target: 400, tol: 6 };
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
    });
  }

  // Channels: nạp dropdown
  loadPlannerChannels();

  // ==================== Generate với content cleaning + target_words ====================
  document.getElementById("pl_generate")?.addEventListener("click", () =>
    withLoader(document.getElementById("pl_form_card"), async () => {
      const goal = getSelectedGoal();
      if (!goal) {
        showToast("Hãy chọn 1 mục tiêu truyền thông.");
        return;
      }

      const lengthLine = document.getElementById("pl_length").value;
      const { target, tol } = mapLengthToTarget(lengthLine);

      const payload = {
        goal, // backend mới
        objectives: [goal], // tương thích backend cũ (mảng)
        stage: document.getElementById("pl_stage").value,
        channel: document.getElementById("pl_channel").value,
        format: document.getElementById("pl_format").value,
        length: lengthLine,
        tones: getCheckedValues("#pl_tones input[type=checkbox]", 2),
        keywords: document.getElementById("pl_keywords").value.trim(),
        offer: document.getElementById("pl_offer").value.trim(),
        cta: document.getElementById("pl_cta").value.trim(),
        lang: document.getElementById("pl_lang").value,
        // QUAN TRỌNG:
        target_words: target,
        tolerance_pct: tol,
        // Nếu bạn có ô nhập nội dung nguồn để tóm tắt/mở rộng thì gửi thêm:
        // full_content: (document.getElementById("pl_input")?.value || "").trim(),
      };

      try {
        const r = await fetch(
          window.PLANNER_API || "/marketing/api/planner/generate",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );

        if (!r.ok) {
          throw new Error(`HTTP ${r.status}: ${r.statusText}`);
        }

        const d = await r.json();
        if (d.error) {
          throw new Error(d.error);
        }

        const out = document.getElementById("pl_out");
        if (!out) return;

        // ========== CLEAN CONTENT HERE ==========
        const rawContent = d.text || "";
        let cleanedContent = cleanPlannerResponse(rawContent);
        if (!cleanedContent || cleanedContent.replace(/\s/g, "").length < 30) {
          cleanedContent = rawContent.trim();
        }
        // Lưu cả raw và cleaned content
        out.dataset.mdRaw = rawContent; // raw cho debug
        out.dataset.md = cleanedContent; // cleaned cho display

        // Render cleaned content
        mdRenderTo(out, cleanedContent);

        // Switch to result tab
        document
          .querySelector('.tabs[data-scope="pl"] .tab[data-tab="result"]')
          ?.click();

        showToast("Đã tạo nội dung thành công!");
      } catch (error) {
        console.error("Generate error:", error);
        showToast("Lỗi tạo nội dung: " + error.message);
      }
    })
  );

  // Copy - sử dụng cleaned content
  document.getElementById("pl_copy")?.addEventListener("click", () => {
    const outEl = document.getElementById("pl_out");
    const cleanedText = outEl?.dataset?.md || outEl?.textContent || "";

    if (!cleanedText.trim()) {
      showToast("Chưa có nội dung để sao chép.");
      return;
    }

    // Copy using modern clipboard API if available
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard
        .writeText(cleanedText)
        .then(() => {
          showToast("Đã sao chép nội dung.");
        })
        .catch(() => {
          // Fallback to old method
          copyFrom(outEl);
          showToast("Đã sao chép nội dung.");
        });
    } else {
      copyFrom(outEl);
      showToast("Đã sao chép nội dung.");
    }
  });

  // Save - sử dụng cleaned content
  document.getElementById("pl_save")?.addEventListener("click", async () => {
    const outEl = document.getElementById("pl_out");
    const text = (outEl?.dataset?.md || "").trim();

    if (!text) {
      showToast("Chưa có nội dung để lưu.");
      return;
    }

    const sum =
      "Planner – " +
      (document.getElementById("pl_channel").value || "Kênh?") +
      " / " +
      (document.getElementById("pl_format").value || "Định dạng?") +
      " / " +
      (getSelectedGoal() || "Mục tiêu?");

    try {
      const response = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "planner",
          text,
          input: { summary: sum },
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      showToast("Đã lưu (Planner).");
      await loadSaved("planner", "pl_saved_list");
      document
        .querySelector('.tabs[data-scope="pl"] .tab[data-tab="saved"]')
        ?.click();
    } catch (error) {
      console.error("Save error:", error);
      showToast("Lỗi khi lưu: " + error.message);
    }
  });

  // Download .txt (Planner) - sử dụng cleaned content
  document.getElementById("pl_download")?.addEventListener("click", () => {
    const outEl = document.getElementById("pl_out");
    const text = (outEl?.dataset?.md || outEl?.textContent || "").trim();

    if (!text) {
      showToast("Chưa có nội dung để tải.");
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

/* Backup: load channels */
async function loadChannels() {
  try {
    const res = await fetch("/api/channels");
    if (!res.ok) return;
    const data = await res.json();
    const sel = document.getElementById("pl_channel");
    if (!sel) return;
    sel.innerHTML = '<option value="">Chọn kênh..</option>';
    for (const ch of data.items || []) {
      const id = ch.id || ch.name;
      const name = ch.name || ch.title || id;
      sel.insertAdjacentHTML(
        "beforeend",
        `<option value="${id}">${name}</option>`
      );
    }
  } catch (error) {
    console.error("Load channels error:", error);
  }
}
