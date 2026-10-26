/* Service worker của Tymex (PWA) — chiến lược bộ nhớ đệm THẬN TRỌNG để không bao giờ
   phục vụ mã ứng dụng cũ sau một đợt triển khai:
   - Điều hướng mở trang: NETWORK-FIRST — có mạng là luôn lấy bản mới nhất từ máy chủ,
     chỉ khi mất mạng mới dùng index.html đã đệm (vỏ ứng dụng vẫn mở được).
   - Tài nguyên cùng nguồn còn lại (js/css có hậu tố ?v=, biểu tượng, manifest):
     stale-while-revalidate — hiện bản đệm ngay cho nhanh, đồng thời tải bản mới ở nền.
   - Chỉ can thiệp GET cùng nguồn. Mọi request khác nguồn (Supabase, ESPN, TheSportsDB)
     và mọi POST/đăng nhập đều đi thẳng ra mạng, không qua bộ nhớ đệm này.
   NGHĨA VỤ NGƯỜI DUY TRÌ: VERSION dưới đây phải luôn khớp hậu tố ?v= trong web/index.html.
   Mỗi đợt phát hành tăng ?v= thì phải tăng cả VERSION (tên cache đổi → cache cũ bị xóa). */
"use strict";

const VERSION = "20261026f";
const CACHE = `tymex-shell-${VERSION}`;
const PRECACHE = ["/", "/index.html", "/manifest.json", "/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith("tymex-shell-") && k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // khác nguồn: trình duyệt tự gọi mạng như bình thường

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put("/index.html", copy));
          }
          return res;
        })
        .catch(() => caches.match("/index.html"))
    );
    return;
  }

  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(req).then((cached) => {
        const network = fetch(req)
          .then((res) => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          })
          .catch(() => cached);
        return cached || network;
      })
    )
  );
});
