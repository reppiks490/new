export const DEFAULT_PRIVACY_PREFERENCES = Object.freeze({
  privacy_mode: true,
  mask_prompts: true,
  blur_media: true,
  quick_hide: true,
  idle_lock_seconds: 30,
  require_unlock_on_resume: true,
  neutral_project_names: true,
});

const PREFERENCE_KEYS = new Set(Object.keys(DEFAULT_PRIVACY_PREFERENCES));

export function createPrivacyController({
  initial = DEFAULT_PRIVACY_PREFERENCES,
  documentRef = globalThis.document,
  onChange = () => {},
  setTimeoutRef = globalThis.setTimeout?.bind(globalThis),
  clearTimeoutRef = globalThis.clearTimeout?.bind(globalThis),
} = {}) {
  let preferences = {...DEFAULT_PRIVACY_PREFERENCES, ...initial};
  let quickHidden = false;
  const revealed = new Set();

  const notify = () => onChange(api.snapshot());
  const concealAll = ({notifyChange = true} = {}) => {
    const changed = revealed.size > 0;
    revealed.clear();
    if (changed && notifyChange) notify();
  };

  const api = {
    snapshot() {
      return {
        preferences: {...preferences},
        quickHidden,
        revealed: [...revealed],
      };
    },
    preferences() {
      return {...preferences};
    },
    setPreferences(next) {
      const safe = {};
      for (const [key, value] of Object.entries(next || {})) {
        if (PREFERENCE_KEYS.has(key)) safe[key] = value;
      }
      preferences = {...preferences, ...safe};
      if (!preferences.privacy_mode) revealed.clear();
      notify();
      return {...preferences};
    },
    isQuickHidden() {
      return quickHidden;
    },
    isRevealed(key) {
      return revealed.has(String(key));
    },
    shouldMaskPrompt() {
      return Boolean(preferences.privacy_mode && preferences.mask_prompts && !revealed.has('prompt'));
    },
    shouldBlurMedia(key) {
      return Boolean(preferences.privacy_mode && preferences.blur_media && !revealed.has(String(key)));
    },
    reveal(key) {
      if (!preferences.privacy_mode || quickHidden) return false;
      const normalized = String(key);
      if (!revealed.has(normalized)) {
        revealed.add(normalized);
        notify();
      }
      return true;
    },
    conceal(key) {
      if (revealed.delete(String(key))) notify();
    },
    toggleReveal(key) {
      const normalized = String(key);
      if (revealed.has(normalized)) api.conceal(normalized);
      else api.reveal(normalized);
      return revealed.has(normalized);
    },
    concealAll,
    quickHide() {
      revealed.clear();
      quickHidden = true;
      notify();
    },
    restore() {
      quickHidden = false;
      revealed.clear();
      notify();
    },
    attachVisibilityGuard() {
      if (!documentRef?.addEventListener) return () => {};
      const handler = () => {
        if (!documentRef.hidden) return;
        revealed.clear();
        if (preferences.require_unlock_on_resume) quickHidden = true;
        notify();
      };
      documentRef.addEventListener('visibilitychange', handler);
      return () => documentRef.removeEventListener?.('visibilitychange', handler);
    },
    attachIdleGuard() {
      if (!documentRef?.addEventListener || !setTimeoutRef || !clearTimeoutRef) return () => {};
      let timer = null;
      const arm = () => {
        if (timer !== null) clearTimeoutRef(timer);
        const seconds = Number(preferences.idle_lock_seconds) || 0;
        if (!preferences.privacy_mode || seconds <= 0) {
          timer = null;
          return;
        }
        timer = setTimeoutRef(() => {
          revealed.clear();
          quickHidden = true;
          notify();
        }, seconds * 1000);
      };
      const activity = () => arm();
      const events = ['pointerdown', 'touchstart', 'keydown'];
      for (const name of events) documentRef.addEventListener(name, activity);
      arm();
      return () => {
        if (timer !== null) clearTimeoutRef(timer);
        for (const name of events) documentRef.removeEventListener?.(name, activity);
      };
    },
  };

  return api;
}

export function revealWhileHeld(target, key, controller) {
  if (!target?.addEventListener) return () => {};
  const reveal = event => {
    event?.preventDefault?.();
    controller.reveal(key);
  };
  const conceal = () => controller.conceal(key);
  const bindings = [
    ['pointerdown', reveal],
    ['touchstart', reveal],
    ['pointerup', conceal],
    ['pointercancel', conceal],
    ['pointerleave', conceal],
    ['touchend', conceal],
    ['touchcancel', conceal],
  ];
  for (const [name, handler] of bindings) target.addEventListener(name, handler);
  return () => {
    for (const [name, handler] of bindings) target.removeEventListener?.(name, handler);
    controller.conceal(key);
  };
}
