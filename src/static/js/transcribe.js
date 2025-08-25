/* ====== Speech-to-Text Client (2-column + history) ====== */
(() => {
  const ENDPOINT = "/transcribe"; // backend đã có alias /tools/stt nếu cần
  const card = document.getElementById("tk_form_card");

  // ---------- Elements ----------
  const els = {
    // LEFT
    lang: document.getElementById("stt_lang"),
    file: document.getElementById("stt_file"),
    uploadBtn: document.getElementById("stt_upload_btn"),
    recordBtn: document.getElementById("stt_record"),
    stopBtn: document.getElementById("stt_stop"),
    timer: document.getElementById("stt_timer"),
    status: document.getElementById("stt_status"),
    // RIGHT - result
    text: document.getElementById("stt_text"),
    copyBtn: document.getElementById("stt_copy"),
    downloadBtn: document.getElementById("stt_download"),
    segments: document.getElementById("stt_segments"),
    // RIGHT - history
    historyList: document.getElementById("stt_history_list"),
    historyClear: document.getElementById("stt_history_clear"),
  };

  // ---------- Helpers ----------
  const fmtTime = (sec) => {
    sec = Math.max(0, Math.floor(sec));
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    return `${m}:${s}`;
  };
  const fmtHMS = (sec) => {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(
      2,
      "0"
    )}:${String(s).padStart(2, "0")}`;
  };
  const setStatus = (msg, type = "ready") => {
    els.status.className = `stt-status ${type}`;
    els.status.textContent = msg;
  };
  const makeProgressBar = () => {
    let wrap = card.querySelector(".stt-progress");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "stt-progress";
      const inner = document.createElement("span");
      wrap.appendChild(inner);
      els.status.after(wrap);
    }
    const bar = wrap.querySelector("span");
    bar.style.width = "0%";
    return (pct) => (bar.style.width = `${Math.min(100, Math.max(0, pct))}%`);
  };
  const renderSegments = (segments = []) => {
    els.segments.innerHTML = "";
    if (!segments || !segments.length) return;
    const f = document.createDocumentFragment();
    segments.forEach((seg) => {
      const row = document.createElement("div");
      row.className = "seg";
      const t = document.createElement("div");
      t.className = "seg-time";
      const start = seg.start != null ? seg.start : (seg.start_ms || 0) / 1000;
      const end = seg.end != null ? seg.end : (seg.end_ms || 0) / 1000;
      t.textContent = `${fmtHMS(start || 0)} → ${fmtHMS(end || start || 0)}`;
      const tx = document.createElement("div");
      tx.className = "seg-text";
      tx.textContent = seg.text || "";
      row.appendChild(t);
      row.appendChild(tx);
      f.appendChild(row);
    });
    els.segments.appendChild(f);
  };
  const downloadTxt = (filename, text) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob([text || ""], { type: "text/plain;charset=utf-8" })
    );
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 0);
  };

  // ---------- History (local) ----------
  const HISTORY_KEY = "stt_history_v1";
  const loadHistory = () => {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    } catch {
      return [];
    }
  };
  const saveHistory = (arr) =>
    localStorage.setItem(HISTORY_KEY, JSON.stringify(arr));
  const addHistoryItem = (item) => {
    const arr = loadHistory();
    arr.unshift(item);
    if (arr.length > 100) arr.pop();
    saveHistory(arr);
    renderHistory();
  };
  const renderHistory = () => {
    const list = loadHistory();
    els.historyList.innerHTML = "";
    if (!list.length) {
      els.historyList.innerHTML = `<div class="hist-item"><div class="hist-meta">Chưa có mục nào. Hãy tải file/ghi âm để bắt đầu.</div></div>`;
      return;
    }
    const frag = document.createDocumentFragment();

    list.forEach((it) => {
      const div = document.createElement("div");
      div.className = "hist-item";
      div.dataset.id = String(it.id);

      const name = (it.filename || "transcript").toString();
      const when = new Date(it.createdAt || Date.now());
      // thời gian kiểu 16:24 • 22/08/2025
      const timeStr = `${when.toLocaleTimeString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })} • ${when.toLocaleDateString("vi-VN")}`;
      const lang = (it.lang || "auto").toUpperCase();

      div.innerHTML = `
      <div class="hist-top">
        <div class="hist-left">
          <div class="hist-name" title="${name}">${name}</div>
          <div class="hist-meta">
            <span class="lang-badge">${lang}</span>
            <span class="dot">•</span>
            <span>${timeStr}</span>
          </div>
        </div>
        <div class="hist-actions">
          <button class="btn-ghost" data-act="load" title="Mở">📄</button>
          <button class="btn-ghost" data-act="copy" title="Sao chép">📋</button>
          <button class="btn-ghost" data-act="download" title="Tải TXT">💾</button>
          <button class="btn-ghost" data-act="delete" title="Xóa">🗑</button>
        </div>
      </div>
    `;
      frag.appendChild(div);
    });

    els.historyList.appendChild(frag);
  };

  const bindHistoryEvents = () => {
    els.historyList.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const itemEl = btn.closest(".hist-item");
      const id = itemEl?.dataset?.id;
      const arr = loadHistory();
      const idx = arr.findIndex((x) => String(x.id) === String(id));
      if (idx < 0) return;
      const it = arr[idx];

      const doCopy = async (text) => {
        try {
          await navigator.clipboard.writeText(text || "");
          setStatus("Đã sao chép vào clipboard.", "done");
        } catch {
          setStatus("Không thể sao chép. Hãy chọn và Ctrl+C.", "error");
        }
      };

      switch (btn.dataset.act) {
        case "load":
          els.text.value = it.text || "";
          renderSegments(it.segments || []);
          setStatus("Đã mở từ lịch sử.", "ready");
          break;
        case "copy":
          doCopy(it.text || "");
          break;
        case "download": {
          const base = (it.filename || "transcript").replace(/\.[^/.]+$/, "");
          const stamp = new Date(it.createdAt || Date.now())
            .toISOString()
            .replace(/[:.]/g, "-");
          downloadTxt(`${base}_${stamp}.txt`, it.text || "");
          break;
        }
        case "delete":
          arr.splice(idx, 1);
          saveHistory(arr);
          renderHistory();
          break;
      }
    });

    els.historyClear?.addEventListener("click", () => {
      if (!confirm("Xóa toàn bộ lịch sử?")) return;
      saveHistory([]);
      renderHistory();
    });
  };

  // ---------- XHR Upload ----------
  const xhrUpload = (formData, url, onProgress) =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url, true);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress)
          onProgress((e.loaded / e.total) * 100);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            resolve({ text: xhr.responseText });
          }
        } else {
          reject(
            new Error(
              `HTTP ${xhr.status}: ${xhr.responseText || "Upload failed"}`
            )
          );
        }
      };
      xhr.onerror = () => reject(new Error("Network error"));
      xhr.send(formData);
    });

  const uploadBlob = async (blob, filename, lang) => {
    const fd = new FormData();
    fd.append("audio", blob, filename || "audio.webm"); // field name phải là 'audio'
    if (lang) fd.append("lang", lang);
    const setPct = makeProgressBar();
    setStatus("Đang tải lên & nhận dạng…", "uploading");
    const res = await xhrUpload(fd, ENDPOINT, (p) => setPct(p));
    return res;
  };

  // ---------- Drag & Drop ----------
  ["dragenter", "dragover"].forEach((ev) =>
    card.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      card.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    card.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (ev === "drop") {
        const file = e.dataTransfer?.files?.[0];
        if (file) handleFile(file);
      }
      card.classList.remove("dragover");
    })
  );

  // ---------- Timer ----------
  let t0 = 0,
    timerId = 0;
  const startTimer = () => {
    t0 = Date.now();
    if (timerId) clearInterval(timerId);
    timerId = setInterval(() => {
      const sec = (Date.now() - t0) / 1000;
      els.timer.textContent = fmtTime(sec);
    }, 200);
  };
  const stopTimer = () => {
    if (timerId) clearInterval(timerId);
    timerId = 0;
  };

  // ---------- Recording ----------
  let mediaRecorder = null;
  let chunks = [];
  let stream = null;

  const bestMime = () => {
    const cands = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4;codecs=mp4a.40.2",
      "audio/mp4",
    ];
    for (const m of cands) {
      try {
        if (MediaRecorder.isTypeSupported(m)) return m;
      } catch {}
    }
    return "";
  };

  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setStatus("Trình duyệt không hỗ trợ ghi âm.", "error");
        return;
      }
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      const mime = bestMime();
      mediaRecorder = new MediaRecorder(
        stream,
        mime ? { mimeType: mime } : undefined
      );
      mediaRecorder.ondataavailable = (e) =>
        e.data?.size && chunks.push(e.data);
      mediaRecorder.onstop = async () => {
        stopTimer();
        els.recordBtn.classList.remove("recording");
        els.stopBtn.disabled = true;
        stream.getTracks().forEach((t) => t.stop());
        const type = mediaRecorder.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunks, { type });
        await transcribeBlob(blob, `recording.${ext}`, "record");
      };
      mediaRecorder.start(100);
      els.recordBtn.classList.add("recording");
      els.stopBtn.disabled = false;
      setStatus("Đang ghi âm… Nói đi nào!", "recording");
      startTimer();
    } catch (err) {
      console.error(err);
      setStatus(
        "Không thể bắt đầu ghi âm. Vui lòng kiểm tra quyền micro.",
        "error"
      );
    }
  };

  const stopRecording = () => {
    if (mediaRecorder && mediaRecorder.state !== "inactive")
      mediaRecorder.stop();
  };

  // ---------- File handling ----------
  const handleFile = async (file) => {
    if (!file) return;
    if (!file.type.startsWith("audio/") && !file.type.startsWith("video/")) {
      setStatus("File không hợp lệ (chỉ audio/video).", "error");
      return;
    }
    await transcribeBlob(file, file.name || "audio", "upload");
  };

  // Build history object from response
  const buildHistoryItem = (res, meta) => {
    const segments = res.segments || [];
    let duration = 0;
    if (segments.length) {
      const first = segments[0];
      const last = segments[segments.length - 1];
      const s = first.start ?? (first.start_ms || 0) / 1000;
      const e = last.end ?? (last.end_ms || 0) / 1000;
      duration = Math.max(0, (e || 0) - (s || 0));
    }
    return {
      id: Date.now(),
      filename: res.filename || meta.filename || "transcript",
      lang: meta.lang,
      source: meta.source, // upload | record
      createdAt: new Date().toISOString(),
      duration,
      text: res.text || res.transcript || "",
      segments: segments,
    };
  };

  const transcribeBlob = async (blob, filename, source) => {
    try {
      els.uploadBtn.disabled = true;
      els.recordBtn.disabled = true;
      els.stopBtn.disabled = true;

      const lang = els.lang?.value || "vi";
      const res = await uploadBlob(blob, filename, lang);

      const text = res.text || res.transcript || "";
      const segments = res.segments || res.data?.segments || [];
      if (text) els.text.value = text;
      renderSegments(segments);

      // Save to history
      const histItem = buildHistoryItem(res, { filename, lang, source });
      if ((histItem.text || "").trim()) addHistoryItem(histItem);

      if (res.error) setStatus(`Lưu ý: ${res.error}`, "error");
      else setStatus("Xong! 🎉", "done");
    } catch (err) {
      console.error(err);
      const m = String(err.message || "");
      if (m.toLowerCase().includes("không có track âm thanh")) {
        setStatus(
          "File không có tiếng. Hãy chọn file có audio hoặc ghi âm lại.",
          "error"
        );
      } else {
        setStatus(`Lỗi: ${m}`, "error");
      }
    } finally {
      els.uploadBtn.disabled = false;
      els.recordBtn.disabled = false;
    }
  };

  // ---------- Bind UI ----------
  els.uploadBtn?.addEventListener("click", async () => {
    const f = els.file.files?.[0];
    if (!f) return setStatus("Chưa chọn file.", "error");
    await handleFile(f);
  });
  els.recordBtn?.addEventListener("click", () => startRecording());
  els.stopBtn?.addEventListener("click", () => stopRecording());

  els.copyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.text.value || "");
      setStatus("Đã sao chép vào clipboard.", "done");
    } catch {
      setStatus("Không thể sao chép. Hãy chọn và Ctrl+C.", "error");
    }
  });

  els.downloadBtn?.addEventListener("click", () => {
    const fn = `transcript_${Date.now()}.txt`;
    downloadTxt(fn, els.text.value || "");
  });

  els.file?.addEventListener("change", () => {
    if (els.file.files?.length) {
      setStatus(`Đã chọn: ${els.file.files[0].name}`, "ready");
    }
  });

  bindHistoryEvents();
  renderHistory(); // load history lần đầu
  // ===== Pill tabs giống trang mẫu =====
  (function tabs() {
    const scope = document.querySelector('.pill-tabs[data-scope="stt"]');
    const panelsWrap = document.querySelector(".stt-panel");
    if (!scope || !panelsWrap) return;
    scope.querySelectorAll(".pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        // toggle pill
        scope
          .querySelectorAll(".pill")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        // toggle panel
        panelsWrap
          .querySelectorAll(".tab-panel")
          .forEach((p) => p.classList.remove("active"));
        const id = `stt_tab_${btn.dataset.tab}`;
        const panel = document.getElementById(id);
        if (panel) panel.classList.add("active");
      });
    });
  })();
  setStatus("Sẵn sàng.", "ready");
})();
