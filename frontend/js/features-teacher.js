(function () {
  const D = window.DDS_DATA;
  const M = window.DDS_METRICS;
  window.DDS_TABS = window.DDS_TABS || [];

  const openClusters = new Set(["fire"]);
  let editingId = null;

  const TEMPLATES = {
    fire: [
      { title: "Горит гараж во дворе", types: ["fire_trash"], address: "Москва, ул. Ясный проезд, 3", name: "Романов Олег", opening: "Здравствуйте, во дворе горит гараж, огонь перекидывается на машины!", description: "Горит металлический гараж, рядом припаркованы автомобили" },
      { title: "Дым из окна на 5 этаже", types: ["fire_flat"], address: "Москва, ул. Тверская, 20, кв. 41", name: "Мельникова Вера", opening: "Алло, из окна соседей на пятом этаже валит дым!", description: "Из окна пятого этажа идёт чёрный дым, хозяев не слышно" },
    ],
    road: [
      { title: "Столкновение на перекрёстке", types: ["dtp"], address: "Москва, Профсоюзная ул., 45", name: "Егоров Максим", opening: "Здравствуйте, на перекрёстке столкнулись три машины!", description: "Три автомобиля столкнулись на перекрёстке, движение встало" },
    ],
    utility: [
      { title: "Запах газа в подъезде", types: ["gas_smell"], address: "Москва, ул. Профсоюзная, 45", name: "Соколова Мария", opening: "Здравствуйте, у нас в подъезде сильно пахнет газом!", description: "В подъезде сильный запах газа, жильцы выходят на улицу" },
      { title: "Прорыв горячей воды во дворе", types: ["pipe_burst"], address: "Москва, ул. Молостовых, 5", name: "Ершов Павел", opening: "Алло, во дворе из земли бьёт кипяток!", description: "Из-под земли бьёт горячая вода, парит, лужа растёт" },
    ],
    medical: [
      { title: "Потеряла сознание на улице", types: ["medical"], address: "Москва, Ленинский проспект, 22", name: "Захаров Николай", opening: "Здравствуйте, на улице женщина упала и не встаёт!", description: "Женщина лет пятидесяти лежит на тротуаре, глаза закрыты" },
    ],
    order: [
      { title: "Мужчина ломится в квартиру", types: ["suspicious"], address: "Москва, ул. Тверская, 12, кв. 9", name: "Крылова Надежда", opening: "Помогите, какой-то мужчина ломится к соседям!", description: "Неизвестный мужчина бьёт в дверь соседней квартиры и кричит" },
    ],
    other: [
      { title: "Консультация по вызову", types: ["consultation"], address: "Москва, Шоссейная ул., 62", name: "Пахомов Лев", opening: "Здравствуйте, подскажите, куда звонить по протечке с крыши?", description: "Заявитель уточняет, в какую службу обращаться по протечке кровли" },
    ],
  };

  function newId(prefix) {
    return prefix + "_" + Date.now() + "_" + Math.floor(Math.random() * 1000);
  }

  function makeScenario(f, generated) {
    const phone = "+7 (9" + (10 + Math.floor(Math.random() * 89)) + ") " + (100 + Math.floor(Math.random() * 899)) + "-" + (10 + Math.floor(Math.random() * 89)) + "-" + (10 + Math.floor(Math.random() * 89));
    return {
      id: newId("custom"),
      clusterId: f.clusterId || "other",
      title: f.title,
      difficulty: f.difficulty || "Средняя",
      types: f.types,
      approved: false,
      generated: !!generated,
      caller: { name: f.name, status: "Очевидец", phone: phone },
      address: f.address,
      description: f.description,
      injured: false,
      opening: f.opening,
      answers: [
        { keys: "адрес|где|улиц|дом", text: f.address + "." },
        { keys: "имя|фамили|как вас|представ", text: f.name + "." },
        { keys: "что случил|что происход|расскаж", text: f.description + "." },
        { keys: "пострадав|ранен|люди", text: "Пострадавших я не видел(а)." },
        { keys: "телефон|номер", text: "Звоню с этого номера." },
      ],
    };
  }

  function typeName(ctx, id) {
    return (ctx.INCIDENT_TYPES.find((t) => t.id === id) || { label: id }).label;
  }

  function scenarioRow(ctx, s) {
    const custom = s.id.indexOf("custom_") === 0;
    return `<tr data-scenario="${s.id}">
      <td data-label="Сценарий"><b>${ctx.esc(s.title)}</b><br><span class="cell-muted">${ctx.esc(s.address)}</span></td>
      <td data-label="Тип">${ctx.esc(s.types.map((id) => typeName(ctx, id)).join(", "))}</td>
      <td data-label="Сложность">${ctx.esc(s.difficulty)}</td>
      <td data-label="Статус"><span class="status-pill ${s.approved ? "status-done" : "status-new"}">${s.approved ? "Утверждён" : "Ждёт подтверждения"}</span></td>
      <td data-label="">
        <button type="button" class="row-action" data-row-open data-open-scenario="${s.id}">Открыть</button>
        <button type="button" class="row-action" data-approve="${s.id}">${s.approved ? "Снять" : "Утвердить"}</button>
        ${custom ? `<button type="button" class="row-action danger" data-delete="${s.id}">Удалить</button>` : ""}
      </td>
    </tr>`;
  }

  function clusterBlock(ctx, c) {
    const list = D.scenariosOfCluster(c.id);
    const approved = list.filter((s) => s.approved).length;
    const custom = D.readCustomClusterIds().indexOf(c.id) !== -1;
    const table = list.length
      ? `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Сценарий</th><th>Тип</th><th>Сложность</th><th>Статус</th><th></th></tr></thead><tbody>${list.map((s) => scenarioRow(ctx, s)).join("")}</tbody></table></div>`
      : `<div class="empty-hint">В кластере пока нет сценариев.</div>`;
    return `<details class="cluster" data-cluster="${c.id}" ${openClusters.has(c.id) ? "open" : ""}>
      <summary>
        <span class="cluster-title">${ctx.esc(c.title)}</span>
        <span class="cluster-type">${ctx.esc(c.type)}</span>
        <span class="cluster-count">утверждено ${approved} из ${list.length}</span>
        <span class="cluster-actions">
          <button type="button" class="row-action" data-cluster-approve="${c.id}" ${list.length ? "" : "disabled"}>Утвердить все</button>
          <button type="button" class="row-action" data-cluster-revoke="${c.id}" ${approved ? "" : "disabled"}>Снять все</button>
          ${custom && !list.length ? `<button type="button" class="row-action danger" data-cluster-delete="${c.id}">Удалить кластер</button>` : ""}
        </span>
      </summary>
      ${c.note ? `<div class="cluster-note">${ctx.esc(c.note)}</div>` : ""}
      ${table}
    </details>`;
  }

  function scenariosPanel(ctx) {
    const clusters = D.getClusters();
    const total = D.getScenarios().length;
    const typeOptions = ctx.INCIDENT_TYPES.filter((t) => t.services.length)
      .map((t) => `<option value="${t.id}">${ctx.esc(t.label)}</option>`)
      .join("");
    const clusterOptions = clusters.map((c) => `<option value="${c.id}">${ctx.esc(c.title)}</option>`).join("");
    return `
      <div class="panel-head"><h2>Сценарии по кластерам</h2><span class="count">Кластеров: ${clusters.length} · сценариев: ${total}</span></div>
      <p class="empty-hint" style="padding:0 0 12px;">Кластер — набор сценариев одного типа ЧС. На рабочее место назначается кластер целиком: оператор или диспетчер проходит его сценарии по очереди. Нажмите на строку, чтобы открыть сценарий.</p>
      ${clusters.map((c) => clusterBlock(ctx, c)).join("")}

      <section class="info-block" style="margin-top:16px;">
        <h3>Новый кластер</h3>
        <form id="cluster-form" class="inline-form">
          <div class="form-field"><label for="cl-title">Название</label><input id="cl-title" required /></div>
          <div class="form-field"><label for="cl-type">Тип ЧС</label><input id="cl-type" placeholder="Например: Наводнение" required /></div>
          <button type="submit" class="btn-card">Создать кластер</button>
        </form>
      </section>

      <section class="info-block" style="margin-top:12px;">
        <h3>Новый сценарий</h3>
        <form id="scenario-form" class="scenario-form">
          <div class="form-field"><label for="sc-title">Название</label><input id="sc-title" required /></div>
          <div class="form-field"><label for="sc-cluster">Кластер</label><select id="sc-cluster">${clusterOptions}</select></div>
          <div class="form-field"><label for="sc-type">Тип происшествия</label><select id="sc-type">${typeOptions}</select></div>
          <div class="form-field"><label for="sc-diff">Сложность</label><select id="sc-diff"><option>Лёгкая</option><option selected>Средняя</option><option>Сложная</option></select></div>
          <div class="form-field"><label for="sc-name">ФИО заявителя</label><input id="sc-name" required /></div>
          <div class="form-field"><label for="sc-address">Адрес</label><input id="sc-address" required /></div>
          <div class="form-field span-2"><label for="sc-opening">Первая реплика заявителя</label><input id="sc-opening" required /></div>
          <div class="form-field span-2"><label for="sc-desc">Что произошло (ответ заявителя)</label><input id="sc-desc" required /></div>
          <div class="form-row-actions"><button type="submit" class="btn-card">Создать черновик</button><button type="button" class="row-action" id="sc-generate">Сгенерировать ИИ-черновик в выбранный кластер</button></div>
        </form>
      </section>`;
  }

  function wireScenarios(root, ctx) {
    root.querySelectorAll("details.cluster").forEach((d) => {
      d.addEventListener("toggle", () => {
        if (d.open) openClusters.add(d.dataset.cluster);
        else openClusters.delete(d.dataset.cluster);
      });
    });
    root.querySelectorAll("summary button").forEach((b) => b.addEventListener("click", (e) => e.stopPropagation()));
    root.querySelectorAll("summary .cluster-actions").forEach((box) => {
      box.addEventListener("click", (e) => e.preventDefault());
    });

    root.querySelectorAll("[data-open-scenario]").forEach((btn) => btn.addEventListener("click", () => openScenario(ctx, btn.dataset.openScenario)));
    root.querySelectorAll("[data-approve]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const s = D.getScenarios().find((x) => x.id === btn.dataset.approve);
        D.patchScenario(s.id, { approved: !s.approved });
        window.DDS_API.log("scenario_approve", `${s.title}: ${!s.approved ? "утверждён" : "снят с утверждения"}`);
        ctx.renderWorkspace();
      });
    });
    root.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", () => {
        D.deleteCustomScenario(btn.dataset.delete);
        window.DDS_API.log("scenario_delete", btn.dataset.delete);
        ctx.renderWorkspace();
      });
    });
    root.querySelectorAll("[data-cluster-approve],[data-cluster-revoke]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.clusterApprove || btn.dataset.clusterRevoke;
        const approve = !!btn.dataset.clusterApprove;
        D.scenariosOfCluster(id).forEach((s) => D.patchScenario(s.id, { approved: approve }));
        window.DDS_API.log("cluster_approve", `${id}: ${approve ? "утверждён целиком" : "снят целиком"}`);
        ctx.showToast(approve ? "Кластер утверждён" : "Утверждение снято");
        ctx.renderWorkspace();
      });
    });
    root.querySelectorAll("[data-cluster-delete]").forEach((btn) => {
      btn.addEventListener("click", () => {
        D.deleteCluster(btn.dataset.clusterDelete);
        ctx.renderWorkspace();
      });
    });

    root.querySelector("#cluster-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const c = { id: newId("cluster"), title: root.querySelector("#cl-title").value.trim(), type: root.querySelector("#cl-type").value.trim(), note: "Создан преподавателем" };
      D.saveCluster(c);
      openClusters.add(c.id);
      window.DDS_API.log("cluster_create", c.title);
      ctx.showToast("Кластер создан");
      ctx.renderWorkspace();
    });

    root.querySelector("#scenario-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const g = (id) => root.querySelector(id).value.trim();
      const sc = makeScenario({ title: g("#sc-title"), clusterId: g("#sc-cluster"), types: [g("#sc-type")], difficulty: g("#sc-diff"), name: g("#sc-name"), address: g("#sc-address"), opening: g("#sc-opening"), description: g("#sc-desc") }, false);
      D.saveCustomScenario(sc);
      openClusters.add(sc.clusterId);
      window.DDS_API.log("scenario_create", sc.title);
      ctx.showToast("Черновик сценария создан — утвердите его в списке");
      ctx.renderWorkspace();
    });

    root.querySelector("#sc-generate").addEventListener("click", () => {
      const clusterId = root.querySelector("#sc-cluster").value;
      const pool = TEMPLATES[clusterId] || TEMPLATES.other;
      const t = pool[Math.floor(Math.random() * pool.length)];
      const sc = makeScenario(Object.assign({ clusterId: clusterId }, t), true);
      D.saveCustomScenario(sc);
      openClusters.add(clusterId);
      window.DDS_API.log("scenario_generate", sc.title);
      ctx.showToast("ИИ-черновик создан — проверьте и утвердите");
      ctx.renderWorkspace();
    });
  }

  // ---------- окно сценария ----------
  const $ = (id) => document.getElementById(id);
  let scenarioCtx = null;

  function closeScenario() {
    const ov = $("scenario-sheet");
    ov.classList.remove("is-open");
    ov.setAttribute("aria-hidden", "true");
    editingId = null;
    setTimeout(() => {
      if (!ov.classList.contains("is-open")) ov.hidden = true;
    }, 320);
  }

  function openScenario(ctx, id) {
    const s = D.getScenarios().find((x) => x.id === id);
    if (!s) return;
    scenarioCtx = ctx;
    editingId = id;
    const custom = s.id.indexOf("custom_") === 0;
    const clusters = D.getClusters();
    const opt = (v, label, cur) => `<option value="${ctx.esc(v)}" ${cur === v ? "selected" : ""}>${ctx.esc(label)}</option>`;

    $("scenario-title").textContent = s.title;
    $("scenario-sub").textContent = (D.getCluster(s.clusterId) || { title: "Без кластера" }).title + " · " + (s.approved ? "утверждён" : "ждёт подтверждения");

    $("scenario-body").innerHTML = `
      <div class="scenario-detail">
        <div class="form-field span-2"><label for="sd-title">Название</label><input id="sd-title" value="${ctx.esc(s.title)}" /></div>
        <div class="form-field"><label for="sd-cluster">Кластер</label><select id="sd-cluster">${clusters.map((c) => opt(c.id, c.title, s.clusterId)).join("")}</select></div>
        <div class="form-field"><label for="sd-diff">Сложность</label><select id="sd-diff">${["Лёгкая", "Средняя", "Сложная"].map((x) => opt(x, x, s.difficulty)).join("")}</select></div>
        <div class="form-field span-2"><label>Тип происшествия</label><input value="${ctx.esc(s.types.map((t) => typeName(ctx, t)).join(", "))}" readonly /></div>
        <div class="form-field"><label for="sd-name">Заявитель</label><input id="sd-name" value="${ctx.esc(s.caller.name)}" /></div>
        <div class="form-field"><label for="sd-phone">Телефон заявителя</label><input id="sd-phone" value="${ctx.esc(s.caller.phone)}" /></div>
        <div class="form-field span-2"><label for="sd-address">Адрес</label><input id="sd-address" value="${ctx.esc(s.address)}" /></div>
        <div class="form-field span-2"><label for="sd-opening">Первая реплика заявителя</label><input id="sd-opening" value="${ctx.esc(s.opening)}" /></div>
        <div class="form-field span-2"><label for="sd-desc">Что произошло</label><textarea id="sd-desc" style="min-height:54px;">${ctx.esc(s.description)}</textarea></div>
        <div class="form-field span-2"><label>Ответы заявителя на вопросы оператора (по ключевым словам)</label>
          <div class="answers-list">${(s.answers || []).map((a) => `<div><b>${ctx.esc(a.keys.replace(/\|/g, ", "))}</b> → ${ctx.esc(a.text)}</div>`).join("")}</div></div>
      </div>`;

    $("scenario-foot").innerHTML = `
      ${custom ? `<button type="button" class="btn-decline" id="sd-delete">Удалить</button>` : ""}
      <button type="button" class="btn-decline" id="sd-toggle">${s.approved ? "Снять с утверждения" : "Утвердить"}</button>
      <button type="button" class="btn-primary" id="sd-save">Сохранить</button>`;

    $("sd-save").addEventListener("click", () => {
      const patch = {
        title: $("sd-title").value.trim() || s.title,
        clusterId: $("sd-cluster").value,
        difficulty: $("sd-diff").value,
        caller: Object.assign({}, s.caller, { name: $("sd-name").value.trim() || s.caller.name, phone: $("sd-phone").value.trim() || s.caller.phone }),
        address: $("sd-address").value.trim() || s.address,
        opening: $("sd-opening").value.trim() || s.opening,
        description: $("sd-desc").value.trim() || s.description,
      };
      D.patchScenario(s.id, patch);
      openClusters.add(patch.clusterId);
      window.DDS_API.log("scenario_edit", patch.title);
      ctx.showToast("Сценарий сохранён");
      closeScenario();
      ctx.renderWorkspace();
    });
    $("sd-toggle").addEventListener("click", () => {
      D.patchScenario(s.id, { approved: !s.approved });
      window.DDS_API.log("scenario_approve", `${s.title}: ${!s.approved ? "утверждён" : "снят с утверждения"}`);
      closeScenario();
      ctx.renderWorkspace();
    });
    const del = $("sd-delete");
    if (del) {
      del.addEventListener("click", () => {
        D.deleteCustomScenario(s.id);
        window.DDS_API.log("scenario_delete", s.id);
        closeScenario();
        ctx.renderWorkspace();
      });
    }

    const ov = $("scenario-sheet");
    ov.hidden = false;
    requestAnimationFrame(() => ov.classList.add("is-open"));
    ov.setAttribute("aria-hidden", "false");
  }

  document.addEventListener("DOMContentLoaded", () => {});
  (function bindClose() {
    const ov = document.getElementById("scenario-sheet");
    if (!ov) return;
    document.getElementById("scenario-close").addEventListener("click", closeScenario);
    ov.addEventListener("click", (e) => {
      if (e.target === ov) closeScenario();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && ov.classList.contains("is-open")) closeScenario();
    });
  })();

  // ---------- раздача по рабочим местам ----------
  function assignPanel(ctx) {
    const clusters = D.getClusters().filter((c) => D.scenariosOfCluster(c.id, true).length);
    const assigned = D.getAssignments();
    const cards = ctx.getIncidents();
    const rows = D.WORKSTATIONS.map((ws) => {
      const a = assigned[ws] || {};
      const clOpts = `<option value="">— не назначен —</option>` + clusters.map((c) => `<option value="${c.id}" ${a.clusterId === c.id ? "selected" : ""}>${ctx.esc(c.title)} (${D.scenariosOfCluster(c.id, true).length})</option>`).join("");
      return `<tr>
        <td data-label="Место" class="cell-mono">${ws}</td>
        <td data-label="Роль"><select class="cell-select" data-ws="${ws}" data-field="role"><option value="">—</option><option value="student" ${a.role === "student" ? "selected" : ""}>Оператор</option><option value="dispatcher" ${a.role === "dispatcher" ? "selected" : ""}>Диспетчер</option></select></td>
        <td data-label="Кластер сценариев"><select class="cell-select" data-ws="${ws}" data-field="cluster">${clOpts}</select></td>
        <td data-label="Карточек" class="cell-mono">${cards.filter((c) => c.workstation === ws).length}</td>
      </tr>`;
    }).join("");
    return `
      <div class="panel-head"><h2>Раздача по рабочим местам</h2><span class="count">Кластеров с утверждёнными сценариями: ${clusters.length}</span></div>
      <p class="empty-hint" style="padding:0 0 12px;">Оператор на выбранном месте получает сценарии назначенного кластера по очереди при создании карточек; диспетчеру кластер задаёт входящий поток. Без назначения берутся все утверждённые сценарии.</p>
      <div class="data-table-wrap"><table class="data-table"><thead><tr><th>Место</th><th>Роль</th><th>Кластер сценариев</th><th>Карточек</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function wireAssign(root, ctx) {
    root.querySelectorAll("select[data-ws]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const ws = sel.dataset.ws;
        const role = root.querySelector(`select[data-ws="${ws}"][data-field="role"]`).value;
        const clusterId = root.querySelector(`select[data-ws="${ws}"][data-field="cluster"]`).value;
        D.setAssignment(ws, role || clusterId ? { role: role, clusterId: clusterId } : null);
        window.DDS_API.log("assign", `${ws}: роль ${role || "—"}, кластер ${clusterId || "—"}`);
        ctx.showToast(`Место ${ws} обновлено`);
      });
    });
  }

  // ---------- мониторинг ----------
  function monitorPanel(ctx) {
    const cards = ctx.getIncidents().slice(0, 25);
    const active = cards.filter((c) => c.status === "review" && ["pending", "active"].indexOf(ctx.ddsState(c).phase) !== -1).length;
    const rows = cards
      .map((c) => `<tr>
        <td data-label="№" class="cell-mono">${ctx.esc(c.number)}</td>
        <td data-label="Место" class="cell-mono">${ctx.esc(c.workstation || (c.source === "system" ? "поток" : "—"))}</td>
        <td data-label="Тип">${ctx.esc((ctx.typeLabels(c) || ["—"]).join(", "))}</td>
        <td data-label="Заполнение" class="cell-mono">${c.fillSeconds == null ? "—" : c.fillSeconds + " с"}</td>
        <td data-label="Статус">${ctx.statusPill(c)}</td>
        <td data-label="">${c.status !== "new" ? `<button type="button" class="row-action" data-row-open data-monitor-open="${c.id}">Просмотр</button>` : ""}</td>
      </tr>`)
      .join("");
    return `
      <div class="panel-head"><h2>Мониторинг занятия</h2><span class="count">В работе у диспетчеров: ${active} · обновление каждые 5 с</span></div>
      <div class="data-table-wrap" data-monitor>${cards.length ? `<table class="data-table"><thead><tr><th>№</th><th>Место</th><th>Тип</th><th>Заполнение</th><th>Статус</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty-hint">Карточек пока нет.</div>'}</div>`;
  }

  let monitorTimer = null;

  function wireMonitor(root, ctx) {
    root.querySelectorAll("[data-monitor-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const call = ctx.getIncidents().find((c) => c.id === btn.dataset.monitorOpen);
        if (call) ctx.openReview(call, false);
      });
    });
    clearInterval(monitorTimer);
    monitorTimer = setInterval(() => {
      const reviewOpen = document.getElementById("review-sheet").classList.contains("is-open");
      if (!document.querySelector("[data-monitor]")) {
        clearInterval(monitorTimer);
        return;
      }
      if (!reviewOpen) ctx.renderWorkspace();
    }, 5000);
  }

  // ---------- отчёты ----------
  function reportsPanel(ctx) {
    const cards = ctx.getIncidents();
    const rows = D.WORKSTATIONS.map((ws) => {
      const s = M.operatorStats(cards, ws);
      if (!s.total) return "";
      return `<tr><td data-label="Место" class="cell-mono">${ws}</td><td data-label="Карточек" class="cell-mono">${s.total}</td><td data-label="Отправлено" class="cell-mono">${s.sent}</td><td data-label="Ср. время" class="cell-mono">${s.avgFill == null ? "—" : Math.round(s.avgFill) + " с"}</td><td data-label="Оценка ИИ" class="cell-mono">${s.avgGrade == null ? "—" : Math.round(s.avgGrade)}</td><td data-label="Не принято" class="cell-mono">${s.declined}</td></tr>`;
    }).join("");
    const d = M.dispatcherStats(cards);
    return `
      <div class="panel-head"><h2>Отчёты</h2><button type="button" class="btn-card" id="export-csv">Скачать CSV</button></div>
      <div class="stat-grid">
        <div class="stat-card"><span class="stat-label">Карточек в потоке</span><strong class="stat-value">${d.total}</strong></div>
        <div class="stat-card"><span class="stat-label">Приём в норматив</span><strong class="stat-value">${d.inTimePct == null ? "—" : d.inTimePct + "%"}</strong></div>
        <div class="stat-card"><span class="stat-label">Работы завершены</span><strong class="stat-value">${d.done}</strong></div>
      </div>
      <div class="panel-head" style="margin-top:20px;"><h2>По операторам</h2></div>
      <div class="data-table-wrap">${rows ? `<table class="data-table"><thead><tr><th>Место</th><th>Карточек</th><th>Отправлено</th><th>Ср. время</th><th>Оценка ИИ</th><th>Не принято</th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty-hint">Данных пока нет.</div>'}</div>`;
  }

  function wireReports(root, ctx) {
    root.querySelector("#export-csv").addEventListener("click", () => {
      const head = ["Номер", "Время", "Место", "Кластер", "Типы", "Адрес", "Статус", "Время заполнения, с", "Оценка ИИ", "Оценка преподавателя"];
      const q = (v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
      const lines = ctx.getIncidents().map((c) => {
        const g = M.gradeCard(c);
        const st = c.status === "review" ? ctx.ddsState(c).label : c.status;
        const cl = c.clusterId ? (D.getCluster(c.clusterId) || {}).title || "" : "";
        return [c.number, c.time, c.workstation || "", cl, (ctx.typeLabels(c) || []).join("; "), c.addressLine || "", st, c.fillSeconds == null ? "" : c.fillSeconds, g ? g.score : "", c.teacherGrade ? c.teacherGrade.value : ""].map(q).join(";");
      });
      const blob = new Blob(["\ufeff" + [head.map(q).join(";")].concat(lines).join("\r\n")], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "dds-report.csv";
      a.click();
      URL.revokeObjectURL(a.href);
      window.DDS_API.log("report_export", "Выгрузка CSV");
    });
  }

  // ---------- оценка ИИ ----------
  function gradingPanel(ctx) {
    const cards = ctx.getIncidents().filter((c) => c.status === "review" && c.source !== "system");
    const rows = cards
      .map((c) => {
        const g = M.gradeCard(c);
        const val = c.teacherGrade ? c.teacherGrade.value : g.score;
        return `<tr>
          <td data-label="№" class="cell-mono">${ctx.esc(c.number)}</td>
          <td data-label="Место" class="cell-mono">${ctx.esc(c.workstation || "—")}</td>
          <td data-label="Оценка ИИ" class="cell-mono">${g.score}</td>
          <td data-label="Замечания ИИ">${g.notes.length ? ctx.esc(g.notes.join("; ")) : '<span class="cell-muted">нет</span>'}</td>
          <td data-label="Оценка преподавателя"><input type="number" min="0" max="100" value="${val}" data-grade-input="${c.id}" class="grade-input" /></td>
          <td data-label=""><button type="button" class="row-action" data-grade="${c.id}">${c.teacherGrade ? "Обновить" : "Подтвердить"}</button></td>
        </tr>`;
      })
      .join("");
    return `
      <div class="panel-head"><h2>Оценка ИИ</h2><span class="count">Подтверждено: ${cards.filter((c) => c.teacherGrade).length} из ${cards.length}</span></div>
      <p class="empty-hint" style="padding:0 0 12px;">Автоматическая оценка предлагается ИИ; преподаватель подтверждает её или вносит свою — изменения фиксируются в журнале.</p>
      <div class="data-table-wrap">${rows ? `<table class="data-table"><thead><tr><th>№</th><th>Место</th><th>ИИ</th><th>Замечания ИИ</th><th>Оценка</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty-hint">Нет отправленных карточек для оценки.</div>'}</div>`;
  }

  function wireGrading(root, ctx) {
    root.querySelectorAll("[data-grade]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.grade;
        const input = root.querySelector(`[data-grade-input="${id}"]`);
        const value = Math.max(0, Math.min(100, parseInt(input.value, 10) || 0));
        const call = ctx.getIncidents().find((c) => c.id === id);
        const auto = M.gradeCard(call).score;
        call.teacherGrade = { value: value, auto: auto, by: ctx.session.fullName, at: Date.now() };
        ctx.saveIncidents();
        window.DDS_API.log("grade", `Карточка № ${call.number}: ИИ ${auto}, преподаватель ${value}`);
        ctx.showToast("Оценка сохранена");
        ctx.renderWorkspace();
      });
    });
  }

  window.DDS_TABS.push({ roles: ["teacher"], id: "scenarios", label: "Сценарии", order: 10, render: scenariosPanel, wire: wireScenarios });
  window.DDS_TABS.push({ roles: ["teacher"], id: "assign", label: "Раздача по местам", order: 20, render: assignPanel, wire: wireAssign });
  window.DDS_TABS.push({ roles: ["teacher"], id: "monitor", label: "Мониторинг", order: 30, render: monitorPanel, wire: wireMonitor });
  window.DDS_TABS.push({ roles: ["teacher"], id: "reports", label: "Отчёты", order: 40, render: reportsPanel, wire: wireReports });
  window.DDS_TABS.push({ roles: ["teacher"], id: "grading", label: "Оценка ИИ", order: 50, render: gradingPanel, wire: wireGrading });
})();
