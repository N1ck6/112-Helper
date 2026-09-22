

(function () {
  const roleButtons = document.querySelectorAll(".role-btn");
  const roleSwitch = document.getElementById("role-switch");
  const roleIndicator = document.getElementById("role-indicator");
  const form = document.getElementById("login-form");
  const submitBtn = document.getElementById("login-submit");
  const errorEl = document.getElementById("form-error");

  let selectedRole = "student";

  function moveIndicatorTo(btn) {
    const switchRect = roleSwitch.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    roleIndicator.style.setProperty("--x", `${btnRect.left - switchRect.left}px`);
    roleIndicator.style.setProperty("--w", `${btnRect.width}px`);
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
      moveIndicatorTo(btn);
    });
  });


  requestAnimationFrame(() => moveIndicatorTo(document.querySelector(".role-btn.active")));
  window.addEventListener("resize", () => moveIndicatorTo(document.querySelector(".role-btn.active")));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;

    const username = form.username.value.trim();
    const password = form.password.value.trim();

    if (!username || !password) {
      errorEl.hidden = false;
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Проверка…";

    try {
      const session = await mockLogin({ username, password, role: selectedRole });


      localStorage.setItem("ddsSession", JSON.stringify(session));

      window.location.href = "dashboard.html";
    } catch (err) {
      errorEl.textContent = err.message || "Не удалось войти. Проверьте данные.";
      errorEl.hidden = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Войти";
    }
  });


  function mockLogin({ username, password, role }) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (username.length < 2) {
          reject(new Error("Слишком короткий логин"));
          return;
        }
        resolve({
          role,
          fullName: username,
          loggedInAt: new Date().toISOString(),
        });
      }, 500);
    });
  }
})();
