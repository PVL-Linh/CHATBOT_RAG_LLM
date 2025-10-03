document.addEventListener('DOMContentLoaded', () => {
  // ========== Toggle 🙊/🙈 ==========
  const pwd  = document.getElementById('password');
  const btn  = document.getElementById('togglePwd');
  const hide = document.getElementById('icon-hide');
  const show = document.getElementById('icon-show');

  if (btn && pwd) {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();

      const isShown = (pwd.type === 'text');
      pwd.type = isShown ? 'password' : 'text';

      if (hide && show) {
        hide.classList.toggle('d-none', !isShown);
        show.classList.toggle('d-none', isShown);
      }
      btn.setAttribute('aria-label', isShown ? 'Hiện mật khẩu' : 'Ẩn mật khẩu');
      btn.title = isShown ? 'Hiện mật khẩu' : 'Ẩn mật khẩu';
    });
  }

  // ========== Meter & Caps ==========
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
    if (!meterBar || !pwd) return;
    const s  = pwd.value || "";
    const sc = strengthScore(s);
    const widths = ['0%','25%','50%','75%','100%'];
    meterBar.style.width = widths[sc];

    meterBar.classList.remove('bg-weak','bg-ok','bg-good','bg-strong');
    if      (sc <= 1) meterBar.classList.add('bg-weak');
    else if (sc === 2) meterBar.classList.add('bg-ok');
    else if (sc === 3) meterBar.classList.add('bg-good');
    else               meterBar.classList.add('bg-strong');
  }

  function capsLockCheck(e) {
    if (!capsEl) return;
    const on = e.getModifierState && e.getModifierState('CapsLock');
    capsEl.classList.toggle('opacity-1', !!on);
    capsEl.classList.toggle('opacity-0', !on);
  }

  if (pwd) {
    pwd.addEventListener('input', updateMeter);
    pwd.addEventListener('keydown', capsLockCheck);
    pwd.addEventListener('keyup', capsLockCheck);
    pwd.addEventListener('blur', () => {
      if (capsEl) {
        capsEl.classList.remove('opacity-1');
        capsEl.classList.add('opacity-0');
      }
    });
    updateMeter();
  }

  // ========== Submit loading & chặn double-submit ==========
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', () => {
      const btnSubmit = form.querySelector('button[type="submit"]');
      if (btnSubmit) {
        btnSubmit.classList.add('loading');
        btnSubmit.setAttribute('aria-busy', 'true');
        btnSubmit.disabled = true;
      }
    });
  }

  // ========== Đổi preset nền ==========
  const body = document.body;
  const bgBtn  = document.getElementById('bgToggle');
  const presets = ['bg--aurora','bg--mesh','bg--grid','bg--stripes','bg--blobs'];

  if (body && bgBtn) {
    const saved = localStorage.getItem('tixi-bg');
    if (saved && presets.includes(saved)) {
      body.classList.remove(...presets);
      body.classList.add(saved);
    }

    bgBtn.addEventListener('click', () => {
      const current = presets.find(p => body.classList.contains(p)) || presets[0];
      const nextIdx = (presets.indexOf(current) + 1) % presets.length;
      const next = presets[nextIdx];
      body.classList.remove(...presets);
      body.classList.add(next);
      localStorage.setItem('tixi-bg', next);
    });
  }
});
