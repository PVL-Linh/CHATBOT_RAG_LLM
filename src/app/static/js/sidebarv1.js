// static/js/sidebarv1.js
(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const MIN = 190, MAX = 260, EXTRA = 40;
    const labels = Array.from(document.querySelectorAll('.sidebar .nav-item span'));
    let widest = 0;
    labels.forEach(el => widest = Math.max(widest, el?.scrollWidth || 0));
    const w = Math.min(MAX, Math.max(MIN, widest + EXTRA));
    document.body.style.setProperty('--sidebar-w', w + 'px');

    const sbToggle = document.getElementById('sbToggle');
    const sidebar = document.getElementById('sidebar');

    // Khôi phục trạng thái
    const savedCollapsed = (localStorage.getItem('txm_sb_collapsed') === '1');
    const savedPinned = (localStorage.getItem('txm_sb_pinned') === '1');
    
    // Mobile mặc định collapsed
    if (!isDesktop()) {
      document.body.classList.add('sb-collapsed');
    } else {
      document.body.classList.toggle('sb-collapsed', savedCollapsed);
      document.body.classList.toggle('sb-pinned', savedPinned);
    }

    // Click toggle
    sbToggle?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      onToggle(e);
      if (window.lucide) { try { window.lucide.createIcons(); } catch (_) { } }
    });

    // Tooltip khi thu gọn
    function applyCollapsedTitles() {
      const collapsed = document.body.classList.contains('sb-collapsed');
      document.querySelectorAll('.sidebar .nav-item').forEach(a => {
        const label = a.querySelector('span')?.textContent?.trim() || '';
        if (collapsed) a.title = label; else a.removeAttribute('title');
      });
    }
    applyCollapsedTitles();
    const obs = new MutationObserver(applyCollapsedTitles);
    obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  });

  const KEY_PIN = "txm_sb_pinned";
  const KEY_COLLAPSE = "txm_sb_collapsed";
  const MQ = window.matchMedia("(min-width: 992px)");
  const isDesktop = () => MQ.matches;

  let _sbPrev = null;

  /* ---------------- helpers ---------------- */
  function updateIcon() {
    const ico = document.querySelector(".sb-toggle i[data-lucide]");
    if (!ico) return;
    
    const open = document.body.classList.contains("sb-open") || 
                 (!document.body.classList.contains("sb-collapsed") &&
                  (document.body.classList.contains("sb-pinned") ||
                   document.body.classList.contains("sb-hover")));

    ico.setAttribute("data-lucide", open ? "x" : "menu");
    if (window.lucide) { try { lucide.createIcons(); } catch (_) { } }

    const btn = document.querySelector(".sb-toggle");
    if (btn) {
      btn.setAttribute("aria-pressed", open ? "true" : "false");
      const label = open ? "Đóng sidebar" : "Mở sidebar";
      btn.setAttribute("title", label);
      btn.setAttribute("aria-label", label);
    }
  }

  function setCollapsed(collapsed, persist = true) {
    document.body.classList.toggle("sb-collapsed", collapsed);
    if (collapsed) {
      document.body.classList.remove("sb-hover", "sb-pinned", "sb-open");
    }
    if (persist) localStorage.setItem(KEY_COLLAPSE, collapsed ? "1" : "0");
    updateIcon();
    window.dispatchEvent(new Event("resize"));
  }

  function setPinned(pinned, persist = true) {
    document.body.classList.toggle("sb-pinned", pinned);
    if (pinned) {
      document.body.classList.remove("sb-collapsed", "sb-hover", "sb-open");
    }
    if (persist) localStorage.setItem(KEY_PIN, pinned ? "1" : "0");
    updateIcon();
    window.dispatchEvent(new Event("resize"));
  }

  function applyState() {
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
      document.body.classList.remove("sb-open");
      const collapsed = (localStorage.getItem(KEY_COLLAPSE) ?? "1") === "1";
      setCollapsed(collapsed, false);
    }
  }

  /* ---------------- events ---------------- */
  function onToggle(e) {
    e?.preventDefault?.();
    e?.stopPropagation?.();

    // Đóng lịch sử nếu đang mở
    if (document.body.classList.contains("history-open")) {
      document.body.classList.remove("history-open");
      if (_sbPrev) {
        document.body.classList.toggle("sb-pinned", _sbPrev.pinned);
        document.body.classList.toggle("sb-collapsed", _sbPrev.collapsed);
        _sbPrev = null;
        updateIcon();
      }
      return;
    }

    if (isDesktop()) {
      const nextPinned = !document.body.classList.contains("sb-pinned");
      setPinned(nextPinned);
    } else {
      // Mobile: toggle sb-open
      const isOpen = document.body.classList.contains("sb-open");
      if (isOpen) {
        document.body.classList.remove("sb-open");
        document.body.classList.add("sb-collapsed");
      } else {
        document.body.classList.add("sb-open");
        document.body.classList.remove("sb-collapsed");
      }
      updateIcon();
    }
  }

  // Hover mở/đóng trên desktop
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
        if (lastX <= rightEdge + ENTER_PAD) {
          document.body.classList.add("sb-hover");
          document.body.classList.remove("sb-collapsed");
        }
      } else {
        if (lastX > rightEdge + LEAVE_PAD) {
          document.body.classList.remove("sb-hover");
        }
      }
      updateIcon();
    });
  }

  // Click outside để đóng sidebar trên mobile
  function handleClickOutside(e) {
    if (isDesktop()) return;
    if (!document.body.classList.contains("sb-open")) return;
    
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("sbToggle");
    
    if (sidebar && !sidebar.contains(e.target) && !toggle?.contains(e.target)) {
      document.body.classList.remove("sb-open");
      document.body.classList.add("sb-collapsed");
      updateIcon();
    }
  }

  // Quan sát class .history-open
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
        setCollapsed(true);
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
    document.addEventListener("click", handleClickOutside);

    MQ.addEventListener("change", applyState);
    window.addEventListener("resize", updateIcon);

    if (window.lucide) { try { window.lucide.createIcons(); } catch (_) { } }
  });
})();