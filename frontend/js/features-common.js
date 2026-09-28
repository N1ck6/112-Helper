(function () {
  const D = window.DDS_DATA;
  const M = window.DDS_METRICS;
  window.DDS_TABS = window.DDS_TABS || [];

  const fmt = (n, digits) => (n == null ? "—" : Number(n).toFixed(digits || 0));

  function statCard(label, value, hint, tone) {
    return `<div class="stat-card ${tone || ""}"><span class="stat-label">${label}</span><strong class="stat-value">${value}</strong>${hint ? `<span class="stat-hint">${hint}</span>` : ""}</div>`;
  }

  function list(items) {
    return `<ul class="tips-list">${items.map((t) => `<li>${t}</li>`).join("")}</ul>`;
  }

  function operatorPanel(ctx) {
    const cards = ctx.getIncidents();
    const s = M.operatorStats(cards, ctx.session.workstation);
    const mine = cards.filter((c) => c.status === "review" && c.source !== "system" && (!ctx.session.workstation || c.workstation === ctx.session.workstation));
    const grade = s.avgGrade == null ? "—" : Math.round(s.avgGrade) + " / 100";
    const rows = mine
      .map((c) => {
        const g = M.gradeCard(c);
        return `<tr><td data-label="№" class="cell-mono">${ctx.esc(c.number)}</td><td data-label="Время заполнения" class="cell-mono">${c.fillSeconds == null ? "—" : c.fillSeconds + " с"}</td><td data-label="Оценка ИИ" class="cell-mono">${g.score}</td><td data-label="Замечания">${g.notes.length ? ctx.esc(g.notes.join("; ")) : '<span class="cell-muted">замечаний нет</span>'}</td><td data-label="Оценка преподавателя" class="cell-mono">${c.teacherGrade ? c.teacherGrade.value : "—"}</td></tr>`;
      })
      .join("");
    const mistakes = s.mistakes.length ? list(s.mistakes.map((m) => `${ctx.esc(m.text)} — ${m.count}`)) : '<p class="empty-hint" style="padding:0;">Ошибок пока нет.</p>';
    return `
      <div class="panel-head"><h2>Статистика и оценка</h2><span class="count">Рабочее место: ${ctx.esc(ctx.session.workstation || "—")}</span></div>
      <div class="stat-grid">
        ${statCard("Оценка ИИ (средняя)", grade, "по отправленным карточкам", "accent")}
        ${statCard("Отправлено диспетчеру", s.sent, "из " + s.total + " открытых")}
        ${statCard("Среднее время заполнения", s.avgFill == null ? "—" : Math.round(s.avgFill) + " с", "норматив " + D.NORMS.fillSeconds + " с")}
        ${statCard("Вне норматива", s.overNorm, "карточек")}
        ${statCard("Опросная карта", s.avgSurvey == null ? "—" : Math.round(s.avgSurvey * 100) + "%", "заполнено в среднем")}
        ${statCard("Не принято диспетчером", s.declined, "принято: " + s.accepted, s.declined ? "bad" : "")}
      </div>
      <div class="two-col">
        <section class="info-block"><h3>Рекомендации ИИ</h3><div id="ai-tips">${list(M.recommendations("student", s))}</div><p class="stat-hint" id="ai-source">Рекомендации по правилам на основе ваших карточек.</p></section>
        <section class="info-block"><h3>Типичные ошибки</h3>${mistakes}</section>
      </div>
      <div class="panel-head" style="margin-top:22px;"><h2>История ошибок и оценок</h2></div>
      <div class="data-table-wrap">
        ${rows ? `<table class="data-table"><thead><tr><th>№</th><th>Время заполнения</th><th>Оценка ИИ</th><th>Замечания</th><th>Оценка преподавателя</th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty-hint">Отправьте карточку диспетчеру — здесь появится оценка.</div>'}
      </div>`;
  }

  function dispatcherPanel(ctx) {
    const s = M.dispatcherStats(ctx.getIncidents());
    return `
      <div class="panel-head"><h2>Статистика диспетчера</h2><span class="count">Рабочее место: ${ctx.esc(ctx.session.workstation || "—")}</span></div>
      <div class="stat-grid">
        ${statCard("Карточек в потоке", s.total, "в работе: " + s.pending)}
        ${statCard("Приём в норматив", s.inTimePct == null ? "—" : s.inTimePct + "%", "норматив " + D.TIMERS.accept + " с", "accent")}
        ${statCard("Среднее время решения", s.avgAccept == null ? "—" : Math.round(s.avgAccept) + " с", "принята / не принята")}
        ${statCard("Принято", s.accepted, "не принято: " + s.declined, s.declined ? "bad" : "")}
        ${statCard("Работы завершены", s.done, "")}
        ${statCard("Отказ от работ", s.refused, "", s.refused ? "bad" : "")}
      </div>
      <section class="info-block"><h3>Рекомендации ИИ</h3><div id="ai-tips">${list(M.recommendations("dispatcher", s))}</div><p class="stat-hint" id="ai-source">Рекомендации по правилам на основе решений в потоке.</p></section>`;
  }

  function wireTips(root, ctx) {
    const api = window.DDS_API;
    if (!api || api.isOnline() !== true) return;
    api.request("GET", "/recommendations?role=" + encodeURIComponent(ctx.session.role) + "&workstation=" + encodeURIComponent(ctx.session.workstation || ""))
      .then((data) => {
        const items = data && Array.isArray(data.items) ? data.items : null;
        const box = root.querySelector("#ai-tips");
        if (!items || !items.length || !box) return;
        box.innerHTML = list(items.map((t) => ctx.esc(t)));
        const src = root.querySelector("#ai-source");
        if (src) src.textContent = "Рекомендации ИИ-модуля (ML API).";
      })
      .catch(() => {});
  }

  function referencePanel(ctx) {
    const statusRows = [
      ["Добавлена / Получена службой", "Технические статусы, ставятся системой автоматически", "—"],
      ["Принята", "В течение " + D.TIMERS.accept + " с после поступления карточки", "по желанию"],
      ["Не принята", "В течение " + D.TIMERS.accept + " с: место или тип не входят в зону службы, работа уже ведётся по другой карточке", "обязателен"],
      ["Начало реагирования", "Выезд сил и средств; далее — в течение " + D.TIMERS.respond / 60 + " мин на очередной статус", "по желанию"],
      ["Прибытие", "Силы и средства прибыли на место", "по желанию"],
      ["Проведение работ", "Начаты аварийно-восстановительные работы", "по желанию"],
      ["Работы завершены", "Работы окончены, карточка закрывается для правки", "по желанию"],
      ["Отказ от выполнения работ", "Реагирование начато, но работы на месте не проводились", "обязателен"],
      ["Не оповещено", "Служба не поставила «Принята / Не принята» за " + D.TIMERS.accept + " с", "—"],
      ["Не завершено", "После приёма не поставлен очередной статус в срок", "—"],
    ]
      .map((r) => `<tr><td data-label="Статус"><b>${r[0]}</b></td><td data-label="Условие">${r[1]}</td><td data-label="Комментарий">${r[2]}</td></tr>`)
      .join("");

    const types = ctx.INCIDENT_TYPES.map((t) => `<tr><td data-label="Тип">${ctx.esc(t.label)}</td><td data-label="Службы">${t.services.length ? ctx.esc(t.services.join(", ")) : '<span class="cell-muted">не оповещаются</span>'}</td></tr>`).join("");

    const surveys = Object.keys(D.SURVEYS)
      .map((k) => `<p><b>${k}:</b> ${D.SURVEYS[k].map((g) => g.label + " (" + g.options.join(" / ") + ")").join("; ")}</p>`)
      .join("");

    return `
      <div class="panel-head"><h2>Справочная база</h2></div>
      <div class="reference">
        <details open><summary>Статусы реагирования и регламент</summary>
          <div class="data-table-wrap"><table class="data-table"><thead><tr><th>Статус</th><th>Условие</th><th>Комментарий</th></tr></thead><tbody>${statusRows}</tbody></table></div>
          <p class="stat-hint">Статусы реагирования выбираются только последовательно.</p>
        </details>
        <details><summary>Классификатор типов происшествий и службы оповещения</summary>
          <div class="data-table-wrap"><table class="data-table"><thead><tr><th>Тип</th><th>Службы</th></tr></thead><tbody>${types}</tbody></table></div>
        </details>
        <details><summary>Опросные карты</summary><div class="info-block">${surveys}</div></details>
        <details><summary>Статусы заявителя и отметки по вызову</summary>
          <div class="info-block"><p><b>Статус заявителя:</b> очевидец, пострадавший, родственник, знакомый, ребёнок, участник.</p>
          <p><b>Отметки:</b> пострадавшие (с количеством), нет на месте, отказ от скорой, заблокированные, вызов на иностранном языке.</p>
          <p><b>Быстрое завершение:</b> «Нет контакта» и «Срыв звонка» сохраняют карточку без заполнения остальных полей.</p></div>
        </details>
        <details><summary>Как проходит занятие</summary>
          <div class="info-block"><p>Оператор принимает вызов (голосом через телефонию или текстом в чате с заявителем), заполняет карточку и отправляет диспетчеру. Диспетчер принимает или не принимает карточку в течение ${D.TIMERS.accept} с и ведёт статусы реагирования. Преподаватель раздаёт сценарии по местам и подтверждает оценку ИИ, администратор наблюдает за состоянием системы.</p></div>
        </details>
      </div>`;
  }

  window.DDS_TABS.push({ roles: ["student"], id: "stats", label: "Статистика", order: 30, render: operatorPanel, wire: wireTips });
  window.DDS_TABS.push({ roles: ["dispatcher"], id: "stats", label: "Статистика", order: 30, render: dispatcherPanel, wire: wireTips });
  window.DDS_TABS.push({ roles: ["student", "dispatcher"], id: "reference", label: "Справочная база", order: 40, render: referencePanel });
})();
