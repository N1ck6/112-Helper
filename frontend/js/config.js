window.APP_CONFIG = (function () {
  // На стенде (docker compose) всё идёт через nginx этого же адреса: /api/, /telephony/, /ml/.
  // Страница открыта с GitHub Pages или файлом — сервисы стенда на этом же ПК.
  const standalone = location.protocol === "file:" || location.hostname.endsWith("github.io");
  return {
    // Backend (backend/docs/INTEGRATION.md §3): вход и роли. Недоступен — демо-режим в браузере.
    API_BASE_URL: standalone ? "http://localhost:8000/api/v1" : "api/v1",
    API_HEALTH_URL: standalone ? "http://localhost:8000/health/live" : "api/health/live",
    // API телефонии (telephony/API.md)
    TELEPHONY_API_URL: standalone ? "http://localhost:8092" : "telephony",
    // Звонок «В браузере» (js/webphone.js): реплики собеседников из ML по контракту
    // POST {ML_DIALOGUE_URL}/dialogue/turn (telephony/API.md §3). Пусто — встроенные правила.
    ML_DIALOGUE_URL: standalone ? "" : "ml",
  };
})();
