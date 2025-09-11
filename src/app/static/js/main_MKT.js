/* app/static/js/main_MKT.js */
/* eslint-disable no-console */
(() => {
  "use strict";

  const STORAGE_KEY = "txm_fb_saved_v1";
  const byId = (id) => document.getElementById(id);

  // ---------- Tabs ----------
  function setActiveTab(name) {
    const tabsRoot = document.querySelector('.tabs[data-scope="fb"]');
    if (!tabsRoot) return;
    tabsRoot.querySelectorAll(".tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === name);
    });
    ["fb_result", "fb_images", "fb_saved"].forEach((pid) => {
      const el = byId(pid);
      if (el) el.classList.toggle("active", pid === `fb_${name}`);
    });
    if (name === "saved") renderSavedList();
  }

  async function withLoader(cardEl, task) {
    const loader = cardEl?.querySelector?.(".local-loader");
    try {
      if (loader) loader.style.display = "flex";
      return await task();
    } finally {
      if (loader) loader.style.display = "none";
    }
  }

  function mdRenderTo(el, text) {
    if (!el) return;
    try {
      if (window.DOMPurify && window.marked) {
        el.innerHTML = window.DOMPurify.sanitize(
          window.marked.parse(text || "")
        );
      } else el.textContent = text || "";
    } catch {
      el.textContent = text || "";
    }
  }

  function toast(msg) {
    try {
      window
        .Toastify?.({
          text: msg,
          duration: 2200,
          gravity: "top",
          position: "right",
        })
        .showToast();
    } catch {}
    console.log(msg);
  }

  function inferOutputFormatFromFile(f) {
    const mime = (f?.type || "").toLowerCase();
    const name = (f?.name || "").toLowerCase();
    if (
      mime.includes("jpeg") ||
      mime.includes("jpg") ||
      name.endsWith(".jpg") ||
      name.endsWith(".jpeg")
    )
      return "jpeg";
    if (mime.includes("webp") || name.endsWith(".webp")) return "webp";
    if (mime.includes("png") || name.endsWith(".png")) return "png";
    return "png";
  }

  function getVal(el, def = "") {
    return (el?.value ?? def).toString();
  }
  function parsePercentToFloat(pctStr, def = 0.15) {
    const n = parseFloat(pctStr);
    return Number.isFinite(n) ? n / 100 : def;
  }
  function parseIntSafe(v, def = 20) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : def;
  }

  function renderImages(b64List, fmt) {
    const grid = byId("fb_img_grid");
    if (!grid) return;
    grid.innerHTML = "";
    if (!Array.isArray(b64List) || b64List.length === 0) return;
    const ext = (fmt || "png").toLowerCase();

    b64List.forEach((b64, i) => {
      const wrap = document.createElement("div");
      wrap.className = "img-item";

      const img = new Image();
      img.src = `data:image/${ext};base64,${b64}`;
      img.alt = `Kết quả ${i + 1}`;
      img.style.maxWidth = "100%";
      img.style.height = "auto";
      img.loading = "lazy";

      const a = document.createElement("a");
      a.href = img.src;
      a.download = `tiximax_fbads_${Date.now()}_${i + 1}.${ext}`;
      a.textContent = "Tải về";

      wrap.append(img, a);
      grid.appendChild(wrap);
    });
  }

  // ---------- Saved (LocalStorage) ----------
  function getSaved() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  }
  function setSaved(items) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch (e) {
      toast("Không thể lưu: bộ nhớ trình duyệt đã đầy.");
    }
  }
  function renderSavedList() {
    const wrap = byId("fb_saved_list");
    if (!wrap) return;
    const items = getSaved();
    wrap.innerHTML = "";
    if (!items.length) {
      wrap.innerHTML = `<div style="opacity:.7">Chưa có mục đã lưu.</div>`;
      return;
    }
    items
      .slice()
      .reverse()
      .forEach((it, idx) => {
        const i = items.length - 1 - idx;
        const card = document.createElement("div");
        card.className = "saved-item";
        card.style.cssText =
          "border:1px solid #243044;border-radius:8px;padding:10px;margin-bottom:10px;";
        const time = new Date(it.ts || Date.now()).toLocaleString();
        const head = document.createElement("div");
        head.style.cssText =
          "display:flex;justify-content:space-between;align-items:center;";
        head.innerHTML = `<strong>${
          it.meta?.flow || "Saved item"
        }</strong><span style="opacity:.7">${time}</span>`;
        const body = document.createElement("div");
        body.style.cssText =
          "display:grid;grid-template-columns:120px 1fr;gap:10px;";
        const img = new Image();
        img.style.width = "120px";
        img.style.objectFit = "cover";
        if (it.images?.length) {
          const ext = (it.meta?.format || "png").toLowerCase();
          img.src = `data:image/${ext};base64,${it.images[0]}`;
        }
        const pre = document.createElement("pre");
        pre.style.cssText =
          "margin:0;white-space:pre-wrap;max-height:140px;overflow:auto;";
        pre.textContent = it.text || "";
        body.append(img, pre);
        const actions = document.createElement("div");
        actions.style.marginTop = "8px";
        const br = document.createElement("button");
        br.className = "btn-ghost";
        br.textContent = "Khôi phục";
        br.onclick = () => {
          lastResult = it;
          mdRenderTo(byId("fb_result_md"), it.text || "");
          renderImages(it.images || [], it.meta?.format || "png");
          setActiveTab(it.images?.length ? "images" : "result");
          toast("Đã khôi phục mục đã lưu.");
        };
        const bd = document.createElement("button");
        bd.className = "btn-ghost";
        bd.style.marginLeft = "8px";
        bd.textContent = "Xoá";
        bd.onclick = () => {
          const arr = getSaved();
          arr.splice(i, 1);
          setSaved(arr);
          renderSavedList();
          toast("Đã xoá mục đã lưu.");
        };
        actions.append(br, bd);
        card.append(head, body, actions);
        wrap.appendChild(card);
      });
  }

  function doCopyCaption() {
    const t = (lastResult.text || "").trim();
    if (!t) return toast("Chưa có nội dung để sao chép.");
    navigator.clipboard
      .writeText(t)
      .then(() => toast("Đã sao chép caption."))
      .catch(() => toast("Không thể sao chép."));
  }
  function doSaveCurrent() {
    const it = {
      ts: Date.now(),
      text: lastResult.text || "",
      images: Array.isArray(lastResult.images)
        ? lastResult.images.slice(0, 1)
        : [],
      meta: lastResult.meta || {},
    };
    const arr = getSaved();
    arr.push(it);
    setSaved(arr);
    toast("Đã lưu vào History.");
  }
  function doDownload() {
    const txt = (lastResult.text || "").trim();
    if (txt) {
      const blob = new Blob([txt], { type: "text/markdown;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `caption_${Date.now()}.md`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
    if (lastResult.images?.length) {
      const ext = (lastResult.meta?.format || "png").toLowerCase();
      const a = document.createElement("a");
      a.href = `data:image/${ext};base64,${lastResult.images[0]}`;
      a.download = `image_${Date.now()}.${ext}`;
      document.body.append(a);
      a.click();
      a.remove();
    }
    if (!txt && !lastResult.images?.length) toast("Không có gì để tải về.");
    else toast("Đã tải caption / ảnh.");
  }

  // ---------- APIs (CÓ ẢNH) ----------
  async function apiOverlayExact(imgFile) {
    const fd = new FormData();
    fd.append("image_file", imgFile);
    // giữ đúng nhánh “có ảnh” của bạn (ghép logo)
    const addLogo = byId("fb_add_logo")?.checked ? "true" : "false";
    fd.append("add_logo", addLogo);
    fd.append(
      "logo_scale",
      String(parsePercentToFloat(getVal(byId("fb_logo_scale"), "15"), 0.15))
    );
    fd.append(
      "logo_margin",
      String(parseIntSafe(getVal(byId("fb_logo_margin"), "20"), 20))
    );
    // nếu bạn có logo_pos thì đọc; không có thì bỏ
    const posEl = byId("fb_logo_pos");
    if (posEl)
      fd.append("logo_pos", (getVal(posEl, "br") || "br").toLowerCase());
    const logoFile = byId("fb_logo_file")?.files?.[0];
    if (logoFile) fd.append("logo_file", logoFile);
    fd.append("output_format", inferOutputFormatFromFile(imgFile));

    const r = await fetch("/api/fbads/image_exact", {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`Lỗi overlay ${r.status}`);
    return r.json();
  }

  async function apiGenerateTextFromImage(imgFile) {
    const fd = new FormData();
    fd.append("image_file", imgFile);
    fd.append("product_desc", getVal(byId("fb_product"), ""));
    fd.append("customer", getVal(byId("fb_customer"), ""));
    fd.append("brand", getVal(byId("fb_brand"), "Tiximax Logistics"));
    fd.append("lang", getVal(byId("fb_lang"), "Tiếng Việt"));
    fd.append("tone", getVal(byId("fb_tone"), "Chuyên nghiệp"));

    // GỌI API MỚI: phân tích ảnh → dùng chung “logic” như api_fb_text
    const r = await fetch("/api/fbads/text_from_image_v2", {
      method: "POST",
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err?.error || `Lỗi phân tích/viết nội dung ${r.status}`);
    }
    return r.json();
  }

  // ---------- APIs (KHÔNG ẢNH) — dùng 2 API bạn yêu cầu ----------
  async function apiNoImage_GenerateText() {
    const payload = {
      product_desc: getVal(byId("fb_product"), "").trim(),
      customer: getVal(byId("fb_customer"), "").trim(),
      lang: getVal(byId("fb_lang"), "Tiếng Việt"),
      brand: getVal(byId("fb_brand"), "Tiximax Logistics"),
      tone: getVal(byId("fb_tone"), "Chuyên nghiệp"),
    };
    const r = await fetch("/api/fbads/generate_text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      // server của bạn trả 400 khi thiếu product/customer
      const err = await r.json().catch(() => ({}));
      throw new Error(err?.error || `Lỗi tạo nội dung ${r.status}`);
    }
    return r.json();
  }

  async function apiNoImage_GenerateImages(resultText) {
    const fd = new FormData();
    // BẮT BUỘC: gửi nguyên vẹn result_text để server tự extract IMAGE_PROMPT
    fd.append("result_text", resultText || "");

    // Thông tin phụ trợ (server có dùng build_image_prompt khi thiếu IMAGE_PROMPT)
    fd.append("product_desc", getVal(byId("fb_product"), ""));
    fd.append("customer", getVal(byId("fb_customer"), ""));
    fd.append("brand", getVal(byId("fb_brand"), "Tiximax Logistics"));

    // UI ảnh
    fd.append("engine_label", getVal(byId("fb_engine"), "Gemini 2.0 Flash"));
    fd.append("aspect", getVal(byId("fb_aspect"), "1:1"));
    fd.append("style_preset", getVal(byId("fb_style"), "Semi-realistic"));
    fd.append("composition", getVal(byId("fb_comp"), "Lifestyle scene"));

    // Logo options (đúng tên tham số API của bạn)
    const addLogo = byId("fb_add_logo")?.checked ? "true" : "false";
    const keepLogo = byId("fb_keep_logo")?.checked ? "true" : "false";
    fd.append("add_logo", addLogo);
    fd.append("keep_logo_original", keepLogo);
    fd.append(
      "logo_scale",
      String(parsePercentToFloat(getVal(byId("fb_logo_scale"), "15"), 0.15))
    );
    fd.append(
      "logo_margin",
      String(parseIntSafe(getVal(byId("fb_logo_margin"), "20"), 20))
    );
    const logoFile = byId("fb_logo_file")?.files?.[0];
    if (logoFile) fd.append("logo_file", logoFile);

    const r = await fetch("/api/fbads/generate_images", {
      method: "POST",
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err?.error || `Lỗi tạo ảnh ${r.status}`);
    }
    return r.json();
  }

  // ---------- Flows ----------
  let lastResult = { text: "", images: [], meta: {} };

  async function flowHasImage() {
    const img = byId("fb_image_file")?.files?.[0];
    if (!img) throw new Error("Vui lòng chọn ảnh sản phẩm.");
    const overlayRes = await apiOverlayExact(img);
    const textRes = await apiGenerateTextFromImage(img).catch(() => ({
      text: "",
    }));
    return {
      text: (textRes?.text || "").trim(),
      images: overlayRes?.images || [],
      meta: overlayRes?.meta || {},
    };
  }

  async function flowNoImage() {
    // 1) Tạo text theo template (có chứa IMAGE_PROMPT)
    const textRes = await apiNoImage_GenerateText();
    const fullText = (textRes?.text || "").trim();

    // 2) Gửi NGUYÊN VẸN text sang API ảnh (server sẽ tự extract IMAGE_PROMPT)
    const imgRes = await apiNoImage_GenerateImages(fullText);

    // Note: backend trả used_prompt (sau khi ensure tiếng Anh)
    if (byId("fb_used_prompt")) {
      byId("fb_used_prompt").textContent = imgRes?.used_prompt || "";
    }

    return {
      text: fullText,
      images: imgRes?.images || [],
      meta: { format: "png", flow: "no-image" },
    };
  }

  // ---------- Wire-up ----------
  document.addEventListener("DOMContentLoaded", () => {
    // Tabs click
    const tabsRoot = document.querySelector('.tabs[data-scope="fb"]');
    tabsRoot?.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".tab");
      if (!btn) return;
      const name = btn.dataset.tab;
      if (!name) return;
      setActiveTab(name);
    });

    // Generate
    // Generate — HIỂN THỊ TEXT TRƯỚC, ẢNH SAU
    byId("fb_generate")?.addEventListener("click", async () => {
      const card = byId("fb_form_card");
      const imgFile = byId("fb_image_file")?.files?.[0];
      const hasImage = !!imgFile;

      if (hasImage) {
        // CÓ ẢNH: chạy song song, nhưng ưu tiên hiển thị TEXT
        let pOverlay, pText;
        await withLoader(card, async () => {
          pOverlay = apiOverlayExact(imgFile); // bắt đầu overlay (không chặn UI)
          pText = apiGenerateTextFromImage(imgFile); // gọi text từ ảnh

          const textRes = await pText; // <- chờ TEXT thôi
          lastResult.text = (textRes?.text || "").trim();
          mdRenderTo(byId("fb_result_md"), lastResult.text);
          setActiveTab("result");
          toast("Đã tạo nội dung từ ảnh. Đang xử lý ảnh…");
        });

        // Sau khi loader đóng, cập nhật ảnh khi overlay xong
        try {
          const overlayRes = await pOverlay; // dùng promise đã khởi chạy
          lastResult.images = overlayRes?.images || [];
          lastResult.meta = overlayRes?.meta || {};
          renderImages(lastResult.images, lastResult?.meta?.format || "png");
          toast("Ảnh (đã ghép logo) sẵn sàng.");
        } catch (e) {
          console.error(e);
          toast("Ghép logo thất bại.");
        }
      } else {
        // KHÔNG ẢNH: hiển thị TEXT trước
        await withLoader(card, async () => {
          const textRes = await apiNoImage_GenerateText();
          lastResult.text = (textRes?.text || "").trim();
          mdRenderTo(byId("fb_result_md"), lastResult.text);
          setActiveTab("result");
          const up = byId("fb_used_prompt");
          if (up) up.textContent = "";
          toast("Đã tạo nội dung. Đang tạo ảnh…");
        });

        // Tạo ảnh SAU, không chặn UI
        (async () => {
          try {
            const imgRes = await apiNoImage_GenerateImages(lastResult.text);
            lastResult.images = imgRes?.images || [];
            lastResult.meta = {
              ...(lastResult.meta || {}),
              format: "png",
              flow: "no-image",
            };
            renderImages(lastResult.images, lastResult?.meta?.format || "png");
            const up = byId("fb_used_prompt");
            if (up) up.textContent = imgRes?.used_prompt || "";
            toast("Ảnh đã sẵn sàng.");
          } catch (e) {
            console.error(e);
            toast("Tạo ảnh thất bại.");
          }
        })();
      }
    });

    // Copy / Save / Download
    byId("fb_copy")?.addEventListener("click", doCopyCaption);
    byId("fb_save")?.addEventListener("click", doSaveCurrent);
    byId("fb_download")?.addEventListener("click", doDownload);

    setActiveTab("result");
  });
})();
