(function () {
  const D = window.DDS_DATA;
  const API = window.DDS_API;
  const roleButtons = document.querySelectorAll(".role-btn");
  const roleSwitch = document.getElementById("role-switch");
  const roleIndicator = document.getElementById("role-indicator");
  const form = document.getElementById("login-form");
  const submitBtn = document.getElementById("login-submit");
  const errorEl = document.getElementById("form-error");
  const wsField = document.getElementById("ws-field");
  const wsSelect = document.getElementById("ws-select");
  const modeEl = document.getElementById("login-mode");

  const ROLES_WITH_WORKSTATION = ["student", "dispatcher"];

  let selectedRole = "student";

  wsSelect.innerHTML = D.WORKSTATIONS.map((ws) => `<option value="${ws}">${ws}</option>`).join("");
  wsSelect.value = localStorage.getItem("ddsWorkstation") || D.WORKSTATIONS[0];

  function moveIndicatorTo(btn) {
    const switchRect = roleSwitch.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    roleIndicator.style.setProperty("--x", `${btnRect.left - switchRect.left}px`);
    roleIndicator.style.setProperty("--y", `${btnRect.top - switchRect.top}px`);
    roleIndicator.style.setProperty("--w", `${btnRect.width}px`);
    roleIndicator.style.setProperty("--h", `${btnRect.height}px`);
  }

  function refreshWorkstationField() {
    wsField.hidden = ROLES_WITH_WORKSTATION.indexOf(selectedRole) === -1;
  }

  roleButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      roleButtons.forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      selectedRole = btn.dataset.role;
      refreshWorkstationField();
      moveIndicatorTo(btn);
    });
  });

  refreshWorkstationField();
  requestAnimationFrame(() => moveIndicatorTo(document.querySelector(".role-btn.active")));
  window.addEventListener("resize", () => moveIndicatorTo(document.querySelector(".role-btn.active")));

  API.probe().then((ok) => {
    modeEl.textContent = ok
      ? "Сервер тренажёра подключён"
      : "Сервер тренажёра недоступен — вход невозможен. Проверьте, что стенд запущен (docker compose ps).";
    modeEl.classList.toggle("is-online", !!ok);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;

    const username = form.username.value.trim();
    const password = form.password.value;
    const workstation = ROLES_WITH_WORKSTATION.indexOf(selectedRole) !== -1 ? wsSelect.value : null;

    if (!username || !password) {
      errorEl.textContent = "Введите логин и пароль";
      errorEl.hidden = false;
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Проверка…";

    try {
      const session = await login({ username, password, role: selectedRole, workstation });
      localStorage.setItem("ddsSession", JSON.stringify(session));
      if (workstation) localStorage.setItem("ddsWorkstation", workstation);
      window.location.href = "dashboard.html";
    } catch (err) {
      errorEl.textContent = err.message || "Не удалось войти. Проверьте данные.";
      errorEl.hidden = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Войти";
    }
  });

  async function login(payload) {
    const remote = await API.login(payload);
    return Object.assign({ role: payload.role, fullName: payload.username, workstation: payload.workstation }, remote,
      { loggedInAt: new Date().toISOString() });
  }
})();
