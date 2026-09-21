# Этап 3 — виртуальный учебный абонент

## Что здесь реализовано

- `virtual_caller/fastagi_server.py` — отдельный сервис (отдельный
  контейнер), который через протокол AGI "играет" за позвонившего:
  отвечает на звонок, проигрывает реплики сценария, опционально
  записывает ответ диспетчера, кладёт JSON-лог событий.
- Dialplan-номера `700`/`701` (context `[training]`, этап2+3) — трейни
  набирает номер и получает учебный сценарий.
- Привязка звонка к `session_id` (генерируется на каждый звонок),
  `scenario_id` (берётся из AGI-адреса `agi://.../scenario_001`) и
  `call_id` (`agi_uniqueid` — родной ID канала Asterisk).
- `scenarios/*.json` — описание сценария (реплики + сколько секунд
  писать ответ трейни). Звуки — заглушки из штатных файлов Asterisk,
  см. комментарий `_comment` в каждом JSON.

## Как это работает

```text
alice набирает 700
        │
        ▼
Asterisk: Answer() -> AGI(agi://virtual-caller:4573/scenario_001)
        │  (TCP-соединение, Asterisk выступает КЛИЕНТОМ)
        ▼
virtual_caller: читает agi_* переменные окружения
        │        генерирует session_id, читает scenario_001.json
        ▼
        ANSWER -> STREAM FILE (реплика 1) -> STREAM FILE (реплика 2) -> ...
        -> RECORD FILE (ответ диспетчера) -> HANGUP
        │
        ▼
data/stage3/sessions/sessions.log  <- JSON-лог: call_started, prompt_played,
                                       response_recorded, call_ended
```

## Почему именно так

- **Отдельный контейнер, а не код внутри Asterisk**: инструкция прямо
  требует не встраивать ML/сценарную логику в SIP-код (п.3, этап 6;
  п.5.2/5.5). AGI по TCP (FastAGI) — штатный механизм Asterisk именно
  для этого разделения.
- **JSON Lines вместо БД**: PostgreSQL появляется по плану только в
  этапе 8 вместе с Backend. До того — простой файл, который легко
  инспектировать `cat`/`tail` и который не требует лишней инфраструктуры
  для MVP из 4 этапов.
- **Bind-mount `/data` на хост**: чтобы `tests/test_stage3_virtual_caller.py`
  мог проверить результат звонка, просто прочитав файл — без Docker SDK.

## Ручная проверка

```bash
cp .env.example .env
docker compose up --build -d

# зарегистрируйте alice в софтфоне (см. README этапа 2, порт 5062)
# наберите 700, послушайте реплики сценария

# проверьте лог событий:
cat data/stage3/sessions/sessions.log
```

Без софтфона — автотест `tests/test_stage3_virtual_caller.py` инициирует
звонок через AMI Originate на `training,700,1` и проверяет, что в
`sessions.log` появилась запись `call_started` с ожидаемым `scenario_id`.

## Definition of Done

- [x] код в `telephony/stage3_virtual_caller/`
- [x] сервис запускается (`docker compose up`, зависит только от этапа 3)
- [x] проверка результата есть (лог + softphone + pytest)
- [x] ошибки логируются (`logging` в virtual_caller + Asterisk логи)
- [x] секретов нет
- [x] этапы 1 и 2 продолжают работать сами по себе
