(function () {
  const cfg = window.APP_CONFIG || {};
  const BASE = String(cfg.API_BASE_URL || "").replace(/\/$/, "");
  const TIMEOUT_MS = 2500;
  const LOG_LIMIT = 300;

  let online = null;
  let probing = null;
  const lastSent = {};

  function readSession() {
    try {
      return JSON.parse(localStorage.getItem("ddsSession") || "null") || {};
    } catch (e) {
      return {};
    }
  }

  async function request(method, path, body) {
    if (!BASE) throw new Error("API_BASE_URL не задан");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    const token = readSession().token;
    const headers = {};
    if (body) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    try {
      const res = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  function probe(force) {
    if (probing && !force) return probing;
    probing = request("GET", "/health")
      .then(() => (online = true))
      .catch(() => (online = false));
    return probing;
  }

  async function login(payload) {
    if (!(await probe())) return null;
    return request("POST", "/auth/login", payload);
  }

  async function pullIncidents() {
    if (!(await probe())) return null;
    const list = await request("GET", "/incidents").catch(() => null);
    if (Array.isArray(list)) list.forEach((i) => (lastSent[i.id] = JSON.stringify(i)));
    return Array.isArray(list) ? list : null;
  }

  function syncIncidents(list) {
    if (online !== true) return;
    list.forEach((inc) => {
      const json = JSON.stringify(inc);
      if (lastSent[inc.id] === json) return;
      lastSent[inc.id] = json;
      request("PUT", "/incidents/" + encodeURIComponent(inc.id), inc).catch(() => delete lastSent[inc.id]);
    });
  }

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
    if (online === true) request("POST", "/events", entry).catch(() => {});
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
