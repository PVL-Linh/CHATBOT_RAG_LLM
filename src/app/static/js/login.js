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
});
document.addEventListener('DOMContentLoaded', () => {
  // ====== Meter độ mạnh & cảnh báo Caps ======
  const pwd      = document.getElementById('password');
  const meterBar = document.getElementById('meter-bar');
  const capsEl   = document.getElementById('caps');

  function strengthScore(s) {
    let score = 0;
    if (s.length >= 8)  score++;
    if (/[a-z]/.test(s) && /[A-Z]/.test(s)) score++;
    if (/\d/.test(s))   score++;
    if (/[^A-Za-z0-9]/.test(s)) score++;
    if (s.length >= 12) score++;
    return Math.min(score, 4); // 0..4
  }
  function updateMeter() {
    if (!meterBar) return;
    const s  = pwd.value || "";
    const sc = strengthScore(s);
    const widths = ['0%','25%','50%','75%','100%'];
    meterBar.style.width = widths[sc];
    meterBar.className = ''; // reset
    if      (sc <= 1) meterBar.classList.add('weak');
    else if (sc === 2) meterBar.classList.add('ok');
    else if (sc === 3) meterBar.classList.add('good');
    else               meterBar.classList.add('strong');
  }
  if (pwd) {
    pwd.addEventListener('input', updateMeter);
    pwd.addEventListener('blur', () => { if (capsEl) capsEl.style.opacity = 0; });
    updateMeter();
  }

  // ====== Nút submit: trạng thái loading ======
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', () => {
      const btnSubmit = form.querySelector('.btn');
      if (btnSubmit) {
        btnSubmit.classList.add('loading');
        btnSubmit.setAttribute('aria-busy', 'true');
        btnSubmit.disabled = true; // tránh double-submit
      }
    });
  }

});
document.addEventListener('DOMContentLoaded', () => {
  const body = document.body;
  const btn  = document.getElementById('bgToggle');
  if (!btn || !body) return;

  const presets = ['bg--aurora','bg--mesh','bg--grid','bg--stripes','bg--blobs'];
  // đọc preset đã lưu
  const saved = localStorage.getItem('tixi-bg');
  if (saved && presets.includes(saved)) {
    body.classList.remove(...presets);
    body.classList.add(saved);
  }

  btn.addEventListener('click', () => {
    const current = presets.find(p => body.classList.contains(p)) || presets[0];
    const nextIdx = (presets.indexOf(current) + 1) % presets.length;
    const next = presets[nextIdx];
    body.classList.remove(...presets);
    body.classList.add(next);
    localStorage.setItem('tixi-bg', next);
  });
});
