(function () {
  const D = window.DDS_DATA;
  const API = window.DDS_API;

  const ROLE_LABELS = {
    student: "Оператор",
    dispatcher: "Диспетчер",
    teacher: "Преподаватель",
    admin: "Администратор",
  };

  const ICON_KEYS = ["call", "nature", "medicine", "infrastructure", "shield", "warning"];

  function iconHtml(key, size) {
    if (ICON_KEYS.indexOf(key) === -1) return "";
    return `<span class="icon i-${key}" style="width:${size}px; height:${size}px;" aria-hidden="true"></span>`;
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }

  const hhmm = () => new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

  const session = JSON.parse(localStorage.getItem("ddsSession") || "null");

  if (!session || !ROLE_LABELS[session.role]) {
    localStorage.removeItem("ddsSession");
    window.location.href = "index.html";
    return;
  }

  const INCIDENT_TYPES = [
    { id: "fire_flat", label: "Пожар: квартира", services: ["Служба 101 (МЧС)"], color: "var(--cat-nature)", icon: "nature" },
    { id: "fire_entrance", label: "Пожар: подъезд", services: ["Служба 101 (МЧС)", "ГБУ «Жилищник»"], color: "var(--cat-nature)", icon: "nature" },
    { id: "fire_trash", label: "Пожар: мусор на улице", services: ["Служба 101 (МЧС)"], color: "var(--cat-nature)", icon: "nature" },
    { id: "smoke", label: "Задымление", services: ["Служба 101 (МЧС)"], color: "var(--cat-nature)", icon: "nature" },
    { id: "fuel_spill", label: "Разлив топлива", services: ["Служба 101 (МЧС)", "ЦОДД"], color: "var(--cat-nature)", icon: "nature" },
    { id: "gas_smell", label: "Запах газа", services: ["Служба 104 (Мосгаз)", "Служба 101 (МЧС)"], color: "var(--cat-nature)", icon: "nature" },
    { id: "medical", label: "Вызов скорой помощи (103)", services: ["Служба 103 (СМП)"], color: "var(--cat-medicine)", icon: "medicine" },
    { id: "dtp", label: "ДТП", services: ["Служба 102 (ОМВД)", "Служба 103 (СМП)", "ЦОДД"], color: "var(--cat-security)", icon: "shield" },
    { id: "suspicious", label: "Подозрительные лица", services: ["Служба 102 (ОМВД)"], color: "var(--cat-security)", icon: "shield" },
    { id: "pipe_burst", label: "Прорыв трубы", services: ["Мосводоканал", "ГБУ «Жилищник»"], color: "var(--cat-infrastructure)", icon: "infrastructure" },
    { id: "open_hatch", label: "Открытый канализационный люк", services: ["Упр. района", "ГБУ «Жилищник»"], color: "var(--cat-infrastructure)", icon: "infrastructure" },
    { id: "tree_fall", label: "Упавшее дерево", services: ["ГБУ «Жилищник»", "Упр. района"], color: "var(--cat-infrastructure)", icon: "infrastructure" },
    { id: "power_outage", label: "Отключение электроэнергии", services: ["ОДС ПСЦ", "Упр. района"], color: "var(--cat-infrastructure)", icon: "infrastructure" },
    { id: "wrong_number", label: "Ошибочно набран номер", services: [], color: "var(--cat-other)", icon: "warning" },
    { id: "test_call", label: "Тестовый вызов", services: [], color: "var(--cat-other)", icon: "warning" },
    { id: "call_cancel", label: "Отмена вызова", services: [], color: "var(--cat-other)", icon: "warning" },
    { id: "consultation", label: "Консультация", services: [], color: "var(--cat-other)", icon: "warning" },
  ];

  const ALL_SERVICES = [
    "Служба 101 (МЧС)",
    "Служба 102 (ОМВД)",
    "Служба 103 (СМП)",
    "Служба 104 (Мосгаз)",
    "ОДС ПСЦ",
    "Мосводоканал",
    "ГБУ «Жилищник»",
    "Упр. района",
    "Мос.Без.",
    "ЦОДД",
  ];

  function emptyAddress() {
    return { country: "Россия", region: "Москва", locality: "Москва", okrug: "", district: "", street: "", house: "", korpus: "", flat: "", entrance: "", floor: "", code: "", descriptive: "" };
  }

  function newDds() {
    return { decision: "pending", decisionAt: null, comment: null, reaction: null, reactionAt: null, history: [] };
  }

  function nextNumber() {
    const n = Number(localStorage.getItem("ddsCardCounter") || 36814850) + 1;
    localStorage.setItem("ddsCardCounter", String(n));
    return String(n);
  }

  function defaults() {
    return {
      status: "new",
      source: "operator",
      workstation: null,
      scenarioId: null,
      clusterId: null,
      seq: null,
      seqTotal: null,
      types: [],
      address: emptyAddress(),
      addressLine: null,
      caller: null,
      callerStatus: null,
      foreignLanguage: false,
      description: null,
      services: [],
      phoneGiven: null,
      phoneOnsite: null,
      flags: { injured: false, notOnSite: false, ambulanceRefused: false, blocked: false },
      injuredCount: null,
      survey: {},
      chat: [],
      fillSeconds: null,
      sentAt: null,
      dds: newDds(),
      teacherGrade: null,
      dispatcherComment: null,
      emptyReason: null,
    };
  }

  function poolFor(ws) {
    const all = D.getScenarios().filter((s) => s.approved);
    const a = ws ? D.getAssignments()[ws] : null;
    if (a && a.clusterId) {
      const inCluster = all.filter((s) => s.clusterId === a.clusterId);
      if (inCluster.length) return inCluster;
    }
    if (a && a.scenarioId) {
      const one = all.find((s) => s.id === a.scenarioId);
      if (one) return [one];
    }
    return all;
  }

  function scenarioFor(ws, index) {
    const list = poolFor(ws);
    return list.length ? list[index % list.length] : null;
  }

  function clusterInfo(sc) {
    if (!sc) return { clusterId: null, seq: null, seqTotal: null };
    const list = D.scenariosOfCluster(sc.clusterId, true);
    const pos = list.findIndex((x) => x.id === sc.id);
    return { clusterId: sc.clusterId, seq: pos >= 0 ? pos + 1 : null, seqTotal: list.length || null };
  }

  function clusterLabel(call) {
    const c = call && call.clusterId ? D.getCluster(call.clusterId) : null;
    if (!c) return "";
    return "Кластер «" + c.title + "»" + (call.seq ? " · сценарий " + call.seq + " из " + call.seqTotal : "");
  }

  function clusterProgress() {
    const a = session.workstation ? D.getAssignments()[session.workstation] : null;
    if (!a || !a.clusterId) return "";
    const cluster = D.getCluster(a.clusterId);
    const total = D.scenariosOfCluster(a.clusterId, true).length;
    if (!cluster || !total) return "";
    const dispatcher = session.role === "dispatcher";
    const mine = incidents.filter((c) => c.workstation === session.workstation && c.clusterId === a.clusterId && (dispatcher ? c.source === "system" : c.source !== "system"));
    const passed = dispatcher
      ? mine.filter((c) => ["declined", "done", "refused"].indexOf(ddsState(c).phase) !== -1).length
      : mine.filter((c) => c.status === "review" || c.status === "empty").length;
    return "Кластер «" + esc(cluster.title) + "» · пройдено " + passed + " из " + total;
  }

  function newIncident(id, time, phone, scenarioId) {
    const sc = scenarioId ? D.getScenarios().find((x) => x.id === scenarioId) : null;
    const info = clusterInfo(sc);
    return Object.assign(defaults(), {
      id: id,
      number: nextNumber(),
      time: time,
      phone: phone,
      workstation: session.workstation || null,
      scenarioId: scenarioId || null,
      clusterId: info.clusterId,
      seq: info.seq,
      seqTotal: info.seqTotal,
    });
  }

  function normalize(inc) {
    const base = defaults();
    const n = Object.assign(base, inc);
    n.flags = Object.assign(base.flags, inc.flags);
    n.address = Object.assign(emptyAddress(), inc.address);
    n.dds = Object.assign(newDds(), inc.dds);
    n.survey = inc.survey || {};
    n.chat = inc.chat || [];
    if (!n.number) n.number = nextNumber();
    if (n.status === "approved") {
      n.status = "review";
      n.dds.decision = "accepted";
      n.dds.reaction = "done";
    } else if (n.status === "returned") {
      n.status = "review";
      n.dds.decision = "declined";
      n.dds.comment = inc.dispatcherComment || null;
    }
    if (n.status === "review" && !n.sentAt) n.sentAt = Date.now();
    return n;
  }

  function seedIncidents() {
    return [
      ["c1", "10:47", "+7 (495) 123-45-67"],
      ["c2", "10:52", "+7 (903) 555-12-09"],
      ["c3", "10:58", "+7 (499) 887-21-34"],
      ["c4", "11:04", "Номер скрыт"],
    ].map((row, i) => {
      const sc = scenarioFor(null, i);
      return newIncident(row[0], row[1], row[2], sc ? sc.id : null);
    });
  }

  function loadIncidents() {
    try {
      const raw = localStorage.getItem("ddsIncidents");
      if (raw) return JSON.parse(raw).map(normalize);
    } catch (e) {
      localStorage.removeItem("ddsIncidents");
    }
    return seedIncidents();
  }

  function saveIncidents() {
    localStorage.setItem("ddsIncidents", JSON.stringify(incidents));
    API.syncIncidents(incidents);
  }

  let incidents = loadIncidents();

  let users = [
    { name: "Иванов И.И.", role: "Оператор", blocked: false },
    { name: "Смирнова О.П.", role: "Диспетчер", blocked: false },
    { name: "Кузнецова Е.А.", role: "Преподаватель", blocked: false },
    { name: "Сидоров П.П.", role: "Администратор", blocked: false },
    { name: "Козлов Д.А.", role: "Оператор", blocked: true },
  ];

  const TOOLBARS = {
    student: {
      tabs: [{ id: "queue", label: "Очередь вызовов", order: 10 }],
      primary: { label: "Создать карточку", action: "create-card" },
    },
    dispatcher: {
      tabs: [
        { id: "stream", label: "Поток карточек", order: 10 },
        { id: "history", label: "История", order: 20 },
      ],
      primary: { label: "Смоделировать поступление", action: "simulate-incoming" },
    },
    teacher: { tabs: [] },
    admin: {
      tabs: [
        { id: "progress", label: "Прогресс", order: 10 },
        { id: "users", label: "Пользователи", order: 20 },
      ],
    },
  };

  function tabsFor(role) {
    const extra = (window.DDS_TABS || []).filter((t) => t.roles.indexOf(role) !== -1);
    return TOOLBARS[role].tabs.concat(extra).sort((a, b) => a.order - b.order);
  }

  let activeTab = tabsFor(session.role)[0].id;

  function renderTopbar() {
    document.getElementById("role-badge").textContent = ROLE_LABELS[session.role] || session.role;
    const wsBadge = document.getElementById("ws-badge");
    if (wsBadge && session.workstation && (session.role === "student" || session.role === "dispatcher")) {
      wsBadge.textContent = session.workstation;
      wsBadge.hidden = false;
    }
    const status = document.getElementById("telephony-status");
    if (status) {
      status.hidden = session.role !== "student";
      if (session.role === "student") setTelephonyStatus("available");
    }
  }

  function renderToolbar() {
    const config = TOOLBARS[session.role];
    const toolbar = document.getElementById("toolbar");

    const tabsHtml = tabsFor(session.role)
      .map(
        (tab) =>
          `<button type="button" class="toolbar-btn ${tab.id === activeTab ? "active" : ""}" data-tab="${tab.id}">${tab.label}</button>`
      )
      .join("");

    const primaryHtml = config.primary
      ? `<button type="button" class="btn-primary" data-action="${config.primary.action}">${config.primary.label}</button>`
      : "";

    toolbar.innerHTML = `${tabsHtml}<span class="toolbar-spacer"></span>${primaryHtml}`;

    toolbar.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeTab = btn.dataset.tab;
        renderToolbar();
        renderWorkspace();
      });
    });

    const createBtn = toolbar.querySelector('[data-action="create-card"]');
    if (createBtn) createBtn.addEventListener("click", createOperatorCard);

    const simBtn = toolbar.querySelector('[data-action="simulate-incoming"]');
    if (simBtn) simBtn.addEventListener("click", simulateIncoming);
  }

  function createOperatorCard() {
    const now = new Date();
    const mineCount = incidents.filter((c) => c.source !== "system" && c.workstation === session.workstation && String(c.id).charAt(0) === "m").length;
    const sc = scenarioFor(session.workstation, mineCount);
    const phone = sc ? sc.caller.phone : "—";
    const call = newIncident("m" + now.getTime(), hhmm(), phone, sc ? sc.id : null);
    incidents = [call].concat(incidents);
    saveIncidents();
    API.log("card_created", "Открыта карточка № " + call.number);
    openSheet(call);
  }

  function servicesForTypes(types) {
    const set = [];
    types.forEach((id) => {
      const t = INCIDENT_TYPES.find((x) => x.id === id);
      if (t) t.services.forEach((s) => set.indexOf(s) === -1 && set.push(s));
    });
    return set;
  }

  function simulateIncoming() {
    const pool = poolFor(session.workstation);
    if (!pool.length) {
      showToast("Нет утверждённых сценариев — утвердите сценарий у преподавателя");
      return;
    }
    const given = incidents.filter((c) => c.source === "system" && c.workstation === session.workstation).length;
    const sc = pool[given % pool.length];
    const now = new Date();
    const inc = newIncident("s" + now.getTime(), hhmm(), sc.caller.phone, sc.id);
    inc.source = "system";
    inc.workstation = session.workstation || null;
    inc.types = sc.types.slice();
    inc.addressLine = sc.address;
    inc.caller = sc.caller.name;
    inc.callerStatus = sc.caller.status;
    inc.description = sc.description;
    inc.flags.injured = !!sc.injured;
    inc.injuredCount = sc.injured ? "1" : null;
    inc.services = servicesForTypes(inc.types);
    inc.status = "review";
    inc.sentAt = Date.now();
    incidents = [inc].concat(incidents);
    saveIncidents();
    API.log("card_incoming", "Поступила карточка № " + inc.number);
    showToast("Поступила карточка № " + inc.number + ": на приём " + D.TIMERS.accept + " с");
    renderWorkspace();
  }

  function typeLabels(call) {
    if (!call.types || !call.types.length) return null;
    return call.types.map((id) => {
      const t = INCIDENT_TYPES.find((x) => x.id === id);
      return t ? t.label : id;
    });
  }

  function formatAddress(call) {
    if (call.emptyReason) return null;
    if (!call.addressLine) return null;
    const a = call.address || {};
    const parts = [a.street, a.house ? `д. ${a.house}` : "", a.flat ? `кв. ${a.flat}` : ""].filter(Boolean);
    return esc(parts.length ? `${call.addressLine} (${parts.join(", ")})` : call.addressLine);
  }

  function fmtClock(sec) {
    const s = Math.abs(sec);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function acceptLeft(call) {
    return D.TIMERS.accept - Math.floor((Date.now() - call.sentAt) / 1000);
  }

  function respondLeft(call) {
    const from = call.dds.reactionAt || call.dds.decisionAt;
    return D.TIMERS.respond - Math.floor((Date.now() - from) / 1000);
  }

  function reactionLabel(id) {
    if (id === D.REACTION_REFUSED.id) return D.REACTION_REFUSED.label;
    const hit = D.REACTION_STATUSES.find((s) => s.id === id);
    return hit ? hit.label : "";
  }

  function ddsState(call) {
    if (call.status !== "review") return { phase: "none", label: "", cls: "status-new" };
    const d = call.dds;
    if (d.decision === "pending") {
      if (acceptLeft(call) < 0) return { phase: "pending", label: "Не оповещено", cls: "status-blocked", late: true };
      return { phase: "pending", label: "Ожидает приёма", cls: "status-new" };
    }
    if (d.decision === "declined") return { phase: "declined", label: "Не принята", cls: "status-blocked" };
    if (d.reaction === "done") return { phase: "done", label: reactionLabel("done"), cls: "status-done" };
    if (d.reaction === "refused") return { phase: "refused", label: reactionLabel("refused"), cls: "status-blocked" };
    if (respondLeft(call) < 0) return { phase: "active", label: "Не завершено", cls: "status-blocked", late: true };
    return { phase: "active", label: d.reaction ? reactionLabel(d.reaction) : "Принята", cls: "status-done" };
  }

  function statusPill(call) {
    if (call.status === "empty") return `<span class="cell-muted">${call.emptyReason === "no_contact" ? "Нет контакта" : "Срыв звонка"}</span>`;
    if (call.status === "review") {
      const st = ddsState(call);
      return `<span class="status-pill ${st.cls}">${st.label}</span>`;
    }
    return `<span class="status-pill status-new">Новый вызов</span>`;
  }

  function timerCellHtml(call, kind) {
    const st = ddsState(call);
    if (kind === "accept") {
      if (st.phase === "pending") {
        const left = acceptLeft(call);
        return left >= 0
          ? `<span class="timer ${left <= 10 ? "warn" : ""}">${fmtClock(left)}</span>`
          : `<span class="timer bad">−${fmtClock(left)}</span>`;
      }
      return `<span class="cell-muted">${st.phase === "declined" ? "не принята" : "принята"}</span>`;
    }
    if (st.phase === "active") {
      const left = respondLeft(call);
      return left >= 0
        ? `<span class="timer ${left <= 30 ? "warn" : ""}">${fmtClock(left)}</span>`
        : `<span class="timer bad">−${fmtClock(left)}</span>`;
    }
    return `<span class="cell-muted">—</span>`;
  }

  function tickTimers() {
    document.querySelectorAll("[data-timer]").forEach((cell) => {
      const call = incidents.find((c) => c.id === cell.dataset.id);
      if (call) cell.innerHTML = timerCellHtml(call, cell.dataset.timer);
    });
    document.querySelectorAll("[data-ddsstatus]").forEach((cell) => {
      const call = incidents.find((c) => c.id === cell.dataset.id);
      if (call) cell.innerHTML = statusPill(call);
    });
    if (reviewOverlay && reviewOverlay.classList.contains("is-open") && currentReviewCall) updateReviewTimers();
  }

  function wireRowClicks(root) {
    root.querySelectorAll("tr").forEach((tr) => {
      const target = tr.querySelector("[data-row-open]");
      if (!target) return;
      tr.classList.add("row-click");
      tr.tabIndex = 0;
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button, a, input, select, textarea, label")) return;
        target.click();
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target === tr) target.click();
      });
    });
  }

  function renderWorkspace() {
    renderWorkspaceInner();
    wireRowClicks(document.getElementById("workspace"));
  }

  function renderWorkspaceInner() {
    const workspace = document.getElementById("workspace");
    const role = session.role;

    if (role === "student" && activeTab === "queue") {
      workspace.innerHTML = renderOperatorQueue();
      wireOperatorQueue();
      return;
    }
    if (role === "dispatcher" && activeTab === "stream") {
      workspace.innerHTML = renderDispatcherStream();
      openReviewOnClick("[data-review-id]", "reviewId", true);
      return;
    }
    if (role === "dispatcher" && activeTab === "history") {
      workspace.innerHTML = renderDispatcherHistory();
      openReviewOnClick(".row-action[data-id]", "id", false);
      return;
    }
    if (role === "admin" && activeTab === "progress") {
      workspace.innerHTML = renderAdminProgress();
      openReviewOnClick(".row-action[data-id]", "id", false);
      return;
    }
    if (role === "admin" && activeTab === "users") {
      workspace.innerHTML = renderUsersPanel();
      wireUsersPanel();
      return;
    }

    const tab = tabsFor(role).find((t) => t.id === activeTab);
    if (tab && tab.render) {
      workspace.innerHTML = tab.render(window.DDS);
      if (tab.wire) tab.wire(workspace, window.DDS);
      return;
    }
    workspace.innerHTML = `<div class="panel-head"><h2>Раздел не найден</h2></div>`;
  }

  function cardRow(call, i, extra) {
    const labels = typeLabels(call);
    const typeCell = labels ? (labels.length === 1 ? esc(labels[0]) : `${esc(labels[0])} <span class="cell-muted">+${labels.length - 1}</span>`) : `<span class="cell-muted">—</span>`;
    const addressCell = formatAddress(call) || `<span class="cell-muted">—</span>`;
    return `
      <tr style="--i:${i}">
        <td data-label="№" class="cell-mono">${esc(call.number)}</td>
        <td data-label="Время" class="cell-mono">${esc(call.time)}</td>
        ${extra.before || ""}
        <td data-label="Тип происшествия">${typeCell}</td>
        <td data-label="Адрес">${addressCell}</td>
        ${extra.after || ""}
      </tr>`;
  }

  function renderOperatorQueue() {
    const mine = incidents.filter((c) => c.source !== "system" && (!c.workstation || !session.workstation || c.workstation === session.workstation));
    const openCount = mine.filter((c) => c.status === "new" || (c.status === "review" && c.dds.decision === "declined")).length;

    const rows = mine
      .map((call, i) => {
        const canEdit = call.status === "new" || (call.status === "review" && call.dds.decision === "declined");
        const actionBtn = canEdit
          ? `<button type="button" class="row-action" data-row-open data-id="${call.id}">Открыть</button>`
          : `<button type="button" class="row-action" data-row-open data-view-id="${call.id}">Просмотр</button>`;
        return cardRow(call, i, {
          before: `<td data-label="АОН" class="cell-mono">${esc(call.phone)}</td>`,
          after: `<td data-label="Статус">${statusPill(call)}</td><td data-label="">${actionBtn}</td>`,
        });
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>Очередь вызовов</h2>
        <span class="count">${clusterProgress() ? clusterProgress() + " · " : ""}Требуют заполнения: ${openCount}</span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>№</th><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Адрес</th><th>Статус</th><th></th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function wireOperatorQueue() {
    document.querySelectorAll(".row-action[data-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const call = incidents.find((c) => c.id === btn.dataset.id);
        if (call) openSheet(call);
      });
    });
    openReviewOnClick(".row-action[data-view-id]", "viewId", false);
  }

  function openReviewOnClick(selector, dataKey, allowActions) {
    document.querySelectorAll(selector).forEach((btn) => {
      btn.addEventListener("click", () => {
        const call = incidents.find((c) => c.id === btn.dataset[dataKey]);
        if (call) openReviewSheet(call, allowActions && session.role === "dispatcher");
      });
    });
  }

  function renderDispatcherStream() {
    const pending = incidents.filter((c) => {
      if (c.status !== "review") return false;
      const ph = ddsState(c).phase;
      return ph === "pending" || ph === "active";
    });
    const rows = pending
      .map((call, i) =>
        cardRow(call, i, {
          before: `<td data-label="АОН" class="cell-mono">${esc(call.phone)}</td>`,
          after: `
            <td data-label="Приём (${D.TIMERS.accept} с)" class="cell-mono" data-timer="accept" data-id="${call.id}">${timerCellHtml(call, "accept")}</td>
            <td data-label="Реагирование (${D.TIMERS.respond / 60} мин)" class="cell-mono" data-timer="respond" data-id="${call.id}">${timerCellHtml(call, "respond")}</td>
            <td data-label="Статус" data-ddsstatus data-id="${call.id}">${statusPill(call)}</td>
            <td data-label=""><button type="button" class="row-action" data-row-open data-review-id="${call.id}">${call.dds.decision === "pending" ? "Принять решение" : "Открыть"}</button></td>`,
        })
      )
      .join("");

    return `
      <div class="panel-head">
        <h2>Поток карточек</h2>
        <span class="count">${clusterProgress() ? clusterProgress() + " · " : ""}В работе: ${pending.length}</span>
      </div>
      <p class="empty-hint" style="padding:0 0 12px;">На решение «Принята / Не принята» даётся ${D.TIMERS.accept} с, иначе карточка получает статус «Не оповещено». После приёма — ${D.TIMERS.respond / 60} мин на следующий статус реагирования, иначе «Не завершено».</p>
      <div class="data-table-wrap">
        ${pending.length ? `<table class="data-table"><thead><tr><th>№</th><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Адрес</th><th>Приём</th><th>Реагирование</th><th>Статус</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty-hint">Поток пуст. Нажмите «Смоделировать поступление» или дождитесь карточек от операторов.</div>`}
      </div>`;
  }

  function renderDispatcherHistory() {
    const done = incidents.filter((c) => {
      if (c.status !== "review") return false;
      const ph = ddsState(c).phase;
      return ph === "declined" || ph === "done" || ph === "refused";
    });
    const rows = done
      .map((call, i) =>
        cardRow(call, i, {
          after: `<td data-label="Решение">${statusPill(call)}</td><td data-label=""><button type="button" class="row-action" data-row-open data-id="${call.id}">Просмотр</button></td>`,
        })
      )
      .join("");

    return `
      <div class="panel-head">
        <h2>История</h2>
        <span class="count">Завершено: ${done.length}</span>
      </div>
      <div class="data-table-wrap">
        ${done.length ? `<table class="data-table"><thead><tr><th>№</th><th>Время</th><th>Тип происшествия</th><th>Адрес</th><th>Решение</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty-hint">Пока нет завершённых карточек.</div>`}
      </div>`;
  }

  function renderAdminProgress() {
    const rows = incidents
      .map((call, i) =>
        cardRow(call, i, {
          before: `<td data-label="Место" class="cell-mono">${esc(call.workstation || "—")}</td>`,
          after: `<td data-label="Статус">${statusPill(call)}</td><td data-label="">${call.status !== "new" ? `<button type="button" class="row-action" data-row-open data-id="${call.id}">Просмотр</button>` : ""}</td>`,
        })
      )
      .join("");

    return `
      <div class="panel-head">
        <h2>Прогресс операторов и диспетчеров</h2>
        <span class="count">Карточек всего: ${incidents.length}</span>
      </div>
      <p class="empty-hint" style="padding:0 0 14px;">Режим наблюдения: администратор видит весь конвейер обработки вызова, но не может редактировать карточки.</p>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>№</th><th>Время</th><th>Место</th><th>Тип происшествия</th><th>Адрес</th><th>Статус</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderUsersPanel() {
    const rows = users
      .map((u, i) => {
        const statusCell = u.blocked
          ? `<span class="status-pill status-blocked">Заблокирован</span>`
          : `<span class="status-pill status-done">Активен</span>`;
        const actionLabel = u.blocked ? "Разблокировать" : "Заблокировать";
        return `
        <tr style="--i:${i}">
          <td data-label="ФИО">${esc(u.name)}</td>
          <td data-label="Роль" class="cell-muted">${esc(u.role)}</td>
          <td data-label="Статус">${statusCell}</td>
          <td data-label=""><button type="button" class="row-action ${u.blocked ? "" : "danger"}" data-name="${esc(u.name)}">${actionLabel}</button></td>
        </tr>`;
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>Пользователи</h2>
        <span class="count">Всего: ${users.length}</span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>ФИО</th><th>Роль</th><th>Статус</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function wireUsersPanel() {
    document.querySelectorAll(".row-action[data-name]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const user = users.find((u) => u.name === btn.dataset.name);
        if (!user) return;
        user.blocked = !user.blocked;
        API.log("user_block", `${user.name}: ${user.blocked ? "заблокирован" : "разблокирован"}`);
        showToast(user.blocked ? `${user.name}: доступ заблокирован` : `${user.name}: доступ восстановлен`);
        renderWorkspace();
      });
    });
  }

  const overlay = document.getElementById("incident-sheet");
  const titleEl = document.getElementById("sheet-title");
  const numberEl = document.getElementById("sheet-number");
  const clusterEl = document.getElementById("sheet-cluster");
  const timerBox = document.getElementById("sheet-timer");
  const timerNormEl = document.getElementById("sheet-timer-norm");
  const stripWho = document.getElementById("caller-strip-who");
  const stripText = document.getElementById("caller-strip-text");
  const phoneEl = document.getElementById("sheet-phone");
  const timeEl = document.getElementById("sheet-time");
  const phoneAonInput = document.getElementById("sheet-phone-aon");
  const phoneGivenInput = document.getElementById("sheet-phone-given");
  const phoneOnsiteInput = document.getElementById("sheet-phone-onsite");
  const typesField = document.getElementById("field-types");
  const typeSearchInput = document.getElementById("type-search");
  const typeTilesEl = document.getElementById("type-tiles");
  const surveyField = document.getElementById("field-survey");
  const surveyEl = document.getElementById("survey");
  const chatLog = document.getElementById("chat-log");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  const addressField = document.getElementById("field-address");
  const addressInput = document.getElementById("sheet-address-input");
  const addrInputs = {
    country: document.getElementById("addr-country"),
    region: document.getElementById("addr-region"),
    locality: document.getElementById("addr-locality"),
    okrug: document.getElementById("addr-okrug"),
    district: document.getElementById("addr-district"),
    street: document.getElementById("addr-street"),
    house: document.getElementById("addr-house"),
    korpus: document.getElementById("addr-korpus"),
    flat: document.getElementById("addr-flat"),
    entrance: document.getElementById("addr-entrance"),
    floor: document.getElementById("addr-floor"),
    code: document.getElementById("addr-code"),
    descriptive: document.getElementById("addr-descriptive"),
  };
  const callerField = document.getElementById("field-caller");
  const callerInput = document.getElementById("sheet-caller-input");
  const callerStatusField = document.getElementById("field-caller-status");
  const callerStatusSelect = document.getElementById("sheet-caller-status");
  const foreignLanguageCheckbox = document.getElementById("foreign-language");
  const injuredField = document.getElementById("field-injured");
  const injuredCountInput = document.getElementById("injured-count");
  const descriptionInput = document.getElementById("sheet-description");
  const descriptionCounter = document.getElementById("description-counter");
  const servicesHint = document.getElementById("sheet-services-hint");
  const serviceChips = document.getElementById("service-chips");
  const serviceAddWrap = document.getElementById("service-add");
  const serviceAddSelect = document.getElementById("service-add-select");
  const serviceAddBtn = document.getElementById("service-add-btn");
  const timerValueEl = document.getElementById("sheet-timer-value");
  const telephonyStatusBtn = document.getElementById("telephony-status");
  const telephonyStatusLabel = document.getElementById("telephony-status-label");

  let timerInterval = null;
  let secondsElapsed = 0;
  let currentCall = null;
  let selectedTypes = [];
  let currentSurvey = {};
  let manualServices = [];
  let removedAutoServices = [];
  let currentFlags = { injured: false, notOnSite: false, ambulanceRefused: false, blocked: false };
  let telephonyResetTimer = null;
  let manualPause = false;

  function scenarioOf(call) {
    return D.getScenarios().find((s) => s.id === call.scenarioId) || null;
  }

  function initSheet() {
    typeTilesEl.innerHTML = INCIDENT_TYPES.map(
      (t) => `<button type="button" class="type-tile" data-id="${t.id}" style="--tile-color:${t.color}">${iconHtml(t.icon, 13)}${t.label}</button>`
    ).join("");

    typeTilesEl.querySelectorAll(".type-tile").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        const idx = selectedTypes.indexOf(id);
        if (idx === -1) selectedTypes.push(id);
        else selectedTypes.splice(idx, 1);
        typesField.classList.remove("has-error");
        applyTypes();
      });
    });

    typeSearchInput.addEventListener("input", () => {
      const query = typeSearchInput.value.trim().toLowerCase();
      typeTilesEl.querySelectorAll(".type-tile").forEach((btn) => {
        const matches = btn.textContent.toLowerCase().includes(query);
        btn.classList.toggle("hidden-by-search", query.length > 0 && !matches);
      });
    });

    injuredField.querySelectorAll(".flag-pill[data-flag]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const flag = btn.dataset.flag;
        currentFlags[flag] = !currentFlags[flag];
        btn.classList.toggle("active", currentFlags[flag]);
        if (flag === "injured") {
          injuredCountInput.hidden = !currentFlags.injured;
          if (!currentFlags.injured) injuredCountInput.value = "";
        }
      });
    });

    document.getElementById("sheet-close").addEventListener("click", closeSheet);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeSheet();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.classList.contains("is-open")) closeSheet();
    });

    addressInput.addEventListener("input", () => addressField.classList.remove("has-error"));
    callerInput.addEventListener("input", () => callerField.classList.remove("has-error"));
    callerStatusSelect.addEventListener("change", () => callerStatusField.classList.remove("has-error"));
    descriptionInput.addEventListener("input", () => {
      descriptionCounter.textContent = `${descriptionInput.value.length} / 500`;
      descriptionInput.closest(".form-field").classList.remove("has-error");
    });

    serviceAddBtn.addEventListener("click", () => {
      const value = serviceAddSelect.value;
      if (!value) return;
      manualServices.push(value);
      renderServiceChips();
    });

    chatSend.addEventListener("click", sendChat);
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        sendChat();
      }
    });

    document.getElementById("btn-no-contact").addEventListener("click", () => finishAsEmpty("no_contact"));
    document.getElementById("btn-call-failed").addEventListener("click", () => finishAsEmpty("call_failed"));

    if (telephonyStatusBtn) {
      telephonyStatusBtn.addEventListener("click", () => {
        if (overlay.classList.contains("is-open")) return;
        manualPause = !manualPause;
        clearTimeout(telephonyResetTimer);
        setTelephonyStatus(manualPause ? "unavailable" : "available");
      });
    }

    document.getElementById("sheet-cancel").addEventListener("click", closeSheet);
    document.getElementById("sheet-submit").addEventListener("click", submitCard);
  }

  function renderChat() {
    chatLog.innerHTML = (currentCall.chat || [])
      .slice(-4)
      .map((m) => `<div class="chat-msg ${m.role}"><b>${m.role === "operator" ? "Вы" : "Заявитель (ИИ)"}</b>${esc(m.text)}</div>`)
      .join("") || `<div class="chat-empty">Сообщений пока нет</div>`;
    chatLog.scrollTop = chatLog.scrollHeight;
    const lastCaller = (currentCall.chat || []).slice().reverse().find((m) => m.role === "caller");
    stripWho.textContent = currentCall.phone && currentCall.phone !== "—" ? currentCall.phone : "номер не определён";
    stripText.textContent = lastCaller ? "«" + lastCaller.text + "»" : "Сообщений пока нет";
  }

  function sendChat() {
    const text = chatInput.value.trim();
    if (!text || !currentCall) return;
    const call = currentCall;
    chatInput.value = "";
    call.chat.push({ role: "operator", text: text });
    renderChat();
    saveIncidents();
    setTimeout(() => {
      call.chat.push({ role: "caller", text: D.callerReply(scenarioOf(call), text) });
      if (currentCall === call) renderChat();
      saveIncidents();
    }, 500);
  }

  function finishAsEmpty(reason) {
    const label = reason === "no_contact" ? "Нет контакта" : "Срыв звонка";
    if (!confirm(`Сохранить карточку со статусом «${label}» без заполнения остальных полей?`)) return;
    currentCall.status = "empty";
    currentCall.emptyReason = reason;
    API.log("card_empty", `Карточка № ${currentCall.number}: ${label}`);
    showToast(`Карточка сохранена · ${label}`);
    saveIncidents();
    closeSheet();
    renderWorkspace();
  }

  function setTelephonyStatus(status) {
    if (!telephonyStatusBtn) return;
    telephonyStatusBtn.classList.toggle("is-available", status === "available");
    telephonyStatusBtn.classList.toggle("is-unavailable", status === "unavailable");
    telephonyStatusLabel.textContent = status === "available" ? "доступен" : "недоступен";
    emit("dds:operator-status", { available: status === "available" });
  }

  function currentAutoServices() {
    return servicesForTypes(selectedTypes);
  }

  function surveySets() {
    const keys = [];
    selectedTypes.forEach((id) => {
      const k = D.TYPE_SURVEY[id];
      if (k && keys.indexOf(k) === -1) keys.push(k);
    });
    return keys;
  }

  function renderSurvey() {
    const sets = surveySets();
    surveyField.hidden = !sets.length;
    surveyEl.innerHTML = sets
      .map((setKey) =>
        D.SURVEYS[setKey]
          .map((g) => {
            const key = setKey + "." + g.key;
            const opts = g.options
              .map((o) => `<button type="button" class="flag-pill ${currentSurvey[key] === o ? "active" : ""}" data-survey="${key}" data-value="${o}">${o}</button>`)
              .join("");
            return `<div class="survey-group"><span class="survey-label">${g.label}</span><div class="flag-row">${opts}</div></div>`;
          })
          .join("")
      )
      .join("");
    surveyEl.querySelectorAll("[data-survey]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.survey;
        if (currentSurvey[key] === btn.dataset.value) delete currentSurvey[key];
        else currentSurvey[key] = btn.dataset.value;
        renderSurvey();
      });
    });
  }

  function prunedSurvey() {
    const valid = {};
    surveySets().forEach((setKey) => D.SURVEYS[setKey].forEach((g) => {
      const key = setKey + "." + g.key;
      if (currentSurvey[key]) valid[key] = currentSurvey[key];
    }));
    return valid;
  }

  function applyTypes() {
    typeTilesEl.querySelectorAll(".type-tile").forEach((btn) => {
      btn.classList.toggle("selected", selectedTypes.indexOf(btn.dataset.id) !== -1);
    });

    if (selectedTypes.length === 1) {
      titleEl.textContent = INCIDENT_TYPES.find((t) => t.id === selectedTypes[0]).label;
    } else if (selectedTypes.length > 1) {
      titleEl.textContent = `Происшествие (${selectedTypes.length} типа)`;
    } else {
      titleEl.textContent = "Новая карточка";
    }

    servicesHint.hidden = selectedTypes.length > 0;
    renderSurvey();
    renderServiceChips();
  }

  function renderServiceChips() {
    const auto = currentAutoServices().filter((s) => removedAutoServices.indexOf(s) === -1);
    const shown = auto.concat(manualServices.filter((s) => auto.indexOf(s) === -1));

    serviceChips.innerHTML = shown
      .map(
        (service) =>
          `<span class="service-chip">${iconHtml("call", 12)}${service}<button type="button" class="chip-remove" data-service="${service}" aria-label="Убрать службу">×</button></span>`
      )
      .join("");

    serviceChips.querySelectorAll(".chip-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        const service = btn.dataset.service;
        if (manualServices.indexOf(service) !== -1) {
          manualServices = manualServices.filter((s) => s !== service);
        } else {
          removedAutoServices.push(service);
        }
        renderServiceChips();
      });
    });

    const remaining = ALL_SERVICES.filter((s) => shown.indexOf(s) === -1);
    if (selectedTypes.length && remaining.length) {
      serviceAddWrap.hidden = false;
      serviceAddSelect.innerHTML = remaining.map((s) => `<option value="${s}">${s}</option>`).join("");
    } else {
      serviceAddWrap.hidden = true;
    }
  }

  function submitCard() {
    let valid = true;

    if (!selectedTypes.length) {
      typesField.classList.add("has-error");
      valid = false;
    }
    if (!addressInput.value.trim()) {
      addressField.classList.add("has-error");
      valid = false;
    }
    if (!callerInput.value.trim()) {
      callerField.classList.add("has-error");
      valid = false;
    }
    if (!callerStatusSelect.value) {
      callerStatusField.classList.add("has-error");
      valid = false;
    }
    if (!descriptionInput.value.trim()) {
      descriptionInput.closest(".form-field").classList.add("has-error");
      valid = false;
    }
    if (!valid) return;

    const auto = currentAutoServices().filter((s) => removedAutoServices.indexOf(s) === -1);
    const finalServices = auto.concat(manualServices.filter((s) => auto.indexOf(s) === -1));

    currentCall.types = selectedTypes.slice();
    currentCall.addressLine = addressInput.value.trim();
    currentCall.address = {
      country: addrInputs.country.value.trim(),
      region: addrInputs.region.value.trim(),
      locality: addrInputs.locality.value.trim(),
      okrug: addrInputs.okrug.value.trim(),
      district: addrInputs.district.value.trim(),
      street: addrInputs.street.value.trim(),
      house: addrInputs.house.value.trim(),
      korpus: addrInputs.korpus.value.trim(),
      flat: addrInputs.flat.value.trim(),
      entrance: addrInputs.entrance.value.trim(),
      floor: addrInputs.floor.value.trim(),
      code: addrInputs.code.value.trim(),
      descriptive: addrInputs.descriptive.value.trim(),
    };
    currentCall.caller = callerInput.value.trim();
    currentCall.callerStatus = callerStatusSelect.value;
    currentCall.foreignLanguage = foreignLanguageCheckbox.checked;
    currentCall.phoneGiven = phoneGivenInput.value.trim();
    currentCall.phoneOnsite = phoneOnsiteInput.value.trim();
    currentCall.description = descriptionInput.value.trim();
    currentCall.flags = Object.assign({}, currentFlags);
    currentCall.injuredCount = currentFlags.injured ? injuredCountInput.value : null;
    currentCall.survey = prunedSurvey();
    currentCall.services = finalServices;
    currentCall.fillSeconds = secondsElapsed;
    currentCall.workstation = session.workstation || currentCall.workstation;
    currentCall.status = "review";
    currentCall.sentAt = Date.now();
    currentCall.dds = newDds();
    currentCall.dispatcherComment = null;

    API.log("card_sent", `Карточка № ${currentCall.number} отправлена диспетчеру за ${secondsElapsed} с`);
    showToast(`Карточка № ${currentCall.number} отправлена диспетчеру · заполнена за ${secondsElapsed} с`);
    saveIncidents();
    closeSheet();
    renderWorkspace();
  }

  function startTimer() {
    stopTimer();
    secondsElapsed = 0;
    renderTimer();
    timerInterval = setInterval(() => {
      secondsElapsed += 1;
      renderTimer();
    }, 1000);
  }

  function renderTimer() {
    const m = Math.floor(secondsElapsed / 60);
    const s = secondsElapsed % 60;
    timerValueEl.textContent = `${m}:${String(s).padStart(2, "0")}`;
    timerNormEl.textContent = "норматив " + fmtClock(D.NORMS.fillSeconds);
    timerBox.classList.toggle("is-over", secondsElapsed > D.NORMS.fillSeconds);
  }

  function stopTimer() {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  function openSheet(call) {
    currentCall = call;
    clearTimeout(telephonyResetTimer);
    setTelephonyStatus("unavailable");

    selectedTypes = call.types ? call.types.slice() : [];
    currentSurvey = Object.assign({}, call.survey);
    addressInput.value = call.addressLine || "";
    Object.keys(addrInputs).forEach((key) => {
      addrInputs[key].value = (call.address && call.address[key]) || (key === "country" ? "Россия" : key === "region" || key === "locality" ? "Москва" : "");
    });
    callerInput.value = call.caller || "";
    callerStatusSelect.value = call.callerStatus || "";
    foreignLanguageCheckbox.checked = !!call.foreignLanguage;
    phoneGivenInput.value = call.phoneGiven || "";
    phoneOnsiteInput.value = call.phoneOnsite || "";
    descriptionInput.value = call.description || "";
    descriptionCounter.textContent = `${descriptionInput.value.length} / 500`;
    manualServices = call.services ? call.services.slice() : [];
    removedAutoServices = [];

    currentFlags = Object.assign({ injured: false, notOnSite: false, ambulanceRefused: false, blocked: false }, call.flags);
    injuredField.querySelectorAll(".flag-pill[data-flag]").forEach((btn) => {
      btn.classList.toggle("active", !!currentFlags[btn.dataset.flag]);
    });
    injuredCountInput.hidden = !currentFlags.injured;
    injuredCountInput.value = call.injuredCount || "";

    [typesField, addressField, callerField, callerStatusField].forEach((f) => f.classList.remove("has-error"));
    descriptionInput.closest(".form-field").classList.remove("has-error");

    applyTypes();

    numberEl.textContent = call.number;
    clusterEl.textContent = clusterLabel(call);
    phoneAonInput.value = call.phone;
    phoneEl.textContent = call.phone;
    timeEl.textContent = call.time;

    const sc = scenarioOf(call);
    if (!call.chat.length && sc) {
      call.chat.push({ role: "caller", text: sc.opening });
      saveIncidents();
    }
    chatInput.value = "";
    renderChat();

    if (call.status === "review" && call.dds.decision === "declined" && call.dds.comment) {
      showToast(`Не принята диспетчером: ${call.dds.comment}`);
    }

    startTimer();

    overlay.hidden = false;
    fitOperator();
    requestAnimationFrame(() => overlay.classList.add("is-open"));
    overlay.setAttribute("aria-hidden", "false");
    typeSearchInput.focus();
    emit("dds:card-open", call);
  }

  function closeSheet() {
    overlay.classList.remove("is-open");
    overlay.setAttribute("aria-hidden", "true");
    stopTimer();
    clearTimeout(telephonyResetTimer);
    telephonyResetTimer = setTimeout(() => {
      if (!manualPause) setTelephonyStatus("available");
    }, 10000);
    emit("dds:card-close", currentCall);
    setTimeout(() => {
      overlay.hidden = true;
    }, 320);
  }

  const reviewOverlay = document.getElementById("review-sheet");
  const reviewComment = document.getElementById("review-comment");
  let currentReviewCall = null;
  let currentReviewAllow = false;

  function initReviewSheet() {
    document.getElementById("review-close").addEventListener("click", closeReviewSheet);
    reviewOverlay.addEventListener("click", (e) => {
      if (e.target === reviewOverlay) closeReviewSheet();
    });
    document.getElementById("review-callback-btn").addEventListener("click", () => {
      API.log("callback", `Перезвон заявителю по карточке № ${currentReviewCall.number}`);
      if (window.DDS_TELEPHONY) emit("dds:callback", currentReviewCall);
      else showToast(`Звонок заявителю: ${currentReviewCall.phone}`);
    });
    document.getElementById("review-accept").addEventListener("click", () => decide("accepted"));
    document.getElementById("review-decline").addEventListener("click", () => decide("declined"));
    document.getElementById("review-statuses").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-reaction]");
      if (btn && !btn.disabled) setReaction(btn.dataset.reaction);
    });
  }

  function pushHistory(call, id, label, comment) {
    call.dds.history.push({ id: id, label: label, time: hhmm(), comment: comment || null });
  }

  function decide(kind) {
    const call = currentReviewCall;
    if (!call || call.dds.decision !== "pending") return;
    const comment = reviewComment.value.trim();
    if (kind === "declined" && !comment) {
      reviewComment.focus();
      showToast("Комментарий обязателен: укажите причину и кому передана информация");
      return;
    }
    call.dds.decision = kind;
    call.dds.decisionAt = Date.now();
    call.dds.comment = comment || null;
    pushHistory(call, kind, kind === "accepted" ? "Принята" : "Не принята", comment);
    API.log("dds_" + kind, `Карточка № ${call.number}: ${kind === "accepted" ? "принята" : "не принята"}`);
    saveIncidents();
    if (kind === "declined") {
      showToast("Карточка не принята, причина передана оператору");
      closeReviewSheet();
    } else {
      showToast("Карточка принята");
      fillReview(call, true);
    }
    renderWorkspace();
  }

  function setReaction(id) {
    const call = currentReviewCall;
    if (!call || call.dds.decision !== "accepted") return;
    const order = D.REACTION_STATUSES.map((s) => s.id);
    const cur = call.dds.reaction ? order.indexOf(call.dds.reaction) : -1;
    const comment = reviewComment.value.trim();
    if (id === D.REACTION_REFUSED.id) {
      if (!comment) {
        reviewComment.focus();
        showToast("Для отказа от выполнения работ комментарий обязателен");
        return;
      }
    } else if (order.indexOf(id) !== cur + 1) {
      return;
    }
    call.dds.reaction = id;
    call.dds.reactionAt = Date.now();
    pushHistory(call, id, reactionLabel(id), comment);
    reviewComment.value = "";
    API.log("dds_reaction", `Карточка № ${call.number}: ${reactionLabel(id)}`);
    saveIncidents();
    fillReview(call, true);
    renderWorkspace();
  }

  function surveyChips(call) {
    const items = Object.keys(call.survey || {}).map((key) => {
      const parts = key.split(".");
      const group = (D.SURVEYS[parts[0]] || []).find((g) => g.key === parts[1]);
      return `<span class="review-flag">${esc(group ? group.label : key)}: ${esc(call.survey[key])}</span>`;
    });
    return items.length ? items.join("") : `<span class="cell-muted">Не заполнена</span>`;
  }

  function reactionButtons(call, allow) {
    const order = D.REACTION_STATUSES.map((s) => s.id);
    const cur = call.dds.reaction ? order.indexOf(call.dds.reaction) : -1;
    const refused = call.dds.reaction === D.REACTION_REFUSED.id;
    const finished = refused || call.dds.reaction === "done";
    const steps = D.REACTION_STATUSES.map((s, i) => {
      const passed = !refused && i <= cur;
      const next = !finished && i === cur + 1;
      return `<button type="button" class="step-btn ${passed ? "passed" : next ? "next" : ""}" data-reaction="${s.id}" ${!allow || !next ? "disabled" : ""}>${s.label}</button>`;
    }).join("");
    const refuse = `<button type="button" class="step-btn refuse ${refused ? "passed" : ""}" data-reaction="${D.REACTION_REFUSED.id}" ${!allow || finished ? "disabled" : ""}>${D.REACTION_REFUSED.label}</button>`;
    return steps + refuse;
  }

  function fillReview(call, allow) {
    currentReviewAllow = allow;
    document.getElementById("review-title").textContent = "Карточка № " + call.number;
    document.getElementById("review-cluster").textContent = clusterLabel(call);
    document.getElementById("review-phone").textContent = call.phone;
    document.getElementById("review-callback-btn").hidden = !!call.emptyReason;

    const labels = typeLabels(call);
    document.getElementById("review-types").textContent = labels ? labels.join(", ") : "—";
    document.getElementById("review-address").innerHTML = formatAddress(call) || "—";
    document.getElementById("review-caller").textContent = call.caller || "—";
    document.getElementById("review-caller-status").textContent = call.callerStatus || "—";
    document.getElementById("review-description").textContent = call.description || "—";
    document.getElementById("review-survey").innerHTML = surveyChips(call);

    const flagLabels = { injured: "Пострадавшие", notOnSite: "Нет на месте", ambulanceRefused: "Отказ от скорой", blocked: "Заблокированные" };
    const activeFlags = Object.keys(flagLabels).filter((k) => call.flags && call.flags[k]);
    if (call.foreignLanguage) activeFlags.push("__foreign__");
    document.getElementById("review-flags").innerHTML = activeFlags.length
      ? activeFlags.map((k) => `<span class="review-flag">${k === "__foreign__" ? "Иностранный язык" : flagLabels[k]}${k === "injured" && call.injuredCount ? ": " + esc(call.injuredCount) : ""}</span>`).join("")
      : `<span class="cell-muted">Отметок нет</span>`;

    document.getElementById("review-services").innerHTML = (call.services || [])
      .map((s) => `<span class="service-chip">${iconHtml("call", 12)}${esc(s)}</span>`)
      .join("") || `<span class="cell-muted">Службы не назначены</span>`;

    document.getElementById("review-chat").innerHTML = (call.chat || [])
      .map((m) => `<div class="chat-msg ${m.role}"><b>${m.role === "operator" ? "Оператор" : "Заявитель (ИИ)"}</b>${esc(m.text)}</div>`)
      .join("") || `<span class="cell-muted">Переписки нет</span>`;

    const st = ddsState(call);
    const isReview = call.status === "review";
    const pending = isReview && call.dds.decision === "pending";
    const accepted = isReview && call.dds.decision === "accepted";
    const canComment = allow && (pending || (accepted && st.phase === "active"));

    document.getElementById("review-timers").hidden = !isReview;
    document.getElementById("review-decision").hidden = !(allow && pending);
    document.getElementById("review-reaction-block").hidden = !accepted;
    document.getElementById("review-statuses").innerHTML = accepted ? reactionButtons(call, allow) : "";
    document.getElementById("review-comment-field").hidden = !(canComment || (isReview && call.dds.comment));
    reviewComment.disabled = !canComment;
    reviewComment.value = canComment ? "" : call.dds.comment || "";

    document.getElementById("review-history").innerHTML = call.dds.history.length
      ? call.dds.history.map((h) => `<div class="history-row"><span class="cell-mono">${esc(h.time)}</span><b>${esc(h.label)}</b>${h.comment ? `<span class="cell-muted">${esc(h.comment)}</span>` : ""}</div>`).join("")
      : "";
    updateReviewTimers();
  }

  function updateReviewTimers() {
    if (!currentReviewCall || currentReviewCall.status !== "review") return;
    document.getElementById("review-timer-accept").innerHTML = timerCellHtml(currentReviewCall, "accept");
    document.getElementById("review-timer-respond").innerHTML = timerCellHtml(currentReviewCall, "respond");
    document.getElementById("review-state").innerHTML = statusPill(currentReviewCall);
  }

  function openReviewSheet(call, allowActions) {
    currentReviewCall = call;
    fillReview(call, !!allowActions);
    reviewOverlay.hidden = false;
    fitReview();
    requestAnimationFrame(() => reviewOverlay.classList.add("is-open"));
    reviewOverlay.setAttribute("aria-hidden", "false");
    emit("dds:review-open", call);
  }

  function closeReviewSheet() {
    emit("dds:review-close", currentReviewCall);
    reviewOverlay.classList.remove("is-open");
    reviewOverlay.setAttribute("aria-hidden", "true");
    setTimeout(() => {
      reviewOverlay.hidden = true;
    }, 320);
  }

  const FIT_MAX = 11;
  const FIT_MIN = 7.5;

  function fitWindow(sheet) {
    if (!sheet || sheet.offsetParent === null) return;
    const body = sheet.querySelector(".win-body");
    const cols = sheet.querySelectorAll(".win-col");
    const tooTall = () => {
      for (let i = 0; i < cols.length; i++) if (cols[i].scrollHeight - cols[i].clientHeight > 1) return true;
      return body.scrollHeight - body.clientHeight > 1;
    };
    let fs = FIT_MAX;
    sheet.classList.remove("fit-fail");
    sheet.style.setProperty("--fs", fs + "px");
    while (tooTall() && fs > FIT_MIN) {
      fs = Math.round((fs - 0.25) * 100) / 100;
      sheet.style.setProperty("--fs", fs + "px");
    }
    if (tooTall()) sheet.classList.add("fit-fail");
  }

  function watchFit(overlayEl) {
    const sheet = overlayEl.querySelector(".sheet-wide");
    const body = sheet.querySelector(".win-body");
    let raf = 0;
    const run = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => fitWindow(sheet));
    };
    new MutationObserver(run).observe(body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class", "hidden"] });
    new MutationObserver(run).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", run);
    return () => fitWindow(sheet);
  }

  let fitOperator = () => {};
  let fitReview = () => {};

  function emit(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail }));
  }

  function showToast(text) {
    const toast = document.getElementById("toast");
    document.getElementById("toast-text").textContent = text;
    toast.classList.add("is-visible");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("is-visible"), 2600);
  }

  window.DDS = {
    role: session.role,
    session: session,
    addCallLog(incidentId, entry) {
      const call = incidents.find((c) => c.id === incidentId);
      if (!call) return false;
      call.calls = (call.calls || []).concat([entry]);
      saveIncidents();
      return true;
    },
    getIncident(incidentId) {
      return incidents.find((c) => c.id === incidentId) || null;
    },
    getIncidents: () => incidents,
    saveIncidents: saveIncidents,
    getUsers: () => users,
    showToast: showToast,
    renderWorkspace: renderWorkspace,
    openReview: openReviewSheet,
    typeLabels: typeLabels,
    formatAddress: formatAddress,
    statusPill: statusPill,
    clusterLabel: clusterLabel,
    poolFor: poolFor,
    ddsState: ddsState,
    esc: esc,
    INCIDENT_TYPES: INCIDENT_TYPES,
    ALL_SERVICES: ALL_SERVICES,
    ROLE_LABELS: ROLE_LABELS,
  };

  function startClock() {
    const clockEl = document.getElementById("clock");
    const dateEl = document.getElementById("date");

    function tick() {
      const now = new Date();
      clockEl.textContent = now.toLocaleTimeString("ru-RU");
      dateEl.textContent = now.toLocaleDateString("ru-RU", {
        weekday: "long",
        day: "numeric",
        month: "long",
      });
    }

    tick();
    setInterval(tick, 1000);
  }

  renderTopbar();
  renderToolbar();
  renderWorkspace();
  startClock();
  initSheet();
  initReviewSheet();
  fitOperator = watchFit(overlay);
  fitReview = watchFit(reviewOverlay);
  setInterval(tickTimers, 1000);

  if (!session.sid) {
    session.sid = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    localStorage.setItem("ddsSession", JSON.stringify(session));
  }
  API.touchSession(session);
  setInterval(() => API.touchSession(session), 15000);

  API.pullIncidents().then((list) => {
    if (!list) return;
    incidents = list.map(normalize);
    localStorage.setItem("ddsIncidents", JSON.stringify(incidents));
    renderWorkspace();
  });

  document.getElementById("logout-btn").addEventListener("click", () => {
    API.log("logout", "Выход из системы");
    API.dropSession(session.sid);
    localStorage.removeItem("ddsSession");
    window.location.href = "index.html";
  });
})();
