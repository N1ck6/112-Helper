/* Данные АРМ — Backend (backend/docs/INTEGRATION.md §3). В браузере ничего не хранится,
 * кроме сеанса входа.
 *
 *   • оператор 112 и диспетчер ДДС работают в занятии, которое запустил преподаватель:
 *     карточки выдаёт Backend, он же считает время, статусы и оценку (ML);
 *   • оператор: «Принять вызов» → карточка + входящий голосовой вызов 112 на телефон рабочего
 *     места; содержание карточки скрыто, его рассказывает заявитель; «Сохранить» → оценка;
 *   • диспетчер: «Поток карточек» — незакрытые карточки занятия с таймерами 30 с / 3 мин,
 *     «Принята / Не принята» и статусы реагирования уходят в Backend по регламенту АРМ-112;
 *   • свои карточки занятия (и закрытые, с оценкой) — после перезагрузки страницы тоже;
 *   • отработки: звонки по карточке с панели «Телефон» — строки отработки в Backend.
 *
 * app.js берёт отсюда данные и вызывает действия через window.DDS_SERVER.
 */
(function () {
  "use strict";

  const API = window.DDS_API;
  const session = (function () {
    try { return JSON.parse(localStorage.getItem("ddsSession") || "null") || {}; } catch (e) { return {}; }
  })();
  const S = (window.DDS_SERVER = { enabled: !!session.token && !!API });
  if (!S.enabled) return;

  const req = API.request;
  const ROLE_MODE = { student: "card_fill", dispatcher: "card_action" };
  // статусы реагирования: id в интерфейсе (DDS_DATA.REACTION_STATUSES) <-> Backend (ResponseStatus)
  const TO_BACKEND = { start: "response_started", arrival: "arrived", works: "work_in_progress", done: "work_completed", refused: "work_refused" };
  const FROM_BACKEND = {};
  Object.keys(TO_BACKEND).forEach((k) => (FROM_BACKEND[TO_BACKEND[k]] = k));
  const STATUS_LABEL = {
    accepted: "Принята", not_accepted: "Не принята", response_started: "Начало реагирования", arrived: "Прибытие",
    work_in_progress: "Проведение работ", work_completed: "Работы завершены", work_refused: "Отказ от выполнения работ",
  };

  const hhmm = (iso) => new Date(iso || Date.now()).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const ms = (iso) => (iso ? new Date(iso).getTime() : null);
  const wsNumber = (ws) => { const m = /(\d+)$/.exec(String(ws || "")); return m ? String(Number(m[1])).padStart(2, "0") : null; };

  S.state = "loading";   // loading | no_lesson | joined | error
  S.lesson = null;
  S.message = "";
  const listeners = [];
  S.onChange = (fn) => listeners.push(fn);
  const changed = () => listeners.forEach((fn) => { try { fn(); } catch (e) { /* интерфейс не должен падать */ } });

  // ------------------------------------------------------------ занятие ---
  async function findLesson() {
    const mode = ROLE_MODE[session.role];
    if (!mode) return;
    try {
      const page = await req("GET", "/lessons?status=running&size=50");
      const lesson = (page.items || []).find((l) => l.mode === mode);
      if (!lesson) {
        S.lesson = null;
        S.state = "no_lesson";
        S.message = mode === "card_fill"
          ? "Нет запущенного занятия для оператора 112. Преподаватель запускает занятие в разделе «Занятия»."
          : "Нет запущенного занятия для диспетчера ДДС. Преподаватель запускает занятие в разделе «Занятия».";
        changed();
        return;
      }
      if (!S.lesson || S.lesson.id !== lesson.id) {
        const joined = await req("POST", "/training/lessons/" + lesson.id + "/join", { workplace_number: wsNumber(session.workstation) });
        S.lesson = joined.lesson || lesson;
        S.workplace = joined.workplace || null;
        S.state = "joined";
        S.message = "";
        if (joined.active_attempt) upsert(fromAttempt(joined.active_attempt));
        await loadMine();
        if (mode === "card_action") await refreshStream();
        changed();
      }
    } catch (e) {
      S.state = "error";
      S.message = "Не удалось войти в занятие: " + e.message;
      changed();
    }
  }

  S.banner = function () {
    if (S.state === "joined") {
      const l = S.lesson || {};
      return `Занятие «${l.title || ""}»${S.workplace ? " · место " + S.workplace : ""}`;
    }
    return S.message || "Подключение к занятию…";
  };

  // ---------------------------------------------------- карточка -> АРМ ---
  function addressLine(p) {
    const parts = [p.address_region, p.address_district, p.address_area, p.address_street,
      p.address_house ? "д. " + p.address_house : "", p.address_building ? "корп. " + p.address_building : "",
      p.address_flat ? "кв. " + p.address_flat : ""].filter(Boolean);
    return parts.length ? parts.join(", ") : p.address_text || null;
  }

  function reactionFrom(attempt) {
    const last = attempt.last_response_status;
    return FROM_BACKEND[last] || null;
  }

  // Карточка Backend (AttemptWithCard) -> объект карточки интерфейса (app.js defaults())
  function fromAttempt(view, base) {
    const a = view.attempt || view;
    const card = view.card || {};
    const p = card.payload || {};
    const statuses = (a.response_statuses || []).filter((e) => !e.set_by_system);
    const primary = a.first_response_status;
    const lastAt = statuses.length ? ms(statuses[statuses.length - 1].at) : null;
    // «Не принята» можно сменить на «Принята» — решение по последнему статусу
    const decision = !primary ? "pending" : a.last_response_status === "not_accepted" ? "declined" : "accepted";
    const inc = Object.assign({}, base || {}, {
      id: a.id,
      server: { attemptId: a.id, lessonId: a.lesson_id, status: a.status, lifecycle: a.lifecycle_status },
      number: card.card_no || (base && base.number) || "—",
      time: hhmm(a.issued_at),
      phone: (card.caller_profile || {}).phone || p.aon_phone || (base && base.phone) || "—",
      workstation: session.workstation || null,
      source: session.role === "dispatcher" ? "system" : "operator",
    });
    if (session.role === "dispatcher") {
      Object.assign(inc, {
        status: "review",
        types: p.incident_class ? [p.incident_class] : [],
        addressLine: addressLine(p),
        address: { street: p.address_street || "", house: p.address_house || "", flat: p.address_flat || "" },
        caller: p.applicant_name || null,
        callerStatus: p.applicant_role || null,
        description: p.description || null,
        flags: { injured: !!p.has_victims, notOnSite: false, ambulanceRefused: !!p.ambulance_refusal, blocked: !!p.blocked_persons },
        injuredCount: p.has_victims ? String(p.victims_count || "") : null,
        services: (card.notification_list || a.notification_list || []).map((n) => n.service_name || n.name || n.code).filter(Boolean),
        sentAt: ms(a.issued_at) || Date.now(),
        dds: {
          decision: decision,
          decisionAt: ms(a.first_response_at),
          comment: (statuses.find((e) => e.is_primary) || {}).comment || null,
          reaction: reactionFrom(a),
          reactionAt: FROM_BACKEND[a.last_response_status] ? lastAt : null,
          history: statuses.map((e) => ({ id: e.status, label: e.title || STATUS_LABEL[e.status] || e.status, time: hhmm(e.at), comment: e.comment || null })),
        },
      });
    } else {
      Object.assign(inc, { status: base ? base.status : "new" });
    }
    return inc;
  }

  function upsert(inc) {
    const list = window.DDS ? window.DDS.getIncidents() : [];
    const i = list.findIndex((c) => c.id === inc.id);
    if (i === -1) list.unshift(inc);
    else list[i] = Object.assign(list[i], inc);
    return i === -1 ? inc : list[i];
  }

  // Закрытые карточки занятия: оператору — строка с оценкой, диспетчеру — карточка целиком (история)
  const CLOSED_OPERATOR = { submitted: "graded", evaluated: "graded", skipped: "empty", expired: "empty" };
  async function loadMine() {
    const rows = await req("GET", "/training/lessons/" + S.lesson.id + "/my-attempts");
    const list = window.DDS ? window.DDS.getIncidents() : [];
    for (const row of rows || []) {
      if (!CLOSED_OPERATOR[row.status] || list.some((c) => c.id === row.attempt_id)) continue;
      if (session.role === "dispatcher") {
        await loadCard({ id: row.attempt_id, number: row.card_no }).catch(() => {});
        continue;
      }
      list.push({
        id: row.attempt_id,
        server: { attemptId: row.attempt_id, lessonId: S.lesson.id, status: row.status },
        number: row.card_no || "—",
        time: hhmm(row.issued_at),
        phone: row.phone || "—",
        workstation: session.workstation || null,
        source: "operator",
        types: row.incident_class ? [row.incident_class] : [],
        addressLine: row.address || null,
        address: {},
        status: CLOSED_OPERATOR[row.status],
        emptyReason: row.status === "expired" ? "expired" : row.status === "skipped" ? "skipped" : null,
        evaluation: row.score == null ? null : { score: row.score, passed: row.passed, errors: [] },
        dds: { decision: "pending", history: [] },
      });
    }
  }

  // ------------------------------------------------------------ отработки ---
  // Звонок по карточке с панели «Телефон» (js/telephony.js) -> строка отработки в Backend.
  // sip_call_id — звонок уже состоялся: Backend не поднимает его повторно и не дублирует строку.
  S.addProcessing = function (inc, entry) {
    if (!inc || !inc.server) return Promise.resolve(null);
    return req("POST", "/training/attempts/" + inc.server.attemptId + "/processings", entry);
  };
  S.processings = function (inc) {
    if (!inc || !inc.server) return Promise.resolve([]);
    return req("GET", "/training/attempts/" + inc.server.attemptId + "/processings");
  };

  // ------------------------------------------------------------ оператор ---
  S.nextCall = async function () {
    if (S.state !== "joined") throw new Error(S.message || "Занятие не запущено");
    const view = await req("POST", "/training/lessons/" + S.lesson.id + "/next-card");
    const inc = upsert(fromAttempt(view));
    S.action(inc, "call_accepted");
    return inc;
  };

  S.action = function (inc, type, fieldCode) {
    if (!inc || !inc.server) return;
    inc.server.actions = inc.server.actions || {};
    if (inc.server.actions[type + (fieldCode || "")]) return;   // одно действие каждого вида
    inc.server.actions[type + (fieldCode || "")] = true;
    req("POST", "/training/attempts/" + inc.server.attemptId + "/actions",
      { action_type: type, field_code: fieldCode || null, client_at: new Date().toISOString() }).catch(() => {});
  };

  // Карточка интерфейса -> поля карточки АРМ-112 в Backend (коды — backend/app/core/arm112.py)
  function toPayload(c, typeLabels) {
    const a = c.address || {};
    const labels = typeLabels || [];
    const signs = Object.keys(c.survey || {}).map((k) => c.survey[k]);
    return {
      aon_phone: c.phone && c.phone !== "—" ? c.phone : null,
      provided_phone: c.phoneGiven || null,
      site_phone: c.phoneOnsite || null,
      applicant_name: c.caller || null,
      applicant_role: c.callerStatus || null,
      address_region: a.region || null,
      address_district: a.okrug || null,
      address_area: a.district || null,
      address_street: a.street || null,
      address_house: a.house || null,
      address_building: a.korpus || null,
      address_flat: a.flat || null,
      address_entrance: a.entrance || null,
      address_floor: a.floor || null,
      address_code: a.code || null,
      address_text: [c.addressLine, a.descriptive].filter(Boolean).join("; ") || null,
      survey_signs: labels.concat(signs),
      incident_class: labels.join(", ") || null,
      has_victims: !!(c.flags && c.flags.injured),
      victims_count: c.flags && c.flags.injured ? Number(c.injuredCount) || null : 0,
      ambulance_refusal: !!(c.flags && c.flags.ambulanceRefused),
      blocked_persons: !!(c.flags && c.flags.blocked),
      description: c.description || null,
      notification_services: c.services || [],
    };
  }

  S.submit = async function (inc, typeLabels) {
    S.action(inc, "classified");
    S.action(inc, "field_filled", "address_street");
    S.action(inc, "card_submitted");
    const res = await req("POST", "/training/attempts/" + inc.server.attemptId + "/submit",
      { payload: toPayload(inc, typeLabels), client_at: new Date().toISOString() });
    inc.status = "graded";
    inc.evaluation = { score: res.score, passed: res.passed, errors: res.errors || [] };
    return res;
  };

  S.skip = async function (inc) {
    await req("POST", "/training/attempts/" + inc.server.attemptId + "/skip");
  };

  // ------------------------------------------------------------ диспетчер ---
  async function loadCard(inc) {
    const view = await req("GET", "/training/attempts/" + (inc.server ? inc.server.attemptId : inc.id) + "/card");
    return upsert(fromAttempt(view, inc));
  }
  S.loadCard = loadCard;

  async function refreshStream() {
    if (S.state !== "joined" || !S.lesson || S.lesson.mode !== "card_action") return;
    const data = await req("GET", "/training/lessons/" + S.lesson.id + "/incidents");
    const list = window.DDS ? window.DDS.getIncidents() : [];
    for (const row of data.rows || []) {
      const known = list.find((c) => c.id === row.attempt_id);
      if (!known || (known.server && known.server.first !== row.first_response_status)) {
        const inc = await loadCard({ id: row.attempt_id, number: row.card_no });
        inc.server.first = row.first_response_status;
      }
    }
    S.stream = data;
  }

  S.nextCard = async function () {
    if (S.state !== "joined") throw new Error(S.message || "Занятие не запущено");
    const view = await req("POST", "/training/lessons/" + S.lesson.id + "/next-card");
    return upsert(fromAttempt(view));
  };

  // «Принята» / «Не принята» и статусы хода работ
  S.respond = async function (inc, uiStatus, comment) {
    const status = uiStatus === "accepted" ? "accepted" : uiStatus === "declined" ? "not_accepted" : TO_BACKEND[uiStatus];
    const res = await req("POST", "/training/attempts/" + inc.server.attemptId + "/response-status",
      { status: status, comment: comment || null, client_at: new Date().toISOString() });
    const updated = await loadCard(inc);
    if (res.card_closed) updated.evaluation = { score: res.score, passed: res.passed, errors: res.errors || [] };
    return { card: updated, result: res };
  };

  // ------------------------------------------------------------ цикл ---
  async function tick() {
    try {
      if (S.state !== "joined") await findLesson();
      else if (S.lesson.mode === "card_action") { await refreshStream(); changed(); }
      else {
        // занятие закончилось — ждём следующее
        const lesson = await req("GET", "/lessons/" + S.lesson.id);
        if (lesson.status !== "running") { S.state = "no_lesson"; S.lesson = null; await findLesson(); changed(); }
      }
    } catch (e) { /* сеть моргнула — следующий такт */ }
  }
  if (ROLE_MODE[session.role]) {
    findLesson();
    setInterval(tick, 4000);
  }
})();
