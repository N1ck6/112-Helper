(function () {
  const ROLE_LABELS = {
    student: "Оператор",
    teacher: "Диспетчер",
    admin: "Администратор",
  };

  const ICONS = {
    call: "/assets/icons/misc_phone.png",
    nature: "/assets/icons/nature_storm.png",
    medicine: "/assets/icons/med_heart.png",
    infrastructure: "/assets/icons/med_house.png",
    shield: "/assets/icons/misc_shield.png",
    warning: "/assets/icons/misc_warning.png",
  };

  function iconHtml(key, size) {
    const src = ICONS[key];
    if (!src) return "";
    return `<span class="icon" style="--icon-src:url('${src}'); width:${size}px; height:${size}px;" aria-hidden="true"></span>`;
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

  function newIncident(id, time, phone) {
    return {
      id: id,
      time: time,
      phone: phone,
      status: "new",
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
      fillSeconds: null,
      dispatcherComment: null,
      emptyReason: null,
    };
  }

  function seedIncidents() {
    return [
      newIncident("c1", "10:47", "+7 (495) 123-45-67"),
      newIncident("c2", "10:52", "+7 (903) 555-12-09"),
      newIncident("c3", "10:58", "+7 (499) 887-21-34"),
      newIncident("c4", "11:04", "Номер скрыт"),
    ];
  }

  function loadIncidents() {
    try {
      const raw = localStorage.getItem("ddsIncidents");
      if (raw) return JSON.parse(raw);
    } catch (e) {
      /* повреждённые данные в localStorage — начинаем заново */
    }
    return seedIncidents();
  }

  function saveIncidents() {
    localStorage.setItem("ddsIncidents", JSON.stringify(incidents));
  }

  let incidents = loadIncidents();

  let users = [
    { name: "Иванов И.И.", role: "Оператор", blocked: false },
    { name: "Смирнова О.П.", role: "Диспетчер", blocked: false },
    { name: "Сидоров П.П.", role: "Администратор", blocked: false },
    { name: "Козлов Д.А.", role: "Оператор", blocked: true },
  ];

  const TOOLBARS = {
    student: {
      tabs: [
        { id: "queue", label: "Очередь вызовов" },
        { id: "stats", label: "Статистика" },
      ],
      primary: { label: "Создать карточку", action: "create-card" },
    },
    teacher: {
      tabs: [
        { id: "review", label: "На проверке" },
        { id: "history", label: "История проверок" },
      ],
    },
    admin: {
      tabs: [
        { id: "progress", label: "Прогресс" },
        { id: "users", label: "Пользователи" },
      ],
    },
  };

  const session = JSON.parse(localStorage.getItem("ddsSession") || "null");

  if (!session) {
    window.location.href = "index.html";
    return;
  }

  let activeTab = TOOLBARS[session.role].tabs[0].id;

  function renderTopbar() {
    document.getElementById("role-badge").textContent = ROLE_LABELS[session.role] || session.role;
    const status = document.getElementById("telephony-status");
    if (status) {
      status.hidden = session.role !== "student";
      if (session.role === "student") {
        status.classList.add("is-available");
        document.getElementById("telephony-status-label").textContent = "доступен";
      }
    }
  }

  function renderToolbar() {
    const config = TOOLBARS[session.role];
    const toolbar = document.getElementById("toolbar");

    const tabsHtml = config.tabs
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
    if (createBtn) {
      createBtn.addEventListener("click", () => {
        const now = new Date();
        const id = "m" + now.getTime();
        const time = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
        const call = newIncident(id, time, "—");
        incidents = [call].concat(incidents);
        saveIncidents();
        openSheet(call);
      });
    }
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
    const a = call.address;
    const parts = [a.street, a.house ? `д. ${a.house}` : "", a.flat ? `кв. ${a.flat}` : ""].filter(Boolean);
    return parts.length ? `${call.addressLine} (${parts.join(", ")})` : call.addressLine;
  }

  function statusPill(call) {
    switch (call.status) {
      case "review":
        return `<span class="status-pill status-new">Отправлена диспетчеру</span>`;
      case "approved":
        return `<span class="status-pill status-done">Утверждена</span>`;
      case "returned":
        return `<span class="status-pill status-blocked">Возвращена оператору</span>`;
      case "empty":
        return `<span class="cell-muted">${call.emptyReason === "no_contact" ? "Нет контакта" : "Срыв звонка"}</span>`;
      default:
        return `<span class="status-pill status-new">Новый вызов</span>`;
    }
  }

  function renderWorkspace() {
    const workspace = document.getElementById("workspace");

    if (session.role === "student" && activeTab === "queue") {
      workspace.innerHTML = renderOperatorQueue();
      wireOperatorQueue();
      return;
    }

    if (session.role === "teacher" && activeTab === "review") {
      workspace.innerHTML = renderDispatcherQueue();
      wireDispatcherQueue();
      return;
    }

    if (session.role === "teacher" && activeTab === "history") {
      workspace.innerHTML = renderDispatcherHistory();
      wireReadOnlyOpen(".row-action[data-id]", false);
      return;
    }

    if (session.role === "admin" && activeTab === "progress") {
      workspace.innerHTML = renderAdminProgress();
      wireReadOnlyOpen(".row-action[data-id]", false);
      return;
    }

    if (session.role === "admin" && activeTab === "users") {
      workspace.innerHTML = renderUsersPanel();
      wireUsersPanel();
      return;
    }

    const config = TOOLBARS[session.role];
    const tab = config.tabs.find((t) => t.id === activeTab);
    workspace.innerHTML = `
      <div class="panel-head"><h2>${tab.label}</h2></div>
      <div class="data-table-wrap"><div class="empty-hint">Раздел «${tab.label}» пока не реализован в этом прототипе.</div></div>
    `;
  }

  // --- Оператор: очередь вызовов, заполнение карточки ---
  function renderOperatorQueue() {
    const openCount = incidents.filter((c) => c.status === "new" || c.status === "returned").length;

    const rows = incidents
      .map((call, i) => {
        const labels = typeLabels(call);
        const typeCell = labels ? (labels.length === 1 ? labels[0] : `${labels[0]} <span class="cell-muted">+${labels.length - 1}</span>`) : `<span class="cell-muted">—</span>`;
        const addressCell = formatAddress(call) || `<span class="cell-muted">—</span>`;
        const canEdit = call.status === "new" || call.status === "returned";
        const actionBtn = canEdit
          ? `<button type="button" class="row-action" data-id="${call.id}">Открыть</button>`
          : `<button type="button" class="row-action" data-view-id="${call.id}">Просмотр</button>`;

        return `
          <tr style="--i:${i}">
            <td data-label="Время" class="cell-mono">${call.time}</td>
            <td data-label="АОН" class="cell-mono">${call.phone}</td>
            <td data-label="Тип происшествия">${typeCell}</td>
            <td data-label="Адрес">${addressCell}</td>
            <td data-label="Статус">${statusPill(call)}</td>
            <td data-label="">${actionBtn}</td>
          </tr>`;
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>Очередь вызовов</h2>
        <span class="count">Требуют заполнения: ${openCount}</span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Адрес</th><th>Статус</th><th></th></tr>
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
    wireReadOnlyOpen(".row-action[data-view-id]", false, "view-id");
  }

  // --- Диспетчер: карточки на проверке и история решений ---
  function renderDispatcherQueue() {
    const pending = incidents.filter((c) => c.status === "review");
    const rows = pending
      .map((call, i) => {
        const labels = typeLabels(call);
        const typeCell = labels ? labels.join(", ") : `<span class="cell-muted">—</span>`;
        return `
          <tr style="--i:${i}">
            <td data-label="Время" class="cell-mono">${call.time}</td>
            <td data-label="АОН" class="cell-mono">${call.phone}</td>
            <td data-label="Тип происшествия">${typeCell}</td>
            <td data-label="Адрес">${formatAddress(call) || "—"}</td>
            <td data-label=""><button type="button" class="row-action" data-review-id="${call.id}">Проверить</button></td>
          </tr>`;
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>На проверке</h2>
        <span class="count">Ожидают решения: ${pending.length}</span>
      </div>
      <div class="data-table-wrap">
        ${pending.length ? `<table class="data-table"><thead><tr><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Адрес</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty-hint">Пока нет карточек, ожидающих проверки.</div>`}
      </div>`;
  }

  function wireDispatcherQueue() {
    document.querySelectorAll("[data-review-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const call = incidents.find((c) => c.id === btn.dataset.reviewId);
        if (call) openReviewSheet(call, true);
      });
    });
  }

  function renderDispatcherHistory() {
    const done = incidents.filter((c) => c.status === "approved" || c.status === "returned");
    const rows = done
      .map((call, i) => {
        const labels = typeLabels(call);
        return `
          <tr style="--i:${i}">
            <td data-label="Время" class="cell-mono">${call.time}</td>
            <td data-label="АОН" class="cell-mono">${call.phone}</td>
            <td data-label="Тип происшествия">${labels ? labels.join(", ") : "—"}</td>
            <td data-label="Решение">${statusPill(call)}</td>
            <td data-label=""><button type="button" class="row-action" data-id="${call.id}">Просмотр</button></td>
          </tr>`;
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>История проверок</h2>
        <span class="count">Всего решений: ${done.length}</span>
      </div>
      <div class="data-table-wrap">
        ${done.length ? `<table class="data-table"><thead><tr><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Решение</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty-hint">Пока нет проверенных карточек.</div>`}
      </div>`;
  }

  // --- Администратор: наблюдение за прогрессом (без права правки) ---
  function renderAdminProgress() {
    const rows = incidents
      .map((call, i) => {
        const labels = typeLabels(call);
        return `
          <tr style="--i:${i}">
            <td data-label="Время" class="cell-mono">${call.time}</td>
            <td data-label="АОН" class="cell-mono">${call.phone}</td>
            <td data-label="Тип происшествия">${labels ? labels.join(", ") : "<span class=\"cell-muted\">—</span>"}</td>
            <td data-label="Адрес">${formatAddress(call) || "<span class=\"cell-muted\">—</span>"}</td>
            <td data-label="Статус">${statusPill(call)}</td>
            <td data-label="">${call.status !== "new" ? `<button type="button" class="row-action" data-id="${call.id}">Просмотр</button>` : ""}</td>
          </tr>`;
      })
      .join("");

    return `
      <div class="panel-head">
        <h2>Прогресс операторов и диспетчеров</h2>
        <span class="count">Карточек всего: ${incidents.length}</span>
      </div>
      <p class="empty-hint" style="padding:0 0 14px;">Режим наблюдения: администратор видит весь конвейер обработки вызова, но не может редактировать карточки.</p>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>Время</th><th>АОН</th><th>Тип происшествия</th><th>Адрес</th><th>Статус</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderUsersPanel() {
    const rows = users.map((u, i) => {
      const statusCell = u.blocked
        ? `<span class="status-pill status-blocked">Заблокирован</span>`
        : `<span class="status-pill status-done">Активен</span>`;
      const actionLabel = u.blocked ? "Разблокировать" : "Заблокировать";
      return `
        <tr style="--i:${i}">
          <td data-label="ФИО">${u.name}</td>
          <td data-label="Роль" class="cell-muted">${u.role}</td>
          <td data-label="Статус">${statusCell}</td>
          <td data-label=""><button type="button" class="row-action ${u.blocked ? "" : "danger"}" data-name="${u.name}">${actionLabel}</button></td>
        </tr>`;
    }).join("");

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
    document.querySelectorAll('.row-action[data-name]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const user = users.find((u) => u.name === btn.dataset.name);
        if (!user) return;
        user.blocked = !user.blocked;
        showToast(user.blocked ? `${user.name}: доступ заблокирован` : `${user.name}: доступ восстановлен`);
        renderWorkspace();
      });
    });
  }

  // Общий обработчик кнопок "Просмотр" — открывает карточку проверки без
  // права принятия решения (используется историей диспетчера и админом).
  function wireReadOnlyOpen(selector, allowActions, dataKey) {
    const key = dataKey || "id";
    document.querySelectorAll(selector).forEach((btn) => {
      btn.addEventListener("click", () => {
        const call = incidents.find((c) => c.id === btn.dataset[key === "id" ? "id" : "viewId"]);
        if (call) openReviewSheet(call, allowActions);
      });
    });
  }

  // =========================================================
  // Карточка заполнения (Оператор)
  // =========================================================

  const overlay = document.getElementById("incident-sheet");
  const titleEl = document.getElementById("sheet-title");
  const phoneEl = document.getElementById("sheet-phone");
  const timeEl = document.getElementById("sheet-time");
  const phoneAonInput = document.getElementById("sheet-phone-aon");
  const phoneGivenInput = document.getElementById("sheet-phone-given");
  const phoneOnsiteInput = document.getElementById("sheet-phone-onsite");
  const typesField = document.getElementById("field-types");
  const typeSearchInput = document.getElementById("type-search");
  const typeTilesEl = document.getElementById("type-tiles");
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
  const timerEl = document.getElementById("sheet-timer");
  const timerValueEl = document.getElementById("sheet-timer-value");
  const telephonyStatusBtn = document.getElementById("telephony-status");
  const telephonyStatusLabel = document.getElementById("telephony-status-label");

  let timerInterval = null;
  let secondsElapsed = 0;
  let currentCall = null;
  let selectedTypes = [];
  let manualServices = [];
  let removedAutoServices = [];
  let currentFlags = { injured: false, notOnSite: false, ambulanceRefused: false, blocked: false };
  let telephonyResetTimer = null;

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

    document.getElementById("btn-no-contact").addEventListener("click", () => finishAsEmpty("no_contact"));
    document.getElementById("btn-call-failed").addEventListener("click", () => finishAsEmpty("call_failed"));

    if (telephonyStatusBtn) {
      telephonyStatusBtn.addEventListener("click", () => {
        if (telephonyStatusBtn.classList.contains("is-unavailable")) return;
        setTelephonyStatus(telephonyStatusBtn.classList.contains("is-available") ? "unavailable" : "available");
      });
    }

    document.getElementById("sheet-cancel").addEventListener("click", closeSheet);
    document.getElementById("sheet-submit").addEventListener("click", submitCard);
  }

  function finishAsEmpty(reason) {
    const label = reason === "no_contact" ? "Нет контакта" : "Срыв звонка";
    if (!confirm(`Сохранить карточку со статусом «${label}» без заполнения остальных полей?`)) return;
    currentCall.status = "empty";
    currentCall.emptyReason = reason;
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
  }

  function currentAutoServices() {
    const set = [];
    selectedTypes.forEach((id) => {
      const type = INCIDENT_TYPES.find((t) => t.id === id);
      type.services.forEach((s) => {
        if (set.indexOf(s) === -1) set.push(s);
      });
    });
    return set;
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
    currentCall.services = finalServices;
    currentCall.fillSeconds = secondsElapsed;
    currentCall.status = "review";
    currentCall.dispatcherComment = null;

    showToast(`Карточка отправлена диспетчеру · заполнена за ${secondsElapsed} с`);
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

    phoneAonInput.value = call.phone;
    phoneEl.textContent = call.phone;
    timeEl.textContent = call.time;

    if (call.status === "returned" && call.dispatcherComment) {
      showToast(`Возвращена диспетчером: ${call.dispatcherComment}`);
    }

    startTimer();

    overlay.hidden = false;
    requestAnimationFrame(() => overlay.classList.add("is-open"));
    overlay.setAttribute("aria-hidden", "false");
    typeSearchInput.focus();
  }

  function closeSheet() {
    overlay.classList.remove("is-open");
    overlay.setAttribute("aria-hidden", "true");
    stopTimer();
    clearTimeout(telephonyResetTimer);
    telephonyResetTimer = setTimeout(() => setTelephonyStatus("available"), 10000);
    setTimeout(() => {
      overlay.hidden = true;
    }, 320);
  }

  // =========================================================
  // Карточка проверки (Диспетчер / наблюдение Администратора)
  // =========================================================

  const reviewOverlay = document.getElementById("review-sheet");
  let currentReviewCall = null;

  function initReviewSheet() {
    document.getElementById("review-close").addEventListener("click", closeReviewSheet);
    reviewOverlay.addEventListener("click", (e) => {
      if (e.target === reviewOverlay) closeReviewSheet();
    });
    document.getElementById("review-callback-btn").addEventListener("click", () => {
      showToast(`Звонок заявителю: ${currentReviewCall.phone}`);
    });
    document.getElementById("review-approve").addEventListener("click", () => {
      currentReviewCall.status = "approved";
      currentReviewCall.dispatcherComment = document.getElementById("review-comment").value.trim() || null;
      showToast("Карточка утверждена");
      saveIncidents();
      closeReviewSheet();
      renderWorkspace();
    });
    document.getElementById("review-return").addEventListener("click", () => {
      const comment = document.getElementById("review-comment").value.trim();
      if (!comment) {
        document.getElementById("review-comment").focus();
        showToast("Укажите, что нужно исправить");
        return;
      }
      currentReviewCall.status = "returned";
      currentReviewCall.dispatcherComment = comment;
      showToast("Карточка возвращена оператору");
      saveIncidents();
      closeReviewSheet();
      renderWorkspace();
    });
  }

  function openReviewSheet(call, allowActions) {
    currentReviewCall = call;
    document.getElementById("review-title").textContent = "Карточка происшествия";
    document.getElementById("review-phone").textContent = call.phone;
    document.getElementById("review-callback-btn").hidden = call.emptyReason ? true : false;

    const labels = typeLabels(call);
    document.getElementById("review-types").textContent = labels ? labels.join(", ") : "—";
    document.getElementById("review-address").textContent = formatAddress(call) || "—";
    document.getElementById("review-caller").textContent = call.caller || "—";
    document.getElementById("review-caller-status").textContent = call.callerStatus || "—";
    document.getElementById("review-description").textContent = call.description || "—";

    const flagLabels = { injured: "Пострадавшие", notOnSite: "Нет на месте", ambulanceRefused: "Отказ от скорой", blocked: "Заблокированные" };
    const activeFlags = Object.keys(flagLabels).filter((k) => call.flags && call.flags[k]);
    if (call.foreignLanguage) activeFlags.push("__foreign__");
    document.getElementById("review-flags").innerHTML = activeFlags.length
      ? activeFlags.map((k) => `<span class="review-flag">${k === "__foreign__" ? "Иностранный язык" : flagLabels[k]}${k === "injured" && call.injuredCount ? ": " + call.injuredCount : ""}</span>`).join("")
      : `<span class="cell-muted">Отметок нет</span>`;

    document.getElementById("review-services").innerHTML = (call.services || [])
      .map((s) => `<span class="service-chip">${iconHtml("call", 12)}${s}</span>`)
      .join("") || `<span class="cell-muted">Службы не назначены</span>`;

    const commentInput = document.getElementById("review-comment");
    commentInput.value = call.dispatcherComment || "";

    const actions = document.getElementById("review-actions");
    actions.hidden = !allowActions;

    reviewOverlay.hidden = false;
    requestAnimationFrame(() => reviewOverlay.classList.add("is-open"));
    reviewOverlay.setAttribute("aria-hidden", "false");
  }

  function closeReviewSheet() {
    reviewOverlay.classList.remove("is-open");
    reviewOverlay.setAttribute("aria-hidden", "true");
    setTimeout(() => {
      reviewOverlay.hidden = true;
    }, 320);
  }

  // --- тост-уведомление ---
  let toastTimer = null;
  function showToast(text) {
    const toast = document.getElementById("toast");
    document.getElementById("toast-text").textContent = text;
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2400);
  }

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

  document.getElementById("logout-btn").addEventListener("click", () => {
    localStorage.removeItem("ddsSession");
    window.location.href = "index.html";
  });
})();
