// Minimal service worker: network passthrough, exists for PWA installability.
// Only registers over HTTPS (secure context); the app itself never depends on it.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  e.respondWith(fetch(e.request));
});
