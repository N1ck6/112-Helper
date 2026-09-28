(function () {
  const D = window.DDS_DATA;

  function sentCards(list) {
    return list.filter((c) => c.status === "review");
  }

  function surveyCoverage(c) {
    const keys = [];
    (c.types || []).forEach((id) => {
      const set = D.TYPE_SURVEY[id];
      if (set && keys.indexOf(set) === -1) keys.push(set);
    });
    const total = keys.reduce((n, k) => n + D.SURVEYS[k].length, 0);
    if (!total) return 1;
    const filled = Object.keys(c.survey || {}).length;
    return Math.min(1, filled / total);
  }

  function gradeCard(c) {
    if (c.status !== "review") return null;
    let score = 100;
    const notes = [];
    if (surveyCoverage(c) < 0.6) {
      score -= 15;
      notes.push("опросная карта заполнена не полностью");
    }
    const a = c.address || {};
    if (!a.street || !a.house) {
      score -= 15;
      notes.push("в адресе не указаны улица и дом");
    }
    if (!a.okrug || !a.district) {
      score -= 5;
      notes.push("не указаны округ и район");
    }
    if (c.fillSeconds != null && c.fillSeconds > D.NORMS.fillSeconds) {
      const over = c.fillSeconds - D.NORMS.fillSeconds;
      score -= Math.min(25, Math.ceil(over / 4));
      notes.push("превышен норматив заполнения " + D.NORMS.fillSeconds + " с");
    }
    if (c.dds && c.dds.decision === "declined") {
      score -= 20;
      notes.push("диспетчер не принял карточку");
    }
    if (!c.description || c.description.length < 15) {
      score -= 10;
      notes.push("слишком краткое описание");
    }
    return { score: Math.max(0, score), notes: notes };
  }

  function avg(arr) {
    return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
  }

  function operatorStats(list, ws) {
    const mine = list.filter((c) => (c.source || "operator") === "operator" && (!ws || c.workstation === ws));
    const sent = sentCards(mine);
    const fill = sent.map((c) => c.fillSeconds).filter((x) => x != null);
    const grades = sent.map((c) => gradeCard(c).score);
    return {
      total: mine.length,
      sent: sent.length,
      empty: mine.filter((c) => c.status === "empty").length,
      declined: sent.filter((c) => c.dds.decision === "declined").length,
      accepted: sent.filter((c) => c.dds.decision === "accepted").length,
      avgFill: avg(fill),
      overNorm: fill.filter((x) => x > D.NORMS.fillSeconds).length,
      avgSurvey: avg(sent.map(surveyCoverage)),
      avgGrade: avg(grades),
      mistakes: collectMistakes(sent),
    };
  }

  function collectMistakes(sent) {
    const counts = {};
    sent.forEach((c) => gradeCard(c).notes.forEach((n) => (counts[n] = (counts[n] || 0) + 1)));
    return Object.keys(counts)
      .map((k) => ({ text: k, count: counts[k] }))
      .sort((a, b) => b.count - a.count);
  }

  function dispatcherStats(list) {
    const sent = sentCards(list);
    const decided = sent.filter((c) => c.dds.decisionAt);
    const respTimes = decided.map((c) => Math.round((c.dds.decisionAt - c.sentAt) / 1000)).filter((x) => x >= 0);
    const inTime = respTimes.filter((x) => x <= D.TIMERS.accept).length;
    return {
      total: sent.length,
      decided: decided.length,
      pending: sent.length - decided.length,
      accepted: decided.filter((c) => c.dds.decision === "accepted").length,
      declined: decided.filter((c) => c.dds.decision === "declined").length,
      avgAccept: avg(respTimes),
      inTimePct: respTimes.length ? Math.round((inTime / respTimes.length) * 100) : null,
      done: sent.filter((c) => c.dds.reaction === "done").length,
      refused: sent.filter((c) => c.dds.reaction === "refused").length,
    };
  }

  function recommendations(role, s) {
    const out = [];
    if (role === "student") {
      if (!s.sent) return ["Отправьте хотя бы одну карточку диспетчеру — тогда появятся рекомендации."];
      if (s.avgFill != null && s.avgFill > D.NORMS.fillSeconds) out.push("Среднее время заполнения " + Math.round(s.avgFill) + " с при нормативе " + D.NORMS.fillSeconds + " с: сначала выбирайте тип происшествия и адрес, детали уточняйте по ходу разговора.");
      if (s.avgSurvey != null && s.avgSurvey < 0.6) out.push("Опросная карта заполняется реже нормы — задавайте заявителю уточняющие вопросы из тегов: где, признаки, угроза людям.");
      s.mistakes.slice(0, 2).forEach((m) => out.push("Частая ошибка: " + m.text + " (" + m.count + ").")) ;
      if (s.declined) out.push("Диспетчер не принял " + s.declined + " карточек — перед отправкой сверяйте адрес и описание с репликами заявителя.");
      if (!out.length) out.push("Ошибок по текущим данным нет — попробуйте сложный сценарий.");
    } else {
      if (!s.total) return ["Пока нет карточек в потоке — смоделируйте поступление."];
      if (s.inTimePct != null && s.inTimePct < 100) out.push("В норматив приёма (" + D.TIMERS.accept + " с) уложилось " + s.inTimePct + "% решений — не откладывайте статус «Принята / Не принята».");
      if (s.declined) out.push("Для «Не принята» всегда указывайте причину и куда передана информация.");
      if (s.pending) out.push("Есть карточки без решения: " + s.pending + ". Просроченные попадают в статус «Не оповещено».");
      if (!out.length) out.push("Работа по регламенту, замечаний нет.");
    }
    return out;
  }

  window.DDS_METRICS = { gradeCard, operatorStats, dispatcherStats, recommendations, surveyCoverage };
})();
