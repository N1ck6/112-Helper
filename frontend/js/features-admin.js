(function () {
  window.DDS_TABS = window.DDS_TABS || [];
  const cfg = window.APP_CONFIG || {};
  const TEL = String(cfg.TELEPHONY_API_URL || "telephony").replace(/\/$/, "");

  async function telGet(path) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    try {
      const res = await fetch(TEL + path, { signal: ctrl.signal });
      if (!res.ok) throw new Error("HTTP " + res.status);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function badge(ok, okText, badText) {
    return `<span class="status-pill ${ok ? "status-done" : "status-blocked"}">${ok ? okText : badText}</span>`;
  }

  const startedAt = Date.now();

  function fmtBytes(n) {
    if (n < 1024) return n + " Б";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " КБ";
    return (n / 1024 / 1024).toFixed(2) + " МБ";
  }

  function fmtDuration(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? h + " ч " + m + " мин" : m + " мин " + (s % 60) + " с";
  }

  function storageBytes() {
    let total = 0;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf("dds") === 0) total += (k.length + (localStorage.getItem(k) || "").length) * 2;
    }
    return total;
  }

  function cardBuckets(ctx) {
    const b = { new: 0, pending: 0, active: 0, declined: 0, done: 0, refused: 0, empty: 0 };
    ctx.getIncidents().forEach((c) => {
      if (c.status === "new") b.new++;
      else if (c.status === "empty") b.empty++;
      else if (c.status === "review") b[ctx.ddsState(c).phase] = (b[ctx.ddsState(c).phase] || 0) + 1;
    });
    return b;
  }

  function sessionsList() {
    return window.DDS_API.activeSessions();
  }

  function localHtml(ctx) {
    const cards = ctx.getIncidents();
    const b = cardBuckets(ctx);
    const log = window.DDS_API.readLog();
    const sessions = sessionsList();
    const users = ctx.getUsers();
    const byRole = {};
    sessions.forEach((x) => (byRole[x.role] = (byRole[x.role] || 0) + 1));
    const roleHint = Object.keys(byRole).map((r) => ctx.ROLE_LABELS[r] + ": " + byRole[r]).join(", ") || "нет активных";
    const lastEvent = log.length ? new Date(log[log.length - 1].t).toLocaleString("ru-RU") : "—";
    const scenarios = window.DDS_DATA.getScenarios();
    const bar = (label, n) => `<div class="history-row"><b>${label}</b><span class="cell-mono">${n}</span></div>`;

    const sessRows = sessions
      .slice()
      .sort((x, y) => y.lastSeen - x.lastSeen)
      .map((x) => `<tr>
        <td data-label="Пользователь">${ctx.esc(x.user || "—")}</td>
        <td data-label="Роль">${ctx.esc(ctx.ROLE_LABELS[x.role] || x.role)}</td>
        <td data-label="Место" class="cell-mono">${ctx.esc(x.ws || "—")}</td>
        <td data-label="Вход" class="cell-mono">${new Date(x.since).toLocaleTimeString("ru-RU")}</td>
        <td data-label="Активность" class="cell-mono">${Math.max(0, Math.round((Date.now() - x.lastSeen) / 1000))} с назад</td>
      </tr>`)
      .join("");

    return `
      <div class="stat-grid">
        <div class="stat-card accent"><span class="stat-label">Карточек в системе</span><strong class="stat-value">${cards.length}</strong><span class="stat-hint">в работе: ${b.pending + b.active} · завершено: ${b.done + b.declined + b.refused + b.empty}</span></div>
        <div class="stat-card"><span class="stat-label">Записей в журнале</span><strong class="stat-value">${log.length}</strong><span class="stat-hint">последняя: ${lastEvent}</span></div>
        <div class="stat-card accent"><span class="stat-label">Активных сессий</span><strong class="stat-value">${sessions.length}</strong><span class="stat-hint">${ctx.esc(roleHint)}</span></div>
        <div class="stat-card"><span class="stat-label">Пользователей</span><strong class="stat-value">${users.length}</strong><span class="stat-hint">заблокировано: ${users.filter((u) => u.blocked).length}</span></div>
        <div class="stat-card"><span class="stat-label">Сценариев / кластеров</span><strong class="stat-value">${scenarios.length} / ${window.DDS_DATA.getClusters().length}</strong><span class="stat-hint">утверждено: ${scenarios.filter((x) => x.approved).length}</span></div>
        <div class="stat-card"><span class="stat-label">Хранилище</span><strong class="stat-value">${fmtBytes(storageBytes())}</strong><span class="stat-hint">${window.DDS_API.isOnline() === true ? "Backend + кэш браузера" : "localStorage браузера"}</span></div>
      </div>
      <div class="two-col">
        <section class="info-block"><h3>Карточки по статусам</h3>
          ${bar("Новые вызовы (не открыты)", b.new)}
          ${bar("Ждут приёма диспетчером", b.pending)}
          ${bar("Приняты, реагирование идёт", b.active)}
          ${bar("Работы завершены", b.done)}
          ${bar("Не приняты", b.declined)}
          ${bar("Отказ от выполнения работ", b.refused)}
          ${bar("Нет контакта / срыв звонка", b.empty)}
        </section>
        <section class="info-block"><h3>Активные сессии</h3>
          ${sessRows ? `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Пользователь</th><th>Роль</th><th>Место</th><th>Вход</th><th>Активность</th></tr></thead><tbody>${sessRows}</tbody></table></div>` : '<p class="sys-note">Активных сессий нет.</p>'}
          <p class="sys-note">Сессия считается активной, если от неё был сигнал за последние 45 с. Работа этого экрана: ${fmtDuration(Date.now() - startedAt)}.</p>
        </section>
      </div>`;
  }

  function systemPanel(ctx) {
    return `
      <div class="panel-head"><h2>Состояние системы</h2><button type="button" class="btn-card" id="sys-refresh">Обновить</button></div>
      <div id="sys-local">${localHtml(ctx)}</div>
      <div class="panel-head" style="margin-top:8px;"><h2>Компоненты</h2></div>
      <div class="stat-grid">
        <div class="stat-card"><span class="stat-label">Frontend</span><strong class="stat-value">работает</strong><span class="stat-hint">сессия: ${ctx.esc(ctx.session.fullName)}</span></div>
        <div class="stat-card"><span class="stat-label">Backend</span><strong class="stat-value" id="sys-backend">проверка…</strong><span class="stat-hint">${ctx.esc(window.DDS_API.base || "API_BASE_URL не задан")}</span></div>
        <div class="stat-card"><span class="stat-label">Телефония</span><strong class="stat-value" id="sys-tel">проверка…</strong><span class="stat-hint">${ctx.esc(TEL)}</span></div>
        <div class="stat-card"><span class="stat-label">ML-собеседники</span><strong class="stat-value" id="sys-ml">проверка…</strong><span class="stat-hint">по /health телефонии</span></div>
        <div class="stat-card"><span class="stat-label">Софтфоны</span><strong class="stat-value" id="sys-reg">—</strong><span class="stat-hint">зарегистрировано из 20</span></div>
      </div>
      <section class="info-block" style="margin-top:16px;"><h3>Ответ /health телефонии</h3><pre class="json-box" id="sys-health">—</pre></section>`;
  }

  let sysTimer = null;

  function wireSystem(root, ctx) {
    async function refresh() {
      const set = (id, text) => {
        const n = root.querySelector(id);
        if (n) n.textContent = text;
      };
      window.DDS_API.probe(true).then((ok) => set("#sys-backend", ok ? "доступен" : "не подключён"));
      try {
        const [health, eps] = await Promise.all([telGet("/health"), telGet("/endpoints").catch(() => [])]);
        set("#sys-tel", "доступна");
        set("#sys-ml", health.ml === false ? "недоступны" : "работают");
        set("#sys-reg", (Array.isArray(eps) ? eps.filter((e) => e.registered).length : 0) + " / 20");
        set("#sys-health", JSON.stringify(health, null, 2));
      } catch (e) {
        set("#sys-tel", "недоступна");
        set("#sys-ml", "—");
        set("#sys-health", "Телефония не отвечает: " + e.message);
      }
    }
    root.querySelector("#sys-refresh").addEventListener("click", () => {
      root.querySelector("#sys-local").innerHTML = localHtml(ctx);
      refresh();
    });
    clearInterval(sysTimer);
    sysTimer = setInterval(() => {
      const box = document.getElementById("sys-local");
      if (!box) {
        clearInterval(sysTimer);
        return;
      }
      box.innerHTML = localHtml(ctx);
    }, 5000);
    refresh();
  }

  function logsPanel(ctx) {
    const log = window.DDS_API.readLog().slice().reverse();
    const types = Array.from(new Set(log.map((e) => e.type)));
    const rows = log
      .map((e) => `<tr data-type="${ctx.esc(e.type)}">
        <td data-label="Время" class="cell-mono">${new Date(e.t).toLocaleString("ru-RU")}</td>
        <td data-label="Роль">${ctx.esc(ctx.ROLE_LABELS[e.role] || e.role || "—")}</td>
        <td data-label="Пользователь">${ctx.esc(e.user || "—")}</td>
        <td data-label="Место" class="cell-mono">${ctx.esc(e.ws || "—")}</td>
        <td data-label="Событие" class="cell-mono">${ctx.esc(e.type)}</td>
        <td data-label="Описание">${ctx.esc(e.text)}</td>
      </tr>`)
      .join("");
    return `
      <div class="panel-head"><h2>Журналы</h2><span class="count">Записей: ${log.length}</span></div>
      <div class="form-field" style="max-width:280px; margin-bottom:12px;"><label for="log-filter">Тип события</label>
        <select id="log-filter"><option value="">Все</option>${types.map((t) => `<option>${ctx.esc(t)}</option>`).join("")}</select></div>
      <div class="data-table-wrap">${rows ? `<table class="data-table"><thead><tr><th>Время</th><th>Роль</th><th>Пользователь</th><th>Место</th><th>Событие</th><th>Описание</th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty-hint">Журнал пуст.</div>'}</div>`;
  }

  function wireLogs(root) {
    const filter = root.querySelector("#log-filter");
    filter.addEventListener("change", () => {
      root.querySelectorAll("tbody tr").forEach((tr) => {
        tr.hidden = !!filter.value && tr.dataset.type !== filter.value;
      });
    });
  }

  function telephonyPanel(ctx) {
    return `
      <div class="panel-head"><h2>Настройки IP-телефонии</h2><button type="button" class="btn-card" id="tel-refresh">Обновить</button></div>
      <div class="two-col">
        <section class="info-block"><h3>Подключение</h3>
          <p><b>API телефонии:</b> <span class="cell-mono">${ctx.esc(TEL)}</span></p>
          <p><b>SIP-сервер:</b> <span class="cell-mono">${ctx.esc(location.hostname || "<IP стенда>")}:5063 (UDP)</span></p>
          <p><b>Аккаунты рабочих мест:</b> <span class="cell-mono">ws01 … ws20</span></p>
          <p class="stat-hint">Параметры SIP меняются на стороне телефонии (telephony/API.md); здесь показывается текущее состояние.</p>
        </section>
        <section class="info-block"><h3>Справочник номеров</h3><div id="tel-numbers" class="stat-hint">загрузка…</div></section>
      </div>
      <div class="panel-head" style="margin-top:20px;"><h2>Рабочие места</h2></div>
      <div class="data-table-wrap" id="tel-endpoints"><div class="empty-hint">загрузка…</div></div>`;
  }

  function wireTelephony(root, ctx) {
    async function refresh() {
      const eps = root.querySelector("#tel-endpoints");
      const nums = root.querySelector("#tel-numbers");
      try {
        const [list, numbers] = await Promise.all([telGet("/endpoints"), telGet("/numbers").catch(() => [])]);
        const assigned = window.DDS_DATA.getAssignments();
        eps.innerHTML = `<table class="data-table"><thead><tr><th>Место</th><th>Регистрация</th><th>Назначение</th></tr></thead><tbody>${window.DDS_DATA.WORKSTATIONS.map((ws) => {
          const ep = (Array.isArray(list) ? list : []).find((e) => e.endpoint === ws);
          const a = assigned[ws];
          return `<tr><td data-label="Место" class="cell-mono">${ws}</td><td data-label="Регистрация">${badge(!!(ep && ep.registered), "зарегистрирован", "не подключён")}</td><td data-label="Назначение">${a && a.role ? ctx.esc(ctx.ROLE_LABELS[a.role]) : '<span class="cell-muted">—</span>'}</td></tr>`;
        }).join("")}</tbody></table>`;
        nums.innerHTML = Array.isArray(numbers) && numbers.length
          ? `<ul class="tips-list">${numbers.map((n) => `<li><span class="cell-mono">${ctx.esc(n.number)}</span> — ${ctx.esc(n.title)}${n.name ? " (" + ctx.esc(n.name) + ")" : ""}</li>`).join("")}</ul>`
          : "Справочник пуст.";
      } catch (e) {
        eps.innerHTML = `<div class="empty-hint">Телефония недоступна (${ctx.esc(e.message)}). Проверьте адрес ${ctx.esc(TEL)} и запущен ли стенд.</div>`;
        nums.textContent = "—";
      }
    }
    root.querySelector("#tel-refresh").addEventListener("click", refresh);
    refresh();
  }

  window.DDS_TABS.push({ roles: ["admin"], id: "system", label: "Состояние системы", order: 30, render: systemPanel, wire: wireSystem });
  window.DDS_TABS.push({ roles: ["admin"], id: "logs", label: "Журналы", order: 40, render: logsPanel, wire: wireLogs });
  window.DDS_TABS.push({ roles: ["admin"], id: "telephony", label: "IP-телефония", order: 50, render: telephonyPanel, wire: wireTelephony });
})();
