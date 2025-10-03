(() => {
  "use strict";
  const KEY = "txm_sb_collapsed";
  let _lastCollapsed = null;
  let _resizeRAF = 0;

  function debouncedResize() {
    if (_resizeRAF) cancelAnimationFrame(_resizeRAF);
    _resizeRAF = requestAnimationFrame(() => {
      _resizeRAF = 0;
      window.dispatchEvent(new Event("resize"));
    });
  }

  function applySidebarState() {
    const collapsed = localStorage.getItem(KEY) === "1";
    if (collapsed === _lastCollapsed) return;
    _lastCollapsed = collapsed;
    document.body.classList.toggle("sb-collapsed", collapsed);
    const btn = document.getElementById("sbToggle");
    if (btn) btn.setAttribute("aria-pressed", collapsed ? "true" : "false");
    debouncedResize();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.innerWidth < 992 && localStorage.getItem(KEY) == null) {
      localStorage.setItem(KEY, "1");
    }
    _lastCollapsed = document.body.classList.contains("sb-collapsed");
    applySidebarState();

    document.getElementById("sbToggle")?.addEventListener("click", (e) => {
      if (document.body.classList.contains("history-open")) {
        e.preventDefault();
        document.body.classList.remove("history-open"); // chỉ ẩn, không gọi logic nặng
        return;
      }
      const collapsed = localStorage.getItem(KEY) === "1";
      localStorage.setItem(KEY, collapsed ? "0" : "1");
      applySidebarState();
    });
  });
})();
