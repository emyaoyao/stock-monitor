// 买点监控 PWA · Service Worker
const CACHE = "bm-pwa-v2";   // 版本号变化会触发 Service Worker 更新并重建缓存
const SHELL = [
  "./", "./index.html", "./app.js", "./styles.css", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-180.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;            // 跨域（api.github.com）走网络
  if (u.pathname.includes("/outputs/")) {             // 监控数据：网络优先，失败回退缓存
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // 外壳：网络优先，失败回退缓存（在线总能拿到最新版本，离线仍可用）
  e.respondWith(
    fetch(e.request).then((res) => {
      const cp = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, cp));
      return res;
    }).catch(() => caches.match(e.request).then((r) => r || caches.match("./")))
  );
});
