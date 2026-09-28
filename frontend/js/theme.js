(function () {
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyToggleLabel(btn) {
    btn.setAttribute("aria-label", currentTheme() === "dark" ? "Включить светлую тему" : "Включить тёмную тему");
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ddsTheme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(applyToggleLabel);
  }

  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    applyToggleLabel(btn);
    btn.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
  });
})();
