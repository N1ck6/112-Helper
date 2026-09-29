#!/usr/bin/env sh
# Установка и запуск тренажёра ДДС-112 на Linux / macOS: ./start.sh
# 1) Docker запущен; 2) .env — создать со случайными паролями или дополнить;
# 3) docker compose up; 4) дождаться готовности и открыть АРМ в браузере.
# Повторный запуск безопасен: .env не перезаписывается, данные в БД сохраняются.
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nОШИБКА: %s\n' "$1" >&2; exit 1; }

step "Проверка Docker"
command -v docker >/dev/null 2>&1 || fail "Docker не установлен: https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || fail "Docker не отвечает: запустите его (sudo systemctl start docker) или добавьте пользователя в группу docker"
docker compose version >/dev/null 2>&1 || fail "Нет docker compose v2 (пакет docker-compose-plugin)"
echo "Docker готов."

step "Файл настроек .env"
# IP этого ПК в локальной сети: по нему софтфоны других рабочих мест получают звук
IP=""
if command -v ip >/dev/null 2>&1; then
  IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' | head -n1)
elif command -v ipconfig >/dev/null 2>&1; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || true)
fi
if command -v python3 >/dev/null 2>&1; then
  python3 deploy/make_env.py --media-ip "$IP"
else
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:/work" -w /work python:3.12-alpine \
    python deploy/make_env.py --media-ip "$IP"
fi

val() { grep -E "^$1=" .env | head -n1 | cut -d= -f2-; }
PORT=$(val FRONTEND_PORT); PORT=${PORT:-8080}
URL="http://localhost:$PORT"

step "Сборка и запуск сервисов (первый раз — 10-30 минут: образы, модели голоса и ИИ)"
docker compose up -d --build || fail "docker compose up завершился с ошибкой. Подробности: docker compose logs"

step "Ожидание готовности (база данных, ИИ-сервис, стартовые данные)"
ready=0
i=0
while [ $i -lt 180 ]; do
  if curl -fsS "$URL/api/health/ready" >/dev/null 2>&1 || wget -q -O /dev/null "$URL/api/health/ready" 2>/dev/null; then
    ready=1; break
  fi
  i=$((i + 1)); sleep 10; printf '.'
done
echo
[ $ready -eq 1 ] || fail "Стенд не ответил за 30 минут. Состояние: docker compose ps; журналы: docker compose logs api ml"

printf '\nТренажёр запущен: %s\n' "$URL"
[ -n "$IP" ] && printf 'С других компьютеров класса: http://%s:%s\n' "$IP" "$PORT"
printf '\nУчётные записи (пароли хранятся в файле .env):\n'
printf '  admin             %s   администратор\n' "$(val ADMIN_PASSWORD)"
printf '  teacher           %s   преподаватель\n' "$(val TEACHER_PASSWORD)"
printf '  student, student2 %s   обучающиеся\n' "$(val STUDENT_PASSWORD)"
printf '  Софтфон рабочего места: сервер %s:%s, логин ws01…ws20, пароль %s\n' "${IP:-<IP этого ПК>}" "$(val EXTERNAL_SIGNALING_PORT)" "$(val TRAINEE_PASSWORD)"
printf '  Настройка софтфона (UDP, логин = номер места при входе в АРМ) — README, раздел «Подключение MicroSIP»\n'
case "$(val COMPOSE_PROFILES)" in
  *llm*) printf '\nМодель ИИ (%s) и голоса при первом запуске докачиваются в фоне;\n' "$(val LLM_MODEL)"
         printf 'до этого проверка грамотности и рассказы заявителей идут по правилам. Ход: docker compose logs -f ollama-init voice-service\n' ;;
esac
printf '\nОстановить: docker compose stop    Запустить снова: ./start.sh\n'
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "$URL" || true
fi
