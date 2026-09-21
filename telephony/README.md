# Этап 1 — базовая инфраструктура (локальный SIP-сервер)

## Что здесь реализовано

- Docker-образ Asterisk (собирается из `ubuntu:24.04` через `apt`,
  компонент `universe`, а не из стороннего образа с неясной поддержкой —
  историю про то, почему не Debian, см. в комментарии в начале
  `asterisk/Dockerfile`).
- `entrypoint.sh` — подставляет секреты из переменных окружения в конфиги
  перед стартом (сами конфиги в git хранятся как шаблоны без паролей).
- `healthcheck.sh` — Docker health check через `asterisk -rx "core show version"`.
- AMI (Asterisk Manager Interface, порт 5038) — простой протокол для
  мониторинга и автоматических тестов без необходимости в SIP-клиенте.
- Логи: в консоль (`docker logs`) и в volume `asterisk-logs`
  (файл `/var/log/asterisk/messages`).
- Работает полностью локально, без обращения в интернет.

## Как это работает (коротко)

1. `docker compose build` собирает образ: включает `universe` и ставит
   Asterisk из репозитория Ubuntu.
2. При `docker compose up` контейнер стартует `entrypoint.sh`, который:
   - рендерит `conf/*.conf` (шаблоны) → `/etc/asterisk/*.conf` внутри
     контейнера, подставляя `${AMI_PASSWORD}`;
   - запускает `asterisk -f -vvv` (foreground, чтобы Docker видел процесс).
3. Docker раз в 10 секунд дёргает `healthcheck.sh` — если Asterisk не
   отвечает на CLI-команду, контейнер помечается `unhealthy`.

## Почему так, а не иначе

- **AMI, а не сразу ARI**: ARI (REST + WebSocket) избыточен для простого
  health-check на этапе 1. AMI — текстовый TCP-протокол в 5 строк кода,
  этого достаточно и для мониторинга, и для автотестов в `tests/`.
- **Конфиги — шаблоны + entrypoint, а не переменные прямо в .conf**:
  Asterisk не умеет `${VAR}` из окружения нативно. Вариант "заранее
  сгенерировать .conf на хосте" плодит скрипты вне Docker; вариант
  "хардкодить пароль в git" запрещён инструкцией (п.5.8). envsubst в
  entrypoint — простое и воспроизводимое решение.

## Ручная проверка

```bash
cp .env.example .env      # при желании поменяйте пароль AMI
docker compose up --build -d

# 1) контейнер здоров?
docker compose ps
# STATUS должен стать "healthy" в течение ~10-15 секунд

# 2) Asterisk отвечает на CLI?
docker exec -it telephony-stage1-asterisk asterisk -rx "core show version"

# 3) AMI-порт открыт?
nc -zv localhost 5038

# 4) логи пишутся?
docker exec -it telephony-stage1-asterisk tail -n 20 /var/log/asterisk/messages
```

Автоматическая проверка: `tests/test_stage1_sip_server.py` (логинится в
AMI и шлёт `Ping`, ожидает `Pong`).

## Definition of Done — проверка по пунктам

- [x] код в `telephony/stage1_sip_server/`
- [x] сервис запускается одной командой (`docker compose up`)
- [x] есть способ проверить результат (см. выше + pytest)
- [x] ошибки логируются (console + файл)
- [x] секретов в репозитории нет (`.env` в `.gitignore`, конфиги — шаблоны)
- [x] тест есть (`tests/test_stage1_sip_server.py`)
