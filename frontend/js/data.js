(function () {
  const TIMERS = { accept: 30, respond: 180 };
  const NORMS = { fillSeconds: 90 };

  const REACTION_STATUSES = [
    { id: "start", label: "Начало реагирования" },
    { id: "arrival", label: "Прибытие" },
    { id: "works", label: "Проведение работ" },
    { id: "done", label: "Работы завершены" },
  ];
  const REACTION_REFUSED = { id: "refused", label: "Отказ от выполнения работ" };

  const WORKSTATIONS = Array.from({ length: 20 }, (_, i) => "ws" + String(i + 1).padStart(2, "0"));

  const SURVEYS = {
    fire: [
      { key: "where", label: "Где", options: ["Улица", "Транспорт", "Дом", "Здание/объект", "Опасный объект"] },
      { key: "sign", label: "Признак", options: ["Дым", "Открытое пламя", "Запах гари", "Сработала сигнализация"] },
      { key: "threat", label: "Угроза людям", options: ["Да", "Нет"] },
      { key: "evac", label: "Требуется эвакуация", options: ["Да", "Нет"] },
      { key: "access", label: "Доступ", options: ["Есть", "Нет доступа"] },
    ],
    medical: [
      { key: "who", label: "Кому плохо", options: ["Взрослый", "Ребёнок", "Пожилой"] },
      { key: "conscious", label: "Сознание", options: ["Есть", "Нет"] },
      { key: "breath", label: "Дыхание", options: ["Есть", "Нет"] },
      { key: "bleeding", label: "Кровотечение", options: ["Да", "Нет"] },
    ],
    dtp: [
      { key: "kind", label: "Вид ДТП", options: ["Столкновение", "Наезд на пешехода", "Опрокидывание"] },
      { key: "injured", label: "Есть пострадавшие", options: ["Да", "Нет"] },
      { key: "blocked", label: "Движение перекрыто", options: ["Да", "Нет"] },
      { key: "fuel", label: "Течёт топливо", options: ["Да", "Нет"] },
    ],
    communal: [
      { key: "where", label: "Где", options: ["Двор", "Подъезд", "Подвал", "Улица"] },
      { key: "threat", label: "Угроза людям", options: ["Да", "Нет"] },
      { key: "scale", label: "Масштаб", options: ["Один дом", "Несколько домов", "Квартал"] },
    ],
    security: [
      { key: "count", label: "Число лиц", options: ["Один", "Двое", "Группа"] },
      { key: "weapon", label: "Оружие", options: ["Да", "Нет", "Неизвестно"] },
      { key: "where", label: "Где", options: ["Улица", "Подъезд", "Подвал/чердак", "Квартира"] },
    ],
  };

  const TYPE_SURVEY = {
    fire_flat: "fire", fire_entrance: "fire", fire_trash: "fire", smoke: "fire", fuel_spill: "fire", gas_smell: "fire",
    medical: "medical", dtp: "dtp", suspicious: "security",
    pipe_burst: "communal", open_hatch: "communal", tree_fall: "communal", power_outage: "communal",
  };

  const DEFAULT_CLUSTERS = [
    { id: "fire", title: "Пожары и задымления", type: "Пожар", note: "Горение в квартирах и подъездах, мусор, задымление" },
    { id: "road", title: "ДТП и транспорт", type: "ДТП", note: "Столкновения, наезды, разлив топлива" },
    { id: "utility", title: "Коммунальные аварии", type: "ЖКХ", note: "Прорывы, люки, деревья, отключения" },
    { id: "medical", title: "Медицинские вызовы", type: "Медицина", note: "Плохо человеку, ребёнок, отравление" },
    { id: "order", title: "Правопорядок", type: "Правопорядок", note: "Подозрительные лица, шум, нарушение порядка" },
    { id: "other", title: "Прочие сценарии", type: "Прочее", note: "Сценарии без своего кластера" },
  ];

  function makeScenario(o) {
    const injuredText = o.injured ? o.injuredText || "Да, есть пострадавший, ему нужна помощь." : "Пострадавших нет.";
    return {
      id: o.id,
      clusterId: o.cluster,
      title: o.title,
      difficulty: o.difficulty || "Средняя",
      types: o.types,
      approved: true,
      generated: !!o.generated,
      caller: { name: o.name, status: o.status || "Очевидец", phone: o.phone },
      address: o.address,
      description: o.description,
      injured: !!o.injured,
      opening: o.opening,
      answers: [
        { keys: "адрес|где|улиц|дом|место", text: o.addressSpoken || o.address + "." },
        { keys: "имя|фамили|как вас|представ", text: o.name + "." },
        { keys: "что случил|что происход|расскаж", text: o.description + "." },
        { keys: "пострадав|ранен|люди|кто|скорая|врач", text: injuredText },
        { keys: "телефон|номер", text: "Звоню с этого номера, он у вас должен определиться." },
      ].concat(o.extra || []),
    };
  }

  const DEFAULT_SCENARIOS = [
    makeScenario({
      id: "scenario_001", cluster: "fire", generated: true, title: "Пожар в квартире", difficulty: "Средняя", types: ["fire_flat"],
      name: "Иванов Иван", phone: "+7 (495) 123-45-67", address: "Москва, ул. Ясный проезд, 10, кв. 12",
      addressSpoken: "Москва, Ясный проезд, дом 10, третий подъезд, квартира 12.",
      description: "В соседней квартире пожар, из-под двери идёт дым", injured: true,
      injuredText: "Кажется, внутри остался человек, он не выходит.",
      opening: "Алло! У нас в соседней квартире пожар, дым идёт в подъезд!",
      extra: [{ keys: "огонь|пламя|дым|видн|горит", text: "Пламени не вижу, только густой дым и слышны крики." }],
    }),
    makeScenario({
      id: "fire_002", cluster: "fire", title: "Пожар в подъезде", difficulty: "Лёгкая", types: ["fire_entrance"],
      name: "Козлов Дмитрий", phone: "+7 (499) 300-11-22", address: "Москва, ул. Молостовых, 11, 2 подъезд",
      description: "В подъезде горят почтовые ящики, пахнет гарью",
      opening: "Здравствуйте, у нас в подъезде горят почтовые ящики!",
      extra: [{ keys: "огонь|пламя|дым|видн|горит", text: "Горит на первом этаже, дым поднимается по лестнице." }],
    }),
    makeScenario({
      id: "fire_003", cluster: "fire", title: "Горит мусор во дворе", difficulty: "Лёгкая", types: ["fire_trash"],
      name: "Лебедева Ольга", phone: "+7 (916) 555-40-03", address: "Москва, Шоссейная ул., 62",
      description: "Во дворе горят мусорные баки рядом с детской площадкой",
      opening: "Добрый день, во дворе горят мусорные баки, рядом дети!",
      extra: [{ keys: "огонь|пламя|дым|видн|горит", text: "Пламя высокое, баки стоят у самого дома." }],
    }),
    makeScenario({
      id: "fire_004", cluster: "fire", generated: true, title: "Задымление в подвале", difficulty: "Сложная", types: ["smoke"],
      name: "Григорьев Сергей", phone: "+7 (903) 700-18-44", address: "Москва, ул. Профсоюзная, 45, подвал",
      description: "Из подвального окна идёт густой дым, запах гари в первом подъезде", injured: true,
      injuredText: "В подвале мог остаться слесарь, он не отвечает.",
      opening: "Помогите, из подвала валит дым, в подъезде нечем дышать!",
      extra: [{ keys: "огонь|пламя|дым|видн|горит", text: "Огня не видно, дым чёрный и очень плотный." }],
    }),
    makeScenario({
      id: "scenario_002", cluster: "road", generated: true, title: "ДТП на проспекте", difficulty: "Лёгкая", types: ["dtp"],
      name: "Петрова Анна", status: "Участник", phone: "+7 (903) 555-12-09", address: "Москва, Ленинский проспект, 15",
      addressSpoken: "Ленинский проспект, дом 15, напротив аптеки.",
      description: "Столкновение двух автомобилей, есть пострадавшая", injured: true,
      injuredText: "Пассажирке во второй машине плохо, у неё кровь на лице.",
      opening: "Здравствуйте, я попала в аварию на Ленинском проспекте!",
      extra: [{ keys: "топлив|бензин|течёт|дым", text: "Из-под второй машины что-то капает." }],
    }),
    makeScenario({
      id: "road_002", cluster: "road", title: "ДТП с разливом топлива", difficulty: "Сложная", types: ["dtp", "fuel_spill"],
      name: "Смирнов Алексей", status: "Участник", phone: "+7 (925) 410-77-30", address: "Москва, Кутузовский проспект, 30",
      description: "Грузовик столкнулся с легковой машиной, из бака течёт солярка", injured: true,
      injuredText: "Водитель легковой зажат, сам выбраться не может.",
      opening: "Срочно! На Кутузовском грузовик врезался в легковушку, течёт топливо!",
      extra: [{ keys: "топлив|бензин|течёт|солярк", text: "Лужа уже метра три, рядом искрят провода." }],
    }),
    makeScenario({
      id: "road_003", cluster: "road", title: "Наезд на пешехода", difficulty: "Средняя", types: ["dtp"],
      name: "Ковалёва Марина", phone: "+7 (916) 222-09-81", address: "Москва, ул. Тверская, 8",
      description: "Автомобиль сбил женщину на пешеходном переходе, водитель на месте", injured: true,
      injuredText: "Женщина лежит на дороге, в сознании, жалуется на ногу.",
      opening: "Здравствуйте, на переходе сбили человека, скорее приезжайте!",
    }),
    makeScenario({
      id: "util_001", cluster: "utility", title: "Прорыв трубы в подвале", difficulty: "Лёгкая", types: ["pipe_burst"],
      name: "Орлов Пётр", phone: "+7 (495) 777-31-10", address: "Москва, ул. Тверская, 12",
      description: "В подвале прорвало трубу, вода заливает подъезд",
      opening: "Алло, у нас в подвале хлещет вода из трубы!",
    }),
    makeScenario({
      id: "util_002", cluster: "utility", generated: true, title: "Открытый люк во дворе", difficulty: "Лёгкая", types: ["open_hatch"],
      name: "Никитина Светлана", phone: "+7 (903) 118-55-62", address: "Москва, ул. Профсоюзная, 45, двор",
      description: "Во дворе открыт канализационный люк, рядом играют дети",
      opening: "Здравствуйте, во дворе открытый люк, там дети бегают!",
    }),
    makeScenario({
      id: "util_003", cluster: "utility", title: "Упавшее дерево на проезде", difficulty: "Средняя", types: ["tree_fall"],
      name: "Фёдоров Игорь", phone: "+7 (926) 640-29-17", address: "Москва, Открытое шоссе, 12",
      description: "Дерево упало на проезд и перекрыло дорогу, задело провода",
      opening: "Добрый день, на Открытом шоссе дерево упало на дорогу!",
      extra: [{ keys: "провод|искр|электр", text: "Провода провисли, что-то искрит." }],
    }),
    makeScenario({
      id: "util_004", cluster: "utility", title: "Отключение электроэнергии", difficulty: "Средняя", types: ["power_outage"],
      name: "Зайцева Татьяна", phone: "+7 (495) 333-70-08", address: "Москва, ул. Молостовых, 11",
      description: "В доме второй час нет света, в лифте застряли люди", injured: false,
      opening: "Здравствуйте, у нас во всём доме нет света, а в лифте люди!",
    }),
    makeScenario({
      id: "med_001", cluster: "medical", title: "Плохо пожилому человеку", difficulty: "Лёгкая", types: ["medical"],
      name: "Соколова Мария", status: "Родственник", phone: "+7 (916) 480-12-55", address: "Москва, ул. Ясный проезд, 4, кв. 31",
      description: "Пожилой отец жалуется на боль в груди, бледный, тяжело дышит", injured: true,
      injuredText: "Отцу 72 года, боль за грудиной, в сознании.",
      opening: "Помогите, папе плохо, у него болит сердце!",
      extra: [{ keys: "сознани|дыша|дыхани", text: "Он в сознании, но дышит тяжело." }],
    }),
    makeScenario({
      id: "med_002", cluster: "medical", generated: true, title: "Ребёнок потерял сознание", difficulty: "Сложная", types: ["medical"],
      name: "Алексеева Ирина", status: "Родственник", phone: "+7 (903) 600-45-19", address: "Москва, Шоссейная ул., 62, кв. 8",
      description: "Ребёнок четырёх лет упал и потерял сознание, не реагирует", injured: true,
      injuredText: "Мальчик четырёх лет, лежит, глаза закрыты.",
      opening: "Скорее, у меня ребёнок упал и не приходит в себя!",
      extra: [{ keys: "сознани|дыша|дыхани", text: "Дышит, но очень слабо, на голос не реагирует." }],
    }),
    makeScenario({
      id: "med_003", cluster: "medical", title: "Отравление угарным газом", difficulty: "Сложная", types: ["medical", "gas_smell"],
      name: "Тимофеев Андрей", phone: "+7 (499) 905-33-71", address: "Москва, ул. Тверская, 12, кв. 5",
      description: "В квартире запах газа, у жены и сына кружится голова, тошнит", injured: true,
      injuredText: "Жена и сын, им плохо, я тоже чувствую слабость.",
      opening: "Помогите, у нас в квартире пахнет газом, всем плохо!",
      extra: [{ keys: "газ|запах|плита", text: "Запах сильный, на кухне, плиту мы не включали." }],
    }),
    makeScenario({
      id: "ord_001", cluster: "order", generated: true, title: "Подозрительные лица на чердаке", difficulty: "Средняя", types: ["suspicious"],
      name: "Лебедева Ольга", phone: "+7 (916) 555-40-03", address: "Москва, Шоссейная ул., 62",
      description: "На чердаке слышны шаги, двое мужчин с сумками не из нашего дома",
      opening: "Здравствуйте, на чердаке нашего дома кто-то ходит.",
    }),
    makeScenario({
      id: "ord_002", cluster: "order", title: "Шум и драка во дворе", difficulty: "Лёгкая", types: ["suspicious"],
      name: "Воронин Павел", phone: "+7 (925) 118-90-24", address: "Москва, ул. Профсоюзная, 45, двор",
      description: "Во дворе группа людей дерётся, слышны крики", injured: true,
      injuredText: "Один человек упал, кажется, ему разбили голову.",
      opening: "Алло, у нас во дворе драка, скорее вышлите наряд!",
    }),
  ];

  function readCustomClusters() {
    return readJson("ddsClusters", []);
  }

  function getClusters() {
    return DEFAULT_CLUSTERS.concat(readCustomClusters());
  }

  function saveCluster(cluster) {
    const list = readCustomClusters();
    const idx = list.findIndex((c) => c.id === cluster.id);
    if (idx === -1) list.push(cluster);
    else list[idx] = cluster;
    localStorage.setItem("ddsClusters", JSON.stringify(list));
  }

  function deleteCluster(id) {
    localStorage.setItem("ddsClusters", JSON.stringify(readCustomClusters().filter((c) => c.id !== id)));
  }

  function readCustomClusterIds() {
    return readCustomClusters().map((c) => c.id);
  }

  function getCluster(id) {
    return getClusters().find((c) => c.id === id) || null;
  }

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function getScenarios() {
    const patches = readJson("ddsScenarioPatch", {});
    const defaults = DEFAULT_SCENARIOS.map((s) => Object.assign({}, s, patches[s.id] || {}));
    const custom = readJson("ddsScenarios", []).map((s) => Object.assign({ clusterId: "other" }, s));
    return defaults.concat(custom);
  }

  function scenariosOfCluster(clusterId, approvedOnly) {
    return getScenarios().filter((s) => s.clusterId === clusterId && (!approvedOnly || s.approved));
  }

  function saveCustomScenario(scenario) {
    const custom = readJson("ddsScenarios", []);
    const idx = custom.findIndex((s) => s.id === scenario.id);
    if (idx === -1) custom.push(scenario);
    else custom[idx] = scenario;
    localStorage.setItem("ddsScenarios", JSON.stringify(custom));
  }

  function patchScenario(id, patch) {
    if (DEFAULT_SCENARIOS.some((s) => s.id === id)) {
      const all = readJson("ddsScenarioPatch", {});
      all[id] = Object.assign({}, all[id], patch);
      localStorage.setItem("ddsScenarioPatch", JSON.stringify(all));
      return;
    }
    const custom = readJson("ddsScenarios", []);
    const item = custom.find((s) => s.id === id);
    if (item) {
      Object.assign(item, patch);
      localStorage.setItem("ddsScenarios", JSON.stringify(custom));
    }
  }

  function deleteCustomScenario(id) {
    localStorage.setItem("ddsScenarios", JSON.stringify(readJson("ddsScenarios", []).filter((s) => s.id !== id)));
  }

  function getAssignments() {
    return readJson("ddsAssignments", {});
  }

  function setAssignment(ws, value) {
    const all = getAssignments();
    if (value) all[ws] = value;
    else delete all[ws];
    localStorage.setItem("ddsAssignments", JSON.stringify(all));
  }

  function callerReply(scenario, text) {
    if (!scenario) return "Алло? Вы меня слышите?";
    const q = String(text || "").trim();
    if (/спасибо|до свидания|ожидайте|выехал|направлен|бригад/i.test(q)) return "Хорошо, спасибо, жду.";
    const hit = (scenario.answers || []).find((a) => new RegExp(a.keys, "i").test(q));
    return hit ? hit.text : "Извините, не расслышал(а). Повторите, пожалуйста.";
  }

  window.DDS_DATA = {
    TIMERS, NORMS, REACTION_STATUSES, REACTION_REFUSED, WORKSTATIONS, SURVEYS, TYPE_SURVEY,
    DEFAULT_SCENARIOS, DEFAULT_CLUSTERS, getClusters, getCluster, readCustomClusterIds, saveCluster, deleteCluster, scenariosOfCluster,
    getScenarios, saveCustomScenario, patchScenario, deleteCustomScenario,
    getAssignments, setAssignment, callerReply,
  };
})();
