/* Caches the app shell so the dashboard opens like an app. Garmin data (/api/) always comes from the server. */
const CACHE = 't100-shell-v1';
const SHELL = ['./', 'index.html', 'base.css', 'd3.min.js', 'dash-shim.js', 'settings.js', 'manifest.webmanifest',
  'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png',
  'fonts/montserrat-latin-400-normal.woff2', 'fonts/montserrat-latin-600-normal.woff2',
  'fonts/montserrat-latin-700-normal.woff2', 'fonts/montserrat-latin-800-normal.woff2'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // Network first, so updates show straight away; the cache covers you when offline.
  e.respondWith(fetch(e.request).then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; }).catch(() => caches.match(e.request)));
});
