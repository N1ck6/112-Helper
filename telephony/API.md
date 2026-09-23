# Telephony API — контракт для Backend, ML и Frontend

Всё, что нужно знать другим ролям о телефонии, без чтения кода.
Формат обмена — JSON (UTF-8). Все адреса задаются переменными окружения,
поэтому подключение = поменять URL в `.env`.

```
 Backend ──POST /calls──────────────► virtual-caller :8092 ──AMI──► Asterisk ──SIP/RTP──► телефон обучающегося
    ▲                                        │   ▲
    │ POST {BACKEND_URL}/telephony/events    │   │ FastAGI 4573 (голосовой цикл)
    └────────────────────────────────────────┘   │
                                                 ├──► voice-service :8091  (STT / TTS)
 ML ◄──POST {ML_API_URL}/dialogue/turn───────────┘
```

| Сервис | Порт (хост) | Кто вызывает |
|---|---|---|
| virtual-caller — API звонков | 8092 | Backend |
| voice-service — STT/TTS | 8091 | virtual-caller (и кто угодно для проверки) |
| audio-tools — записи | 8090 | Backend/Frontend (скачать/проиграть запись) |
| mocks — заглушки ML и Backend | 8093 | virtual-caller, пока нет настоящих сервисов |

## Идентификаторы

| Поле | Кто создаёт | Что это |
|---|---|---|
| `session_id` | Backend | Учебная сессия (занятие/карточка). Передаётся в `POST /calls`; если не передан — генерирует телефония. Формат `[A-Za-z0-9_.-]{1,64}` |
| `scenario_id` | ML/Backend | Сценарий происшествия. Телефония его не интерпретирует, только передаёт в ML. Тот же формат |
| `call_id` | Телефония | Звонок = UNIQUEID канала Asterisk. Имя файла записи, ключ всех событий |

Один `session_id` может иметь несколько звонков (повторный дозвон).

---

## 1. API звонков (virtual-caller, `:8092`)

### `POST /calls` — позвонить обучающемуся

Система звонит на SIP-аккаунт обучающегося; после ответа с ним говорит виртуальный абонент по сценарию.

```json
{"scenario_id": "scenario_001", "trainee": "alice", "session_id": "b7c1e0d2"}
```

| Поле | Обяз. | |
|---|---|---|
| `scenario_id` | да | |
| `trainee` | да* | SIP-аккаунт обучающегося (сейчас `alice`, `bob`) |
| `session_id` | нет | если нет — сгенерируется |
| `channel` | нет* | вместо `trainee`, для тестов: `PJSIP/<аккаунт>` или `Local/<exten>@<context>` |

Ответ `202 Accepted` сразу, дозвон идёт в фоне:

```json
{"call_id": "4f0c…", "session_id": "b7c1e0d2", "scenario_id": "scenario_001",
 "direction": "outbound", "trainee": "alice", "channel": null, "status": "dialing",
 "reason": null, "created_at": 1790000000.1, "answered_at": null, "ended_at": null,
 "duration_sec": 0.0, "recording_url": null, "transcript": []}
```

### `GET /calls/{call_id}` — состояние звонка

Тот же объект. Статусы:

| `status` | Значение |
|---|---|
| `dialing` | идёт дозвон |
| `in_progress` | обучающийся ответил, идёт разговор |
| `ended` | разговор завершён, `reason` — почему |
| `failed` | не дозвонились, `reason` — почему |

`reason` для `failed`: `no_answer`, `busy`, `rejected`, `unavailable` (аккаунт не зарегистрирован), `congestion`, `timeout`, `ami_error`.
`reason` для `ended`: `completed` (абонент закончил разговор), `operator_hangup`, `max_turns`, `max_duration`, `ml_error`, `internal_error`.

`transcript` — реплики по порядку: `{"turn": 0, "role": "caller" | "operator", "text": "...", "audio": "/tts/….wav" | "/recordings/….wav"}`.

### `POST /calls/{call_id}/hangup` — завершить звонок

`202` + объект звонка. `409`, если звонок уже завершён. Итог придёт событием `call.ended` (`reason: operator_hangup`).

### `GET /calls` — последние 500 звонков (новые первыми)

### `GET /endpoints` — SIP-аккаунты

```json
[{"endpoint": "alice", "state": "Not in use", "registered": true, "active_channels": ""}]
```

### `GET /health`

`200` если Asterisk (AMI) доступен, иначе `503`:
```json
{"status": "ok", "ami": true, "voice_service": true, "ml_api_url": "http://mocks:8093/ml",
 "backend_url": "http://mocks:8093/backend", "active_calls": 0}
```

Ошибки всех методов: `{"error": "текст"}` с кодом `400` (валидация), `404`, `409`, `502` (AMI), `500`.

### Входящий учебный вызов

Обучающийся может и сам набрать номер сценария: `700` → `scenario_001`, `701` → `scenario_002`.
Такой звонок появляется в `GET /calls` с `direction: "inbound"` и новым `session_id`; события те же.

---

## 2. События звонка → Backend (webhook)

Телефония делает `POST {BACKEND_URL}/telephony/events` на каждое событие (одно событие — один запрос).
Backend отвечает любым `2xx`. При ошибке — повторы через 0.5, 1, 2, 5 с, затем событие остаётся только
в журнале `data/sessions/sessions.log` (JSON Lines, те же объекты). Порядок событий одного звонка сохраняется.
`BACKEND_URL` пустой — только журнал.

Общие поля: `event`, `timestamp` (ISO 8601, UTC), `call_id`, `session_id`, `scenario_id`.

| `event` | Когда | Доп. поля |
|---|---|---|
| `call.dialing` | принят `POST /calls` | `trainee`, `channel` |
| `call.failed` | не дозвонились | `trainee`, `reason` |
| `call.started` | обучающийся ответил (или сам набрал 7xx) | `direction`, `trainee`, `channel`, `caller_id` |
| `call.utterance` | прозвучала реплика | `turn`, `role` (`caller`/`operator`), `text`, `audio`, `latency` |
| `call.error` | сбой внешнего сервиса, звонок продолжается или завершается | `stage` (`ml`/`tts`/`stt`/`internal`), `error` |
| `call.ended` | конец разговора | `reason`, `duration_sec`, `recording_url`, `transcript` (весь разговор) |

Пример:
```json
{"event": "call.utterance", "timestamp": "2026-09-23T15:04:05.123+00:00",
 "call_id": "4f0c…", "session_id": "b7c1e0d2", "scenario_id": "scenario_001",
 "turn": 0, "role": "operator", "text": "Назовите адрес", "audio": "/recordings/4f0c…_op00.wav",
 "latency": {"stt_sec": 1.42}}
```

`turn` — номер шага: реплика абонента `turn: N` и ответ оператора на неё тоже `turn: N`.
`role: "operator"` с пустым `text` — оператор молчал или речь не распознана.
Для Frontend: `call.dialing` → «входящий звонок», `call.started` → «разговор», `call.ended`/`call.failed` → «завершён».

---

## 3. ML: следующая реплика абонента

Телефония вызывает `POST {ML_API_URL}/dialogue/turn` на каждом шаге разговора. API **без состояния**:
вся история приходит в запросе.

```json
{
  "session_id": "b7c1e0d2",
  "scenario_id": "scenario_001",
  "call_id": "4f0c…",
  "turn": 1,
  "history": [
    {"role": "caller", "text": "Алло! Помогите, у меня в квартире пожар!"},
    {"role": "operator", "text": "Назовите адрес"}
  ],
  "operator_text": "Назовите адрес"
}
```

- `turn` — номер реплики абонента, с 0.
- `turn: 0`, `operator_text: null`, `history: []` — начало звонка: вернуть первую фразу абонента.
- `history` включает и последнюю реплику оператора; `operator_text` дублирует её для удобства.
- `operator_text: ""` — оператор молчал или речь не распознана.

Ответ:
```json
{"reply_text": "Улица Ленина, дом пять, квартира двенадцать.", "end_call": false}
```

- `reply_text` озвучивается TTS (до 1000 символов; пустая строка — абонент молчит).
- `end_call: true` — после этой реплики абонент кладёт трубку.
- Лишние поля ответа игнорируются (можно добавлять `emotion` и т.п.).
- Ответ нужен быстро: пауза ML видна оператору как молчание абонента. Цель < 2 с, таймаут `HTTP_TIMEOUT_SEC` (30 с).
- Ошибка/таймаут ML → звонок завершается с `reason: ml_error`.

Лимиты телефонии поверх ML: `MAX_TURNS` (12 реплик абонента), `MAX_CALL_SEC` (300 с).

Заглушка: `telephony/mocks/mock_services.py` — отвечает по ключевым словам из `telephony/mocks/scenarios/*.json`.

---

## 4. Записи и аудио

| Файл (хост `data/…`, URL `RECORDINGS_BASE_URL/…`) | Что |
|---|---|
| `recordings/<call_id>.wav` | весь разговор (оба голоса), `recording_url` в `call.ended` |
| `recordings/<call_id>_opNN.wav` | ответ оператора на шаге NN (вход STT) |
| `tts/<call_id>_cNN.wav` | реплика абонента на шаге NN (выход TTS) |

Формат: WAV PCM 16 бит, моно, 8 кГц. MP3: `docker compose exec audio-tools python convert_to_mp3.py --once`.
voice-service (`POST /stt`, `POST /tts`) — см. `telephony/README.md`, раздел «Этап 5».

---

## 5. Подключение настоящих сервисов

В `telephony/.env` (или в корневом compose):

```env
# убрать заглушки
COMPOSE_PROFILES=
ML_API_URL=http://ml:8000          # базовый URL; телефония добавит /dialogue/turn
BACKEND_URL=http://backend:8000    # телефония добавит /telephony/events
```

Сервисы должны быть в одной Docker-сети с telephony (имена `ml`, `backend` — имена сервисов compose).
Проверка: `curl http://localhost:8092/health` → `ml_api_url`/`backend_url` новые; тестовый звонок `POST /calls`.
