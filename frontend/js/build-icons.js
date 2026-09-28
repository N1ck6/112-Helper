const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const ICONS = {
  call: "misc_phone.svg",
  clock: "misc_clock.svg",
  close: "misc_close.svg",
  nature: "nature_storm.svg",
  medicine: "med_heart.svg",
  infrastructure: "med_house.svg",
  shield: "misc_shield.svg",
  warning: "misc_warning.svg",
  sun: "theme_sun.svg",
  moon: "theme_moon.svg",
};

function toDataUri(svg) {
  const min = svg
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\s+/g, " ")
    .replace(/> </g, "><")
    .replace(/"/g, "'")
    .trim();
  return "data:image/svg+xml," + encodeURIComponent(min).replace(/%20/g, " ").replace(/%3D/g, "=").replace(/%2F/g, "/").replace(/%3A/g, ":").replace(/%27/g, "'").replace(/%2C/g, ",");
}

let css = "/* Файл создаётся скриптом tools/build-icons.js из assets/icons/*.svg — руками не править.\n   Иконки встроены в CSS, поэтому работают без загрузки отдельных файлов (и при открытии через file://). */\n";
Object.keys(ICONS).forEach((name) => {
  const file = path.join(ROOT, "assets", "icons", ICONS[name]);
  const svg = fs.readFileSync(file, "utf8");
  css += `.i-${name} { --icon-src: url("${toDataUri(svg)}"); }\n`;
});

fs.writeFileSync(path.join(ROOT, "css", "icons.css"), css);
console.log("css/icons.css обновлён: " + Object.keys(ICONS).length + " иконок");
