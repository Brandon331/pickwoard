/* Service worker de Migo: la app abre aunque no haya red. Las llamadas a la API (otro dominio) NO se tocan nunca. */
const V = 'migo-v1';   // súbelo (v2, v3…) cuando cambies archivos para forzar la actualización
const SHELL = ['app.html', 'qbank.js', 'adaptive-core.js', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png'];
const FONTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('install', e => e.waitUntil(
  caches.open(V).then(c => Promise.all(SHELL.map(f => c.add(f).catch(() => {}))))));      // si falta algún archivo, no se rompe
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('message', e => { if (e.data === 'SKIP_WAITING') self.skipWaiting(); });

const key = u => new Request(u.origin + u.pathname);                                       // ignora ?lvl=… de la landing
async function put(k, res) {
  if (res && (res.ok || res.type === 'opaque')) { const c = await caches.open(V); await c.put(k, res.clone()); }
  return res;
}
self.addEventListener('fetch', e => {
  const r = e.request; if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin === self.location.origin) {
    const k = key(u);
    if (/\.(png|ico|svg)$/.test(u.pathname)) { e.respondWith(caches.match(k).then(m => m || fetch(r).then(res => put(k, res)))); return; }
    // HTML/JS: primero red (siempre lo más nuevo); sin red, lo guardado
    e.respondWith(fetch(r).then(res => put(k, res)).catch(async () =>
      (await caches.match(k)) || (r.mode === 'navigate' ? await caches.match(key(new URL('app.html', self.location.href))) : Response.error())));
    return;
  }
  if (FONTS.includes(u.hostname))                                                           // tipografías: caché primero
    e.respondWith(caches.match(r).then(m => m || fetch(r).then(res => put(r, res))));
});