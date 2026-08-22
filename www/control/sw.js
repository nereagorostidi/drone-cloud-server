// sw.js — Service Worker del panel de control Drone-SAR
//
// Un Service Worker es un script que el navegador ejecuta aparte de la
// página, incluso cuando la pestaña está cerrada. Aquí lo usamos solo
// para UNA cosa: cachear los archivos estáticos (HTML, CSS, iconos) para
// que la app cargue al instante y arranque aunque no haya red.
//
// IMPORTANTE: las peticiones a la API (comandos al dron) NUNCA se cachean.
// Van siempre a la red; si no hay red, deben fallar (no tiene sentido
// "servir en caché" la respuesta de un comando).

// Cambia este nombre/versión cada vez que edites index.html o estilos.css
// para que los navegadores ya instalados descarguen la versión nueva.
const CACHE_NAME = 'dronesar-control-v1';

// "App shell": lo mínimo para que la interfaz se pinte sin red.
const APP_SHELL = [
  './',
  './index.html',
  './estilos.css',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

// La API vive en otro dominio (api.gorostiditfg.com). Cualquier petición
// a ese origen se deja pasar directa a la red, sin tocar la caché.
const API_ORIGIN = 'https://api.gorostiditfg.com';

// --- INSTALL: se dispara al registrar el service worker por primera vez
// (o al detectar una versión nueva de este archivo). Descarga y guarda
// el app shell en la caché.
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting(); // activa la versión nueva sin esperar a cerrar pestañas
});

// --- ACTIVATE: se dispara cuando el service worker nuevo toma el control.
// Aprovechamos para borrar cachés de versiones antiguas.
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// --- FETCH: se dispara en CADA petición que hace la página (HTML, CSS,
// fetch() al API...). Decidimos aquí de dónde sirve cada una.
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1) Peticiones a la API: siempre red, nunca caché.
  if (url.origin === API_ORIGIN) {
    return; // no llamar a event.respondWith() = dejar pasar tal cual
  }

  // 2) Solo nos interesa cachear peticiones GET de nuestro propio origen.
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // 3) Estrategia "cache-first, luego red": si está en caché se sirve al
  // instante (rápido y funciona offline); si no está, se pide a la red
  // y de paso se guarda una copia para la próxima vez.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      });
    })
  );
});
