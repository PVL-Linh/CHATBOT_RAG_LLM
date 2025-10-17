(() => {
  const API = "/api/indexing";
  let currentDept = "";
  let rootPath = "";
  let allFiles = [];
  let selected = new Set();
  let busy = false;

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const esc = (s) =>
    String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  const baseName = (src) =>
    String(src || "")
      .replace(/\\\\/g, "/")
      .replace(/\\/g, "/")
      .split("/")
      .pop();

  function toast(msg, type = "info") {
    const color =
      type === "success"
        ? "#16a34a"
        : type === "danger" || type === "error"
        ? "#dc2626"
        : type === "warning"
        ? "#d97706"
        : "#4f46e5";
    const el = document.createElement("div");
    el.style.position = "fixed";
    el.style.right = "16px";
    el.style.top = "16px";
    el.style.zIndex = "9999";
    el.style.maxWidth = "440px";
    el.innerHTML = `
      <div style="background:#fff;border-left:5px solid ${color};box-shadow:0 8px 24px rgba(0,0,0,.16);
                  padding:10px 12px;border-radius:10px; display:flex; gap:10px; align-items:center;">
        <div style="color:${color}">●</div>
        <div style="flex:1">${esc(msg)}</div>
        <button aria-label="close" style="border:0;background:transparent;font-weight:700;cursor:pointer">×</button>
      </div>`;
    document.body.appendChild(el);
    el.querySelector("button").onclick = () => el.remove();
    setTimeout(() => el.remove(), 4000);
  }

  const setBusy = (v) => {
    busy = v;
    ["#idx_left_card", "#idx_right_card"].forEach((id) => {
      const el = document.querySelector(id + " .local-loader");
      if (!el) return;
      v ? el.classList.remove("hidden") : el.classList.add("hidden");
    });
    $("#refreshBtn").disabled = v;
    $("#deleteBtn").disabled = v || selected.size === 0;
    $("#deptSelect").disabled = v;
  };
  const updateDeleteBtn = () => {
    $("#deleteCount").textContent = String(selected.size);
    $("#deleteBtn").disabled = busy || selected.size === 0;
  };
  const debounce = (fn, ms = 250) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };

  // ===== API =====
  async function loadDepts() {
    try {
      const res = await fetch(`${API}/paths`);
      const data = await res.json();
      if (!data.ok || !data.data) throw new Error(data.error || "paths fail");
      const depts = Object.keys(data.data);
      const sel = $("#deptSelect");
      sel.innerHTML =
        '<option value="">-- Chọn phòng ban --</option>' +
        depts
          .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
          .join("");
      if (depts.length) {
        rootPath = data.data[depts[0]].root || "";
        $("#rootPath").textContent = rootPath ? `Root: ${rootPath}` : "";
      }
    } catch (e) {
      toast("Không tải được phòng ban: " + e.message, "danger");
    }
  }

  async function loadList() {
    if (!currentDept) return;
    setBusy(true);
    try {
      const qs = new URLSearchParams({ dept: currentDept });
      if (rootPath) qs.append("root", rootPath);
      const res = await fetch(`${API}/list?` + qs.toString());
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "list fail");
      allFiles = data.sources || [];
      selected.clear();
      renderTable(allFiles);
      $("#currentDept").textContent = currentDept;
      $("#totalFiles").textContent = String(allFiles.length);
    } catch (e) {
      toast("Lỗi tải danh sách: " + e.message, "danger");
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(files) {
    if (!currentDept) {
      toast("Chọn phòng ban trước", "warning");
      return;
    }
    if (!files || !files.length) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("dept", currentDept);
      if (rootPath) form.append("root", rootPath);
      [...files].forEach((f) => form.append("files", f));
      const res = await fetch(`${API}/add`, { method: "POST", body: form });
      const data = await res.json();
      if (!data.ok) {
        const msg = data.error || "Không thể tải lên";
        toast(msg, /trùng|duplicate/i.test(msg) ? "warning" : "danger");
        return;
      }
      toast(`Đã tải lên ${data.added} file`, "success");
      allFiles = data.after || [];
      selected.clear();
      renderTable(allFiles);
      $("#totalFiles").textContent = String(allFiles.length);
      $("#fileInput").value = "";
    } catch (e) {
      toast("Lỗi tải lên: " + e.message, "danger");
    } finally {
      setBusy(false);
    }
  }

  async function deleteFiles() {
    if (!selected.size) return;
    if (!confirm(`Bạn có chắc xoá ${selected.size} tài liệu?`)) return;
    setBusy(true);
    try {
      const body = { dept: currentDept, sources: [...selected] };
      if (rootPath) body.root = rootPath;
      const res = await fetch(`${API}/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "delete fail");
      toast(`Đã xoá ${data.deleted_chunks || 0} chunks`, "success");
      allFiles = data.after || [];
      selected.clear();
      renderTable(allFiles);
      $("#totalFiles").textContent = String(allFiles.length);
    } catch (e) {
      toast("Lỗi xoá: " + e.message, "danger");
    } finally {
      setBusy(false);
    }
  }

  // ===== UI =====
  function renderTable(list) {
    const wrap = $("#tableContent");
    if (!list.length) {
      wrap.innerHTML = `
        <div class="empty">
          <i class="fa-regular fa-file-lines"></i>
          <div>Không có tài liệu</div>
        </div>`;
      updateDeleteBtn();
      return;
    }

    const rows = list
      .map((f) => {
        const full = f.source || "";
        const name = baseName(full);
        const ext = (name.split(".").pop() || "txt").toLowerCase();
        const typeClass = ext === "pdf" ? "badge-pdf" : "badge-txt";
        const checked = selected.has(full) ? "checked" : "";
        return `
        <tr class="file-row" data-source="${esc(full)}" title="${esc(full)}">
          <td class="col-select"><input type="checkbox" class="row-check" ${checked} /></td>
          <td class="col-name"><span class="name">${esc(name)}</span></td>
          <td class="col-chunks"><span class="badge-chunks">${
            Number(f.chunks) || 0
          } chunks</span></td>
          <td class="col-type hide-sm"><span class="badge-type ${typeClass}">${ext.toUpperCase()}</span></td>
        </tr>`;
      })
      .join("");

    wrap.innerHTML = `
      <table class="idx-table">
        <thead>
          <tr>
            <th class="col-select"><input type="checkbox" id="selectAll"></th>
            <th class="col-name">Tên tài liệu</th>
            <th class="col-chunks">Số chunks</th>
            <th class="col-type hide-sm">Loại</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;

    // chọn tất cả
    $("#selectAll").addEventListener("change", (e) => {
      const isCk = e.target.checked;
      $$(".row-check").forEach((cb) => {
        cb.checked = isCk;
        const tr = cb.closest("tr");
        const src = tr?.dataset.source;
        if (!src) return;
        if (isCk) selected.add(src);
        else selected.delete(src);
      });
      updateDeleteBtn();
    });

    // toggle theo hàng
    wrap.querySelector("tbody").addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr.file-row");
      if (!tr) return;
      const cb = tr.querySelector(".row-check");
      if (!ev.target.classList.contains("row-check")) cb.checked = !cb.checked;
      const src = tr.dataset.source;
      if (cb.checked) selected.add(src);
      else selected.delete(src);
      updateDeleteBtn();
      const total = $$(".row-check").length;
      const checked = [...$$(".row-check")].filter((x) => x.checked).length;
      const selAll = $("#selectAll");
      selAll.checked = total > 0 && checked === total;
      selAll.indeterminate = checked > 0 && checked < total;
    });

    updateDeleteBtn();
  }

  const filterList = debounce((q) => {
    const key = (q || "").toLowerCase();
    const filtered = allFiles.filter((x) =>
      (x.source || "").toLowerCase().includes(key)
    );
    $("#totalFiles").textContent = String(filtered.length);
    renderTable(filtered);
  }, 200);

  // ===== events =====
  document.addEventListener("DOMContentLoaded", () => {
    loadDepts();

    $("#deptSelect").addEventListener("change", (e) => {
      currentDept = e.target.value || "";
      selected.clear();
      updateDeleteBtn();
      if (currentDept) {
        $("#uploadZone").classList.remove("disabled");
        loadList();
      } else {
        $("#uploadZone").classList.add("disabled");
        $("#currentDept").textContent = "-";
        $("#totalFiles").textContent = "0";
        $("#tableContent").innerHTML = `
          <div class="empty">
            <i class="fa-regular fa-folder-open"></i>
            <div>Vui lòng chọn phòng ban ở khung bên trái</div>
          </div>`;
      }
    });

    $("#uploadZone").addEventListener("click", () => {
      if (!busy && currentDept) $("#fileInput").click();
    });
    $("#fileInput").addEventListener("change", (e) => addFiles(e.target.files));

    // drag-drop
    const uz = $("#uploadZone");
    ["dragenter", "dragover"].forEach((evt) =>
      uz.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (currentDept && !busy) uz.style.borderColor = "#4f46e5";
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      uz.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        uz.style.borderColor = "#d6d9e0";
      })
    );
    uz.addEventListener("drop", (e) => {
      if (currentDept && !busy) addFiles(e.dataTransfer.files);
    });

    $("#searchInput").addEventListener("input", (e) =>
      filterList(e.target.value)
    );
    $("#refreshBtn").addEventListener("click", loadList);
    $("#deleteBtn").addEventListener("click", deleteFiles);

    // shortcuts
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        $("#searchInput").focus();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "r") {
        e.preventDefault();
        loadList();
      }
      if (e.key === "Delete" && selected.size) deleteFiles();
    });
  });
})();
