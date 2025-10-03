/* main_MKT.js – FULL
   Mục tiêu: “Facebook Post” hiển thị 1 dòng/1 ý (không dính một khối <p>).
   Cơ chế: Preprocess Markdown → sửa HTML sau render → MutationObserver.
*/

/* =========================================================
 * Markdown render (kèm hậu xử lý HTML)
 * =======================================================*/
let _fbFixing = false; // chống vòng lặp khi MutationObserver kích hoạt

function forceFixFacebook(container) {
  if (!container || _fbFixing) return;
  _fbFixing = true;
  try {
    container.innerHTML = DOMPurify.sanitize(
      fixFacebookHTML(container.innerHTML)
    );
  } finally {
    _fbFixing = false;
  }
}

function mdRenderTo(el, mdText) {
  const pre = preprocessMarketingMarkdown(mdText || "");

  try {
    if (window.marked?.setOptions)
      marked.setOptions({ gfm: true, breaks: true });
  } catch {}

  // Render markdown → sửa trực tiếp phần Facebook Post
  let html0 = window.marked.parse(pre);
  html0 = fixFacebookHTML(html0);

  // Gắn vào DOM (sanitize)
  el.innerHTML = DOMPurify.sanitize(html0);

  // Highlight code nếu có
  el.querySelectorAll("pre code").forEach((b) =>
    window.hljs?.highlightElement(b)
  );

  // Pass 2 (sau khi DOM attach), phòng trường hợp lib/async can thiệp
  requestAnimationFrame(() => forceFixFacebook(el));
}

/* =========================================================
 * Tiền xử lý chuỗi Markdown
 * =======================================================*/
function preprocessMarketingMarkdown(src) {
  // Chuẩn hoá block Facebook Post → thêm hard-break “  \n” giữa các câu
  const processed = src.replace(
    /(\*\*Facebook Post:\*\*|\bFacebook Post:\s*)([\s\S]*?)(?=(?:\*\*IMAGE_PROMPT:\*\*|\bIMAGE_PROMPT:|\n{2,}|$))/i,
    (_, label, body) => `${label}\n${splitFbLines(body)}\n`
  );

  // IMAGE_PROMPT: chuẩn hoá, không đụng nội dung
  return processed.replace(
    /(\*\*IMAGE_PROMPT:\*\*|\bIMAGE_PROMPT:\s*)([^\n]+(?:\n(?!\*\*|\bFacebook Post:|\bIMAGE_PROMPT:)[^\n]+)*)/i,
    (_, label, body) => `${label}\n${(body || "").trim()}\n`
  );
}

// Bẻ dòng cho Facebook Post ở tầng chuỗi
function splitFbLines(body) {
  let text = (body || "").trim();
  if (!text) return "";

  // Cắt hashtag (nếu đặt cuối)
  let hashtags = "";
  const hi = text.lastIndexOf("#");
  if (hi >= 0) {
    hashtags = text.slice(hi).trim();
    text = text.slice(0, hi).trim();
  }

  // Nếu đã có newline -> giữ; nếu không -> tách theo emoji/bullet + dấu câu
  const parts = /\r?\n/.test(text)
    ? text
        .split(/\r?\n+/)
        .map((s) => s.trim())
        .filter(Boolean)
    : text
        .replace(/\s+(?=(?:👉|✨|🎉|✅|💖|🚀|⭐|🌟|🎇|🎆|•|-)\s*)/g, "\n")
        .replace(/^"|"$/g, "")
        .split(
          /(?<=[\.\!\?…])\s+(?=(?:[A-ZÀ-Ỵ0-9#@“"“”'(\[]|[\u{1F300}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}]))/u
        )
        .map((s) => s.trim())
        .filter(Boolean);

  const joined = parts.join("  \n"); // markdown hard-break -> <br>
  return hashtags ? `${joined}  \n${hashtags}` : joined;
}

/* =========================================================
 * Hậu xử lý: rebuild riêng block "Facebook Post"
 *  - Nhận cả "Facebook Post" có hoặc không dấu ":"; có/không <strong>.
 *  - Nếu label đứng riêng 1 thẻ -> nuốt thẻ kế tiếp làm body.
 * =======================================================*/
function fixFacebookHTML(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;

  const LABEL_HTML_FULL =
    /^\s*(?:<strong>\s*)?Facebook\s*Post\s*:?\s*(?:<\/strong>)?\s*$/i;
  const LABEL_AT_START_H =
    /^\s*(?:<strong>\s*)?Facebook\s*Post\s*:?\s*(?:<\/strong>)?\s*/i;
  const LABEL_AT_START_TX = /^Facebook\s*Post\s*:?\s*/i;

  // Quét cả p/div/li để không bỏ sót cấu trúc mà marked sinh ra
  const blocks = Array.from(tmp.querySelectorAll("p, div, li"));

  for (let i = 0; i < blocks.length; i++) {
    const node = blocks[i];
    const rawHTML = (node.innerHTML || "").trim().replace(/&nbsp;/g, " ");
    const rawText = (node.textContent || "").trim();

    const onlyLabel = LABEL_HTML_FULL.test(rawHTML);
    const startsWithLabel =
      LABEL_AT_START_H.test(rawHTML) || LABEL_AT_START_TX.test(rawText);

    if (!startsWithLabel) continue;

    // Lấy phần body: nếu label đứng riêng → lấy thẻ kế bên
    let bodyHTML = "";
    if (
      onlyLabel &&
      node.nextElementSibling &&
      /^(P|DIV|LI)$/.test(node.nextElementSibling.tagName)
    ) {
      bodyHTML = node.nextElementSibling.innerHTML;
      node.nextElementSibling.remove();
    } else {
      bodyHTML = rawHTML
        .replace(LABEL_AT_START_H, "")
        .replace(LABEL_AT_START_TX, "");
    }

    // Dựng lại block theo định dạng từng dòng
    const block = buildFbBlockHTML(bodyHTML);
    node.replaceWith(block);
  }

  return tmp.innerHTML;
}

// Dựng block hiển thị Facebook Post (mỗi ý 1 dòng + hashtag cuối)
function buildFbBlockHTML(bodyHTML) {
  let parts = [];
  if (/<br\s*\/?>/i.test(bodyHTML)) {
    parts = bodyHTML
      .split(/<br\s*\/?>/i)
      .map((s) => s.replace(/<[^>]+>/g, "").trim())
      .filter(Boolean);
  } else {
    const txt = bodyHTML.replace(/<[^>]+>/g, "").trim();
    parts = splitPlainTextToLines(txt);
  }

  // Hashtag cuối
  let hashtags = "";
  if (parts.length && /^#\S+/.test(parts[parts.length - 1])) {
    hashtags = parts.pop();
  }

  const wrap = document.createElement("div");
  wrap.className = "fb-block";
  wrap.innerHTML =
    `<strong>Facebook Post:</strong>` +
    `<div class="fb-lines">${parts
      .map((s) => `<div>${escapeHTML(s)}</div>`)
      .join("")}</div>` +
    (hashtags ? `<div class="hashtags">${escapeHTML(hashtags)}</div>` : "");

  return wrap;
}

function splitPlainTextToLines(text) {
  if (!text) return [];
  let t = text.trim();

  // Đã có newline -> tách theo newline
  if (/\r?\n/.test(t))
    return t
      .split(/\r?\n+/)
      .map((s) => s.trim())
      .filter(Boolean);

  // Tách theo emoji/bullet + dấu câu
  return t
    .replace(/\s+(?=(?:👉|✨|🎉|✅|💖|🚀|⭐|🌟|🎇|🎆|•|-)\s*)/g, "\n")
    .replace(/^"|"$/g, "")
    .split(
      /(?<=[\.\!\?…])\s+(?=(?:[A-ZÀ-Ỵ0-9#@“"“”'(\[]|[\u{1F300}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}]))/u
    )
    .map((s) => s.trim())
    .filter(Boolean);
}

function escapeHTML(s) {
  return s.replace(
    /[&<>"']/g,
    (m) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
        m
      ])
  );
}

/* =========================================================
 * Tabs / Helpers / Save-Download
 * =======================================================*/
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
function _pickKeySentence(t) {
  const s = _stripMarkdown(t)
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean);
  return s[0] || "";
}
function _truncate(s, n = 80) {
  return s && s.length > n ? s.slice(0, n - 1) + "…" : s || "";
}
function summarizeTitle(md, input = null, type = "", maxLen = 80) {
  if (input && type === "fbads" && (input.product_desc || input.customer)) {
    const p = (input.product_desc || "").trim(),
      c = (input.customer || "").trim();
    if (p || c) return _truncate(`FB Ads – ${p}${c ? " → " + c : ""}`, maxLen);
  }
  const h = _pickHeading(md);
  if (h) return _truncate(h, maxLen);
  return _truncate(_pickKeySentence(md), maxLen) || "Nội dung đã lưu";
}

/* =========================================================
 * Saved list (đủ dùng)
 * =======================================================*/
async function loadSaved(type, targetId) {
  const res = await fetch(`/api/saves?type=${encodeURIComponent(type)}`).catch(
    () => null
  );
  const data = (await res?.json().catch(() => ({ items: [] }))) || {
    items: [],
  };
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
    left.style.alignItems = "center";
    left.style.flexWrap = "wrap";
    const title = document.createElement("div");
    title.className = "item-title";
    title.textContent = summarizeTitle(
      it.text || "",
      it.input || null,
      type,
      80
    );
    const time = document.createElement("div");
    time.className = "item-time";
    left.append(title, time);

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
      if (e.target.closest("button")) return;
      wrap.classList.toggle("open");
      if (wrap.classList.contains("open")) renderIfNeeded();
    });
    bCopy.addEventListener("click", (e) => {
      e.stopPropagation();
      renderIfNeeded();
      copyFrom(md);
      showToast("Đã sao chép.");
    });
    bDown.addEventListener("click", (e) => {
      e.stopPropagation();
      const titleTxt = summarizeTitle(
        it.text || "",
        it.input || null,
        type,
        60
      );
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

/* =========================================================
 * Page wiring
 * =======================================================*/
document.addEventListener("DOMContentLoaded", () => {
  attachTabs();

  // Quan sát #fb_result_md để auto-fix nếu nội dung đổi
  const root = document.getElementById("fb_result_md");
  if (root) {
    const mo = new MutationObserver(() => {
      if (_fbFixing) return; // chống vòng lặp
      forceFixFacebook(root);
    });
    mo.observe(root, { childList: true, subtree: true });
  }

  /* ===== Facebook Ads ===== */
  const btnFb = document.getElementById("fb_generate");
  if (btnFb) {
    loadSaved("fbads", "fb_saved_list");

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

        // 1) TEXT
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
        if (!r1.ok) return alert("Lỗi tạo nội dung (TEXT).");
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

        // 2) IMAGES
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

        const r2 = await fetch("/api/fbads/generate_images", {
          method: "POST",
          body: fd,
        }).catch(() => null);
        const d2 = await r2?.json().catch(() => null);

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

    document
      .getElementById("fb_copy")
      ?.addEventListener("click", () =>
        copyFrom(document.getElementById("fb_result_md"))
      );

    document.getElementById("fb_save")?.addEventListener("click", async () => {
      const el = document.getElementById("fb_result_md");
      const text = (el.dataset.md || "").trim();
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
      await loadSaved("fbads", "fb_saved_list");
      document
        .querySelector('.tabs[data-scope="fb"] .tab[data-tab="saved"]')
        ?.click();
    });

    document.getElementById("fb_download")?.addEventListener("click", () => {
      const el = document.getElementById("fb_result_md");
      const text = (el.dataset.md || el.textContent || "").trim();
      if (!text) return alert("Chưa có nội dung để tải.");
      const title = summarizeTitle(text, null, "fbads", 60);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadTxt(`fbads_${slug(title)}_${stamp}.txt`, text);
      showToast("Đang tải file .txt…");
    });
  }
});
