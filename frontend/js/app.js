/* =========================================================
   app.js — логика экрана после входа (dashboard.html).

   Идея: набор кнопок-переходов зависит от роли пользователя.
   Роль сейчас берётся из localStorage (её туда положил auth.js
   после "входа"). В реальной системе роль нельзя доверять
   фронтенду полностью — бэкенд обязан сам проверять права на
   каждый запрос (RBAC), фронтенд лишь скрывает лишние пункты меню.
   ========================================================= */

(function () {
  const ROLE_LABELS = {
    student: "Обучающийся",
    teacher: "Преподаватель",
    admin: "Администратор",
  };

  // Иконки — реальные PNG из брендового набора (/assets/icons/), подключаются
  // как CSS-маска, поэтому цвет всегда задаётся через background-color.
  // Путь к файлу — это и есть "иконка", ключ используется в ROLE_CARDS/CATEGORIES.
  const ICONS = {
    call: "/assets/icons/misc_phone.png",
    chart: "/assets/icons/biz_chart.png",
    users: "/assets/icons/users_person_add.png",
    shield: "/assets/icons/misc_shield.png",
    warning: "/assets/icons/misc_warning.png",
    wallet: "/assets/icons/biz_wallet.png",
    nature: "/assets/icons/nature_storm.png",
    lightning: "/assets/icons/nature_lightning.png",
    drop: "/assets/icons/nature_drop.png",
    medicine: "/assets/icons/med_heart.png",
    ambulance: "/assets/icons/med_ambulance.png",
    infrastructure: "/assets/icons/med_house.png",
  };

  function iconHtml(key, size) {
    const src = ICONS[key];
    if (!src) return "";
    return `<span class="icon" style="--icon-src:url('${src}'); width:${size}px; height:${size}px;" aria-hidden="true"></span>`;
  }

  // --- категории карточек происшествий ---
  // Цвет и иконка каждой категории; используется и в очереди, и в шторке.
  // Цвета — семантические переменные (--cat-*), у которых в css/style.css
  // есть отдельные, более контрастные значения для светлой темы.
  const CATEGORIES = {
    nature: { label: "Природные явления", icon: "nature", color: "var(--cat-nature)" },
    medicine: { label: "Медицина", icon: "medicine", color: "var(--cat-medicine)" },
    infrastructure: { label: "ЖКХ / инфраструктура", icon: "infrastructure", color: "var(--cat-infrastructure)" },
    security: { label: "Правопорядок", icon: "shield", color: "var(--cat-security)" },
    other: { label: "Прочее", icon: "warning", color: "var(--cat-other)" },
  };

  // Демонстрационные данные очереди — в реальной системе будут приходить
  // с бэкенда (карточка, сгенерированная эмуляцией оператора 112).
  const INCIDENT_QUEUE = [
    {
      id: "913126",
      category: "nature",
      title: "Пожар: мусор на улице",
      address: "Москва, ул. Ясный проезд, 10",
      time: "10:47",
      caller: "Александр А., очевидец",
      services: ["Служба 101 (МЧС)", "ОДС ПСЦ", "Упр. района"],
    },
    {
      id: "913140",
      category: "medicine",
      title: "Справка-103, вызов врача",
      address: "Москва, Тверской б-р, 14",
      time: "10:52",
      caller: "Мария К., родственник",
      services: ["Служба 103 (СМП)"],
    },
    {
      id: "913152",
      category: "infrastructure",
      title: "Прорыв трубы, залив подъезда",
      address: "Москва, ул. Молостовых, 11",
      time: "10:58",
      caller: "Иван И., очевидец",
      services: ["Мосводоканал", "Упр. района", "ГБУ «Жилищник»"],
    },
    {
      id: "913161",
      category: "security",
      title: "Подозрительные граждане в подвале",
      address: "Москва, Шоссейная ул., 62",
      time: "11:04",
      caller: "Не указан",
      services: ["ОМВД", "Упр. района"],
    },
  ];

  // конфигурация карточек-переходов по ролям — ЕДИНСТВЕННОЕ место,
  // которое нужно трогать, чтобы добавить новый пункт меню в кабинет
  const ROLE_CARDS = {
    student: [
      { icon: "call", title: "Начать занятие", desc: "Получить от системы карточку происшествия (эмуляция оператора 112).", action: "start-session" },
      { icon: "chart", title: "Моя статистика", desc: "Оценки, время реакции, история занятий.", href: "#stats" },
    ],
    teacher: [
      { icon: "warning", title: "Сценарии и эталоны", desc: "Создание, проверка и утверждение сценариев ИИ.", href: "#scenarios-editor" },
      { icon: "chart", title: "Мониторинг занятия", desc: "Ход занятия и действия обучающихся в реальном времени.", href: "#monitoring" },
      { icon: "wallet", title: "Отчёты по группе", desc: "Успеваемость, типичные ошибки, рекомендации ИИ.", href: "#reports" },
      { icon: "call", title: "Учебные материалы", desc: "Загрузка методических материалов и ресурсов.", href: "#materials" },
    ],
    admin: [
      { icon: "users", title: "Пользователи и роли", desc: "Учётные записи, права доступа, блокировки.", href: "#users" },
      { icon: "chart", title: "Состояние системы", desc: "Сервисы, нагрузка, показатели производительности.", href: "#system" },
      { icon: "warning", title: "Журналы и аудит", desc: "Системные журналы и аудит действий пользователей.", href: "#logs" },
      { icon: "shield", title: "Резервное копирование", desc: "Настройка и запуск резервного копирования.", href: "#backup" },
    ],
  };

  const session = JSON.parse(localStorage.getItem("ddsSession") || "null");

  // без сессии — возвращаем на экран входа (упрощённая защита маршрута)
  if (!session) {
    window.location.href = "index.html";
    return;
  }

  function renderRole(session) {
    document.getElementById("role-badge").textContent = ROLE_LABELS[session.role] || session.role;
    document.getElementById("welcome-title").textContent = `Здравствуйте, ${session.fullName}`;
    document.getElementById("welcome-sub").textContent =
      session.role === "student"
        ? "Получите карточку, проверьте её и свяжитесь со службами."
        : session.role === "teacher"
        ? "Управляйте сценариями и следите за прогрессом группы."
        : "Технический контроль и настройка учебного комплекса.";
  }

  function renderCards(role) {
    const grid = document.getElementById("card-grid");
    const cards = ROLE_CARDS[role] || ROLE_CARDS.student;

    grid.innerHTML = cards
      .map(
        (card, i) => `
        <article class="card" style="--i:${i}">
          <span class="card-icon">${iconHtml(card.icon, 20)}</span>
          <h3>${card.title}</h3>
          <p>${card.desc}</p>
          <a class="btn-card" href="${card.href || "#"}" ${card.action ? `data-action="${card.action}"` : ""}>Открыть</a>
        </article>`
      )
      .join("");

    // Карточка "Начать занятие" открывает шторку со случайной карточкой очереди
    // вместо перехода по ссылке — имитирует получение задания от системы.
    const startBtn = grid.querySelector('[data-action="start-session"]');
    if (startBtn) {
      startBtn.addEventListener("click", (e) => {
        e.preventDefault();
        const random = INCIDENT_QUEUE[Math.floor(Math.random() * INCIDENT_QUEUE.length)];
        openSheet(random);
      });
    }
  }

  // --- очередь входящих карточек (только для роли "Обучающийся") ---
  function renderQueue() {
    const section = document.getElementById("queue-section");
    const list = document.getElementById("queue-list");
    section.hidden = false;

    list.innerHTML = INCIDENT_QUEUE.map((item, i) => {
      const cat = CATEGORIES[item.category];
      return `
        <button type="button" class="queue-item" style="--cat-color:${cat.color}; --i:${i}" data-id="${item.id}">
          <span class="queue-badge">${iconHtml(cat.icon, 22)}</span>
          <span class="queue-body">
            <span class="queue-category">${cat.label}</span>
            <span class="queue-title">${item.title}</span>
            <span class="queue-address">${item.address}</span>
          </span>
          <span class="queue-time">${item.time}</span>
        </button>`;
    }).join("");

    list.querySelectorAll(".queue-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = INCIDENT_QUEUE.find((i) => i.id === btn.dataset.id);
        if (item) openSheet(item);
      });
    });
  }

  // --- шторка с деталями карточки происшествия ---
  const overlay = document.getElementById("incident-sheet");
  const commentField = document.getElementById("sheet-comment");
  const commentInput = document.getElementById("sheet-comment-input");
  const timerEl = document.getElementById("sheet-timer");
  const timerValueEl = document.getElementById("sheet-timer-value");

  // По регламенту (см. памятку ГБУ «Система 112») диспетчер обязан
  // подтвердить приём карточки за 30 секунд — иначе она уходит в статус
  // "Не оповещено". Таймер ниже воспроизводит именно это правило.
  const ACCEPT_TIME_LIMIT = 30;
  let timerInterval = null;
  let secondsLeft = ACCEPT_TIME_LIMIT;

  function initSheet() {
    document.getElementById("sheet-close").addEventListener("click", closeSheet);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeSheet();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.classList.contains("is-open")) closeSheet();
    });

    // Комментарий обязателен только при отклонении (как в реальном
    // регламенте: причина отказа должна быть зафиксирована), при
    // принятии — необязателен.
    document.getElementById("sheet-accept").addEventListener("click", () => {
      const elapsed = ACCEPT_TIME_LIMIT - secondsLeft;
      showToast(`Карточка принята · ${elapsed} с`);
      closeSheet();
    });
    document.getElementById("sheet-decline").addEventListener("click", () => {
      if (!commentInput.value.trim()) {
        commentField.classList.add("has-error");
        commentInput.focus();
        return;
      }
      commentField.classList.remove("has-error");
      showToast("Карточка отклонена");
      closeSheet();
    });

    // как только диспетчер начинает печатать причину — прячем ошибку
    commentInput.addEventListener("input", () => commentField.classList.remove("has-error"));
  }

  function startTimer() {
    stopTimer();
    secondsLeft = ACCEPT_TIME_LIMIT;
    renderTimer();
    timerInterval = setInterval(() => {
      secondsLeft -= 1;
      renderTimer();
      if (secondsLeft <= 0) stopTimer();
    }, 1000);
  }

  function renderTimer() {
    const m = Math.floor(Math.max(secondsLeft, 0) / 60);
    const s = Math.max(secondsLeft, 0) % 60;
    timerValueEl.textContent = `${m}:${String(s).padStart(2, "0")}`;
    timerEl.classList.toggle("is-warning", secondsLeft <= 10);
  }

  function stopTimer() {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  function openSheet(item) {
    const cat = CATEGORIES[item.category];

    document.getElementById("sheet-badge").style.setProperty("--cat-color", cat.color);
    document.getElementById("sheet-badge-icon").style.setProperty("--icon-src", `url('${ICONS[cat.icon]}')`);
    document.getElementById("sheet-badge-label").textContent = cat.label;
    document.getElementById("sheet-title").textContent = item.title;
    document.getElementById("sheet-address").textContent = item.address;
    document.getElementById("sheet-time").textContent = item.time;
    document.getElementById("sheet-caller").textContent = item.caller;

    // сбрасываем состояние поля комментария от предыдущей карточки
    commentInput.value = "";
    commentField.classList.remove("has-error");

    document.getElementById("sheet-services-list").innerHTML = item.services
      .map(
        (service) => `
        <div class="service-row">
          ${iconHtml("call", 16)}
          <span>${service}</span>
          <button type="button" class="service-call" data-service="${service}" aria-label="Позвонить: ${service}">
            <span class="icon" style="--icon-src:url('${ICONS.call}'); width:14px; height:14px;"></span>
          </button>
        </div>`
      )
      .join("");

    document.querySelectorAll(".service-call").forEach((btn) => {
      btn.addEventListener("click", () => showToast(`Звонок: ${btn.dataset.service}`));
    });

    startTimer();

    overlay.hidden = false;
    // requestAnimationFrame — чтобы браузер успел применить hidden=false
    // ДО добавления класса is-open, иначе transition не отыграет.
    requestAnimationFrame(() => overlay.classList.add("is-open"));
    overlay.setAttribute("aria-hidden", "false");
  }

  function closeSheet() {
    overlay.classList.remove("is-open");
    overlay.setAttribute("aria-hidden", "true");
    stopTimer();
    // ждём конца transition (320ms в CSS) и только потом прячем совсем
    setTimeout(() => {
      overlay.hidden = true;
    }, 320);
  }

  // --- тост-уведомление ---
  let toastTimer = null;
  function showToast(text) {
    const toast = document.getElementById("toast");
    document.getElementById("toast-text").textContent = text;
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2200);
  }

  function startClock() {
    const clockEl = document.getElementById("clock");
    const dateEl = document.getElementById("date");

    function tick() {
      const now = new Date();
      clockEl.textContent = now.toLocaleTimeString("ru-RU");
      dateEl.textContent = now.toLocaleDateString("ru-RU", {
        weekday: "long",
        day: "numeric",
        month: "long",
      });
    }

    tick();
    setInterval(tick, 1000);
  }

  // --- запуск ---
  // Вызываем всё ПОСЛЕ того, как объявлены все функции и константы
  // (включая `overlay` выше) — иначе получим ReferenceError из-за
  // временной мёртвой зоны у const/let.
  renderRole(session);
  renderCards(session.role);
  if (session.role === "student") renderQueue();
  startClock();
  initSheet();

  document.getElementById("logout-btn").addEventListener("click", () => {
    localStorage.removeItem("ddsSession");
    window.location.href = "index.html";
  });
})();
