(function () {
  const scroller = document.getElementById("guideScroll"); // scroller nội bộ
  if (!scroller) return;

  const progress = document.getElementById("scrollProgress");
  // Dùng nav-link của Bootstrap
  const navLinks = scroller.querySelectorAll(".nav-links .nav-link");
  const sections = scroller.querySelectorAll(".section");

  /* ---- Progress theo scroller ---- */
  const onScroll = () => {
    const st = scroller.scrollTop;
    const sh = scroller.scrollHeight - scroller.clientHeight;
    const pct = sh > 0 ? (st / sh) * 100 : 0;
    if (progress) progress.style.width = pct + "%";
  };
  scroller.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---- Active link bằng IntersectionObserver trong scroller ---- */
  const linkById = {};
  navLinks.forEach(l => { linkById[l.getAttribute("href").slice(1)] = l; });

  let currentId = "gioi-thieu";
  const setActive = (id) => {
    if (currentId === id) return;
    currentId = id;
    navLinks.forEach(l => l.classList.remove("active"));
    const link = linkById[id];
    if (link) link.classList.add("active");
  };

  const obs = new IntersectionObserver((entries) => {
    let best = { id: currentId, ratio: 0 };
    entries.forEach(e => {
      if (e.isIntersecting && e.intersectionRatio > best.ratio) {
        best = { id: e.target.id, ratio: e.intersectionRatio };
      }
    });
    if (best.id) setActive(best.id);
  }, {
    root: scroller,
    rootMargin: "-120px 0px -60% 0px",
    threshold: [0.1, 0.25, 0.5, 0.75, 1]
  });

  sections.forEach(sec => obs.observe(sec));

  /* ---- Click anchor: cuộn trong scroller + bù offset topbar ---- */
  const TOPBAR_OFFSET = 80; // cao ~ thanh topbar
  navLinks.forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const id = link.getAttribute("href").slice(1);
      const target = scroller.querySelector(`#${CSS.escape(id)}`);
      if (!target) return;

      const scrollerTop = scroller.getBoundingClientRect().top;
      const targetTop = target.getBoundingClientRect().top;
      const delta = targetTop - scrollerTop;

      scroller.scrollTo({
        top: scroller.scrollTop + delta - TOPBAR_OFFSET,
        behavior: "smooth"
      });

      setActive(id);
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
  });
})();
