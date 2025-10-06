// static/js/sidebarv1.js
(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const MIN = 190, MAX = 260, EXTRA = 40; // padding + icon
    const labels = Array.from(document.querySelectorAll('.sidebar .nav-item span'));
    let widest = 0;
    labels.forEach(el => widest = Math.max(widest, el?.scrollWidth || 0));
    const w = Math.min(MAX, Math.max(MIN, widest + EXTRA));
    document.body.style.setProperty('--sidebar-w', w + 'px');

    const sbToggle = document.getElementById('sbToggle');
    const sidebar = document.getElementById('sidebar');

    // ✅ Khôi phục trạng thái theo BODY CLASS (tránh .is-collapsed)
    const savedCollapsed = (localStorage.getItem('txm_sb_collapsed') === '1');
    const savedPinned    = (localStorage.getItem('txm_sb_pinned') === '1');
    document.body.classList.toggle('sb-collapsed', savedCollapsed);
    document.body.classList.toggle('sb-pinned',    savedPinned);

    // ✅ Click: gọi hàm onToggle (khớp logic khối sau), tránh double-toggle
    sbToggle?.addEventListener('click', (e) => {
      e.preventDefault();
      if (typeof onToggle === 'function') onToggle(e);
    });

    // Tooltip khi thu gọn: đọc theo BODY CLASS
    function applyCollapsedTitles() {
      const collapsed = document.body.classList.contains('sb-collapsed');
      document.querySelectorAll('.sidebar .nav-item').forEach(a => {
        const label = a.querySelector('span')?.textContent?.trim() || '';
        if (collapsed) a.title = label; else a.removeAttribute('title');
      });
    }
    applyCollapsedTitles();
    const obs = new MutationObserver(applyCollapsedTitles);
    obs.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
  });

  const KEY_PIN = "txm_sb_pinned";
  const KEY_COLLAPSE = "txm_sb_collapsed";       // 1 = collapsed (ẩn)
  const MQ = window.matchMedia("(min-width: 992px)");
  const isDesktop = () => MQ.matches;

  // Ghi nhớ trạng thái sidebar trước khi mở lịch sử để khôi phục khi đóng
  let _sbPrev = null;

  /* ---------------- helpers ---------------- */
  function updateIcon() {
    const ico = document.querySelector(".sb-toggle i[data-lucide]");
    if (!ico) return;
    const open =
      !document.body.classList.contains("sb-collapsed") &&
      (document.body.classList.contains("sb-pinned") ||
        document.body.classList.contains("sb-hover") ||
        !isDesktop());

    ico.setAttribute("data-lucide", open ? "chevrons-left" : "chevrons-right");
    if (window.lucide) { try { lucide.createIcons(); } catch (_) { } }

    const btn = document.querySelector(".sb-toggle");
    if (btn) {
      btn.setAttribute("aria-pressed", open ? "true" : "false");
      const label = open ? "Thu gọn sidebar" : "Mở sidebar";
      btn.setAttribute("title", label);
      btn.setAttribute("aria-label", label);
    }
  }

  function setCollapsed(collapsed, persist = true) {
    document.body.classList.toggle("sb-collapsed", collapsed);
    if (collapsed) document.body.classList.remove("sb-hover", "sb-pinned");
    if (persist) localStorage.setItem(KEY_COLLAPSE, collapsed ? "1" : "0");
    updateIcon();
    window.dispatchEvent(new Event("resize"));
  }

  function setPinned(pinned, persist = true) {
    document.body.classList.toggle("sb-pinned", pinned);
    if (pinned) document.body.classList.remove("sb-collapsed", "sb-hover");
    if (persist) localStorage.setItem(KEY_PIN, pinned ? "1" : "0");
    updateIcon();
    window.dispatchEvent(new Event("resize"));
  }

  function applyState() {
    // Ưu tiên: khi lịch sử đang mở → luôn ẩn sidebar
    if (document.body.classList.contains("history-open")) {
      setCollapsed(true);
      return;
    }
    if (isDesktop()) {
      const pinned = localStorage.getItem(KEY_PIN) === "1";
      if (pinned) setPinned(true, false);
      else setCollapsed(localStorage.getItem(KEY_COLLAPSE) === "1", false);
    } else {
      setPinned(false, false);
      // nếu chưa có state thì mặc định ẩn trên màn hình nhỏ
      const collapsed =
        (localStorage.getItem(KEY_COLLAPSE) ?? "1") === "1";
      setCollapsed(collapsed, false);
    }
  }

  /* ---------------- events ---------------- */
  function onToggle(e) {
    e?.preventDefault?.();

    // Mở sidebar → đóng lịch sử trước (đảm bảo không chồng chéo)
    if (document.body.classList.contains("history-open")) {
      document.body.classList.remove("history-open");
      if (_sbPrev) {
        document.body.classList.toggle("sb-pinned", _sbPrev.pinned);
        document.body.classList.toggle("sb-collapsed", _sbPrev.collapsed);
        _sbPrev = null;
        updateIcon();
      }
    }

    if (isDesktop()) {
      const nextPinned = !document.body.classList.contains("sb-pinned");
      setPinned(nextPinned);
    } else {
      const nextCollapsed = !document.body.classList.contains("sb-collapsed");
      setCollapsed(nextCollapsed ? false : true);
    }
  }

  // Hover mở/đóng trên desktop (tắt khi đang mở lịch sử hoặc đang pin)
  let raf = 0, lastX = 0;
  const ENTER_PAD = 8, LEAVE_PAD = 12;
  function onPointerMove(e) {
    if (!isDesktop()) return;
    if (document.body.classList.contains("history-open")) return;
    if (document.body.classList.contains("sb-pinned")) return;

    lastX = e.clientX;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const sb = document.getElementById("sidebar");
      if (!sb) return;
      const rect = sb.getBoundingClientRect();
      const rightEdge = rect.left + rect.width;
      const open = document.body.classList.contains("sb-hover");

      if (!open) {
        if (lastX <= rightEdge + ENTER_PAD) document.body.classList.add("sb-hover");
      } else {
        if (lastX > rightEdge + LEAVE_PAD) document.body.classList.remove("sb-hover");
      }
      updateIcon();
    });
  }

  // Quan sát class .history-open để tự ẩn/khôi phục sidebar
  function watchHistoryToggle() {
    const mo = new MutationObserver(() => {
      const open = document.body.classList.contains("history-open");
      if (open) {
        if (_sbPrev == null) {
          _sbPrev = {
            pinned: document.body.classList.contains("sb-pinned"),
            collapsed: document.body.classList.contains("sb-collapsed"),
          };
        }
        setCollapsed(true);                // ép ẩn sidebar
      } else if (_sbPrev) {
        document.body.classList.toggle("sb-pinned", _sbPrev.pinned);
        document.body.classList.toggle("sb-collapsed", _sbPrev.collapsed);
        _sbPrev = null;
        updateIcon();
      }
    });
    mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }

  /* ---------------- boot ---------------- */
  document.addEventListener("DOMContentLoaded", () => {
    applyState();
    watchHistoryToggle();

    window.addEventListener("pointermove", onPointerMove, { passive: true });

    // ❌ Tránh double-binding: KHÔNG gắn click ở đây nữa (đã gắn ở khối đầu).
    // document.querySelectorAll(".sb-toggle").forEach(b =>
    //   b.addEventListener("click", onToggle)
    // );

    // Media query change & resize icon
    MQ.addEventListener("change", applyState);
    window.addEventListener("resize", updateIcon);

    // render icon lucide
    if (window.lucide) { try { window.lucide.createIcons(); } catch (_) { } }
  });

  // Expose onToggle trong phạm vi IIFE để khối đầu có thể gọi
  window.__txm_sb_onToggle = onToggle; // (không bắt buộc, chỉ phòng hờ)
})();
