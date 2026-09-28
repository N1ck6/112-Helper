/* Панель «Телефон» АРМ ДДС — связь интерфейса с телефонией (контракт: telephony/API.md).
 *
 * Голос идёт через софтфон / IP-телефон рабочего места (SIP-аккаунт ws01…ws20),
 * браузер управляет звонками и показывает разговор:
 *   • номеронабиратель: набор мышкой или с клавиатуры, справочник номеров;
 *   • ☎ у службы в карточке оператора и диспетчера — звонок в службу (dispatch);
 *   • «☎ Вызов голосом» в карточке оператора — учебный заявитель 112 звонит на телефон;
 *   • «Перезвонить и уточнить» у диспетчера — звонок заявителю (applicant);
 *   • «Доклад старшего группы» (диспетчер) — входящий доклад службы (report);
 *   • ход звонка и реплики вживую (SSE), «Завершить», запись после разговора;
 *   • отработки: каждый звонок по карточке сохраняется в ней (служба, номер, кто принял,
 *     суть, время, запись) — window.DDS.addCallLog из app.js;
 *   • статус оператора «доступен / недоступен» передаётся телефонии: на паузе
 *     не приходят входящие вызовы от системы.
 *
 * Связь с app.js — события dds:card-open / dds:card-close / dds:review-open /
 * dds:review-close / dds:callback / dds:operator-status и объект window.DDS.
 * Рабочее место: session.workstation, ?ws=ws02 в адресе (запоминается) или ws01.
 */
(function () {
  "use strict";
  if (!document.getElementById("incident-sheet")) return;
  window.DDS_TELEPHONY = true;

  const cfg = window.APP_CONFIG || {};
  const TEL = String(cfg.TELEPHONY_API_URL || "telephony").replace(/\/$/, "");
  const TEL_RELATIVE = !/^[a-z]+:\/\//i.test(TEL);
  const SCENARIOS_112 = ["scenario_001", "scenario_002"];
  const REPORT_STAGES = ["arrival", "in_progress", "completed"];
  const CALL_TYPE_LABEL = {
    dispatch: "Звонок в службу",
    applicant: "Звонок заявителю",
    report: "Доклад старшего группы",
    incident_112: "Вызов 112",
    echo: "Эхо-тест",
  };
  const FAIL_REASON = {
    unavailable: "телефон рабочего места не подключён",
    busy: "линия занята",
    no_answer: "трубку не сняли",
    rejected: "вызов отклонён",
    timeout: "нет ответа",
    ami_error: "телефония недоступна",
  };
  const END_REASON = {
    completed: "разговор завершён",
    operator_hangup: "вы положили трубку",
    unknown_number: "номер не обслуживается",
    ml_error: "собеседник недоступен (ML)",
    max_turns: "превышено число реплик",
    max_duration: "превышена длительность",
    internal_error: "сбой телефонии",
  };

  const session = (function () {
    try { return JSON.parse(localStorage.getItem("ddsSession") || "null") || {}; } catch (e) { return {}; }
  })();

  if (["student", "dispatcher"].indexOf(session.role) === -1) {
    window.DDS_TELEPHONY = false;
    return;
  }

  const WS = (function () {
    const fromUrl = new URLSearchParams(location.search).get("ws");
    try {
      if (fromUrl) localStorage.setItem("ddsWorkstation", fromUrl);
      return session.workstation || fromUrl || localStorage.getItem("ddsWorkstation") || "ws01";
    } catch (e) {
      return session.workstation || fromUrl || "ws01";
    }
  })();

  // ------------------------------------------------------------------ API ---
  async function api(method, path, body) {
    const res = await fetch(`${TEL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }
  const quiet = (p) => p.catch(() => {});

  function recordingUrl(url) {
    if (!url) return null;
    // на стенде записи отдаёт тот же nginx: /recordings/<файл>
    return TEL_RELATIVE ? `recordings/${String(url).split("/").pop()}` : url;
  }

  const hhmm = () => new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const $ = (id) => document.getElementById(id);
  const text = (id) => {
    const node = $(id);
    if (!node) return "";
    const v = (node.value !== undefined ? node.value : node.textContent) || "";
    return v.trim() === "—" ? "" : v.trim();
  };

  // --------------------------------------------------------------- стили ---
  const style = document.createElement("style");
  style.textContent = `
  .tel-widget{position:fixed;right:16px;bottom:16px;z-index:150;width:min(340px,calc(100vw - 32px));
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    background:var(--panel-800);border:1px solid var(--border-600);border-radius:var(--radius-lg);
    box-shadow:var(--shadow-panel);color:var(--ink-100);font-family:var(--font-ui);font-size:.8rem}
  .tel-head{display:flex;align-items:center;gap:8px;padding:9px 12px;cursor:pointer;user-select:none;flex:none}
  .tel-dot{width:8px;height:8px;border-radius:50%;background:var(--ink-600);flex:none}
  .tel-dot.ok{background:var(--success-500)} .tel-dot.bad{background:var(--danger-500)}
  .tel-dot.live{background:var(--accent-500);animation:tel-pulse 1s infinite}
  @keyframes tel-pulse{50%{opacity:.35}}
  .tel-title{font-weight:700;white-space:nowrap}
  .tel-sub{color:var(--ink-600);margin-left:auto;font-size:.9em;text-align:right}
  .tel-body{border-top:1px solid var(--border-600);padding:10px 12px;display:grid;gap:10px;overflow-y:auto;overflow-x:hidden}
  .tel-body>*{min-width:0} .tel-logitem{overflow-wrap:anywhere}
  .tel-widget.collapsed .tel-body{display:none}
  .tel-section-title{font-size:.85em;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-600);font-weight:700}
  .tel-call-title{font-weight:600} .tel-state{color:var(--ink-400)}
  .tel-log{max-height:200px;overflow-y:auto;display:grid;gap:6px}
  .tel-line{padding:6px 8px;border-radius:var(--radius-md);background:var(--panel-700);line-height:1.35}
  .tel-line.operator{background:transparent;border:1px solid var(--border-600)}
  .tel-line b{display:block;font-size:.85em;color:var(--ink-600);font-weight:600;margin-bottom:2px}
  .tel-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .tel-btn{font:inherit;font-weight:600;cursor:pointer;border-radius:var(--radius-md);padding:6px 10px;
    border:1px solid var(--border-600);background:var(--panel-700);color:var(--ink-100)}
  .tel-btn:hover:not(:disabled){border-color:var(--accent-500)}
  .tel-btn.primary{background:var(--success-500);border-color:transparent;color:#fff}
  .tel-btn.danger{background:var(--accent-500);border-color:transparent;color:#fff}
  .tel-btn:disabled{opacity:.45;cursor:default}
  .tel-display{flex:1;min-width:0;font:600 1.25em var(--font-mono);letter-spacing:.08em;padding:6px 8px;
    border-radius:var(--radius-md);border:1px solid var(--border-600);background:var(--panel-900);color:var(--ink-100)}
  .tel-keys{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
  .tel-keys .tel-btn{font-family:var(--font-mono);font-size:1.2em;padding:.55em 0}
  .tel-select{flex:1;min-width:0;font:inherit;padding:6px;border-radius:var(--radius-md);
    border:1px solid var(--border-600);background:var(--panel-900);color:var(--ink-100)}
  .tel-logs{display:grid;gap:6px}
  .tel-logitem{padding:6px 8px;border-radius:var(--radius-md);border:1px solid var(--border-600);line-height:1.4}
  .tel-logitem .muted,.tel-hint{color:var(--ink-600);font-size:.9em}
  .tel-widget audio{width:100%;height:32px}
  .tel-chip-call{font:inherit;cursor:pointer;border:none;background:var(--accent-500);color:#fff;border-radius:999px;
    padding:1px 8px;margin-left:6px;font-size:.7rem;font-weight:700}
  .tel-chip-call:disabled{opacity:.45;cursor:default}
  .tel-voice-112{margin-left:auto}
  .tel-row .tel-btn[data-el=book]{flex:1}
  .tel-popover{position:fixed;right:calc(min(340px,100vw - 32px) + 28px);bottom:16px;z-index:160;width:310px;
    max-height:min(72vh,540px);overflow:auto;background:var(--panel-800);border:1px solid var(--border-600);
    border-radius:var(--radius-lg);box-shadow:var(--shadow-panel);padding:10px;color:var(--ink-100);
    font-family:var(--font-ui);font-size:.8rem;animation:tel-pop .18s ease-out}
  @keyframes tel-pop{from{opacity:0;transform:translateX(10px)}to{opacity:1;transform:none}}
  .tel-popover[hidden]{display:none}
  .tel-pop-head{display:flex;justify-content:space-between;align-items:center;font-weight:700;margin-bottom:4px}
  .tel-pop-close{font:inherit;border:none;background:transparent;color:var(--ink-600);cursor:pointer;font-size:1.1rem;line-height:1}
  .tel-pop-title{font-size:.66rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-600);font-weight:700;margin:8px 0 4px}
  .tel-num{display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:var(--radius-md);cursor:pointer}
  .tel-num:hover,.tel-num:focus-visible{background:var(--panel-700);outline:none}
  .tel-num b{font:700 1rem var(--font-mono);min-width:46px}
  .tel-num span{flex:1;color:var(--ink-400);overflow-wrap:anywhere}
  .tel-widget.docked{position:static;z-index:auto;width:auto;max-height:none;flex:1;min-height:0;
    box-shadow:none;border-radius:var(--radius-md);font-size:1.1em}
  .tel-widget.docked .tel-head{cursor:default}
  .tel-widget.docked .tel-body{flex:1;min-height:0;align-content:start}
  .tel-widget.docked .tel-log{max-height:none;flex:none}
  @media (max-width:720px){.tel-popover{left:16px;right:16px;width:auto;bottom:auto;top:16px}}
  `;
  document.head.appendChild(style);

  // --------------------------------------------------------------- панель ---
  const widget = document.createElement("section");
  widget.className = "tel-widget collapsed";
  widget.setAttribute("aria-label", "Телефон рабочего места");
  widget.innerHTML = `
    <div class="tel-head" title="Развернуть / свернуть">
      <span class="tel-dot" data-el="dot"></span>
      <span class="tel-title">☎ Телефон · <span data-el="ws"></span></span>
      <span class="tel-sub" data-el="sub">проверка…</span>
    </div>
    <div class="tel-body">
      <div>
        <div class="tel-call-title" data-el="call">Звонков нет</div>
        <div class="tel-state" data-el="state"></div>
      </div>
      <div class="tel-log" data-el="log"></div>
      <div class="tel-row">
        <button type="button" class="tel-btn danger" data-el="hangup" hidden>Завершить</button>
        <button type="button" class="tel-btn" data-el="report" hidden>Доклад старшего группы</button>
      </div>
      <audio controls preload="none" data-el="audio" hidden></audio>

      <div class="tel-section-title">Набор номера</div>
      <div class="tel-row">
        <input class="tel-display" data-el="display" inputmode="numeric" autocomplete="off" maxlength="6" placeholder="2101" aria-label="Номер">
        <button type="button" class="tel-btn" data-el="back" aria-label="Стереть">⌫</button>
      </div>
      <div class="tel-keys" data-el="keys"></div>
      <div class="tel-row">
        <button type="button" class="tel-btn" data-el="book" aria-expanded="false" aria-haspopup="dialog">☰ Справочник</button>
        <button type="button" class="tel-btn primary" data-el="dial">Вызов</button>
      </div>

      <div class="tel-section-title" data-el="logs-title" hidden>Отработки по карточке</div>
      <div class="tel-logs" data-el="logs"></div>

      <div class="tel-hint" data-el="hint"></div>
      <div class="tel-row"><button type="button" class="tel-btn" data-el="change">Сменить рабочее место</button></div>
    </div>`;
  document.body.appendChild(widget);
  const el = {};
  widget.querySelectorAll("[data-el]").forEach((n) => (el[n.dataset.el] = n));
  el.ws.textContent = WS;
  el.hint.textContent =
    `Голос — через софтфон рабочего места: сервер ${location.hostname || "<IP стенда>"}:5063 (UDP), ` +
    `логин ${WS}. Трубку берёте на телефоне, звонком управляет эта панель.`;
  el.report.hidden = session.role !== "dispatcher";

  "123456789*0#".split("").forEach((k) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tel-btn";
    b.textContent = k;
    b.addEventListener("click", () => {
      if (/\d/.test(k) && el.display.value.length < 6) el.display.value += k;
    });
    el.keys.appendChild(b);
  });
  el.back.addEventListener("click", () => (el.display.value = el.display.value.slice(0, -1)));
  el.display.addEventListener("input", () => (el.display.value = el.display.value.replace(/\D/g, "").slice(0, 6)));
  el.display.addEventListener("keydown", (e) => { if (e.key === "Enter") dialNumber(); });
  el.dial.addEventListener("click", dialNumber);
  function setOpen(open) {
    widget.classList.toggle("collapsed", !open);
    document.body.classList.toggle("tel-open", open);
  }
  widget.querySelector(".tel-head").addEventListener("click", () => {
    if (!widget.classList.contains("docked")) setOpen(widget.classList.contains("collapsed"));
  });

  // В карточке оператора панель встроена в правую колонку окна (#phone-dock),
  // вне карточки — плавающая в углу экрана.
  const dock = $("phone-dock");
  let undockTimer = null;
  let floatOpen = false;
  function setDocked(on) {
    clearTimeout(undockTimer);
    if (!dock) return;
    openBook(false);
    if (on) {
      if (widget.classList.contains("docked")) return;
      floatOpen = !widget.classList.contains("collapsed");
      dock.textContent = "";
      dock.appendChild(widget);
      widget.classList.add("docked");
      widget.classList.remove("collapsed");
      document.body.classList.remove("tel-open");
    } else {
      // ждём окончания анимации закрытия окна, чтобы колонка не опустела раньше времени
      undockTimer = setTimeout(() => {
        widget.classList.remove("docked");
        document.body.appendChild(widget);
        setOpen(floatOpen);
      }, 320);
    }
  }
  el.change.addEventListener("click", () => {
    const next = prompt("SIP-аккаунт рабочего места (ws01…ws20):", WS);
    if (next && next.trim() && next.trim() !== WS) {
      const url = new URL(location.href);
      url.searchParams.set("ws", next.trim());
      location.href = url.toString();
    }
  });

  // ------------------------------------------- справочник номеров (всплывающее окно) ---
  const EMERGENCY = [
    { number: "101", title: "Пожарная охрана · МЧС" },
    { number: "102", title: "Полиция" },
    { number: "103", title: "Скорая медицинская помощь" },
    { number: "104", title: "Аварийная газовая служба" },
    { number: "112", title: "Единая служба спасения" },
  ];
  let standNumbers = [];
  const escHtml = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const pop = document.createElement("div");
  pop.className = "tel-popover";
  pop.hidden = true;
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", "Справочник номеров");
  document.body.appendChild(pop);

  function numRow(n) {
    return `<div class="tel-num" data-number="${escHtml(n.number)}" tabindex="0"><b>${escHtml(n.number)}</b><span>${escHtml(n.title)}${n.name ? " (" + escHtml(n.name) + ")" : ""}</span><button type="button" class="tel-chip-call tel-num-call" data-dial="${escHtml(n.number)}" title="Позвонить">☎</button></div>`;
  }

  function renderBook() {
    pop.innerHTML = `
      <div class="tel-pop-head"><span>Справочник номеров</span><button type="button" class="tel-pop-close" aria-label="Закрыть">×</button></div>
      <div class="tel-pop-title">Экстренные службы</div>
      ${EMERGENCY.map(numRow).join("")}
      ${standNumbers.length ? `<div class="tel-pop-title">Номера учебного стенда</div>${standNumbers.map(numRow).join("")}` : ""}`;
  }

  function openBook(open) {
    if (open) renderBook();
    // у встроенной панели справочник открывается слева от неё
    const r = widget.classList.contains("docked") && open ? widget.getBoundingClientRect() : null;
    pop.style.right = r ? Math.max(16, window.innerWidth - r.left + 12) + "px" : "";
    pop.style.bottom = r ? Math.max(16, window.innerHeight - r.bottom) + "px" : "";
    pop.hidden = !open;
    el.book.setAttribute("aria-expanded", open ? "true" : "false");
  }

  el.book.addEventListener("click", () => openBook(pop.hidden));
  pop.addEventListener("click", (e) => {
    if (e.target.closest(".tel-pop-close")) return openBook(false);
    const callBtn = e.target.closest("[data-dial]");
    const row = e.target.closest("[data-number]");
    if (!row) return;
    el.display.value = row.dataset.number;
    openBook(false);
    if (callBtn) dialNumber();
    else el.display.focus();
  });
  pop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("[data-number]")) {
      el.display.value = e.target.dataset.number;
      openBook(false);
      el.display.focus();
    }
  });
  document.addEventListener("mousedown", (e) => {
    if (!pop.hidden && !pop.contains(e.target) && e.target !== el.book) openBook(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.hidden) openBook(false);
  });

  api("GET", "/numbers").then((list) => {
    standNumbers = Array.isArray(list) ? list : [];
  }).catch(() => {});

  // ------------------------------------------------------ состояние звонка ---
  let registered = null;  // софтфон зарегистрирован; null — телефония недоступна
  let mlOk = true;
  let current = null;     // {call_id, call_type, persona, status}
  const tracked = {};     // call_id -> {cardId, call_type, persona, dialed, startedAt} для отработок
  let card = null;        // открытая карточка: {id, source: "sheet"|"review", incident}

  const busy = () => !!(current && current.status !== "ended");

  function renderStatus() {
    el.dot.className = "tel-dot" + (busy() ? " live" : registered && mlOk ? " ok" : registered === null ? "" : " bad");
    if (current && current.status === "dialing") el.sub.textContent = "вызов…";
    else if (current && current.status === "in_progress") el.sub.textContent = "идёт разговор";
    else if (registered === null) el.sub.textContent = "телефония недоступна";
    else if (!registered) el.sub.textContent = "телефон не подключён";
    else el.sub.textContent = mlOk ? "готов" : "собеседники недоступны (ML)";
    el.hangup.hidden = !busy();
    document.querySelectorAll(".tel-chip-call, .tel-voice-112, .tel-callback").forEach((b) => (b.disabled = busy()));
    el.dial.disabled = busy();
    el.report.disabled = busy();
  }

  async function poll() {
    try {
      const [list, health] = await Promise.all([api("GET", "/endpoints"), api("GET", "/health").catch(() => ({}))]);
      const ep = list.find((e) => e.endpoint === WS);
      registered = !!(ep && ep.registered);
      mlOk = health.ml !== false;
    } catch (e) {
      registered = null;
    }
    renderStatus();
  }
  poll();
  setInterval(poll, 10000);

  function who(persona) {
    if (!persona) return "";
    return [persona.service, persona.position, persona.name].filter(Boolean).join(" · ");
  }

  function addLine(role, line, persona) {
    if (!line) return;
    const item = document.createElement("div");
    item.className = "tel-line " + (role === "operator" ? "operator" : "caller");
    const b = document.createElement("b");
    b.textContent = role === "operator" ? "Вы" : (persona && (persona.name || persona.service)) || "Собеседник";
    item.appendChild(b);
    item.appendChild(document.createTextNode(line));
    el.log.appendChild(item);
    el.log.scrollTop = el.log.scrollHeight;
  }

  function showCall(callId, callType, persona, state, dialed) {
    current = { call_id: callId, call_type: callType, persona: persona, status: "dialing" };
    const title = CALL_TYPE_LABEL[callType] || "Звонок";
    el.call.textContent = `${title}${persona ? ": " + who(persona) : dialed ? ": " + dialed : ""}`;
    el.state.textContent = state || "";
    el.log.innerHTML = "";
    el.audio.hidden = true;
    setOpen(true);
    renderStatus();
  }

  function track(callId, info) {
    if (!callId || tracked[callId]) return;
    tracked[callId] = Object.assign({ cardId: card ? card.id : null, startedAt: hhmm() }, info);
  }

  // --------------------------------------------------------- отработки ---
  function saveCallLog(d, status) {
    const t = tracked[d.call_id];
    if (!t || !t.cardId || !window.DDS || !["dispatch", "applicant", "report"].includes(t.call_type)) return;
    const persona = d.persona || t.persona || {};
    const transcript = d.transcript || [];
    const said = transcript.filter((x) => x.role === (t.call_type === "report" ? "caller" : "operator") && x.text);
    const entry = {
      time: t.startedAt,
      call_type: t.call_type,
      service: persona.service || null,
      number: persona.number || t.dialed || null,
      accepted_by: [persona.position, persona.name].filter(Boolean).join(" ") || null,
      summary: said.length ? said[0].text : null,
      status: status,
      duration_sec: d.duration_sec || 0,
      recording_url: d.recording_url || null,
      call_id: d.call_id,
    };
    if (window.DDS.addCallLog(t.cardId, entry)) renderLogs();
    delete tracked[d.call_id];
  }

  function renderLogs() {
    const incident = card && window.DDS ? window.DDS.getIncident(card.id) : null;
    const logs = (incident && incident.calls) || [];
    el["logs-title"].hidden = !logs.length;
    el.logs.innerHTML = "";
    logs.slice().reverse().forEach((c) => {
      const item = document.createElement("div");
      item.className = "tel-logitem";
      const head = document.createElement("div");
      head.textContent = `${c.time} · ${c.service || CALL_TYPE_LABEL[c.call_type] || "звонок"}${c.number ? " (" + c.number + ")" : ""}`;
      const meta = document.createElement("div");
      meta.className = "muted";
      meta.textContent = c.status === "failed"
        ? `Не оповещено: ${FAIL_REASON[c.reason] || c.reason || "нет связи"}`
        : `Принял: ${c.accepted_by || "—"} · ${c.duration_sec} с${c.summary ? " · Суть: " + c.summary : ""}`;
      item.appendChild(head);
      item.appendChild(meta);
      if (c.recording_url) {
        const a = document.createElement("a");
        a.href = recordingUrl(c.recording_url);
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = "Запись";
        a.className = "muted";
        item.appendChild(a);
      }
      el.logs.appendChild(item);
    });
  }

  // ------------------------------------------------------------ события ---
  const es = new EventSource(`${TEL}/events?trainee=${encodeURIComponent(WS)}`);
  const on = (type, fn) => es.addEventListener(type, (e) => {
    try { fn(JSON.parse(e.data)); } catch (err) { /* повреждённое событие пропускаем */ }
  });
  on("call.dialing", (d) => {
    track(d.call_id, { call_type: d.call_type, persona: d.persona, dialed: d.dialed });
    if (!current || current.call_id !== d.call_id) showCall(d.call_id, d.call_type, d.persona, "", d.dialed);
    el.state.textContent = ["incident_112", "report"].includes(d.call_type)
      ? "Входящий вызов — снимите трубку"
      : "Телефон звонит — снимите трубку, дальше пойдёт вызов";
  });
  on("call.started", (d) => {
    // звонок, набранный прямо с трубки, приходит сразу со started
    track(d.call_id, { call_type: d.call_type, persona: d.persona, dialed: d.dialed });
    if (!current || current.call_id !== d.call_id) showCall(d.call_id, d.call_type, d.persona, "", d.dialed);
    current.status = "in_progress";
    current.persona = d.persona || current.persona;
    if (d.persona) el.call.textContent = `${CALL_TYPE_LABEL[d.call_type] || "Звонок"}: ${who(d.persona)}`;
    el.state.textContent = "Разговор";
    renderStatus();
  });
  on("call.utterance", (d) => {
    if (current && current.call_id === d.call_id) addLine(d.role, d.text, current.persona);
  });
  on("call.failed", (d) => {
    const t = tracked[d.call_id];
    if (t && t.cardId && window.DDS && ["dispatch", "applicant"].includes(t.call_type)) {
      window.DDS.addCallLog(t.cardId, {
        time: t.startedAt, call_type: t.call_type, service: (t.persona || {}).service || null,
        number: (t.persona || {}).number || t.dialed || null, status: "failed", reason: d.reason, call_id: d.call_id,
      });
      renderLogs();
    }
    delete tracked[d.call_id];
    if (!current || current.call_id !== d.call_id) return;
    current.status = "ended";
    el.state.textContent = "Не дозвонились: " + (FAIL_REASON[d.reason] || d.reason);
    renderStatus();
  });
  on("call.error", (d) => {
    if (current && current.call_id === d.call_id && d.stage === "ml") el.state.textContent = "Собеседник недоступен (ML) — звонок завершается";
  });
  on("call.ended", (d) => {
    saveCallLog(d, "completed");
    if (!current || current.call_id !== d.call_id) return;
    current.status = "ended";
    el.state.textContent = `Звонок завершён: ${END_REASON[d.reason] || d.reason} · ${d.duration_sec || 0} с`;
    const rec = recordingUrl(d.recording_url);
    if (rec) {
      el.audio.src = rec;
      el.audio.hidden = false;
    }
    renderStatus();
  });

  el.hangup.addEventListener("click", async () => {
    if (!current || !current.call_id) return;
    try {
      await api("POST", `/calls/${current.call_id}/hangup`);
    } catch (e) {
      el.state.textContent = "Не удалось завершить: " + e.message;
    }
  });

  async function placeCall(body, label) {
    setOpen(true);
    if (busy()) return;
    try {
      const call = await api("POST", "/calls", Object.assign({ trainee: WS, initiated_by: "trainee" }, body));
      track(call.call_id, { call_type: call.call_type, persona: call.persona, dialed: call.dialed });
      if (!current || current.call_id !== call.call_id) {
        showCall(call.call_id, call.call_type, call.persona, "Телефон звонит — снимите трубку", call.dialed);
      }
    } catch (e) {
      showCall(null, body.call_type, null, "");
      current.status = "ended";
      el.call.textContent = label;
      el.state.textContent = "Ошибка: " + e.message;
      renderStatus();
    }
  }

  function dialNumber() {
    const number = el.display.value.trim();
    if (!/^\d{2,6}$/.test(number)) {
      el.display.focus();
      return;
    }
    placeCall({ dial: number }, `Набор ${number}`);
  }

  // -------------------------------------------------------- карточки ---
  function sheetCard() {
    const title = text("sheet-title");
    return {
      id: card ? card.id : null,
      phone: text("sheet-phone-aon") || text("sheet-phone"),
      address: text("sheet-address-input"),
      caller: text("sheet-caller-input"),
      description: text("sheet-description"),
      title: title === "Новая карточка" ? "" : title,
    };
  }

  function reviewCard(incident) {
    return {
      id: incident ? incident.id : null,
      phone: text("review-phone") || (incident && incident.phone) || "",
      address: (incident && incident.addressLine) || text("review-address"),
      caller: text("review-caller"),
      description: text("review-description") || text("review-types"),
      title: text("review-types"),
      services: (incident && incident.services) || [],
    };
  }

  const currentCard = () => (card && card.source === "review" ? reviewCard(card.incident) : sheetCard());

  let contextTimer = null;
  function pushContext() {
    clearTimeout(contextTimer);
    contextTimer = setTimeout(() => {
      if (card) quiet(api("PUT", `/trainees/${encodeURIComponent(WS)}/context`, { card: currentCard() }));
    }, 500);
  }

  function openCard(incident, source) {
    card = { id: incident && incident.id, source: source, incident: incident };
    pushContext();
    renderLogs();
  }

  function closeCard() {
    card = null;
    clearTimeout(contextTimer);
    quiet(api("DELETE", `/trainees/${encodeURIComponent(WS)}/context`));
    renderLogs();
  }

  document.addEventListener("dds:card-open", (e) => { setDocked(true); openCard(e.detail, "sheet"); });
  document.addEventListener("dds:review-open", (e) => openCard(e.detail, "review"));
  document.addEventListener("dds:card-close", () => { setDocked(false); closeCard(); });
  document.addEventListener("dds:review-close", closeCard);
  document.addEventListener("dds:callback", (e) => {
    placeCall({ call_type: "applicant", card: reviewCard(e.detail) }, "Звонок заявителю");
  });

  const sheet = $("incident-sheet");
  sheet.addEventListener("input", pushContext);
  sheet.addEventListener("click", (e) => { if (e.target.closest(".type-tile")) pushContext(); });

  // ☎ у каждой службы: карточка оператора (#service-chips) и диспетчера (#review-services)
  function decorateChips(container) {
    container.querySelectorAll(".service-chip").forEach((chip) => {
      if (chip.querySelector(".tel-chip-call")) return;
      const remove = chip.querySelector(".chip-remove");
      const service = remove ? remove.dataset.service : chip.textContent.trim();
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tel-chip-call";
      btn.textContent = "☎";
      btn.title = `Позвонить: ${service}`;
      btn.disabled = busy();
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        placeCall({ call_type: "dispatch", service: service, card: currentCard() }, `Звонок в службу: ${service}`);
      });
      if (remove) chip.insertBefore(btn, remove);
      else chip.appendChild(btn);
    });
  }
  ["service-chips", "review-services"].forEach((id) => {
    const box = $(id);
    if (box) new MutationObserver(() => decorateChips(box)).observe(box, { childList: true });
  });

  // «☎ Вызов голосом» в карточке оператора: учебный заявитель 112 звонит на телефон
  const meta = document.querySelector("#incident-sheet .sheet-meta");
  if (meta && session.role === "student") {
    const voice = document.createElement("button");
    voice.type = "button";
    voice.className = "tel-btn tel-voice-112";
    voice.textContent = "☎ Вызов голосом";
    voice.title = "Учебный заявитель позвонит на телефон рабочего места";
    voice.addEventListener("click", () => {
      const n = parseInt(String((card && card.id) || "").replace(/\D/g, ""), 10) || 1;
      placeCall({ call_type: "incident_112", scenario_id: SCENARIOS_112[(n - 1) % SCENARIOS_112.length],
                  card: sheetCard() }, "Вызов 112");
    });
    meta.appendChild(voice);
  }

  // «Перезвонить и уточнить» — кнопка app.js шлёт dds:callback
  const callback = $("review-callback-btn");
  if (callback) callback.classList.add("tel-callback");

  // «Доклад старшего группы» (диспетчер): служба из открытой карточки, этапы по очереди
  el.report.addEventListener("click", () => {
    const incident = card && card.source === "review" ? card.incident : null;
    const service = (incident && incident.services && incident.services[0]) || "Служба 101 (МЧС)";
    const done = ((incident && incident.calls) || []).filter((c) => c.call_type === "report").length;
    placeCall({
      call_type: "report", service: service, card: currentCard(),
      report: { status: REPORT_STAGES[done % REPORT_STAGES.length] },
    }, "Доклад старшего группы");
  });

  // ---------------------------------------- статус оператора → телефония ---
  function pushStatus(available) {
    quiet(api("PUT", `/trainees/${encodeURIComponent(WS)}/status`, { available: available }));
  }
  document.addEventListener("dds:operator-status", (e) => pushStatus(!!(e.detail && e.detail.available)));
  const statusBtn = $("telephony-status");
  if (statusBtn && !statusBtn.hidden) pushStatus(!statusBtn.classList.contains("is-unavailable"));

  renderStatus();
})();
