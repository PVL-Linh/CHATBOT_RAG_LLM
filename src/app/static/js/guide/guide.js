const scrollProgress = document.getElementById("scrollProgress");
const sections = document.querySelectorAll(".section");
const navLinks = document.querySelectorAll(".nav-links a");

// Cập nhật active khi cuộn
window.addEventListener("scroll", () => {
  const scrollTop = document.documentElement.scrollTop || document.body.scrollTop;
  const scrollHeight = document.documentElement.scrollHeight - document.documentElement.clientHeight;
  const scrolled = (scrollTop / scrollHeight) * 100;
  scrollProgress.style.width = scrolled + "%";

  let current = "";
  sections.forEach(section => {
    const sectionTop = section.offsetTop - 120;
    if (scrollY >= sectionTop) current = section.getAttribute("id");
  });

  navLinks.forEach(link => {
    link.classList.remove("active");
    if (link.getAttribute("href") === "#" + current) {
      link.classList.add("active");
    }
  });
});

// ✅ Cập nhật active ngay khi click (không chờ scroll)
navLinks.forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    const targetId = link.getAttribute("href");
    document.querySelector(targetId).scrollIntoView({ behavior: "smooth" });

    // Thêm đoạn này nè 🔥
    navLinks.forEach(l => l.classList.remove("active"));
    link.classList.add("active");
  });
});