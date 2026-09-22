/* =========================================================
   theme.js — переключение светлой/тёмной темы.

   Сама тема (какая переменная за что отвечает) описана в
   css/style.css через :root и :root[data-theme="light"].
   Здесь — только применение сохранённого выбора и кнопка-тумблер.

   Мгновенное применение темы ДО отрисовки страницы (чтобы не было
   вспышки неправильной темой) сделано отдельным инлайн-скриптом
   в <head> каждой страницы — этот файл его не дублирует, только
   довешивает обработчик клика на кнопку(-и) с [data-theme-toggle].
   ========================================================= */

(function () {
  const ICONS = {
    dark: "/assets/icons/theme_sun.png", // в тёмной теме показываем "включить светлую"
    light: "/assets/icons/theme_moon.png", // в светлой — "включить тёмную"
  };

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyToggleIcon(btn) {
    const theme = currentTheme();
    const icon = btn.querySelector(".icon");
    if (!icon) return;
    icon.style.setProperty("--icon-src", `url('${ICONS[theme]}')`);
    btn.setAttribute("aria-label", theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему");
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ddsTheme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(applyToggleIcon);
  }

  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    applyToggleIcon(btn);
    btn.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
  });
})();
