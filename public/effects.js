const preferenceKey = 'hehe-office-effects';

function savedPreference() {
  try {
    const value = localStorage.getItem(preferenceKey);
    return value === 'soft' || value === 'full' ? value : null;
  } catch {
    return null;
  }
}

export function mountEffects({onChange} = {}) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const button = document.getElementById('fx-toggle');
  let preference = savedPreference();
  let mode;

  function sync() {
    const next = preference ?? (reducedMotion.matches ? 'soft' : 'full');
    if (next === mode) return;
    mode = next;
    document.documentElement.dataset.effects = mode;
    if (button) {
      const full = mode === 'full';
      button.setAttribute('aria-label', '绚彩光效');
      button.setAttribute('aria-pressed', String(full));
      button.title = full ? '绚彩光效已开启，点击切换为柔和光效' : '柔和光效已开启，点击切换为绚彩光效';
    }
    onChange?.(mode);
  }

  function toggle() {
    const next = mode === 'full' ? 'soft' : 'full';
    // Returning to the system default releases the override for future changes.
    preference = next === (reducedMotion.matches ? 'soft' : 'full') ? null : next;
    try {
      if (preference === null) localStorage.removeItem(preferenceKey);
      else localStorage.setItem(preferenceKey, preference);
    } catch { /* Keep the current session's choice when storage is unavailable. */ }
    sync();
  }

  function onStorage(event) {
    if (event.key !== preferenceKey && event.key !== null) return;
    preference = savedPreference();
    sync();
  }

  button?.addEventListener('click', toggle);
  reducedMotion.addEventListener('change', sync);
  window.addEventListener('storage', onStorage);
  sync();
  return {
    get mode() { return mode; },
    dispose() {
      button?.removeEventListener('click', toggle);
      reducedMotion.removeEventListener('change', sync);
      window.removeEventListener('storage', onStorage);
    },
  };
}
