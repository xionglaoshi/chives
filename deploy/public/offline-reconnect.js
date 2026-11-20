// Only the authenticated offline page includes this script.
(() => {
  const interval = 5000;
  let timer;
  let checking = false;
  let navigating = false;

  async function check() {
    clearTimeout(timer);
    if (checking || navigating || document.hidden) return;
    checking = true;
    try {
      const response = await fetch('/chives/api/health', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal: AbortSignal.timeout(4000)
      });
      const expired = response.status === 401;
      if (expired || (response.ok && (await response.json()).ok === true)) {
        navigating = true;
        // The gateway selects the login or workbench view; keep the current Bot URL.
        location.reload();
      }
    } catch {
      // A sleeping Mac or a lost network connection can leave a probe unanswered.
    } finally {
      checking = false;
      if (!navigating && !document.hidden) timer = setTimeout(check, interval);
    }
  }

  window.addEventListener('online', check);
  window.addEventListener('pageshow', check);
  document.addEventListener('visibilitychange', check);
})();
