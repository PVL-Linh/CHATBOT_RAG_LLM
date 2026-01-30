/* main_MKT.js — SAFE_6 (unified for marketing + rephrase + tiktok + fab)
   - Không phụ thuộc bootstrap (có guard nếu tooltip được gọi ở nơi khác)
   - Không dùng regex phức tạp
   - Gọi đúng API backend đã có
*/

console.log("main_MKT.js SAFE_6 loaded");

/* =========================
 * Tiny bootstrap guard (no error if not loaded)
 * ========================= */
document.addEventListener("DOMContentLoaded", () => {
  try {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
      if (window.bootstrap?.Tooltip) new bootstrap.Tooltip(el);
    });
  } catch (e) {
    console.warn("Tooltip init skipped:", e);
  }
});

/* =========================
 * Markdown render (simple + safe)
 * ========================= */
function mdRenderTo(el, mdText) {
  if (!el) return;
  try {
    if (window.marked?.setOptions)
      marked.setOptions({ gfm: true, breaks: true });
  } catch {}
  let html = "";
  try {
    html =
      typeof marked?.parse === "function"
        ? marked.parse(mdText || "")
        : typeof marked === "function"
        ? marked(mdText || "")
        : (mdText || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\n/g, "<br>");
  } catch {
    html = (mdText || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");
  }
  el.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;

  // code highlight nếu có
  try {
    el.querySelectorAll("pre code").forEach((b) =>
      window.hljs?.highlightElement?.(b)
    );
  } catch {}
}

/* =========================
 * UI helpers
 * ========================= */
function attachTabs() {
  document.querySelectorAll(".tabs").forEach((tabs) => {
    const scope = tabs.dataset.scope;
    const panels = tabs.parentElement.querySelectorAll(".tab-panel");
    tabs.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs
          .querySelectorAll(".tab")
          .forEach((t) => t.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const id = tab.dataset.tab;
        tabs.parentElement
          .querySelector(`#${scope}_${id}`)
          ?.classList.add("active");
      });
    });
  });
}

async function withLoader(cardEl, fn) {
  const layer = cardEl?.querySelector?.(".local-loader");
  if (layer) layer.classList.remove("hidden");
  try {
    return await fn();
  } catch (err) {
    console.error(err);
    throw err;
  } finally {
    if (layer) layer.classList.add("hidden");
  }
}

function copyFrom(el) {
  const ta = document.createElement("textarea");
  ta.value = el?.innerText || el?.textContent || "";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

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
    ((s || "").toLowerCase().normalize
      ? (s || "")
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "")
      : (s || "").toLowerCase()
    )
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

/* =========================
 * Simple title summarizer for downloads/saves
 * ========================= */
function summarizeTitle(md, input = null, type = "", maxLen = 80) {
  if (input && type === "fbads" && (input.product_desc || input.customer)) {
    const p = (input.product_desc || "").trim();
    const c = (input.customer || "").trim();
    const t = `FB Ads – ${p}${c ? " → " + c : ""}`;
    return t.length > maxLen ? t.slice(0, maxLen - 1) + "…" : t;
  }
  const first = (md || "").split("\n").find((l) => l.trim()) || "Nội dung";
  return first.length > maxLen ? first.slice(0, maxLen - 1) + "…" : first;
}

/* =========================
 * Facebook Content page
 * ========================= */
async function initFacebookPage() {
  const btnFb = document.getElementById("fb_generate");
  if (!btnFb) return; // không ở trang Facebook

  console.log("init: Facebook Content page");
  attachTabs();

  // copy/save/download
  document
    .getElementById("fb_copy")
    ?.addEventListener("click", () =>
      copyFrom(document.getElementById("fb_result_md"))
    );
  document.getElementById("fb_save")?.addEventListener("click", async () => {
    const el = document.getElementById("fb_result_md");
    const text = (el?.dataset?.md || "").trim();
    if (!text) return alert("Chưa có nội dung để lưu.");
    await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: "fbads",
        text,
        input: {
          product_desc: document.getElementById("fb_product").value,
          customer: document.getElementById("fb_customer").value,
          lang: document.getElementById("fb_lang").value,
        },
      }),
    });
    showToast("Đã lưu (FB Ads).");
  });
  document.getElementById("fb_download")?.addEventListener("click", () => {
    const el = document.getElementById("fb_result_md");
    const text = (el?.dataset?.md || el?.textContent || "").trim();
    if (!text) return alert("Chưa có nội dung để tải.");
    const title = summarizeTitle(text, null, "fbads", 60);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadTxt(`fbads_${slug(title)}_${stamp}.txt`, text);
    showToast("Đang tải file .txt…");
  });

  // main click
  btnFb.addEventListener("click", () =>
    withLoader(document.getElementById("fb_form_card"), async () => {
      const product = document.getElementById("fb_product").value.trim();
      const customer = document.getElementById("fb_customer").value.trim();
      if (!product || !customer)
        return alert("Vui lòng nhập đầy đủ mô tả & chân dung.");

      const lang = document.getElementById("fb_lang").value;
      const brand = (
        document.getElementById("fb_brand")?.value || "Tiximax Logistics"
      ).trim();
      const tone = document.getElementById("fb_tone").value;

      // STEP 1: TEXT
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
        const err = await r1.text().catch(() => "");
        console.error("TEXT API error:", r1.status, err);
        return alert("Lỗi tạo nội dung (TEXT).");
      }
      const d1 = await r1.json();
      if (d1.error) return alert(d1.error);

      const out = document.getElementById("fb_result_md");
      mdRenderTo(out, d1.text || "");
      out.dataset.md = d1.text || "";

      document.getElementById("fb_meta").textContent = `LLM: ${
        d1.meta?.latency_sec || 0
      }s • Brand: ${brand} • Tone: ${tone}`;
      document
        .querySelector('.tabs[data-scope="fb"] .tab[data-tab="result"]')
        ?.click();

      // STEP 2: IMAGES
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
      fd.append(
        "keep_logo_original",
        document.getElementById("fb_keep_logo").checked
      );
      fd.append(
        "logo_scale",
        parseFloat(document.getElementById("fb_logo_scale").value) / 100.0
      );
      fd.append(
        "logo_margin",
        parseInt(document.getElementById("fb_logo_margin").value, 10)
      );
      fd.append("logo_pos", document.getElementById("fb_logo_pos").value);

      const lf = document.getElementById("fb_logo_file").files[0];
      if (addLogo && lf) fd.append("logo_file", lf);

      let d2 = null;
      try {
        const r2 = await fetch("/api/fbads/generate_images", {
          method: "POST",
          body: fd,
        });
        d2 = await r2.json();
      } catch (e) {
        console.warn("Image API warn:", e);
      }

      const grid = document.getElementById("fb_img_grid");
      grid.innerHTML = "";
      if (d2?.images?.length) {
        document.getElementById("fb_used_prompt").textContent =
          d2.used_prompt || "";
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
        document
          .querySelector('.tabs[data-scope="fb"] .tab[data-tab="images"]')
          ?.click();
      }
    })
  );
}

/* =========================
 * Rephrase page
 * ========================= */
function initRephrasePage() {
  const btn = document.getElementById("re_generate");
  if (!btn) return; // không ở trang rephrase

  console.log("init: Rephrase page");
  attachTabs();

  btn.addEventListener("click", async () => {
    const card = document.getElementById("re_form_card");
    await withLoader(card, async () => {
      const text = document.getElementById("re_text").value.trim();
      if (!text) return alert("Vui lòng nhập nội dung.");
      const lang = document.getElementById("re_lang").value;
      const tone = document.getElementById("re_tone").value;

      const r = await fetch("/api/rephrase", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text_src: text, lang, tone }),
      });
      if (!r.ok) return alert("Lỗi /api/rephrase");
      const d = await r.json();
      if (d.error) return alert(d.error);

      const out = document.getElementById("re_out");
      mdRenderTo(out, d.text || "");
      out.dataset.md = d.text || "";
    });
  });

  document
    .getElementById("re_copy")
    ?.addEventListener("click", () =>
      copyFrom(document.getElementById("re_out"))
    );
  document.getElementById("re_download")?.addEventListener("click", () => {
    const el = document.getElementById("re_out");
    const text = (el?.dataset?.md || el?.textContent || "").trim();
    if (!text) return alert("Chưa có nội dung để tải.");
    const title = summarizeTitle(text, null, "re", 60);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadTxt(`rephrase_${slug(title)}_${stamp}.txt`, text);
  });
}

/* =========================
 * TikTok page
 * ========================= */
function initTikTokPage() {
  const btn = document.getElementById("tk_generate");
  if (!btn) return; // không ở trang tiktok

  console.log("init: TikTok page");
  attachTabs();

  btn.addEventListener("click", async () => {
    const card = document.getElementById("tk_form_card");
    await withLoader(card, async () => {
      const brief = document.getElementById("tk_brief").value.trim();
      if (!brief) return alert("Vui lòng nhập brief.");
      const lang = document.getElementById("tk_lang").value;
      const duration = parseInt(
        document.getElementById("tk_duration").value || "20",
        10
      );
      const objective = document.getElementById("tk_objective").value;

      const r = await fetch("/api/tiktok", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief, lang, duration, objective }),
      });
      if (!r.ok) return alert("Lỗi /api/tiktok");
      const d = await r.json();
      if (d.error) return alert(d.error);

      const out = document.getElementById("tk_out");
      mdRenderTo(out, d.text || "");
      out.dataset.md = d.text || "";
    });
  });

  document
    .getElementById("tk_copy")
    ?.addEventListener("click", () =>
      copyFrom(document.getElementById("tk_out"))
    );
  document.getElementById("tk_download")?.addEventListener("click", () => {
    const el = document.getElementById("tk_out");
    const text = (el?.dataset?.md || el?.textContent || "").trim();
    if (!text) return alert("Chưa có nội dung để tải.");
    const title = summarizeTitle(text, null, "tiktok", 60);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadTxt(`tiktok_${slug(title)}_${stamp}.txt`, text);
  });
}

/* =========================
 * FAB page
 * ========================= */
function initFabPage() {
  const btn = document.getElementById("fab_generate");
  if (!btn) return; // không ở trang fab

  console.log("init: FAB page");
  attachTabs();

  btn.addEventListener("click", async () => {
    const card = document.getElementById("fab_form_card");
    await withLoader(card, async () => {
      const benefits = document.getElementById("fab_benefits").value.trim();
      if (!benefits) return alert("Vui lòng nhập lợi ích.");
      const lang = document.getElementById("fab_lang").value;
      const extra = (document.getElementById("fab_extra")?.value || "").trim();

      const r = await fetch("/api/fab", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ benefits, lang, extra }),
      });
      if (!r.ok) return alert("Lỗi /api/fab");
      const d = await r.json();
      if (d.error) return alert(d.error);

      const out = document.getElementById("fab_out");
      mdRenderTo(out, d.text || "");
      out.dataset.md = d.text || "";
    });
  });

  document
    .getElementById("fab_copy")
    ?.addEventListener("click", () =>
      copyFrom(document.getElementById("fab_out"))
    );
  document.getElementById("fab_download")?.addEventListener("click", () => {
    const el = document.getElementById("fab_out");
    const text = (el?.dataset?.md || el?.textContent || "").trim();
    if (!text) return alert("Chưa có nội dung để tải.");
    const title = summarizeTitle(text, null, "fab", 60);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadTxt(`fab_${slug(title)}_${stamp}.txt`, text);
  });
}

/* =========================
 * Boot
 * ========================= */
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM ready (SAFE_6)");
  // Trang nào có ID nào sẽ tự khởi tạo trang đó
  initFacebookPage();
  initRephrasePage();
  initTikTokPage();
  initFabPage();
});
