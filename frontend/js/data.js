// Нормативы, статусы и опросные карты АРМ-112 (памятка «Работа на АРМ-112»). Учебные данные — на Backend.
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

  window.DDS_DATA = { TIMERS, NORMS, REACTION_STATUSES, REACTION_REFUSED, WORKSTATIONS, SURVEYS, TYPE_SURVEY };
})();
