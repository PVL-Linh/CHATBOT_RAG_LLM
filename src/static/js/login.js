document.addEventListener('DOMContentLoaded', () => {
  // =========================
  // Toggle hiện/ẩn mật khẩu
  // =========================
  const pwd  = document.getElementById('password');
  const btn  = document.getElementById('togglePwd');
  const hide = document.getElementById('icon-hide'); // 🙊 (đang ẩn)
  const show = document.getElementById('icon-show'); // 🙈 (đang hiện)

  if (btn && pwd) {
    btn.addEventListener('click', (e) => {
      // tránh label nuốt sự kiện hoặc form submit
      e.preventDefault();
      e.stopPropagation();

      const isShown = (pwd.type === 'text');
      pwd.type = isShown ? 'password' : 'text';

      if (hide && show) {
        hide.style.display = isShown ? '' : 'none';
        show.style.display = isShown ? 'none' : '';
      }

      btn.setAttribute('aria-label', isShown ? 'Hiện mật khẩu' : 'Ẩn mật khẩu');
      btn.title = isShown ? 'Hiện mật khẩu' : 'Ẩn mật khẩu';
    });
  }

  // =========================
  // Hiệu ứng: NHIỀU ảnh nảy
  // =========================
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion) return;

  // Cấu hình
  const NUM_BOUNCERS = 30;                     // ~10 hình
  const IMAGE_SOURCES = ['/static/images/logo.png']; // có thể thêm nhiều nguồn khác nhau
  const SPEED_MIN = 140;                       // px/s
  const SPEED_MAX = 260;                       // px/s
  const ROTATE_WITH_DIRECTION = true;          // xoay theo hướng di chuyển
  const OPACITY_BASE = 0.14;

  // Tính kích thước "to hơn" theo viewport (JS set size, responsive)
  function computeBaseSize() {
    // lớn hơn trước: 8% chiều ngang, min 110, max 200
    return Math.min(Math.max(window.innerWidth * 0.08, 110), 200);
  }

  // Tạo 1 sprite
  function createSprite(i) {
    const src = IMAGE_SOURCES[i % IMAGE_SOURCES.length];
    const el = document.createElement('img');
    el.src = src;
    el.alt = '';
    el.className = 'bouncer';
    // Độ mờ hơi khác nhau để tạo chiều sâu
    el.style.opacity = (OPACITY_BASE * (0.9 + Math.random() * 0.4)).toFixed(2);
    document.body.appendChild(el);

    // Kích thước (to hơn, nhưng có chút random)
    const base = computeBaseSize();
    const size = base * (0.85 + Math.random() * 0.5); // 85% - 135% base
    el.style.width = `${size}px`;

    // Đo kích thước thực
    const rect = el.getBoundingClientRect();
    const w = rect.width || size;
    const h = rect.height || size;

    // Vị trí & vận tốc ngẫu nhiên
    const vw = window.innerWidth, vh = window.innerHeight;
    const x = Math.random() * Math.max(1, vw - w);
    const y = Math.random() * Math.max(1, vh - h);
    const angle = Math.random() * Math.PI * 2;
    const speed = SPEED_MIN + Math.random() * (SPEED_MAX - SPEED_MIN);
    const vx = Math.cos(angle) * speed;
    const vy = Math.sin(angle) * speed;

    return { el, x, y, w, h, vx, vy };
  }

  // Khởi tạo danh sách sprite
  const sprites = [];
  for (let i = 0; i < NUM_BOUNCERS; i++) {
    sprites.push(createSprite(i));
  }

  // Khi đổi kích thước màn hình: scale lại width & clamp vị trí
  function onResize() {
    const vw = window.innerWidth, vh = window.innerHeight;
    const base = computeBaseSize();
    sprites.forEach(s => {
      // giữ tỉ lệ mỗi sprite, nhưng rebase theo viewport mới
      const factor = s.el.width ? (s.el.width / s.w) : 1; // dự phòng
      const newSize = base * (0.85 + Math.random() * 0.5);
      s.el.style.width = `${newSize}px`;
      const r = s.el.getBoundingClientRect();
      s.w = r.width || newSize;
      s.h = r.height || newSize;

      s.x = Math.min(Math.max(0, s.x), Math.max(0, vw - s.w));
      s.y = Math.min(Math.max(0, s.y), Math.max(0, vh - s.h));
    });
  }
  window.addEventListener('resize', onResize);

  // Hiệu ứng nhỏ khi chạm cạnh
  function flash(el) {
    el.style.filter = 'drop-shadow(0 10px 18px rgba(0,0,0,.25)) hue-rotate(30deg)';
    setTimeout(() => {
      el.style.filter = 'drop-shadow(0 6px 12px rgba(0,0,0,.15))';
    }, 90);
  }

  // Vòng lặp animation cho TẤT CẢ sprite (1 RAF duy nhất → mượt hơn)
  let last = performance.now();
  function step(now) {
    const dt = Math.max(0.001, (now - last) / 1000);
    last = now;

    const vw = window.innerWidth, vh = window.innerHeight;

    for (const s of sprites) {
      s.x += s.vx * dt;
      s.y += s.vy * dt;

      // Va chạm theo mép
      if (s.x <= 0)            { s.x = 0;       s.vx = Math.abs(s.vx);  flash(s.el); }
      else if (s.x + s.w >= vw){ s.x = vw - s.w; s.vx = -Math.abs(s.vx); flash(s.el); }

      if (s.y <= 0)            { s.y = 0;       s.vy = Math.abs(s.vy);  flash(s.el); }
      else if (s.y + s.h >= vh){ s.y = vh - s.h; s.vy = -Math.abs(s.vy); flash(s.el); }

      if (ROTATE_WITH_DIRECTION) {
        const theta = Math.atan2(s.vy, s.vx);
        s.el.style.transform = `translate(${s.x}px, ${s.y}px) rotate(${theta}rad)`;
      } else {
        s.el.style.transform = `translate(${s.x}px, ${s.y}px)`;
      }
    }

    requestAnimationFrame(step);
  }
  requestAnimationFrame(step);

  // Dọn dẹp
  window.addEventListener('beforeunload', () => {
    window.removeEventListener('resize', onResize);
  });
});
