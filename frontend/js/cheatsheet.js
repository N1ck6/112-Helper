/* Шпаргалка 112 — выдвижная панель у правого края экрана, открыта на любой вкладке.
 *
 * Только факты из первичных документов (без пересказа «своими словами»):
 *   [И] инструкция пользователя «Заведение карточки происшествия», модуль «Приём и обработка
 *       вызовов 112» (КИС УСС, вторая очередь);
 *   [П] памятка «Работа на АРМ-112» для ДДС, отдел контроля реагирования Службы 112
 *       ГБУ «Система 112», 2025;
 *   [З] 488-ФЗ, ПП РФ № 1931, ФЗ «О связи» ст. 52.
 * Полная версия с таблицами — вкладка «Справочная база».
 */
(function () {
  "use strict";

  const session = (function () {
    try { return JSON.parse(localStorage.getItem("ddsSession") || "null") || {}; } catch (e) { return {}; }
  })();
  // шпаргалка по регламенту 112 — обучающимся и преподавателю; у администратора задачи системные
  if (["student", "dispatcher", "teacher"].indexOf(session.role) === -1) return;

  const OPERATOR = {
    title: "Оператор 112: карточка",
    blocks: [
      ["Приём вызова", [
        "Статус «доступен» → входящий → «Принять»: карточка откроется сама, пошёл таймер до «Сохранить».",
        "Открыта карточка — статус «недоступен»; после закрытия ещё 10 с.",
        "Не принимаются вызовы — Ctrl+F5, затем перезайти, затем техподдержка.",
      ]],
      ["Порядок заполнения (все блоки обязательны)", [
        "<b>Телефоны</b> Alt+F1/F2/F3: АОН — сам; «предоставленный» — контактный заявителя; «на место» — телефон на месте. Номер не с +7 — отметить «зарубежный номер».",
        "<b>Что случилось?</b> Alt+T: плитка или поиск по части слова («пож», «тран»); можно несколько типов — к каждому опросная карта.",
        "<b>Адрес</b> Alt+A: одной строкой <u>вместе с домом</u> → выбрать вариант из списка → проверить автозаполненные поля.",
        "<b>Опросная карта</b> Alt+1…9: ответы уточняют список служб.",
        "<b>Описание со слов заявителя</b> Alt+O: в службу 103 уходят <u>первые 100 символов</u> — главное в начало.",
        "<b>Заявитель</b> Alt+Q: ФИО и статус (очевидец, пострадавший, родственник, знакомый, ребёнок, участник). После сохранения не меняются.",
        "<b>Пострадавшие</b> Alt+P: «Есть» → количество.",
        "<b>Службы</b> Alt+Z: подбираются автоматически по ЕКП, основные — двойное подчёркивание. Вручную — только в нештатной ситуации.",
        "<b>Сохранить</b> Alt+S → «Оповестить и сохранить карточку».",
      ]],
      ["Особые случаи", [
        "Нет контакта / срыв звонка — Alt+N: пустая карточка сразу «Завершена».",
        "Адрес из ФИАС — службы не добавятся сами, добавить вручную. Приоритет — адресам Яндекса.",
        "Та же заявка уже есть — кнопка «Совпадение» → «Привязать».",
        "После сохранения: «Добавить отработку» (служба, куда звонили, телефон, кто принял, суть) → «Отработана».",
      ]],
    ],
  };

  const DISPATCHER = {
    title: "Диспетчер ДДС: реагирование",
    blocks: [
      ["Первичный статус — за 30 секунд", [
        "<b>Принята</b> — реагировать будете.",
        "<b>Не принята</b> — не ваша зона, объект или тип; реагирование уже идёт по другой карточке. <u>Комментарий обязателен</u>: причина и кому передано.",
        "Нет статуса за 30 с — карточка «Не оповещено».",
        "После «Не принята» доступна только «Принята».",
      ]],
      ["Ход работ — по факту", [
        "Начало реагирования → Прибытие → Проведение работ → Работы завершены.",
        "«Работы завершены» и «Отказ от выполнения работ» <u>закрывают карточку</u> — всё важное в комментарий заранее.",
        "Отказ от выполнения работ — только с комментарием: причина и кому передано.",
        "103 не ставит «Не принята» и «Отказ» — вместо них «Работы завершены: завершение работ без бригады».",
      ]],
      ["Правила", [
        "Статус = фактическое состояние: не ставить «Принята», если работ не будет.",
        "Нельзя отказываться только потому, что уже реагирует другая служба.",
        "Дубль: «Не принята: дубль» или «Не принята: реагирование по КП №…».",
        "Читать всё: итоговый тип, признаки, опросную карту и <u>описание</u>. Адрес может не совпадать с местом («дом через дорогу»).",
      ]],
      ["Звонок в службу", [
        "Представиться (служба, должность, фамилия) → адрес → что случилось → пострадавшие → дождаться «информация принята» → записать, кто принял.",
      ]],
      ["Если ошиблись", [
        "Ошибочно «Не принята» → поставить «Принята».",
        "Ошибочно «Принята» → «Отказ от выполнения работ» с причиной.",
        "Ошибочно «Работы завершены» или «Отказ» → звонить в отдел контроля.",
        "Обстановка изменилась, нужны другие службы → звонить 112: ФИО, должность, служба, адрес, повод, номер карточки.",
      ]],
    ],
  };

  const COMMON = {
    title: "Система-112",
    blocks: [
      ["Главное", [
        "Вызов 112 бесплатный, в том числе с устройства без SIM-карты (в АОН — отметка).",
        "«Одно окно»: заявитель говорит с одним оператором, тот оповещает все службы.",
        "Службы получают карточку по ЕКП: итоговый тип → список оповещения. Удалить службу из списка нельзя.",
        "Статусы карточки: Зарегистрирована → Отработана → Проверена → Завершена. Красные: Не оповещено, Отказ, Не завершено (48 ч без «Работы завершены»).",
      ]],
      ["Нормативная база", [
        "488-ФЗ от 30.12.2020 — единый номер 112.",
        "ПП РФ № 1931 от 12.11.2021 — требования и сроки приёма вызовов.",
        "ПП Москвы № 1420-ПП от 01.09.2020 — система-112 в Москве.",
      ]],
    ],
  };

  const sheets = session.role === "student" ? [OPERATOR, COMMON]
    : session.role === "dispatcher" ? [DISPATCHER, COMMON]
    : [OPERATOR, DISPATCHER, COMMON];

  const style = document.createElement("style");
  style.textContent = `
  .cs-tab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:140;writing-mode:vertical-rl;
    padding:12px 6px;border:1px solid var(--border-600);border-right:none;border-radius:var(--radius-lg) 0 0 var(--radius-lg);
    background:var(--panel-800);color:var(--ink-100);font:600 .75rem var(--font-ui);cursor:pointer;letter-spacing:.04em;
    box-shadow:var(--shadow-panel)}
  .cs-tab:hover{color:var(--accent-500)}
  .cs-panel{position:fixed;top:0;right:0;bottom:0;z-index:160;width:min(380px,100vw);display:flex;flex-direction:column;
    background:var(--panel-800);border-left:1px solid var(--border-600);box-shadow:var(--shadow-panel);
    color:var(--ink-100);font:.8rem/1.45 var(--font-ui);transform:translateX(100%);transition:transform .2s ease}
  .cs-panel.open{transform:none}
  .cs-head{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--border-600)}
  .cs-head b{font-size:.9rem} .cs-head input{flex:1;min-width:0}
  .cs-close{margin-left:auto;background:none;border:none;color:var(--ink-600);font-size:1.3rem;cursor:pointer}
  .cs-body{overflow-y:auto;padding:6px 14px 16px}
  .cs-body h4{margin:14px 0 4px;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--accent-500)}
  .cs-body h5{margin:10px 0 4px;font-size:.8rem}
  .cs-body ul{margin:0;padding-left:16px} .cs-body li{margin:3px 0}
  .cs-src{margin-top:14px;color:var(--ink-600);font-size:.72rem}
  @media print{.cs-tab,.cs-panel{display:none}}`;
  document.head.appendChild(style);

  const tab = document.createElement("button");
  tab.type = "button";
  tab.className = "cs-tab";
  tab.textContent = "Шпаргалка 112";
  tab.setAttribute("aria-expanded", "false");

  const panel = document.createElement("aside");
  panel.className = "cs-panel";
  panel.setAttribute("aria-label", "Шпаргалка 112");
  panel.innerHTML = `
    <div class="cs-head"><b>Шпаргалка</b>
      <input type="search" class="ref-search" placeholder="Найти…" aria-label="Поиск по шпаргалке" />
      <button type="button" class="cs-close" aria-label="Закрыть">×</button></div>
    <div class="cs-body">${sheets.map((s) => `<h4>${s.title}</h4>${s.blocks.map((b) =>
      `<section><h5>${b[0]}</h5><ul>${b[1].map((li) => `<li>${li}</li>`).join("")}</ul></section>`).join("")}`).join("")}
      <p class="cs-src">Источники: инструкция «Заведение карточки происшествия» (модуль «Приём и обработка вызовов 112»),
      памятка «Работа на АРМ-112» (ГБУ «Система 112», 2025), 488-ФЗ, ПП РФ № 1931. Подробно — вкладка «Справочная база».</p>
    </div>`;

  document.body.append(tab, panel);
  const search = panel.querySelector("input");

  function toggle(open) {
    panel.classList.toggle("open", open);
    tab.hidden = open;
    tab.setAttribute("aria-expanded", String(open));
    if (open) search.focus();
  }
  tab.addEventListener("click", () => toggle(true));
  panel.querySelector(".cs-close").addEventListener("click", () => toggle(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("open")) toggle(false);
  });
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    panel.querySelectorAll(".cs-body li").forEach((li) => { li.hidden = !!q && li.textContent.toLowerCase().indexOf(q) === -1; });
    panel.querySelectorAll(".cs-body section").forEach((sec) => { sec.hidden = !sec.querySelector("li:not([hidden])"); });
  });
})();
