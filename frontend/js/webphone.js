/* Браузерный телефон: учебный звонок прямо со страницы, без софтфона и SIP.
 *
 * Голос обучающегося — микрофон + распознавание речи браузера (Web Speech API,
 * Chrome / Edge / Яндекс.Браузер); если распознавания нет или фраза не распозналась,
 * реплику можно напечатать. Собеседник говорит синтезом речи браузера
 * (мужской / женский русский голос по справочнику).
 *
 * Реплики собеседников — те же, что в телефонии: ML-сервис (POST {ML_DIALOGUE_URL}/dialogue/turn,
 * telephony/API.md §3); заявитель 112 по карточке занятия — через Backend, который подставляет
 * скрытую от браузера карточку. Справочник служб — из телефонии (GET /directory).
 *
 * События звонка — те же, что шлёт телефония по SSE (call.dialing, call.started,
 * call.utterance, call.ended, call.failed): telephony.js обрабатывает их одинаково,
 * отработки сохраняются в карточке так же.
 */
(function () {
  "use strict";

  const cfg = window.APP_CONFIG || {};
  const ML_URL = String(cfg.ML_DIALOGUE_URL || "").replace(/\/$/, "");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;

  const MAX_TURNS = 12;
  const SCENARIOS_112 = { "700": "scenario_001", "701": "scenario_002", "112": "scenario_001" };
  const LISTEN_MS = 12000;  // сколько ждём реплику обучающегося
  const RING_MS = 2600;     // гудки перед ответом собеседника

  // Справочник учебных служб — telephony/virtual_caller/directory.json (telephony.js: GET /directory)
  let directory = [];

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

  const reply = (text, end) => ({ reply_text: text, end_call: !!end });
  const LOST = reply("Извините, вас плохо слышно, связь прерывается.", true);

  // Реплика собеседника. Нет ответа от сервера — собеседник «теряет связь» и звонок
  // заканчивается (как в телефонии при сбое ML), а не продолжается по выдуманным правилам.
  async function nextTurn(call, turn, op) {
    if (call.call_type === "echo") return reply(turn === 0 ? "Эхо-тест. Скажите что-нибудь." : op ? "Вы сказали: " + op : "Ничего не слышно.", turn > 0);
    const history = call.transcript.map((t) => ({ role: t.role, text: t.text }));
    // заявитель 112 по карточке занятия: реплику готовит ML по карточке, которую подставляет Backend
    if (call.attempt_id) {
      try {
        const data = await window.DDS_API.request("POST", "/training/attempts/" + call.attempt_id + "/dialogue", {
          turn: turn, history: history, operator_text: op,
        });
        if (data && typeof data.reply_text === "string") return data;
      } catch (e) { /* ниже — обрыв связи */ }
      call.lost = true;
      return LOST;
    }
    if (ML_URL) {
      try {
        const res = await fetch(ML_URL + "/dialogue/turn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: call.session_id, scenario_id: call.scenario_id || "", call_id: call.call_id,
            call_type: call.call_type, persona: call.persona,
            context: { card: call.card, report: call.report || null, trainee: call.trainee },
            turn: turn, history: history, operator_text: op,
          }),
        });
        const data = await res.json();
        if (res.ok && data && typeof data.reply_text === "string") return data;
      } catch (e) { /* ниже — обрыв связи */ }
    }
    call.lost = true;
    return LOST;
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
      if (r.end_call) return end(call, call.lost ? "ml_error" : "completed");
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
      attempt_id: opts.attempt_id || null,
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
      // 700 / 701 — учебные сценарии ML (пожар в квартире / ДТП), как при наборе с трубки
      if (!call.attempt_id && !call.scenario_id) call.scenario_id = SCENARIOS_112[call.dialed] || SCENARIOS_112["700"];
      const male = call.scenario_id === SCENARIOS_112["701"];
      persona = { service: "Вызов 112", name: "Заявитель", gender: male ? "male" : "female" };
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
