// Связь с Backend (backend/docs/INTEGRATION.md §3): проверка доступности, вход по логину
// и паролю, роли из /auth/me, токены (обновление по refresh_token).
// Карточки, журнал и сеансы пока живут в localStorage: поток карточек, занятия и отчёты
// Backend (/training, /lessons, /reports) интерфейс ещё не использует.
(function () {
  const cfg = window.APP_CONFIG || {};
  const BASE = String(cfg.API_BASE_URL || "").replace(/\/$/, "");
  const HEALTH_URL = String(cfg.API_HEALTH_URL || "");
  const TIMEOUT_MS = 8000;
  const LOG_LIMIT = 300;
  // Роли Backend -> роли входа в интерфейсе: обучающийся работает оператором 112 или диспетчером ДДС
  const ROLE_MAP = { student: ["student", "dispatcher"], teacher: ["teacher"], admin: ["admin"] };

  let online = null;
  let probing = null;

  function readSession() {
    try {
      return JSON.parse(localStorage.getItem("ddsSession") || "null") || {};
    } catch (e) {
      return {};
    }
  }

  function errorText(data, status) {
    const err = data && data.error;
    if (err && typeof err === "object") return err.message || err.code || "HTTP " + status;
    return (data && (data.detail || err)) || "HTTP " + status;
  }

  async function send(method, url, body, token) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    const headers = {};
    if (body) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    try {
      const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal });
      const data = await res.json().catch(() => ({}));
      return { res, data };
    } finally {
      clearTimeout(timer);
    }
  }

  // access-токен живёт 30 минут: при token_expired один раз обновляем его и повторяем запрос
  async function refreshToken() {
    const s = readSession();
    if (!s.refreshToken) return false;
    const { res, data } = await send("POST", BASE + "/auth/refresh", { refresh_token: s.refreshToken });
    if (!res.ok || !data.access_token) return false;
    s.token = data.access_token;
    s.refreshToken = data.refresh_token || s.refreshToken;
    localStorage.setItem("ddsSession", JSON.stringify(s));
    return true;
  }

  async function request(method, path, body) {
    if (!BASE) throw new Error("API_BASE_URL не задан");
    let { res, data } = await send(method, BASE + path, body, readSession().token);
    if (res.status === 401 && data.error && data.error.code === "token_expired" && (await refreshToken())) {
      ({ res, data } = await send(method, BASE + path, body, readSession().token));
    }
    if (!res.ok) throw new Error(errorText(data, res.status));
    return data;
  }

  function probe(force) {
    if (probing && !force) return probing;
    probing = (HEALTH_URL ? send("GET", HEALTH_URL) : Promise.reject(new Error("API_HEALTH_URL не задан")))
      .then(({ res }) => (online = res.ok))
      .catch(() => (online = false));
    return probing;
  }

  // null — Backend недоступен (вход в демо-режиме); исключение — Backend отказал во входе
  async function login(payload) {
    if (!(await probe())) return null;
    const { res, data } = await send("POST", BASE + "/auth/login", { username: payload.username, password: payload.password });
    if (!res.ok) throw new Error(errorText(data, res.status));
    if (data.mfa_required) throw new Error("Для учётной записи включён второй фактор (MFA) — вход пока только через API");
    const me = await send("GET", BASE + "/auth/me", null, data.access_token);
    if (!me.res.ok) throw new Error(errorText(me.data, me.res.status));
    const allowed = (me.data.roles || []).reduce((acc, r) => acc.concat(ROLE_MAP[r] || []), []);
    if (allowed.indexOf(payload.role) === -1) {
      throw new Error("У учётной записи нет доступа к выбранной роли");
    }
    return {
      token: data.access_token,
      refreshToken: data.refresh_token,
      userId: me.data.id,
      fullName: me.data.full_name || me.data.username,
      roles: me.data.roles || [],
      permissions: me.data.permissions || [],
    };
  }

  // Карточки пока хранит браузер: /incidents Backend — это классификатор происшествий,
  // а не карточки интерфейса, поэтому синхронизации с ним нет.
  function pullIncidents() {
    return Promise.resolve(null);
  }

  function syncIncidents() {}

  function readLog() {
    try {
      return JSON.parse(localStorage.getItem("ddsLog") || "[]");
    } catch (e) {
      return [];
    }
  }

  function log(type, text) {
    const s = readSession();
    const entry = { t: new Date().toISOString(), role: s.role || "", user: s.fullName || "", ws: s.workstation || "", type: type, text: text };
    const list = readLog();
    list.push(entry);
    localStorage.setItem("ddsLog", JSON.stringify(list.slice(-LOG_LIMIT)));
  }

  const SESSIONS_KEY = "ddsSessions";
  const ALIVE_MS = 45000;

  function readSessions() {
    try {
      return JSON.parse(localStorage.getItem(SESSIONS_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function touchSession(s) {
    if (!s || !s.sid) return;
    const now = Date.now();
    const list = readSessions().filter((x) => now - x.lastSeen < ALIVE_MS * 4);
    const idx = list.findIndex((x) => x.sid === s.sid);
    const rec = { sid: s.sid, user: s.fullName, role: s.role, ws: s.workstation || "", since: idx >= 0 ? list[idx].since : now, lastSeen: now };
    if (idx >= 0) list[idx] = rec;
    else list.push(rec);
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(list));
  }

  function dropSession(sid) {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(readSessions().filter((x) => x.sid !== sid)));
  }

  function activeSessions() {
    const now = Date.now();
    return readSessions().filter((x) => now - x.lastSeen < ALIVE_MS);
  }

  probe();

  window.DDS_API = {
    touchSession,
    dropSession,
    activeSessions,
    base: BASE,
    isOnline: () => online,
    probe,
    request,
    login,
    pullIncidents,
    syncIncidents,
    log,
    readLog,
  };
})();
