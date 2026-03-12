const CACHE = 'focus-v4';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/'])));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).catch(() => caches.match('/'))));
});

self.addEventListener('push', e => {
  const d = e.data ? e.data.json() : {
    title: '🔴 LIVE — Mentalité Focus',
    body: 'Un live est en cours !',
    url: '/'
  };
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body,
    icon: '/manifest.json',
    badge: '/manifest.json',
    vibrate: [300, 100, 300, 100, 600],
    tag: d.tag || 'focus-notif',
    renotify: true,
    requireInteraction: true,
    actions: [
      { action: 'open',  title: '▶ Voir maintenant' },
      { action: 'close', title: '✕ Fermer' }
    ],
    data: { url: d.url || '/' }
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'close') return;
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ws => {
    const w = ws.find(x => x.url.includes(self.location.origin));
    if (w) { w.focus(); w.navigate(e.notification.data?.url || '/'); return; }
    return clients.openWindow(e.notification.data?.url || '/');
  }));
});
