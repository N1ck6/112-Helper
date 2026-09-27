window.APP_CONFIG = {
  API_BASE_URL: "http://localhost:8000/api",
  // API телефонии (telephony/API.md): на стенде — тот же адрес через nginx (/telephony/);
  // страница открыта с GitHub Pages или файлом — телефония на этом же ПК
  TELEPHONY_API_URL:
    location.protocol === "file:" || location.hostname.endsWith("github.io")
      ? "http://localhost:8092"
      : "telephony",
};
