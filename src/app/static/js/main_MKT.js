/* ---------- Markdown render ---------- */
function mdRenderTo(el, text) {
  const html = DOMPurify.sanitize(marked.parse(text || ""));
  el.innerHTML = html;
  el.querySelectorAll("pre code").forEach((b) =>
    window.hljs.highlightElement(b)
  );
}

/* ---------- Tabs (scope-based) ---------- */
function attachTabs() {
  document.querySelectorAll(".tabs").forEach((tabs) => {
    const scope = tabs.dataset.scope; // fb | re | tk | fab
    const panels = tabs.parentElement.querySelectorAll(".tab-panel");
    tabs.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const id = tab.dataset.tab; // result | images | saved
        tabs.parentElement.querySelector(`#${scope}_${id}`).classList.add("active");
      });
    });
  });
}

/* ---------- Loader cục bộ ---------- */
async function withLoader(cardEl, fn) {
  const layer = cardEl.querySelector(".local-loader");
  if (layer) layer.classList.remove("hidden");
  try {
    return await fn();
  } finally {
    if (layer) layer.classList.add("hidden");
  }
}

/* ---------- Copy helper ---------- */
function copyFrom(el) {
  const tmp = document.createElement("textarea");
  tmp.value = el.innerText || el.textContent || "";
  document.body.appendChild(tmp);
  tmp.select();
  document.execCommand("copy");
  document.body.removeChild(tmp);
}

/* ---------- Download .txt (UTF-8 BOM) ---------- */
function downloadTxt(filename, text) {
  const blob = new Blob(["\uFEFF" + (text || "")], { type: "text/plain;charset=utf-8" });
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
  return (s || "")
    .toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
    .slice(0, 60) || "content";
}

/* ---------- Toast ---------- */
function showToast(msg, ttl = 2500) {
  const root = document.getElementById("marketing") || document.body;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  root.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 200);
  }, ttl);
}

/* ---------- Tóm tắt nội dung để làm tiêu đề ---------- */
function _stripMarkdown(md) {
  return (md || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[[^\]]*\]\([^)]+\)/g, (m) => m.replace(/\[|\]\([^)]+\)/g, ""))
    .replace(/^>+\s*/gm, "")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/[*_\-~]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
function _pickHeading(md) {
  const m = (md || "").match(/^#{1,6}\s*(.+)$/m);
  return m ? m[1].trim() : null;
}
function _pickBullet(md) {
  const m = (md || "").match(/^(?:-|\*|•)\s+(.+)$/m);
  return m ? m[1].trim() : null;
}
function _pickKeySentence(text) {
  const t = _stripMarkdown(text);
  const sents = t.split(/(?<=[\.\!\?])\s+/).filter(Boolean);
  const KEY = /ý tưởng|hook|headline|caption|lợi ích|ưu điểm|đề xuất|đề bài|kêu gọi/i;
  const found = sents.find((s) => KEY.test(s));
  return (found || sents.find((s) => s.split(/\s+/).length >= 6) || sents[0] || "");
}
function _truncate(s, n = 80) {
  return s && s.length > n ? s.slice(0, n - 1) + "…" : s || "";
}
function summarizeTitle(md, input = null, type = "", maxLen = 80) {
  if (input) {
    if (type === "fbads" && (input.product_desc || input.customer)) {
      const p = (input.product_desc || "").trim();
      const c = (input.customer || "").trim();
      if (p || c) return _truncate(`FB Ads – ${p}${c ? " → " + c : ""}`, maxLen);
    }
    if (type === "rephrase" && input.src) return _truncate(`Rephrase – ${input.src}`, maxLen);
    if (type === "tiktok" && input.brief) return _truncate(`TikTok – ${input.brief}`, maxLen);
    if (type === "fab" && input.benefits) return _truncate(`FAB – ${input.benefits}`, maxLen);
  }
  const fromHeading = _pickHeading(md);
  if (fromHeading) return _truncate(fromHeading, maxLen);
  const fromBullet = _pickBullet(md);
  if (fromBullet) return _truncate(fromBullet, maxLen);
  const fromSentence = _pickKeySentence(md);
  return _truncate(fromSentence, maxLen) || "Nội dung đã lưu";
}

/* ---------- Danh sách đã lưu (accordion, CÓ nút Download) ---------- */
async function loadSaved(type, targetId) {
  const res = await fetch(`/api/saves?type=${encodeURIComponent(type)}`);
  const data = await res.json();
  const list = document.getElementById(targetId);
  if (!list) return;

  list.innerHTML = "";
  (data.items || []).forEach((it) => {
    const wrap = document.createElement("div");
    wrap.className = "item";

    const header = document.createElement("div");
    header.className = "item-header";

    const left = document.createElement("div");
    left.style.display = "flex";
    left.style.flexWrap = "wrap";
    left.style.alignItems = "center";

    const title = document.createElement("div");
    title.className = "item-title";
    title.textContent = summarizeTitle(it.text || "", it.input || null, type, 80);

    const time = document.createElement("div");
    time.className = "item-time";

    left.append(title, time);

    const actions = document.createElement("div");
    actions.className = "item-actions";

    const bCopy = document.createElement("button");
    bCopy.className = "btn-ghost";
    bCopy.title = "Copy";
    bCopy.textContent = "📋";

    const bDown = document.createElement("button");
    bDown.className = "btn-ghost";
    bDown.title = "Download .txt";
    bDown.textContent = "📥";

    const bDel = document.createElement("button");
    bDel.className = "btn-ghost";
    bDel.title = "Delete";
    bDel.textContent = "🗑️";

    actions.append(bCopy, bDown, bDel);
    header.append(left, actions);

    const body = document.createElement("div");
    body.className = "item-body";
    const md = document.createElement("div");
    md.className = "markdown result-scroll";
    body.appendChild(md);

    let rendered = false;
    const renderIfNeeded = () => {
      if (!rendered) {
        mdRenderTo(md, it.text || "");
        rendered = true;
      }
    };

    header.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (btn && (btn === bCopy || btn === bDel || btn === bDown)) return;
      wrap.classList.toggle("open");
      if (wrap.classList.contains("open")) renderIfNeeded();
    });

    bCopy.addEventListener("click", (e) => {
      e.stopPropagation();
      renderIfNeeded();
      copyFrom(md);
      showToast("Đã sao chép nội dung.");
    });

    bDown.addEventListener("click", (e) => {
      e.stopPropagation();
      const titleTxt = summarizeTitle(it.text || "", it.input || null, type, 60);
      const ts = it.ts ? new Date(it.ts) : new Date();
      const stamp = ts.toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`${type}_${slug(titleTxt)}_${stamp}.txt`, it.text || "");
    });

    bDel.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Xóa nội dung đã lưu?")) return;
      await fetch("/api/saves/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, ts: it.ts }),
      });
      await loadSaved(type, targetId);
    });

    wrap.append(header, body);
    list.appendChild(wrap);
  });
}

/* ---------- On ready ---------- */
document.addEventListener("DOMContentLoaded", () => {
  attachTabs();

  /* ===== Facebook Ads ===== */
  const btnFb = document.getElementById("fb_generate");
  if (btnFb) {
    loadSaved("fbads", "fb_saved_list");

    btnFb.addEventListener("click", () =>
      withLoader(document.getElementById("fb_form_card"), async () => {
        const product = document.getElementById("fb_product").value.trim();
        const customer = document.getElementById("fb_customer").value.trim();
        const lang = document.getElementById("fb_lang").value;

        if (!product || !customer) {
          alert("Vui lòng nhập đầy đủ mô tả & chân dung.");
          return;
        }
        // Lấy brand/tone an toàn
        const brandEl = document.getElementById("fb_brand");
        const toneEl = document.getElementById("fb_tone");
        const brand = brandEl ? brandEl.value.trim() : "Tiximax Logistics";
        const tone = toneEl ? toneEl.value : "Chuyên nghiệp";

        // ===== 1) TEXT =====
        const r1 = await fetch("/api/fbads/generate_text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            product_desc: product,
            customer,
            lang,
            brand,
            tone,
          }),
        });

        if (!r1.ok) {
          const errText = await r1.text();
          console.error("generate_text failed:", r1.status, errText);
          alert("Lỗi tạo nội dung (TEXT). Xem Console để biết chi tiết.");
          return;
        }

        const d1 = await r1.json();
        if (d1.error) {
          alert(d1.error);
          return;
        }
        const out = document.getElementById("fb_result_md");
        mdRenderTo(out, d1.text || "");
        out.dataset.md = d1.text || "";
        const metaEl = document.getElementById("fb_meta");
        metaEl.textContent = `LLM: ${d1.meta?.latency_sec || 0}s • Brand: ${brand} • Tone: ${tone}`;

        document
          .querySelector('.tabs[data-scope="fb"] .tab[data-tab="result"]')
          .click();

        // ===== 2) IMAGES =====
        const fd = new FormData();
        fd.append("result_text", d1.text || "");
        fd.append("product_desc", product);
        fd.append("customer", customer);
        fd.append("brand", brand);
        fd.append("engine_label", document.getElementById("fb_engine").value);
        fd.append("aspect", document.getElementById("fb_aspect").value);
        fd.append("style_preset", document.getElementById("fb_style").value);
        fd.append("composition", document.getElementById("fb_comp").value);

        const addLogo = document.getElementById("fb_add_logo").checked;
        fd.append("add_logo", addLogo);
        fd.append("keep_logo_original", document.getElementById("fb_keep_logo").checked);
        fd.append("logo_scale", parseFloat(document.getElementById("fb_logo_scale").value) / 100.0);
        fd.append("logo_margin", parseInt(document.getElementById("fb_logo_margin").value, 10));

        const lf = document.getElementById("fb_logo_file").files[0];
        if (addLogo && lf) fd.append("logo_file", lf);

        const r2 = await fetch("/api/fbads/generate_images", { method: "POST", body: fd });
        if (!r2.ok) {
          const errText = await r2.text();
          console.error("generate_images failed:", r2.status, errText);
          alert("Lỗi tạo ảnh. Xem Console để biết chi tiết.");
          return;
        }

        const d2 = await r2.json();
        const grid = document.getElementById("fb_img_grid");
        if (d2.error) {
          grid.innerHTML = "";
          alert(d2.error);
          return;
        }

        document.getElementById("fb_used_prompt").textContent = d2.used_prompt || "";
        grid.innerHTML = "";
        (d2.images || []).forEach((b64, i) => {
          const c = document.createElement("div");
          c.className = "img-card";
          const img = document.createElement("img");
          img.src = `data:image/png;base64,${b64}`;
          const a = document.createElement("a");
          a.href = img.src;
          a.download = `tiximax_fbads_${Date.now()}_opt${i + 1}.png`;
          a.textContent = "Tải về";
          c.append(img, a);
          grid.appendChild(c);
        });

        if ((d2.images || []).length) {
          document
            .querySelector('.tabs[data-scope="fb"] .tab[data-tab="images"]')
            .click();
        }
      })
    );

    // Copy
    document.getElementById("fb_copy")?.addEventListener("click", () =>
      copyFrom(document.getElementById("fb_result_md"))
    );

    // Save
    document.getElementById("fb_save")?.addEventListener("click", async () => {
      const el = document.getElementById("fb_result_md");
      const text = (el.dataset.md || "").trim();
      if (!text) {
        alert("Chưa có nội dung để lưu.");
        return;
      }
      const body = {
        type: "fbads",
        text,
        input: {
          product_desc: document.getElementById("fb_product").value,
          customer: document.getElementById("fb_customer").value,
          lang: document.getElementById("fb_lang").value,
        },
      };
      const r = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.text();
        console.error("SAVE failed:", err);
        alert("Lỗi lưu nội dung.");
        return;
      }
      showToast(`Đã lưu (FB Ads) lúc ${new Date().toLocaleString()}`);
      await loadSaved("fbads", "fb_saved_list");
      document
        .querySelector('.tabs[data-scope="fb"] .tab[data-tab="saved"]')
        .click();
    });

    // Download (FB Ads)
    document.getElementById("fb_download")?.addEventListener("click", () => {
      const el = document.getElementById("fb_result_md");
      const text = (el.dataset.md || el.textContent || "").trim();
      if (!text) {
        alert("Chưa có nội dung để tải.");
        return;
      }
      const product = document.getElementById("fb_product")?.value || "";
      const customer = document.getElementById("fb_customer")?.value || "";
      const title = summarizeTitle(text, { product_desc: product, customer }, "fbads", 60);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`fbads_${slug(title)}_${stamp}.txt`, text);
      showToast("Đang tải file .txt…");
    });
  }

  /* ===== Rephrase ===== */
  const btnRe = document.getElementById("re_generate");
  if (btnRe) {
    loadSaved("rephrase", "re_saved_list");

    btnRe.addEventListener("click", () =>
      withLoader(document.getElementById("re_form_card"), async () => {
        const src = document.getElementById("re_text").value.trim();
        if (!src) {
          alert("Vui lòng nhập đoạn văn.");
          return;
        }
        const lang = document.getElementById("re_lang").value;
        const tone = document.getElementById("re_tone").value;

        const r = await fetch("/api/rephrase", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text_src: src, lang, tone }),
        });
        const d = await r.json();
        if (d.error) {
          alert(d.error);
          return;
        }

        const out = document.getElementById("re_out");
        mdRenderTo(out, d.text || "");
        out.dataset.md = d.text || "";
        document
          .querySelector('.tabs[data-scope="re"] .tab[data-tab="result"]')
          .click();
      })
    );

    document.getElementById("re_copy")?.addEventListener("click", () =>
      copyFrom(document.getElementById("re_out"))
    );

    document.getElementById("re_save")?.addEventListener("click", async () => {
      const el = document.getElementById("re_out");
      const text = (el.dataset.md || "").trim();
      if (!text) {
        alert("Chưa có nội dung để lưu.");
        return;
      }
      await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "rephrase",
          text,
          input: {
            lang: document.getElementById("re_lang").value,
            tone: document.getElementById("re_tone").value,
            src: document.getElementById("re_text").value,
          },
        }),
      });
      showToast(`Đã lưu (Rephrase) lúc ${new Date().toLocaleString()}`);
      await loadSaved("rephrase", "re_saved_list");
      document
        .querySelector('.tabs[data-scope="re"] .tab[data-tab="saved"]')
        .click();
    });

    // Download (Rephrase)
    document.getElementById("re_download")?.addEventListener("click", () => {
      const el = document.getElementById("re_out");
      const text = (el.dataset.md || el.textContent || "").trim();
      if (!text) return alert("Chưa có nội dung để tải.");
      const title = summarizeTitle(text, { src: document.getElementById("re_text")?.value || "" }, "rephrase", 60);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`rephrase_${slug(title)}_${stamp}.txt`, text);
      showToast("Đang tải file .txt…");
    });
  }

  /* ===== TikTok ===== */
  const btnTk = document.getElementById("tk_generate");
  if (btnTk) {
    loadSaved("tiktok", "tk_saved_list");

    btnTk.addEventListener("click", () =>
      withLoader(document.getElementById("tk_form_card"), async () => {
        const brief = document.getElementById("tk_brief").value.trim();
        if (!brief) {
          alert("Vui lòng nhập nội dung kịch bản.");
          return;
        }
        const lang = document.getElementById("tk_lang").value;
        const duration = parseInt(document.getElementById("tk_duration").value, 10) || 20;
        const objective = document.getElementById("tk_objective").value;

        const r = await fetch("/api/tiktok", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brief, lang, duration, objective }),
        });
        const d = await r.json();
        if (d.error) {
          alert(d.error);
          return;
        }

        const out = document.getElementById("tk_out");
        mdRenderTo(out, d.text || "");
        out.dataset.md = d.text || "";
        document
          .querySelector('.tabs[data-scope="tk"] .tab[data-tab="result"]')
          .click();
      })
    );

    document.getElementById("tk_copy")?.addEventListener("click", () =>
      copyFrom(document.getElementById("tk_out"))
    );

    document.getElementById("tk_save")?.addEventListener("click", async () => {
      const el = document.getElementById("tk_out");
      const text = (el.dataset.md || "").trim();
      if (!text) {
        alert("Chưa có nội dung để lưu.");
        return;
      }
      await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "tiktok",
          text,
          input: {
            lang: document.getElementById("tk_lang").value,
            brief: document.getElementById("tk_brief").value,
            duration: document.getElementById("tk_duration").value,
            objective: document.getElementById("tk_objective").value,
          },
        }),
      });
      showToast(`Đã lưu (TikTok) lúc ${new Date().toLocaleString()}`);
      await loadSaved("tiktok", "tk_saved_list");
      document
        .querySelector('.tabs[data-scope="tk"] .tab[data-tab="saved"]')
        .click();
    });

    // Download (TikTok)
    document.getElementById("tk_download")?.addEventListener("click", () => {
      const el = document.getElementById("tk_out");
      const text = (el.dataset.md || el.textContent || "").trim();
      if (!text) return alert("Chưa có nội dung để tải.");
      const title = summarizeTitle(text, { brief: document.getElementById("tk_brief")?.value || "" }, "tiktok", 60);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`tiktok_${slug(title)}_${stamp}.txt`, text);
      showToast("Đang tải file .txt…");
    });
  }

  /* ===== FAB ===== */
  const btnFab = document.getElementById("fab_generate");
  if (btnFab) {
    loadSaved("fab", "fab_saved_list");

    btnFab.addEventListener("click", () =>
      withLoader(document.getElementById("fab_form_card"), async () => {
        const benefits = document.getElementById("fab_benefits").value.trim();
        if (!benefits) {
          alert("Vui lòng điền Lợi ích.");
          return;
        }
        const lang = document.getElementById("fab_lang").value;
        const extra = document.getElementById("fab_extra").value;

        const r = await fetch("/api/fab", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ benefits, lang, extra }),
        });
        const d = await r.json();
        if (d.error) {
          alert(d.error);
          return;
        }

        const out = document.getElementById("fab_out");
        mdRenderTo(out, d.text || "");
        out.dataset.md = d.text || "";
        document
          .querySelector('.tabs[data-scope="fab"] .tab[data-tab="result"]')
          .click();
      })
    );

    document.getElementById("fab_copy")?.addEventListener("click", () =>
      copyFrom(document.getElementById("fab_out"))
    );

    document.getElementById("fab_save")?.addEventListener("click", async () => {
      const el = document.getElementById("fab_out");
      const text = (el.dataset.md || "").trim();
      if (!text) {
        alert("Chưa có nội dung để lưu.");
        return;
      }
      await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "fab",
          text,
          input: {
            lang: document.getElementById("fab_lang").value,
            benefits: document.getElementById("fab_benefits").value,
            extra: document.getElementById("fab_extra").value,
          },
        }),
      });
      showToast(`Đã lưu (FAB) lúc ${new Date().toLocaleString()}`);
      await loadSaved("fab", "fab_saved_list");
      document
        .querySelector('.tabs[data-scope="fab"] .tab[data-tab="saved"]')
        .click();
    });

    // Download (FAB)
    document.getElementById("fab_download")?.addEventListener("click", () => {
      const el = document.getElementById("fab_out");
      const text = (el.dataset.md || el.textContent || "").trim();
      if (!text) return alert("Chưa có nội dung để tải.");
      const title = summarizeTitle(text, { benefits: document.getElementById("fab_benefits")?.value || "" }, "fab", 60);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`fab_${slug(title)}_${stamp}.txt`, text);
      showToast("Đang tải file .txt…");
    });
  }
});