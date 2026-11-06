/* BioSpine service worker.
   - Pages / scripts / styles: NETWORK FIRST (so people always get the newest version after an update),
     falling back to the cache when offline.
   - /api/ is never cached.  Bump CACHE_NAME on every release. */
const CACHE_NAME = "biospine-v5.7";
const CORE = ["/", "/static/style.css", "/static/app.js", "/static/extras.js", "/static/extras.css", "/static/theme.js", "/static/audio/alarm.mp3", "/static/manifest.json", "/static/img/icon-192.png"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(CORE)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/admin/") || url.pathname.startsWith("/staff/")) return;
  if (url.origin !== location.origin && !url.hostname.endsWith("cdnjs.cloudflare.com")) return;
  event.respondWith(
    fetch(req).then(res => {
      if (res && res.status === 200) { const copy = res.clone(); caches.open(CACHE_NAME).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then(hit => hit || (req.mode === "navigate" ? caches.match("/") : undefined)))
  );
});
