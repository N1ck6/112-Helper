/* Кабинеты на данных Backend: преподаватель, администратор, статистика обучающегося.
 *
 * Каждая вкладка рисует каркас, а данные подгружает в wire(): API — backend/docs/INTEGRATION.md.
 */
(function () {
  "use strict";
  window.DDS_TABS = window.DDS_TABS || [];
  const API = window.DDS_API;
  const req = (method, path, body) => API.request(method, path, body);

  const LESSON_MODE = { card_fill: "Оператор 112 (заполнение карточки)", card_action: "Диспетчер ДДС (статусы реагирования)" };
  const LESSON_STATUS = { planned: "запланировано", running: "идёт", paused: "пауза", finished: "завершено", aborted: "прервано" };
  const SCENARIO_STATUS = { draft: "черновик", pending_review: "на проверке", approved: "утверждён", archived: "в архиве" };
  const ORIGIN = { manual: "вручную", ai_generated: "ИИ", ai_corrected: "ИИ + правка" };
  const ROLE_NAME = { admin: "Администратор", teacher: "Преподаватель", student: "Обучающийся" };

  let esc = (v) => String(v == null ? "" : v);
  const dt = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
  const num = (v, d) => (v == null ? "—" : Number(v).toFixed(d == null ? 0 : d));

  function table(head, rows, empty) {
    if (!rows.length) return `<div class="empty-hint">${empty || "Нет данных."}</div>`;
    return `<div class="data-table-wrap"><table class="data-table"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows
      .map((r) => `<tr>${r.map((c, i) => `<td data-label="${head[i]}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  const pill = (ok, text) => `<span class="status-pill ${ok ? "status-done" : ok === false ? "status-blocked" : "status-new"}">${esc(text)}</span>`;
  const statCard = (label, value, hint) => `<div class="stat-card"><span class="stat-label">${label}</span><strong class="stat-value">${value}</strong>${hint ? `<span class="stat-hint">${hint}</span>` : ""}</div>`;

  function load(root, sel, promise, render) {
    const box = root.querySelector(sel);
    box.innerHTML = '<div class="empty-hint">Загрузка…</div>';
    return promise.then((data) => { box.innerHTML = render(data); return data; })
      .catch((e) => { box.innerHTML = `<div class="empty-hint">Ошибка: ${esc(e.message)}</div>`; });
  }

  let timers = [];
  function every(ms, fn) { timers.forEach(clearInterval); timers = [setInterval(fn, ms)]; }
  const stillHere = (sel) => !!document.querySelector(sel);

  async function lessons(status) {
    const page = await req("GET", "/lessons?size=100" + (status ? "&status=" + status : ""));
    return page.items || [];
  }
  const lessonOptions = (list, selected) => list.map((l) => `<option value="${l.id}" ${l.id === selected ? "selected" : ""}>${esc(l.title)} · ${LESSON_STATUS[l.status] || l.status} · ${dt(l.created_at)}</option>`).join("");

  // ================================================================ преподаватель
  // ---------------------------------------------------------------- Занятия
  function lessonsPanel(ctx) {
    esc = ctx.esc;
    return `
      <div class="panel-head"><h2>Занятия</h2><span class="count">карточки выдаёт сервер, оценку считает ИИ</span></div>
      <section class="info-block">
        <form id="ls-form" class="scenario-form">
          <div class="form-field"><label for="ls-title">Название</label><input id="ls-title" required value="Тренировка ${new Date().toLocaleDateString("ru-RU")}" /></div>
          <div class="form-field"><label for="ls-mode">Режим</label><select id="ls-mode">${Object.keys(LESSON_MODE).map((k) => `<option value="${k}">${LESSON_MODE[k]}</option>`).join("")}</select></div>
          <div class="form-field"><label for="ls-purpose">Назначение</label><select id="ls-purpose"><option value="training">Учебное</option><option value="attestation">Аттестация</option><option value="refresher">Переподготовка</option></select></div>
          <div class="form-field"><label for="ls-max">Карточек на обучающегося</label><input id="ls-max" type="number" min="1" max="50" value="5" /></div>
          <div class="form-field span-2"><label>Обучающиеся</label><div id="ls-students" class="flag-row">загрузка…</div></div>
          <div class="form-field span-2"><label>Категории происшествий (пусто — все)</label><div id="ls-cats" class="flag-row">загрузка…</div></div>
          <div class="form-row-actions"><button type="submit" class="btn-card">Создать и запустить</button></div>
        </form>
      </section>
      <div id="ls-list"></div>`;
  }

  function pickable(items, key, label) {
    return items.map((x) => `<button type="button" class="flag-pill" data-pick="${key}" data-id="${x.id}">${esc(label(x))}</button>`).join("") || '<span class="cell-muted">нет</span>';
  }

  function renderLessons(list) {
    return table(["Занятие", "Режим", "Статус", "Участники", "Создано", ""], list.map((l) => [
      `<b>${esc(l.title)}</b>`, esc(LESSON_MODE[l.mode] || l.mode),
      pill(l.status === "running" ? true : l.status === "finished" ? null : l.status === "aborted" ? false : null, LESSON_STATUS[l.status] || l.status),
      `<span class="cell-mono">${(l.participants || []).length}</span>`, dt(l.created_at),
      l.status === "planned" ? `<button type="button" class="row-action" data-ls-start="${l.id}">Начать</button>`
        : l.status === "running" ? `<button type="button" class="row-action danger" data-ls-finish="${l.id}">Завершить</button>` : "",
    ]), "Занятий пока нет.");
  }

  function wireLessons(root, ctx) {
    const refresh = () => load(root, "#ls-list", lessons(), renderLessons);
    req("GET", "/users?role=student&size=200").then((p) => {
      root.querySelector("#ls-students").innerHTML = pickable(p.items || [], "student", (u) => u.full_name || u.username);
      root.querySelectorAll('[data-pick="student"]').forEach((b) => b.classList.add("active"));   // по умолчанию — все
    }).catch((e) => (root.querySelector("#ls-students").textContent = e.message));
    req("GET", "/categories?size=100").then((p) => {
      root.querySelector("#ls-cats").innerHTML = pickable(p.items || [], "cat", (c) => c.name);
    }).catch((e) => (root.querySelector("#ls-cats").textContent = e.message));
    root.addEventListener("click", (e) => {
      const pick = e.target.closest("[data-pick]");
      if (pick) pick.classList.toggle("active");
      const start = e.target.closest("[data-ls-start]");
      const finish = e.target.closest("[data-ls-finish]");
      if (start) req("POST", "/lessons/" + start.dataset.lsStart + "/start").then(() => { ctx.showToast("Занятие началось"); refresh(); }).catch((x) => ctx.showToast(x.message));
      if (finish && confirm("Завершить занятие? Обучающиеся больше не получат карточек.")) {
        req("POST", "/lessons/" + finish.dataset.lsFinish + "/finish", { reason: "Завершено преподавателем" })
          .then(() => { ctx.showToast("Занятие завершено"); refresh(); }).catch((x) => ctx.showToast(x.message));
      }
    });
    root.querySelector("#ls-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const ids = (key) => Array.from(root.querySelectorAll(`[data-pick="${key}"].active`)).map((b) => b.dataset.id);
      const students = ids("student");
      if (!students.length) return ctx.showToast("Выберите хотя бы одного обучающегося");
      const body = {
        title: root.querySelector("#ls-title").value.trim(), mode: root.querySelector("#ls-mode").value,
        purpose: root.querySelector("#ls-purpose").value, max_cards: Number(root.querySelector("#ls-max").value) || null,
        student_ids: students, category_ids: ids("cat"),
      };
      req("POST", "/lessons", body)
        .then((l) => req("POST", "/lessons/" + l.id + "/start"))
        .then(() => { ctx.showToast("Занятие запущено: обучающиеся получат карточки на своих местах"); refresh(); })
        .catch((x) => ctx.showToast(x.message));
    });
    refresh();
  }

  // ---------------------------------------------------------------- Мониторинг
  let monitorLesson = null;
  function monitorPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Мониторинг занятия</h2><span class="count">обновление каждые 3 с</span></div>
      <div class="form-field"><label for="mn-lesson">Занятие</label><select id="mn-lesson"></select></div>
      <div id="mn-body" data-server-monitor></div>`;
  }
  function wireMonitor(root) {
    const select = root.querySelector("#mn-lesson");
    const show = () => {
      if (!select.value) return (root.querySelector("#mn-body").innerHTML = '<div class="empty-hint">Нет занятий: создайте его во вкладке «Занятия».</div>');
      monitorLesson = select.value;
      req("GET", "/lessons/" + select.value + "/monitor").then((m) => {
        const box = root.querySelector("#mn-body");
        if (!box) return;
        box.innerHTML = table(["Обучающийся", "Место", "Статус", "Карточка", "Осталось", "Выдано / сдано", "Средний балл", "Ошибок"], (m.rows || []).map((r) => [
          esc(r.student_name), `<span class="cell-mono">${esc(r.workplace || "—")}</span>`, esc(r.participant_status),
          `<span class="cell-mono">${esc(r.current_card_no || "—")}</span>`,
          r.seconds_left == null ? "—" : `<span class="timer ${r.seconds_left < 0 ? "bad" : r.seconds_left <= 10 ? "warn" : ""}">${Math.round(r.seconds_left)} с</span>`,
          `<span class="cell-mono">${r.cards_issued} / ${r.cards_submitted}</span>`, num(r.avg_score, 1), num(r.error_count),
        ]), "Участники ещё не вошли в занятие.");
      }).catch(() => {});
    };
    lessons().then((list) => {
      const running = list.filter((l) => l.status === "running");
      const pickList = running.length ? running : list;
      select.innerHTML = lessonOptions(pickList, monitorLesson || (pickList[0] || {}).id);
      show();
    });
    select.addEventListener("change", show);
    every(3000, () => { if (stillHere("[data-server-monitor]")) show(); else timers.forEach(clearInterval); });
  }

  // ---------------------------------------------------------------- Сценарии
  function scenariosPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Сценарии</h2><span class="count">эталоны утверждает преподаватель — только утверждённые попадают в занятия</span></div>
      <section class="info-block">
        <form id="sg-form" class="scenario-form">
          <div class="form-field span-2"><label for="sg-prompt">Что сгенерировать (ИИ по классификатору происшествий)</label><input id="sg-prompt" placeholder="например: пожар в жилом доме, ДТП с пострадавшими" required /></div>
          <div class="form-field"><label for="sg-cat">Категория</label><select id="sg-cat"><option value="">любая</option></select></div>
          <div class="form-field"><label for="sg-count">Сколько</label><input id="sg-count" type="number" min="1" max="5" value="1" /></div>
          <div class="form-row-actions"><button type="submit" class="btn-card">Сгенерировать ИИ</button></div>
        </form>
      </section>
      <div id="sg-list"></div>`;
  }
  function renderScenarios(page) {
    return table(["Сценарий", "Источник", "Статус", "Создан", ""], (page.items || []).map((s) => [
      `<b>${esc(s.title)}</b>${s.description ? `<br><span class="cell-muted">${esc(String(s.description).slice(0, 140))}</span>` : ""}`,
      esc(ORIGIN[s.origin] || s.origin) + (s.ml_model ? `<br><span class="cell-muted">${esc(s.ml_model)}</span>` : ""),
      pill(s.status === "approved" ? true : null, SCENARIO_STATUS[s.status] || s.status), dt(s.created_at),
      s.status !== "approved" && s.status !== "archived" ? `<button type="button" class="row-action" data-sc-approve="${s.id}">Утвердить</button>` : "",
    ]), "Сценариев нет.");
  }
  function wireScenarios(root, ctx) {
    const refresh = () => load(root, "#sg-list", req("GET", "/scenarios?size=100"), renderScenarios);
    req("GET", "/categories?size=100").then((p) => {
      root.querySelector("#sg-cat").innerHTML += (p.items || []).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    }).catch(() => {});
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-sc-approve]");
      if (b) req("POST", "/scenarios/" + b.dataset.scApprove + "/approve", {}).then(() => { ctx.showToast("Эталоны утверждены — сценарий доступен в занятиях"); refresh(); }).catch((x) => ctx.showToast(x.message));
    });
    root.querySelector("#sg-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button[type=submit]");
      btn.disabled = true;
      ctx.showToast("ИИ генерирует сценарии…");
      const cat = root.querySelector("#sg-cat").value;
      req("POST", "/scenarios/generate", { prompt: root.querySelector("#sg-prompt").value.trim(), count: Number(root.querySelector("#sg-count").value) || 1, category_id: cat || null })
        .then((list) => { ctx.showToast(`Сгенерировано: ${list.length}. Проверьте и утвердите`); refresh(); })
        .catch((x) => ctx.showToast(x.message))
        .finally(() => (btn.disabled = false));
    });
    refresh();
  }

  // ---------------------------------------------------------------- Раздача по местам
  function assignPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Карта класса</h2><span class="count">кто за каким рабочим местом</span></div><div id="as-map"></div>
      <p class="stat-hint">Номер места обучающийся выбирает при входе; входящий вызов 112 приходит на телефон этого места (ws01…ws20).</p>`;
  }
  function wireAssign(root) {
    load(root, "#as-map", req("GET", "/workplaces/class-map"), (items) => table(["Место", "Обучающийся", "Занятие", "Статус"],
      (Array.isArray(items) ? items : items.items || []).map((w) => [
        `<span class="cell-mono">${esc(w.number || (w.workplace || {}).number)}</span>`, esc(w.student_name || (w.student || {}).full_name || "—"),
        esc(w.lesson_title || "—"), esc(w.status || (w.is_occupied ? "занято" : "свободно")),
      ]), "Рабочие места ещё не заняты."));
  }

  // ---------------------------------------------------------------- Оценка ИИ
  let gradingLesson = null;
  function gradingPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Оценка ИИ</h2><span class="count">подтвердите или исправьте оценку — правка пишется в аудит</span></div>
      <div class="form-field"><label for="gr-lesson">Занятие</label><select id="gr-lesson"></select></div>
      <div class="form-row-actions"><button type="button" class="row-action" id="gr-reco">Рекомендации ИИ группе</button></div>
      <div id="gr-reco-box"></div><div id="gr-list"></div>`;
  }
  function wireGrading(root, ctx) {
    const select = root.querySelector("#gr-lesson");
    const show = () => {
      if (!select.value) return;
      gradingLesson = select.value;
      load(root, "#gr-list", req("GET", "/evaluations/by-lesson/" + select.value), (list) => table(
        ["Оценка", "Итог", "Время", "Точность", "Регламент", "Грамотность", "Ошибки", "Источник", "Правка"],
        list.map((ev) => [
          `<b class="cell-mono">${num(ev.score, 1)}</b>${ev.original_score != null ? `<br><span class="cell-muted">ИИ: ${num(ev.original_score, 1)}</span>` : ""}`,
          pill(ev.passed, ev.passed ? "зачтено" : "не зачтено"), num(ev.timing_score), num(ev.accuracy_score), num(ev.procedure_score), num(ev.grammar_score),
          (ev.errors || []).slice(0, 4).map((er) => `<span class="${er.severity === "critical" ? "danger" : "cell-muted"}">• ${esc(er.message)}</span>`).join("<br>") || "—",
          esc(ev.ml_model || ev.source),
          `<input type="number" class="grade-input" min="0" max="100" value="${Math.round(ev.score)}" data-gr-score="${ev.id}" style="width:64px"> <button type="button" class="row-action" data-gr-save="${ev.id}">Сохранить</button>`,
        ]), "Оценок пока нет: обучающиеся ещё не сдали карточки."));
    };
    lessons().then((list) => { select.innerHTML = lessonOptions(list, gradingLesson || (list[0] || {}).id); show(); });
    select.addEventListener("change", show);
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-gr-save]");
      if (b) {
        const score = Number(root.querySelector(`[data-gr-score="${b.dataset.grSave}"]`).value);
        const reason = prompt("Причина исправления оценки (обязательно):");
        if (!reason) return;
        req("POST", "/evaluations/" + b.dataset.grSave + "/override", { score: score, reason: reason, passed: score >= 70 })
          .then(() => { ctx.showToast("Оценка исправлена, запись в аудите"); show(); }).catch((x) => ctx.showToast(x.message));
      }
    });
    root.querySelector("#gr-reco").addEventListener("click", () => {
      if (!select.value) return;
      ctx.showToast("ИИ анализирует ошибки группы…");
      load(root, "#gr-reco-box", req("POST", "/evaluations/recommendations/build?lesson_id=" + select.value),
        (items) => `<section class="info-block">${items.map((r) => `<p><b>${esc(r.title)}</b> — ${esc(r.text)}</p>`).join("") || "Недостаточно данных для рекомендаций."}</section>`);
    });
  }

  // ---------------------------------------------------------------- Отчёты
  function reportsPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Отчёты</h2><span class="count">ФИО, рабочее место, время против норматива, ошибки</span></div>
      <section class="info-block"><form id="rp-form" class="scenario-form">
        <div class="form-field"><label for="rp-lesson">Занятие</label><select id="rp-lesson"></select></div>
        <div class="form-field"><label for="rp-type">Отчёт</label><select id="rp-type"><option value="lesson">По занятию</option><option value="errors">Ошибки</option><option value="timing">Время</option><option value="attestation">Протокол аттестации</option></select></div>
        <div class="form-field"><label for="rp-format">Формат</label><select id="rp-format"><option value="pdf">PDF</option><option value="xlsx">Excel</option><option value="csv">CSV</option><option value="json">JSON</option></select></div>
        <div class="form-row-actions"><button type="submit" class="btn-card">Сформировать и скачать</button></div>
      </form></section>`;
  }
  async function download(reportId, name) {
    const s = JSON.parse(localStorage.getItem("ddsSession") || "{}");
    const res = await fetch(API.base + "/reports/" + reportId + "/download", { headers: { Authorization: "Bearer " + s.token } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  function wireReports(root, ctx) {
    lessons().then((list) => (root.querySelector("#rp-lesson").innerHTML = lessonOptions(list)));
    root.querySelector("#rp-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const g = (id) => root.querySelector(id).value;
      try {
        ctx.showToast("Формируется отчёт…");
        let rep = await req("POST", "/reports", { type: g("#rp-type"), format: g("#rp-format"), lesson_id: g("#rp-lesson") || null });
        for (let i = 0; i < 30 && rep.status !== "ready" && rep.status !== "failed"; i++) {
          await new Promise((r) => setTimeout(r, 1000));
          rep = await req("GET", "/reports/" + rep.id);
        }
        if (rep.status !== "ready") throw new Error("отчёт не готов: " + rep.status);
        await download(rep.id, `report_${g("#rp-type")}.${g("#rp-format")}`);
      } catch (x) { ctx.showToast(x.message); }
    });
  }

  // ================================================================ обучающийся
  function myStatsPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Моя статистика</h2><span class="count">по всем занятиям на сервере</span></div>
      <div id="st-summary"></div>
      <section class="info-block"><h3>Рекомендации ИИ</h3><div id="st-reco"></div></section>
      <div class="panel-head" style="margin-top:12px"><h3>Последние оценки</h3></div><div id="st-list"></div>`;
  }
  function wireMyStats(root) {
    load(root, "#st-summary", req("GET", "/analytics/my-summary"), (s) => `<div class="stat-grid">
      ${statCard("Сдано карточек", s.attempts_submitted, "всего выдано: " + s.attempts_total)}
      ${statCard("Средний балл", num(s.avg_score, 1), "зачтено: " + (s.pass_rate == null ? "—" : Math.round(s.pass_rate * 100) + "%"))}
      ${statCard("Среднее время", s.avg_duration_seconds == null ? "—" : Math.round(s.avg_duration_seconds) + " с", "сверх норматива: " + s.attempts_overtime)}
      </div>${(s.top_errors || []).length ? table(["Тип ошибок", "Сколько", "Доля"], s.top_errors.map((b) => [esc(b.category), b.count, Math.round((b.share || 0) * 100) + "%"])) : ""}`);
    load(root, "#st-reco", req("GET", "/evaluations/recommendations/my?size=5"), (p) =>
      (p.items || []).map((r) => `<p><b>${esc(r.title)}</b> — ${esc(r.text)}</p>`).join("") || '<span class="cell-muted">Появятся после разбора занятия преподавателем.</span>');
    load(root, "#st-list", req("GET", "/evaluations/my?size=20"), (p) => table(["Когда", "Оценка", "Итог", "Ошибки"], (p.items || []).map((ev) => [
      dt(ev.evaluated_at), `<b class="cell-mono">${num(ev.score, 1)}</b>`, pill(ev.passed, ev.passed ? "зачтено" : "не зачтено"),
      (ev.errors || []).slice(0, 3).map((er) => "• " + esc(er.message)).join("<br>") || "—",
    ]), "Оценок пока нет."));
  }

  // ================================================================ администратор
  function usersPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Пользователи</h2><span class="count">учётные записи на сервере</span></div>
      <section class="info-block"><form id="us-form" class="scenario-form">
        <div class="form-field"><label for="us-login">Логин</label><input id="us-login" required minlength="3" /></div>
        <div class="form-field"><label for="us-name">ФИО</label><input id="us-name" required /></div>
        <div class="form-field"><label for="us-role">Роль</label><select id="us-role"><option value="student">Обучающийся</option><option value="teacher">Преподаватель</option><option value="admin">Администратор</option></select></div>
        <div class="form-field"><label for="us-pass">Пароль (от 8 символов)</label><input id="us-pass" type="password" required minlength="8" autocomplete="new-password" /></div>
        <div class="form-row-actions"><button type="submit" class="btn-card">Создать</button></div>
      </form></section><div id="us-list"></div>`;
  }
  function wireUsers(root, ctx) {
    const refresh = () => load(root, "#us-list", req("GET", "/users?size=200"), (p) => table(["ФИО", "Логин", "Роль", "Статус", "Последний вход", ""],
      (p.items || []).map((u) => [esc(u.full_name), `<span class="cell-mono">${esc(u.username)}</span>`,
        esc((u.roles || []).map((r) => ROLE_NAME[r] || r).join(", ")),
        pill(u.status === "active", u.status === "active" ? "активен" : u.status === "blocked" ? "заблокирован" : u.status),
        dt(u.last_login_at),
        u.status === "blocked" ? `<button type="button" class="row-action" data-us-unblock="${u.id}">Разблокировать</button>`
          : `<button type="button" class="row-action danger" data-us-block="${u.id}">Заблокировать</button>`])));
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-us-block]");
      const u = e.target.closest("[data-us-unblock]");
      if (b) req("POST", "/users/" + b.dataset.usBlock + "/block", { reason: "Заблокирован администратором" }).then(() => { ctx.showToast("Доступ заблокирован"); refresh(); }).catch((x) => ctx.showToast(x.message));
      if (u) req("POST", "/users/" + u.dataset.usUnblock + "/unblock").then(() => { ctx.showToast("Доступ восстановлен"); refresh(); }).catch((x) => ctx.showToast(x.message));
    });
    root.querySelector("#us-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const g = (id) => root.querySelector(id).value.trim();
      req("POST", "/users", { username: g("#us-login"), full_name: g("#us-name"), password: root.querySelector("#us-pass").value, role_codes: [g("#us-role")] })
        .then(() => { ctx.showToast("Пользователь создан"); e.target.reset(); refresh(); }).catch((x) => ctx.showToast(x.message));
    });
    refresh();
  }

  function progressPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Прогресс и нагрузка</h2><span class="count">сводка по системе</span></div><div id="pr-stats"></div>
      <div class="panel-head" style="margin-top:12px"><h3>Занятия</h3></div><div id="pr-lessons"></div>`;
  }
  function wireProgress(root) {
    load(root, "#pr-stats", req("GET", "/admin/stats"), (s) => `<div class="stat-grid">
      ${statCard("Пользователи", s.users_active + " / " + s.users_total, "активных / всего")}
      ${statCard("Идут занятия", s.lessons_running, "")}
      ${statCard("Карточек сегодня", s.attempts_today, "оценено: " + s.evaluations_today)}
      ${statCard("База данных", s.db_size_bytes == null ? "—" : (s.db_size_bytes / 1048576).toFixed(1) + " МБ", "очередь outbox: " + s.outbox_pending)}
      </div>`);
    load(root, "#pr-lessons", lessons(), (list) => table(["Занятие", "Режим", "Статус", "Участники", "Начато"], list.map((l) => [
      esc(l.title), esc(LESSON_MODE[l.mode] || l.mode), esc(LESSON_STATUS[l.status] || l.status), (l.participants || []).length, dt(l.started_at),
    ]), "Занятий нет."));
  }

  function systemPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Состояние системы</h2><span class="count">обновление каждые 10 с</span></div><div id="sy-health" data-server-system></div><div id="sy-services"></div>`;
  }
  function wireSystem(root) {
    const show = () => {
      load(root, "#sy-health", fetch(window.APP_CONFIG.API_HEALTH_URL.replace(/live$/, "ready")).then((r) => r.json()), (h) => `<div class="stat-grid">
        ${statCard("Backend", pill(h.status === "ok", h.status), "версия " + esc(h.version))}
        ${statCard("PostgreSQL", pill(h.database === "ok", h.database), "")}
        ${Object.keys(h.components || {}).map((k) => statCard(k === "ml" ? "ML / ИИ" : k === "telephony" ? "Телефония" : esc(k), pill((h.components[k] || {}).status === "ok", (h.components[k] || {}).status || "—"), "")).join("")}
        </div>`);
      load(root, "#sy-services", req("GET", "/admin/services"), (list) => table(["Компонент", "Тип", "Статус", "Адрес", "Обновлено"], list.map((s) => [
        esc(s.name), esc(s.kind), pill(s.status === "running" || s.status === "ok", s.status), `<span class="cell-mono">${esc(s.endpoint || "—")}</span>`, dt(s.updated_at),
      ])));
    };
    show();
    every(10000, () => { if (stillHere("[data-server-system]")) show(); else timers.forEach(clearInterval); });
  }

  function logsPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>Журналы</h2><span class="count">аудит действий и системный журнал</span></div>
      <div class="panel-head"><h3>Аудит</h3></div><div id="lg-audit"></div>
      <div class="panel-head" style="margin-top:12px"><h3>Системный журнал</h3></div><div id="lg-system"></div>`;
  }
  function wireLogs(root) {
    load(root, "#lg-audit", req("GET", "/admin/audit?size=50"), (p) => table(["Когда", "Кто", "Действие", "Объект", "Итог"], (p.items || []).map((a) => [
      dt(a.at), esc(a.actor_username || "—"), esc(a.action), esc(a.summary || a.object_type || "—"), esc(a.result || "—"),
    ])));
    load(root, "#lg-system", req("GET", "/admin/logs?size=50"), (p) => table(["Когда", "Уровень", "Компонент", "Сообщение"], (p.items || []).map((l) => [
      dt(l.at), esc(l.level), esc(l.component || "—"), esc(l.message),
    ])));
  }

  // ---------------------------------------------------------------- IP-телефония
  // Рабочие места и параметры — Backend; регистрация телефонов и состояние — модуль телефонии.
  const TEL = String((window.APP_CONFIG || {}).TELEPHONY_API_URL || "telephony").replace(/\/$/, "");
  const telGet = (path) => fetch(TEL + path).then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))));
  const wsOf = (number) => "ws" + String(number || "").padStart(2, "0");
  const recording = (url) => (url && !/^[a-z]+:\/\//i.test(TEL) ? "recordings/" + String(url).split("/").pop() : url);
  const CALL_STATUS = { ringing: "вызов", answered: "разговор", ended: "завершён", missed: "не отвечен", failed: "сбой" };

  function telephonyPanel(ctx) {
    esc = ctx.esc;
    return `<div class="panel-head"><h2>IP-телефония</h2><span class="count">обновление каждые 10 с</span></div>
      <div id="tl-state" data-server-telephony></div>
      <div class="panel-head" style="margin-top:12px"><h3>Рабочие места</h3></div><div id="tl-places"></div>
      <div class="panel-head" style="margin-top:12px"><h3>Последние вызовы</h3></div><div id="tl-calls"></div>`;
  }
  function wireTelephony(root) {
    const show = () => {
      load(root, "#tl-state", Promise.all([req("GET", "/telephony/config"), telGet("/health").catch(() => null)]), ([cfg, h]) => `<div class="stat-grid">
        ${statCard("Модуль телефонии", pill(!!h && h.ami !== false, h ? (h.ami === false ? "нет связи с Asterisk" : "работает") : "недоступен"), h ? "собеседники (ML): " + (h.ml ? "да" : "нет") + " · голос: " + (h.voice_service ? "да" : "нет") : esc(TEL))}
        ${statCard("SIP-сервер", `<span class="cell-mono">${esc(location.hostname || "<IP стенда>")}:5063</span>`, "UDP · аккаунты ws01…ws20")}
        ${statCard("Кодек", esc(cfg.codec), esc(cfg.transport))}
        ${statCard("Норматив задержки", cfg.max_latency_ms + " мс", "превышение — в системный журнал")}
        ${statCard("Запись разговоров", cfg.record_calls ? "включена" : "выключена", esc(cfg.audio_format))}
        </div>`);
      load(root, "#tl-places", Promise.all([req("GET", "/workplaces"), telGet("/endpoints").catch(() => null), req("GET", "/users?size=200")]), ([places, eps, users]) => {
        const names = {};
        (users.items || []).forEach((u) => (names[u.id] = u.full_name || u.username));
        return table(["Место", "SIP-аккаунт", "Внутр. номер", "Телефон", "Кто за местом"], places.map((w) => {
          const ep = Array.isArray(eps) ? eps.find((e) => e.endpoint === wsOf(w.number)) : null;
          return [esc(w.title || w.number), `<span class="cell-mono">${wsOf(w.number)}</span>`, `<span class="cell-mono">${esc(w.phone_extension || "—")}</span>`,
            eps ? pill(!!(ep && ep.registered), ep && ep.registered ? "подключён" : "не подключён") : pill(null, "нет данных"),
            w.occupied_by_id ? esc(names[w.occupied_by_id] || "занято") : '<span class="cell-muted">свободно</span>'];
        }), "Рабочие места не заведены.");
      });
      load(root, "#tl-calls", req("GET", "/telephony/calls?size=20"), (p) => table(["Начало", "Кто", "Куда", "Статус", "Длительность", "Задержка", "Запись"], (p.items || []).map((c) => [
        dt(c.started_at), `<span class="cell-mono">${esc(c.caller_number || "—")}</span>`, `<span class="cell-mono">${esc(c.callee_number || "—")}</span>`,
        pill(c.status === "ended" ? true : c.status === "failed" || c.status === "missed" ? false : null, CALL_STATUS[c.status] || c.status),
        c.duration_ms == null ? "—" : Math.round(c.duration_ms / 1000) + " с", c.latency_ms == null ? "—" : c.latency_ms + " мс",
        c.audio_path ? `<a href="${esc(recording(c.audio_path))}" target="_blank" rel="noopener">слушать</a>` : "—",
      ]), "Вызовов пока не было."));
    };
    show();
    every(10000, () => { if (stillHere("[data-server-telephony]")) show(); else timers.forEach(clearInterval); });
  }

  // своя обёртка на каждую отрисовку: обработчики не копятся на общем #workspace
  const T = (roles, id, label, order, render, wire) => window.DDS_TABS.push({
    roles, id, label, order, server: true,
    render: (ctx) => '<div class="srv-panel">' + render(ctx) + '</div>',
    wire: (root, ctx) => wire(root.querySelector('.srv-panel'), ctx),
  });
  T(["teacher"], "lessons", "Занятия", 5, lessonsPanel, wireLessons);
  T(["teacher"], "scenarios", "Сценарии", 10, scenariosPanel, wireScenarios);
  T(["teacher"], "assign", "Карта класса", 20, assignPanel, wireAssign);
  T(["teacher"], "monitor", "Мониторинг", 30, monitorPanel, wireMonitor);
  T(["teacher"], "reports", "Отчёты", 40, reportsPanel, wireReports);
  T(["teacher"], "grading", "Оценка ИИ", 50, gradingPanel, wireGrading);
  T(["student", "dispatcher"], "stats", "Статистика", 30, myStatsPanel, wireMyStats);
  T(["admin"], "progress", "Прогресс", 10, progressPanel, wireProgress);
  T(["admin"], "users", "Пользователи", 20, usersPanel, wireUsers);
  T(["admin"], "system", "Состояние системы", 30, systemPanel, wireSystem);
  T(["admin"], "logs", "Журналы", 40, logsPanel, wireLogs);
  T(["admin"], "telephony", "IP-телефония", 50, telephonyPanel, wireTelephony);
})();
