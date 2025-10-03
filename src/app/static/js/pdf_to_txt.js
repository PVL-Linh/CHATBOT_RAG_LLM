// static/js/pdf_to_txt.js
document.addEventListener("DOMContentLoaded", () => {
  const els = {
    file: document.getElementById("pdf_file"),
    convertBtn: document.getElementById("pdf_convert"),
    status: document.getElementById("pdf_status"),
    out: document.getElementById("pdf_out"),
    copyBtn: document.getElementById("pdf_copy"),
    saveBtn: document.getElementById("pdf_save"),
    downloadBtn: document.getElementById("pdf_download"),
    histRefresh: document.getElementById("pdf_hist_refresh"),
    histList: document.getElementById("pdf_history_list"),
    card: document.getElementById("pdf_form_card"),
    progress: document.getElementById("pdf_progress"),
  };

  // Đường dẫn TXT tạm để nút Download hoạt động sau khi convert (chưa lưu lịch sử)
  let lastTmpPath = null;

  // Trạng thái để đảm bảo "Lưu đúng 1 lần"
  let saving = false;            // đang lưu
  let dirty = false;             // nội dung đã thay đổi kể từ lần lưu gần nhất?
  let lastSavedHash = null;      // fingerprint nội dung đã lưu

  // ----------------
  // Helpers
  // ----------------
  function showLoader(on) {
    const loader = els.card?.querySelector(".local-loader");
    if (!loader) return;
    loader.classList.toggle("hidden", !on);
  }

  function setStatus(msg, ok = true) {
    if (!els.status) return;
    els.status.style.display = "block";
    els.status.textContent = msg || "";
    els.status.className = "pdf-status " + (ok ? "ok" : "err");
  }

  function attachDownload(path) {
    els.downloadBtn.onclick = () => {
      if (!path) {
        setStatus("Không có file để tải.", false);
        return;
      }
      const url = "/api/pdf_to_txt/download?path=" + encodeURIComponent(path);
      window.open(url, "_blank");
    };
  }

  function escapeHtml(s = "") {
    return s
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }
  function formatTime(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  }

  // Fingerprint nhanh cho nội dung để chặn lưu trùng
  function hashCode(str = "") {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = ((h << 5) - h + str.charCodeAt(i)) | 0;
    }
    return String(h);
  }

  function markDirty() {
    dirty = true;
    lastSavedHash = null;
    if (els.saveBtn) {
      els.saveBtn.removeAttribute("disabled");
      els.saveBtn.classList.remove("is-saved");
    }
  }

  function markSaved(currentHash) {
    dirty = false;
    lastSavedHash = currentHash || null;
    if (els.saveBtn) {
      els.saveBtn.setAttribute("disabled", "disabled");
      els.saveBtn.classList.add("is-saved");
    }
  }

  // ----------------
  // Convert (KHÔNG tự động lưu lịch sử)
  // ----------------
  async function convert() {
    if (!els.file?.files?.length) {
      setStatus("Vui lòng chọn file PDF.", false);
      return;
    }
    const fd = new FormData();
    fd.append("file", els.file.files[0]);

    showLoader(true);
    setStatus("Đang xử lý...");
    els.out.textContent = "";
    lastTmpPath = null;
    attachDownload(null);

    try {
      const r = await fetch("/api/pdf_to_txt", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || "Lỗi không rõ");

      els.out.textContent = data.text || "";
      setStatus("Hoàn tất. (Chưa lưu)");
      lastTmpPath = data.txt_path || null; // có thể là tệp tạm (không vào history)
      attachDownload(lastTmpPath);

      // Nội dung mới -> cho phép Lưu (1 lần)
      markDirty();
    } catch (e) {
      setStatus("Lỗi: " + e.message, false);
    } finally {
      showLoader(false);
    }
  }

  // ----------------
  // Save (bấm Lưu mới ghi; chặn lưu trùng nội dung)
  // ----------------
  async function saveCurrent(ev) {
    ev?.preventDefault?.();

    // ép nút Save là type="button"
    if (els.saveBtn && els.saveBtn.type !== "button") {
      try { els.saveBtn.type = "button"; } catch { /* ignore */ }
    }

    if (saving) return;           // đang lưu dở
    const text = els.out.textContent || "";
    if (!text.trim()) {
      setStatus("Không có nội dung để lưu.", false);
      return;
    }

    // Nếu nội dung chưa thay đổi kể từ lần lưu gần nhất -> bỏ qua
    const baseName = els.file?.files?.[0]?.name || "manual_note";
    const currentHash = hashCode(baseName + "::" + text);

    if (!dirty || currentHash === lastSavedHash) {
      setStatus("Nội dung này đã được lưu rồi.", false);
      markSaved(currentHash);
      return;
    }

    // Chốt "lưu 1 lần": disable nút + cờ saving
    saving = true;
    els.saveBtn?.setAttribute("disabled", "disabled");

    try {
      const r = await fetch("/api/pdf_to_txt/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, base_name: baseName }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || "Save failed");

      setStatus("Đã lưu vào Lịch sử.");
      if (data.txt_path) {
        lastTmpPath = data.txt_path;
        attachDownload(lastTmpPath);
      }
      markSaved(currentHash);
      await loadHistory(); // refresh danh sách sau khi lưu
    } catch (e) {
      setStatus("Lưu thất bại: " + e.message, false);
      // cho phép bấm lại nếu lỗi
      els.saveBtn?.removeAttribute("disabled");
    } finally {
      saving = false;
    }
  }

  // ----------------
  // History
  // ----------------
  async function loadHistory() {
    try {
      const r = await fetch("/api/pdf_to_txt/history?limit=50");
      const data = await r.json();
      const items = (data && data.items) || [];
      renderHistory(items);
    } catch (e) {
      // im lặng
    }
  }

  // Helper: toggle accordion với animation mượt
  function togglePreview(row, preview) {
    const isOpen = row.classList.contains("open");
    if (isOpen) {
      preview.style.maxHeight = "0px";
      row.classList.remove("open");
    } else {
      // mở
      // Đặt tạm maxHeight = scrollHeight (bị giới hạn bởi CSS nếu quá cao)
      const max = preview.scrollHeight;
      preview.style.maxHeight = max + "px";
      row.classList.add("open");
    }
  }

  function renderHistory(items) {
    els.histList.innerHTML = "";
    if (!items.length) {
      els.histList.innerHTML = `<div class="empty">Chưa có lịch sử.</div>`;
      return;
    }
    const frag = document.createDocumentFragment();

    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "hist-item";

      // lấy path từ download_url an toàn
      let itemPath = "";
      try {
        const u = new URL(it.download_url, location.origin);
        itemPath = u.searchParams.get("path") || "";
      } catch (_) {}

      row.innerHTML = `
        <div class="meta">
          <button class="name-link" type="button" title="Nhấn để xem nội dung">
            ${escapeHtml(it.name)}
          </button>
          <div class="sub">${formatSize(it.size)} · ${formatTime(it.mtime)}</div>
        </div>
        <div class="actions">
          <button class="btn-ghost" data-act="dl" title="Tải xuống">📥</button>
          <button class="btn-ghost" data-act="del" title="Xóa">🗑️</button>
        </div>
        <div class="preview">
          <pre class="preview-text"></pre>
        </div>
      `;

      const nameBtn = row.querySelector(".name-link");
      const preview = row.querySelector(".preview");
      const pre = row.querySelector(".preview-text");

      // Khởi tạo trạng thái đóng
      preview.style.maxHeight = "0px";

      // Toggle xem nội dung khi click vào tên (accordion)
      nameBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        const willOpen = !row.classList.contains("open");

        if (willOpen && !row.dataset.loaded) {
          pre.textContent = "Đang tải...";
          try {
            const url = "/api/pdf_to_txt/download?path=" + encodeURIComponent(itemPath);
            const res = await fetch(url);
            const text = await res.text();
            pre.textContent = text || "(trống)";
            row.dataset.loaded = "1";

            // Sau khi có nội dung, tính lại chiều cao để mở mượt
            requestAnimationFrame(() => {
              // ép tính scrollHeight mới
              preview.style.maxHeight = preview.scrollHeight + "px";
            });
          } catch {
            pre.textContent = "Không mở được tệp.";
          }
        }

        togglePreview(row, preview);
      });

      // Download
      row.querySelector('[data-act="dl"]').onclick = () => {
        window.open(it.download_url, "_blank");
      };

      // Delete
      row.querySelector('[data-act="del"]').onclick = async () => {
        if (!confirm("Xóa file này?")) return;
        try {
          const r = await fetch("/api/pdf_to_txt/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: it.name }),
          });
          const d = await r.json();
          if (!r.ok || d.error) throw new Error(d.error || "Delete failed");
          await loadHistory();
          setStatus("Đã xóa.");
        } catch (e) {
          setStatus("Xóa thất bại: " + e.message, false);
        }
      };

      frag.appendChild(row);
    });

    els.histList.appendChild(frag);
  }

  // ----------------
  // Bind events
  // ----------------
  if (els.convertBtn && !els.convertBtn.dataset.bound) {
    els.convertBtn.addEventListener("click", (ev) => { ev?.preventDefault?.(); convert(); });
    els.convertBtn.dataset.bound = "1";
  }

  if (els.saveBtn && !els.saveBtn.dataset.bound) {
    try { if (els.saveBtn.type !== "button") els.saveBtn.type = "button"; } catch {}
    els.saveBtn.addEventListener("click", saveCurrent);
    els.saveBtn.dataset.bound = "1";

    // Chặn submit form cha nếu có
    const form = els.saveBtn.closest("form");
    if (form && !form.dataset.nosubmit) {
      form.addEventListener("submit", (e) => e.preventDefault());
      form.dataset.nosubmit = "1";
    }
  }

  els.copyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.out.textContent || "");
      setStatus("Đã sao chép.");
    } catch {
      setStatus("Không sao chép được.", false);
    }
  });

  els.downloadBtn?.addEventListener("click", () => attachDownload(lastTmpPath));
  els.histRefresh?.addEventListener("click", loadHistory);

  // Tab pills (nếu dùng)
  const pills = document.querySelectorAll('.pill-tabs[data-scope="pdf"] .pill');
  const resultTab = document.getElementById("pdf_tab_result");
  const historyTab = document.getElementById("pdf_tab_history");
  function activate(tab) {
    pills.forEach((p) => p.classList.toggle("active", p.dataset.tab === tab));
    resultTab?.classList.toggle("active", tab === "result");
    historyTab?.classList.toggle("active", tab === "history");
  }
  pills.forEach((p) => p.addEventListener("click", () => activate(p.dataset.tab)));

  // Lần đầu tải lịch sử
  loadHistory();
});
