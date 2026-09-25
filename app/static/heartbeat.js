(() => {
  const script = document.currentScript;
  const serviceId = script?.dataset.lifeHubService;
  if (!serviceId) return;

  const hubOrigin = new URL(script.src, window.location.href).origin;
  const endpoint = `${hubOrigin}/api/heartbeat`;
  const tabId =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

  const heartbeat = () => {
    fetch(endpoint, {
      method: "POST",
      body: JSON.stringify({ serviceId, tabId }),
      cache: "no-store",
      keepalive: true,
    }).catch(() => {});
  };

  heartbeat();
  window.setInterval(heartbeat, 15000);
  window.addEventListener("pageshow", heartbeat);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") heartbeat();
  });
})();
