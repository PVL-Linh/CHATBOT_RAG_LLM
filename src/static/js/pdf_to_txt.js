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

  let lastTxtPath = null;

  function showLoader(on) {
    const loader = els.card.querySelector(".local-loader");
    if (!loader) return;
    loader.classList.toggle("hidden", !on);
  }

  function setStatus(msg, ok = true) {
    els.status.style.display = "block";
    els.status.textContent = msg || "";
    els.status.className = "pdf-status " + (ok ? "ok" : "err");
  }

  async function convert() {
    if (!els.file.files.length) {
      setStatus("Vui lòng chọn file PDF.", false);
      return;
    }
    const fd = new FormData();
    fd.append("file", els.file.files[0]);

    showLoader(true);
    setStatus("Đang xử lý...");
    els.out.textContent = "";
    lastTxtPath = null;

    try {
      const r = await fetch("/api/pdf_to_txt", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || "Lỗi không rõ");

      els.out.textContent = data.text || "";
      setStatus("Hoàn tất.");
      lastTxtPath = data.txt_path || null;

      // gán hành vi cho nút Download
      els.downloadBtn.onclick = () => {
        if (!lastTxtPath) return;
        const url =
          "/api/pdf_to_txt/download?path=" + encodeURIComponent(lastTxtPath);
        window.open(url, "_blank");
      };

      await loadHistory(); // cập nhật list
    } catch (e) {
      setStatus("Lỗi: " + e.message, false);
    } finally {
      showLoader(false);
    }
  }

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
      row.innerHTML = `
        <div class="meta">
          <div class="name">${it.name}</div>
          <div class="sub">${formatSize(it.size)} · ${formatTime(
        it.mtime
      )}</div>
        </div>
        <div class="actions">
          <button class="btn-ghost" data-act="view">👁️</button>
          <button class="btn-ghost" data-act="dl">📥</button>
          <button class="btn-ghost" data-act="del">🗑️</button>
        </div>
      `;
      row.querySelector('[data-act="view"]').onclick = async () => {
        // tải nội dung để xem
        try {
          const url =
            "/api/pdf_to_txt/download?path=" +
            encodeURIComponent(it.download_url.split("path=")[1]);
          const res = await fetch(url);
          const text = await res.text();
          els.out.textContent = text;
          lastTxtPath = decodeURIComponent(it.download_url.split("path=")[1]);
          setStatus("Đã mở từ History.");
        } catch (e) {
          setStatus("Không mở được file.", false);
        }
      };
      row.querySelector('[data-act="dl"]').onclick = () => {
        window.open(it.download_url, "_blank");
      };
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

  els.convertBtn?.addEventListener("click", convert);
  els.copyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.out.textContent || "");
      setStatus("Đã sao chép.");
    } catch {
      setStatus("Không sao chép được.", false);
    }
  });
  els.histRefresh?.addEventListener("click", loadHistory);

  // khởi động
  loadHistory();
});
els.saveBtn?.addEventListener("click", async () => {
  const text = els.out.textContent || "";
  if (!text.trim()) {
    setStatus("Không có nội dung để lưu.", false);
    return;
  }

  // thử lấy tên file PDF đang chọn để đặt tên lịch sử (optional)
  const baseName = els.file?.files?.[0]?.name || "manual_note";

  try {
    const r = await fetch("/api/pdf_to_txt/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, base_name: baseName }),
    });
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || "Save failed");

    setStatus("Đã lưu vào History.");
    // cập nhật đường dẫn tải xuống và danh sách lịch sử
    if (data.txt_path) {
      lastTxtPath = data.txt_path;
      els.downloadBtn.onclick = () => {
        const url =
          "/api/pdf_to_txt/download?path=" + encodeURIComponent(lastTxtPath);
        window.open(url, "_blank");
      };
    }
    await loadHistory();
  } catch (e) {
    setStatus("Lưu thất bại: " + e.message, false);
  }
});
