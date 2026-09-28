/* Браузерный телефон: учебный звонок прямо со страницы, без софтфона и SIP.
 *
 * Голос обучающегося — микрофон + распознавание речи браузера (Web Speech API,
 * Chrome / Edge / Яндекс.Браузер); если распознавания нет или фраза не распозналась,
 * реплику можно напечатать. Собеседник говорит синтезом речи браузера
 * (мужской / женский русский голос по справочнику).
 *
 * Логика собеседников повторяет эталон ML-заглушки телефонии
 * (telephony/mocks/ml_dialogue.py): dispatch / report / applicant / incident_112.
 * Если в config.js задан ML_DIALOGUE_URL — реплики берутся из ML
 * (контракт POST /dialogue/turn, telephony/API.md §3), при ошибке — по правилам.
 *
 * События звонка — те же, что шлёт телефония по SSE (call.dialing, call.started,
 * call.utterance, call.ended, call.failed): telephony.js обрабатывает их одинаково,
 * отработки сохраняются в карточке так же.
 */
(function () {
  "use strict";

  const D = window.DDS_DATA || {};
  const cfg = window.APP_CONFIG || {};
  const ML_URL = String(cfg.ML_DIALOGUE_URL || "").replace(/\/$/, "");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;

  const MAX_TURNS = 12;
  const LISTEN_MS = 12000;  // сколько ждём реплику обучающегося
  const RING_MS = 2600;     // гудки перед ответом собеседника

  // Справочник учебных служб — копия telephony/virtual_caller/directory.json
  // (работает и без запущенной телефонии). Телефония доступна — берётся /directory.
  let directory = [
    { number: "2101", id: "mchs_101", service: "Служба 101 (МЧС)", aliases: ["101", "мчс", "пожарн"], name: "Петров Андрей", position: "Старший диспетчер ЦУКС", gender: "male", accept: "Я вас понял, информация принята. Высылаем пожарный расчёт.", leader: { name: "Громов Сергей", position: "Начальник караула ПСЧ-12", gender: "male" } },
    { number: "2102", id: "police_102", service: "Служба 102 (полиция)", aliases: ["102", "омвд", "мвд", "полиц"], name: "Смирнов Олег", position: "Оперативный дежурный ОМВД", gender: "male", accept: "Понял вас, информация принята. Направляем наряд.", leader: { name: "Кузнецов Илья", position: "Старший наряда ППС", gender: "male" } },
    { number: "2103", id: "smp_103", service: "Служба 103 (СМП)", aliases: ["103", "смп", "скорая"], name: "Ковалёва Елена", position: "Старший врач смены", gender: "female", accept: "Я вас поняла, информация принята. Бригада направлена.", leader: { name: "Орлова Марина", position: "Фельдшер выездной бригады", gender: "female" } },
    { number: "2104", id: "gas_104", service: "Служба 104 (Мосгаз)", aliases: ["104", "мосгаз", "газ"], name: "Лебедев Николай", position: "Диспетчер аварийной газовой службы", gender: "male", accept: "Понял, информация принята. Аварийная бригада выезжает." },
    { number: "2201", id: "mosvodokanal", service: "Мосводоканал", aliases: ["водоканал"], name: "Волков Дмитрий", position: "Диспетчер аварийной службы", gender: "male", accept: "Принял, информация принята. Аварийную бригаду направим.", leader: { name: "Зайцев Павел", position: "Мастер аварийной бригады", gender: "male" } },
    { number: "2202", id: "zhilishnik", service: "ГБУ «Жилищник»", aliases: ["жилищник"], name: "Сорокина Анна", position: "Диспетчер ОДС", gender: "female", accept: "Поняла вас, информация принята. Направляем сантехника и электрика." },
    { number: "2203", id: "uprava", service: "Управа района", aliases: ["упр. района", "управа", "управы"], name: "Белова Ольга", position: "Дежурный управы района", gender: "female", accept: "Поняла, информация принята. Доложу главе управы." },
    { number: "2204", id: "ods_psc", service: "ОДС ПСЦ", aliases: ["одс псц", "псц"], name: "Морозова Ирина", position: "Диспетчер объединённой диспетчерской службы", gender: "female", accept: "Поняла вас, информация принята." },
    { number: "2205", id: "gormost", service: "ГБУ «Гормост»", aliases: ["гормост"], name: "Николаев Виктор", position: "Дежурный диспетчер Гормоста", gender: "male", accept: "Понял, информация принята. Выезжает дежурная бригада.", leader: { name: "Фёдоров Артём", position: "Бригадир дежурной бригады", gender: "male" } },
    { number: "2206", id: "mosgortrans", service: "Мосгортранс", aliases: ["мосгортранс"], name: "Егоров Максим", position: "Дежурный диспетчер Мосгортранса", gender: "male", accept: "Понял вас, информация принята. Изменим маршруты в районе." },
    { number: "2207", id: "codd", service: "ЦОДД", aliases: ["цодд", "дорожного движения"], name: "Павлов Роман", position: "Дежурный диспетчер ситуационного центра ЦОДД", gender: "male", accept: "Понял, информация принята. Направим эвакуатор и выставим ограждение." },
    { number: "2208", id: "mosbez", service: "Мос.Без.", aliases: ["мос.без", "мосбез", "московская безопасность"], name: "Карпова Светлана", position: "Оперативный дежурный Мос.Без.", gender: "female", accept: "Поняла вас, информация принята. Направляем дежурную группу." },
  ];

  function setDirectory(list) {
    if (Array.isArray(list) && list.length) directory = list;
  }

  function findContact(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return null;
    return directory.find((c) => c.number === q || c.id === q || String(c.service).toLowerCase() === q)
      || directory.find((c) => (c.aliases || []).some((a) => q.indexOf(a) !== -1))
      || null;
  }

  // ------------------------------------------------ правила собеседников ---
  // Порт telephony/mocks/ml_dialogue.py: те же фразы и условия.
  const STOP = ["москва", "город", "улица", "проезд", "проспект", "шоссе", "бульвар", "переулок",
                "площадь", "набережная", "корпус", "строение", "квартира", "подъезд", "район"];
  const ASK_ADDRESS = "Назовите, пожалуйста, точный адрес происшествия.";
  const REPORT_TEXT = {
    arrival: "Прибыли на место{addr}. Приступаем к работам.",
    in_progress: "Ведём работы{addr}, обстановка под контролем, помощь не требуется.",
    completed: "Работы{addr} завершены, возвращаемся в подразделение.",
    refused: "Выполнение работ{addr} невозможно, требуется другая служба.",
  };

  const said = (history, role) => history.filter((h) => h.role === role).map((h) => h.text || "");
  const matches = (text, words) => words.some((w) => text.indexOf(w) !== -1);
  const surname = (p) => String((p && p.name) || "").split(" ")[0];
  const female = (p) => !!p && p.gender === "female";
  const reply = (text, end) => ({ reply_text: text, end_call: !!end });

  function trailingSilence(history) {
    let n = 0;
    const list = said(history, "operator");
    for (let i = list.length - 1; i >= 0 && !list[i].trim(); i--) n++;
    return n;
  }

  // «Москва, ул. Ясный проезд, 10» -> ["ясн"]: основы значимых слов (ловит падежи)
  function addressStems(address) {
    const words = String(address || "").toLowerCase().match(/[а-яёa-z]{4,}/g) || [];
    return words.filter((w) => STOP.indexOf(w) === -1).map((w) => w.slice(0, Math.max(3, w.length - 2)));
  }
  function addressMentioned(text, card) {
    const stems = addressStems(card && card.address);
    return !stems.length || stems.some((s) => text.indexOf(s) !== -1);
  }

  function dispatchTurn(p, card, turn, history, op) {
    if (turn === 0 || op == null) return reply(`${p.position || "Дежурный"} ${surname(p)}, слушаю вас.`.replace(/\s+/g, " "));
    const text = op.trim().toLowerCase();
    if (!text) return trailingSilence(history) >= 2 ? reply("Вас не слышно. Перезвоните, пожалуйста.", true) : reply("Алло, слушаю вас, говорите.");
    if (said(history, "caller").indexOf(ASK_ADDRESS) === -1 && !addressMentioned(text, card) && turn < 4) return reply(ASK_ADDRESS);
    return reply(p.accept || (female(p) ? "Я вас поняла, информация принята." : "Я вас понял, информация принята."), true);
  }

  function reportBody(card, report) {
    report = report || {};
    if (report.text) return report.text;
    const tpl = REPORT_TEXT[report.status] || REPORT_TEXT.arrival;
    return tpl.replace("{addr}", card && card.address ? " по адресу " + card.address : "");
  }

  function reportTurn(p, card, report, turn, history, op) {
    const body = reportBody(card, report);
    if (turn === 0 || op == null) return reply(`Дежурно-диспетчерская служба? Говорит ${p.position || "старший группы"} ${surname(p)}. ${body} Как приняли?`);
    if (op.trim()) return reply("Понял вас, конец связи.", true);
    if (trailingSilence(history) >= 2) return reply("Связь плохая, доложу повторно.", true);
    return reply("ДДС, как слышите? Повторяю: " + body);
  }

  function applicantTurn(p, card, turn, history, op) {
    card = card || {};
    if (turn === 0 || op == null) return reply("Алло?");
    const text = op.trim().toLowerCase();
    if (!text) return trailingSilence(history) >= 2 ? reply("Ничего не слышно, до свидания.", true) : reply("Алло, говорите!");
    const story = card.description || card.title || "у нас тут происшествие";
    if (!said(history, "caller").some((s) => s.indexOf(story) !== -1)) {
      if (!matches(text, ["112", "сто двенадцать", "звонил", "обращал", "вызов"]) && turn === 1) return reply("Кто это? По какому вопросу?");
      return reply(`Да, ${female(p) ? "звонила" : "звонил"}. ${story}. Когда приедут?`);
    }
    return reply("Хорошо, спасибо, ждём.", true);
  }

  // Заявитель 112: сценарий преподавателя (ответы по ключевым словам — DDS_DATA.callerReply)
  function incidentTurn(scenario, turn, history, op) {
    if (turn === 0 || op == null) return reply((scenario && scenario.opening) || "Алло! Нужна помощь!");
    const text = op.trim();
    if (!text) return trailingSilence(history) >= 2 ? reply("Вас не слышно, я перезвоню.", true) : reply("Алло? Вы меня слышите?");
    const answer = D.callerReply ? D.callerReply(scenario, text) : "Повторите, пожалуйста.";
    const closing = /спасибо|до свидания|ожидайте|выехал|направлен|бригад/i.test(text);
    return reply(answer, closing || turn >= MAX_TURNS - 1);
  }

  function rulesTurn(call, turn, op) {
    const p = call.persona || {};
    if (call.call_type === "dispatch") return dispatchTurn(p, call.card, turn, call.transcript, op);
    if (call.call_type === "report") return reportTurn(p, call.card, call.report, turn, call.transcript, op);
    if (call.call_type === "applicant") return applicantTurn(p, call.card, turn, call.transcript, op);
    if (call.call_type === "echo") return reply(turn === 0 ? "Эхо-тест. Скажите что-нибудь." : op ? "Вы сказали: " + op : "Ничего не слышно.", turn > 0);
    return incidentTurn(call.scenario, turn, call.transcript, op);
  }

  async function nextTurn(call, turn, op) {
    if (ML_URL) {
      try {
        const res = await fetch(ML_URL + "/dialogue/turn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: call.session_id, scenario_id: call.scenario_id || "", call_id: call.call_id,
            call_type: call.call_type, persona: call.persona,
            context: { card: call.card, report: call.report || null, trainee: call.trainee },
            turn: turn, history: call.transcript.map((t) => ({ role: t.role, text: t.text })), operator_text: op,
          }),
        });
        const data = await res.json();
        if (res.ok && data && typeof data.reply_text === "string") return data;
      } catch (e) { /* ML недоступен — отвечаем по правилам */ }
    }
    return rulesTurn(call, turn, op);
  }

  // ------------------------------------------------------------- голос ---
  let voices = [];
  function loadVoices() {
    voices = synth ? synth.getVoices().filter((v) => /^ru/i.test(v.lang)) : [];
  }
  if (synth) {
    loadVoices();
    synth.addEventListener && synth.addEventListener("voiceschanged", loadVoices);
  }

  const MALE = /pavel|dmitr|dmitri|maxim|yuri|юрий|павел|дмитрий|максим|male|муж/i;
  function pickVoice(gender) {
    if (!voices.length) return null;
    const male = voices.filter((v) => MALE.test(v.name));
    const other = voices.filter((v) => !MALE.test(v.name));
    if (gender === "male") return male[0] || voices[0];
    return other[0] || voices[0];
  }

  function speak(text, gender, call) {
    return new Promise((resolve) => {
      if (!synth || !text) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ru-RU";
      const v = pickVoice(gender);
      if (v) u.voice = v;
      // нет мужского голоса в системе — хотя бы понижаем тон
      if (gender === "male" && (!v || !MALE.test(v.name))) u.pitch = 0.6;
      u.rate = 1.05;
      let done = false;
      const finish = () => { if (!done) { done = true; resolve(); } };
      u.onend = finish;
      u.onerror = finish;
      call.utter = u;
      synth.cancel();
      synth.speak(u);
      // страховка: onend иногда не приходит (Chrome на длинных фразах)
      setTimeout(finish, 1500 + text.length * 110);
    });
  }

  // Гудки (425 Гц: 1 с тон / 4 с пауза — как в телефонной сети РФ, здесь укорочено)
  let audioCtx = null;
  function ring(ms, call) {
    return new Promise((resolve) => {
      try {
        audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.frequency.value = 425;
        gain.gain.value = 0;
        osc.connect(gain).connect(audioCtx.destination);
        const t0 = audioCtx.currentTime;
        for (let t = 0; t < ms / 1000; t += 2) {
          gain.gain.setValueAtTime(0.08, t0 + t);
          gain.gain.setValueAtTime(0, t0 + t + 1);
        }
        osc.start();
        osc.stop(t0 + ms / 1000);
        call.osc = osc;
      } catch (e) { /* без звука — просто пауза */ }
      call.timer = setTimeout(resolve, ms);
    });
  }

  // Реплика обучающегося: распознавание речи или набранный текст — что раньше
  function listen(call, onInterim) {
    return new Promise((resolve) => {
      let finished = false;
      let heard = "";
      const finish = (text) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        call.pending = null;
        if (call.rec) { try { call.rec.abort(); } catch (e) { /* уже остановлено */ } call.rec = null; }
        resolve(String(text || "").trim());
      };
      call.pending = finish;
      const timer = setTimeout(() => finish(heard), LISTEN_MS);
      if (call.queued) {
        // реплику напечатали, пока собеседник ещё говорил
        const text = call.queued;
        call.queued = null;
        return finish(text);
      }
      if (!Recognition || call.noMic) return;
      try {
        const rec = new Recognition();
        rec.lang = "ru-RU";
        rec.interimResults = true;
        rec.continuous = false;
        rec.onresult = (e) => {
          let interim = "";
          let final = "";
          for (let i = 0; i < e.results.length; i++) {
            if (e.results[i].isFinal) final += e.results[i][0].transcript;
            else interim += e.results[i][0].transcript;
          }
          heard = (final || interim).trim();
          if (onInterim) onInterim(heard);
          if (final) finish(final);
        };
        rec.onerror = (e) => {
          // нет доступа к микрофону / сервису распознавания — остаёмся на вводе текстом
          if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "network") {
            call.noMic = e.error;
            if (call.onMicError) call.onMicError(e.error);
          }
        };
        rec.onend = () => { if (!finished && heard) finish(heard); };
        call.rec = rec;
        rec.start();
      } catch (e) {
        call.noMic = "unsupported";
      }
    });
  }

  // Голос заявителя по «Фамилия Имя»: Петрова / Лебедева / Ольга -> женский
  const MALE_NAMES_A = ["никита", "илья", "фома", "кузьма", "лука", "савва"];
  function genderByName(full) {
    const words = String(full || "").toLowerCase().split(/[\s,]+/).filter(Boolean);
    if (words.some((w) => /(ова|ева|ёва|ина|ская|цкая)$/.test(w))) return "female";
    if (words.slice(0, 2).some((w) => /[ая]$/.test(w) && w.length > 2 && MALE_NAMES_A.indexOf(w) === -1)) return "female";
    return "male";
  }

  // ------------------------------------------------------------- звонок ---
  let current = null;

  function event(call, type, extra) {
    const data = Object.assign({
      event: type, timestamp: new Date().toISOString(), call_id: call.call_id, session_id: call.session_id,
      scenario_id: call.scenario_id || "", call_type: call.call_type, trainee: call.trainee,
      persona: call.persona, dialed: call.dialed || null, web: true,
    }, extra || {});
    if (call.emit) call.emit(type, data);
  }

  function stopMedia(call) {
    clearTimeout(call.timer);
    if (call.osc) { try { call.osc.stop(); } catch (e) { /* уже остановлен */ } }
    if (synth) synth.cancel();
    if (call.pending) call.pending("");
  }

  function end(call, reason) {
    if (call.status === "ended") return;
    const wasTalking = call.status === "in_progress";
    call.status = "ended";
    stopMedia(call);
    if (current === call) current = null;
    if (!wasTalking) {
      event(call, "call.failed", { reason: reason === "operator_hangup" ? "rejected" : reason });
      return;
    }
    event(call, "call.ended", {
      reason: reason,
      duration_sec: Math.round((Date.now() - call.answered_at) / 1000),
      recording_url: null,
      card_id: call.card && call.card.id,
      transcript: call.transcript,
    });
  }

  async function run(call) {
    event(call, "call.dialing");
    await ring(call.incoming ? 1200 : RING_MS, call);
    if (call.status === "ended") return;
    if (!call.persona && call.call_type !== "incident_112" && call.call_type !== "echo") {
      call.status = "in_progress";
      call.answered_at = Date.now();
      event(call, "call.started", { direction: "outbound" });
      const text = "Набранный номер не обслуживается.";
      call.transcript.push({ turn: 0, role: "caller", text: text });
      event(call, "call.utterance", { turn: 0, role: "caller", text: text });
      await speak(text, "female", call);
      return end(call, "unknown_number");
    }
    call.status = "in_progress";
    call.answered_at = Date.now();
    event(call, "call.started", { direction: call.incoming ? "inbound" : "outbound", card_id: call.card && call.card.id });

    let op = null;
    for (let turn = 0; turn < MAX_TURNS; turn++) {
      const r = await nextTurn(call, turn, op);
      if (call.status === "ended") return;
      const voice = r.voice || (call.persona && call.persona.gender) || "female";
      call.transcript.push({ turn: turn, role: "caller", text: r.reply_text });
      event(call, "call.utterance", { turn: turn, role: "caller", text: r.reply_text });
      await speak(r.reply_text, voice, call);
      if (call.status === "ended") return;
      if (r.end_call) return end(call, "completed");
      if (call.onListen) call.onListen(true);
      op = await listen(call, call.onInterim);
      if (call.onListen) call.onListen(false);
      if (call.status === "ended") return;
      call.transcript.push({ turn: turn + 1, role: "operator", text: op });
      event(call, "call.utterance", { turn: turn + 1, role: "operator", text: op });
    }
    end(call, "max_turns");
  }

  /* Начать звонок. opts: {call_type, dial, service, card, report, scenario_id, trainee, session_id}
   * hooks: {emit(type, data), onListen(bool), onInterim(text), onMicError(code)} */
  function start(opts, hooks) {
    if (current) return null;
    const call = Object.assign({
      call_id: "web-" + Date.now().toString(36),
      session_id: opts.session_id || "web",
      trainee: opts.trainee,
      card: opts.card || null,
      report: opts.report || null,
      scenario_id: opts.scenario_id || "",
      transcript: [],
      status: "dialing",
      created_at: Date.now(),
    }, hooks || {});

    let type = opts.call_type || "dispatch";
    let persona = null;
    if (opts.dial) {
      const n = String(opts.dial);
      call.dialed = n;
      const short = { "101": "2101", "102": "2102", "103": "2103", "104": "2104" }[n];
      if (n === "3000") type = "applicant";
      else if (n === "600") type = "echo";
      else if (n === "112" || n === "700" || n === "701") type = "incident_112";
      else { type = "dispatch"; persona = findContact(short || n); if (persona && persona.number !== (short || n)) persona = null; }
    } else if (type === "dispatch" || type === "report") {
      persona = findContact(opts.service);
    }
    if (type === "report") {
      const svc = persona || findContact("2101");
      const leader = (svc && svc.leader) || { name: svc ? svc.name : "", position: "Старший группы", gender: "male" };
      persona = Object.assign({}, leader, { service: svc ? svc.service : "", number: svc ? svc.number : "" });
      call.incoming = true;
    }
    if (type === "applicant") {
      const name = String((call.card && call.card.caller) || "Заявитель");
      persona = { service: "Заявитель", name: name, number: (call.card && call.card.phone) || "3000", gender: genderByName(name) };
    }
    if (type === "incident_112") {
      call.incoming = true;
      const all = D.getScenarios ? D.getScenarios() : [];
      call.scenario = all.find((s) => s.id === opts.scenario_id) || all[0] || null;
      const who = call.scenario ? call.scenario.caller.name : "Заявитель";
      persona = { service: "Вызов 112", name: who, gender: genderByName(who) };
    }
    call.call_type = type;
    call.persona = persona;
    current = call;
    run(call).catch(() => end(call, "internal_error"));
    return call;
  }

  function hangup() {
    if (current) end(current, "operator_hangup");
  }

  // Напечатанная реплика вместо голоса (или раньше, чем распознавание закончит)
  function say(text) {
    if (!current || current.status !== "in_progress") return;
    if (current.pending) current.pending(text);
    else current.queued = [current.queued, text].filter(Boolean).join(" ");
  }

  window.DDS_WEBPHONE = {
    supported: !!synth,
    speechInput: !!Recognition,
    start: start,
    hangup: hangup,
    say: say,
    active: () => current,
    setDirectory: setDirectory,
    directory: () => directory.slice(),
  };
})();
