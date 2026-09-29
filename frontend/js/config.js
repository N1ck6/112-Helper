<<<<<<< HEAD
window.APP_CONFIG = {
  API_BASE_URL: "http://localhost:8000/api",
  // API телефонии (telephony/API.md): на стенде — тот же адрес через nginx (/telephony/);
  // страница открыта с GitHub Pages или файлом — телефония на этом же ПК
  TELEPHONY_API_URL:
    location.protocol === "file:" || location.hostname.endsWith("github.io")
      ? "http://localhost:8092"
      : "telephony",
  // Звонок «В браузере» (js/webphone.js): реплики собеседников из ML по контракту
  // POST {ML_DIALOGUE_URL}/dialogue/turn (telephony/API.md §3). Пусто — встроенные правила.
  ML_DIALOGUE_URL: "",
};
=======
window.APP_CONFIG = (function () {
  // Стенд (docker compose): страницу отдаёт nginx стенда — на порту 8080 или за обратным
  // прокси на 80/443, и все сервисы идут через него же: /api/, /telephony/, /ml/.
  // Иначе (Live Server, другой dev-сервер, файл, GitHub Pages) — сервисы стенда на этом ПК
  // по прямым портам. Другой FRONTEND_PORT стенда тоже попадёт сюда: работает на этом ПК.
  const STAND_PORTS = ["", "80", "443", "8080"];
  const onStand = /^https?:$/.test(location.protocol) && !location.hostname.endsWith("github.io") &&
    STAND_PORTS.indexOf(location.port) !== -1;
  const host = location.protocol === "file:" || location.hostname.endsWith("github.io") ? "localhost" : location.hostname;
  const direct = (port, path) => `http://${host}:${port}${path}`;
  return {
    // На стенде без Backend не входим (демо на данных браузера — только GitHub Pages и файл)
    ON_STAND: onStand,
    // Backend (backend/docs/INTEGRATION.md §3): вход и роли. Недоступен — демо-режим в браузере.
    API_BASE_URL: onStand ? "api/v1" : direct(8000, "/api/v1"),
    API_HEALTH_URL: onStand ? "api/health/live" : direct(8000, "/health/live"),
    // API телефонии (telephony/API.md)
    TELEPHONY_API_URL: onStand ? "telephony" : direct(8092, ""),
    // Звонок «В браузере» (js/webphone.js): реплики собеседников из ML по контракту
    // POST {ML_DIALOGUE_URL}/dialogue/turn (telephony/API.md §3). Пусто — встроенные правила
    // (ML наружу открыт только через nginx стенда).
    ML_DIALOGUE_URL: onStand ? "ml" : "",
    // Поиск «Что случилось?» по классификатору происшествий ML (только через nginx стенда)
    ML_TYPES_URL: onStand ? "ml/incident-types" : "",
  };
})();
>>>>>>> origin/main
