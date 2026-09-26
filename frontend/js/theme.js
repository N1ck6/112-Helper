(function () {
  const ICONS = {
    dark: "/assets/icons/theme_sun.png",
    light: "/assets/icons/theme_moon.png",
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
