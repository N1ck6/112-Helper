# Telephony API — контракт для Frontend, Backend и ML

Всё, что нужно другим ролям о телефонии, без чтения кода. Обмен — JSON (UTF-8).
Адреса сервисов задаются в `.env`, подключение = смена URL.

```
 Frontend (браузер) ──HTTP + SSE (CORS)──┐
 Backend ────────────POST /calls─────────┤
                                         ▼
                      virtual-caller :8092 ──AMI──► Asterisk ──SIP/RTP──► телефон рабочего места (ws01…)
                         │   ▲  FastAGI                 (софтфон / IP-телефон / гарнитура)
      POST {BACKEND_URL}/telephony/events               
                         │   ├──► voice-service :8091  (STT / TTS, мужской и женский голос)
 ML ◄─POST {ML_API_URL}/dialogue/turn
```

| Сервис | Порт хоста | Кто вызывает |
|---|---|---|
| virtual-caller — API звонков, SSE | 8092 | Frontend, Backend |
| voice-service — STT/TTS | 8091 | virtual-caller |
| audio-tools — записи | 8090 | Frontend/Backend (проиграть или скачать запись) |
| mocks — заглушки ML (`/ml`) и Backend (`/backend`) | 8093 | virtual-caller, пока нет настоящих |

## Идентификаторы

| Поле | Кто создаёт | Что это |
|---|---|---|
| `trainee` | Backend/Frontend | рабочее место = SIP-аккаунт телефона (`ws01`…`ws20`) |
| `session_id` | Backend | учебная сессия (занятие). `[A-Za-z0-9_.-]{1,64}`; нет — генерирует телефония |
| `card` | Backend | карточка происшествия (объект, поля ниже); телефония не валидирует, передаёт в ML |
| `scenario_id` | ML/Backend | сценарий вводных для `incident_112` |
| `call_id` | Телефония | звонок = UNIQUEID канала Asterisk; имя записи, ключ событий |

Поля `card`, которые использует телефония (остальные передаются как есть): `id`, `title`,
`address`, `caller` (имя заявителя — по нему выбирается голос), `caller_gender` (`male`/`female`,
необязательно), `phone`, `description`, `services` (названия служб).

## Типы звонков

| `call_type` | Кто → кому | Собеседник | Голос |
|---|---|---|---|
| `dispatch` | диспетчер ДДС → служба | дежурный службы из справочника | по справочнику |
| `report` | старший группы → диспетчер ДДС | `leader` службы из справочника | по справочнику |
| `applicant` | диспетчер ДДС → заявитель карточки | заявитель (`card.caller`) | по имени |
| `incident_112` | заявитель → оператор 112 | заявитель из сценария | женский |

С телефона рабочего места: `2XXX` — служба (`dispatch`), `3000` — заявитель открытой карточки,
`700`/`701` — вызов 112 по сценарию, `600` — эхо-тест.

---

## 1. API телефонии (virtual-caller, `:8092`)

CORS: `Access-Control-Allow-Origin: CORS_ORIGINS` (по умолчанию `*`), preflight `OPTIONS` поддержан.
Ошибки: `{"error": "текст"}` с кодами `400` (валидация), `404`, `409`, `502` (Asterisk), `500`.

### `GET /directory` — справочник служб

```json
[{"number": "2101", "id": "mchs_101", "service": "Служба 101 (МЧС)",
  "name": "Петров Андрей", "position": "Старший диспетчер ЦУКС", "gender": "male"}, …]
```
Службу в `POST /calls` можно указать номером, `id` или названием из карточки:
«Служба 101 (МЧС)», «ОМВД», «Упр. района», «Мосводоканал» и т.п. (поиск по `aliases`).
Источник — `virtual_caller/directory.json` (добавить службу = добавить объект).

### `PUT /trainees/{trainee}/context` — что открыто на рабочем месте

Frontend/Backend сообщает при открытии карточки; нужно для звонков, которые обучающийся
набирает с телефона сам (2XXX, 3000), и как значение по умолчанию для `POST /calls`.
```json
{"session_id": "s-42", "card": {"id": "913126", "title": "Пожар: мусор на улице",
 "address": "Москва, ул. Ясный проезд, 10", "caller": "Александр А., очевидец", "services": ["Служба 101 (МЧС)"]}}
```
`GET` — текущий контекст (`404`, если нет), `DELETE` — сбросить (карточка закрыта).

### `POST /calls` — учебный звонок

Телефония звонит на телефон рабочего места; после ответа говорит собеседник.
Для `dispatch`/`applicant` обучающийся «звонит кнопкой»: берёт трубку своего телефона, слышит
гудки (`RINGBACK_SEC`), затем «Слушаю вас».

| Поле | Для | |
|---|---|---|
| `call_type` | все | `dispatch` / `report` / `applicant` / `incident_112` (по умолчанию) |
| `trainee` | все | SIP-аккаунт рабочего места (`ws01`) |
| `service` или `contact` | dispatch, report | название службы из карточки, номер или id |
| `card`, `session_id` | все, необяз. | по умолчанию — из контекста рабочего места |
| `report` | report, необяз. | `{"status": "arrival" \| "in_progress" \| "completed" \| "refused", "text": "свой текст"}` |
| `scenario_id` | incident_112 | сценарий ML |
| `channel` | тесты | вместо `trainee`: `Local/9001@autotest` — имитация рабочего места |

```json
{"call_type": "dispatch", "trainee": "ws01", "service": "Служба 101 (МЧС)"}
```
Ответ `202` сразу (дозвон в фоне) — объект звонка:
```json
{"call_id": "4f0c…", "session_id": "s-42", "scenario_id": "", "direction": "outbound", "trainee": "ws01",
 "call_type": "dispatch", "persona": {"id": "mchs_101", "number": "2101", "service": "Служба 101 (МЧС)",
 "name": "Петров Андрей", "position": "Старший диспетчер ЦУКС", "gender": "male", "accept": "…"},
 "card": {…}, "report": null, "channel": null, "status": "dialing", "reason": null,
 "created_at": 1790000000.1, "answered_at": null, "ended_at": null, "duration_sec": 0.0,
 "recording_url": null, "transcript": []}
```
На экране телефона обучающегося: `dispatch` — «Служба 101 (МЧС)», `report` — «Мастер аварийной
бригады (Мосводоканал)», `applicant` — «Заявитель: …».

### `GET /calls/{call_id}`, `GET /calls?trainee=&session_id=`

| `status` | |
|---|---|
| `dialing` | звонит телефон рабочего места |
| `in_progress` | разговор идёт |
| `ended` | `reason`: `completed`, `operator_hangup`, `max_turns`, `max_duration`, `ml_error`, `unknown_number`, `internal_error` |
| `failed` | `reason`: `no_answer`, `busy`, `rejected`, `unavailable` (телефон не зарегистрирован), `congestion`, `timeout`, `ami_error` |

`transcript`: `{"turn": 0, "role": "caller" | "operator", "text": "...", "audio": "/tts/….wav" | "/recordings/….wav"}`
(`caller` — собеседник, `operator` — обучающийся; пустой `text` у operator — молчал / не распознано).

### `POST /calls/{call_id}/hangup` — завершить (`202`; `409` — уже завершён)

### `GET /endpoints` — телефоны рабочих мест
```json
[{"endpoint": "ws01", "state": "Not in use", "registered": true, "active_channels": ""}, …]
```

### `GET /events?trainee=ws01` — поток событий в браузер (Server-Sent Events)

Фильтры: `trainee`, `session_id`, `call_id`. Формат — `event: <тип>` + `data: <JSON события>` (п. 2),
каждые 15 с комментарий-пинг. Реплика собеседника приходит в момент, когда начинает звучать.

### `GET /health`
```json
{"status": "ok", "ami": true, "voice_service": true, "ml_api_url": "http://mocks:8093/ml",
 "backend_url": "http://mocks:8093/backend", "directory_contacts": 10, "active_calls": 0}
```

---

## 2. События звонка → Backend (webhook) и SSE

`POST {BACKEND_URL}/telephony/events` на каждое событие; ответ `2xx`. Повторы через 0.5, 1, 2, 5 с,
иначе событие остаётся в `data/sessions/sessions.log` (JSON Lines, те же объекты). Порядок сохраняется.

Общие поля: `event`, `timestamp` (ISO 8601 UTC), `call_id`, `session_id`, `scenario_id`, `call_type`, `trainee`.

| `event` | Когда | Доп. поля |
|---|---|---|
| `call.dialing` | принят `POST /calls` | `channel`, `persona` (service, name, position, number) |
| `call.failed` | не дозвонились | `reason` |
| `call.started` | разговор начался | `direction`, `channel`, `caller_id`, `persona`, `card_id` |
| `call.utterance` | реплика | `turn`, `role`, `text`, `audio`, `latency` (`ml_sec`, `tts_sec` / `stt_sec`) |
| `call.error` | сбой сервиса | `stage` (`ml`/`tts`/`stt`/`internal`), `error` |
| `call.ended` | конец | `reason`, `duration_sec`, `recording_url`, `persona`, `card_id`, `transcript` |

Для Backend: `call.ended` — готовая «отработка» карточки (служба = `persona.service`, кто принял =
`persona.name`, суть = `transcript`, время, запись). Для оценки ML — `transcript` доклада диспетчера.

---

## 3. ML: реплика собеседника

`POST {ML_API_URL}/dialogue/turn` на каждом шаге. API **без состояния**: вся история в запросе.

```json
{
  "session_id": "s-42", "scenario_id": "", "call_id": "4f0c…",
  "call_type": "dispatch",
  "persona": {"id": "mchs_101", "number": "2101", "service": "Служба 101 (МЧС)", "name": "Петров Андрей",
              "position": "Старший диспетчер ЦУКС", "gender": "male", "accept": "Я вас понял, информация принята…"},
  "context": {"card": {…}, "report": null, "trainee": "ws01"},
  "turn": 1,
  "history": [{"role": "caller", "text": "Старший диспетчер ЦУКС Петров, слушаю вас."},
              {"role": "operator", "text": "Возгорание мусора, Ясный проезд, дом десять…"}],
  "operator_text": "Возгорание мусора, Ясный проезд, дом десять…"
}
```
- `turn: 0`, `operator_text: null` — начало: первая фраза собеседника («Слушаю вас», доклад, «Алло?»).
- `history` включает последнюю реплику оператора; `operator_text` дублирует её; `""` — молчание.
- Ответ: `{"reply_text": "…", "end_call": false}` — текст озвучивается голосом `persona.gender`;
  `end_call: true` — собеседник кладёт трубку после реплики. Лишние поля игнорируются.
- Нужен быстрый ответ (цель < 2 с; таймаут 30 с). Ошибка → звонок завершается (`ml_error`).
- Сокращения адресов («ул.», «д.») раскрываются перед синтезом — ML может отдавать адрес как в карточке.

Эталон — `mocks/ml_dialogue.py`: правила по `call_type` (приветствие, переспрос адреса, если его нет
в докладе; «информация принята») и режим **LLM** — любой OpenAI-совместимый API:
```env
DIALOGUE_ENGINE=llm
LLM_API_URL=http://host.docker.internal:11434/v1   # Ollama на этой машине / vLLM / внешний API
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=                                        # если нужен
```
При недоступности LLM ответ по правилам (`engine: rules-fallback`), звонок не срывается.

---

## 4. Записи и аудио

| Файл (`data/…`, URL `RECORDINGS_BASE_URL/…`) | Что |
|---|---|
| `recordings/<call_id>.wav` | весь разговор (оба голоса) = `recording_url` |
| `recordings/<call_id>_opNN.wav` | реплика обучающегося на шаге NN (вход STT) |
| `tts/cache_<голос>_<хэш>.wav` | реплика собеседника (кэш: одинаковая фраза синтезируется один раз) |

WAV PCM 16 бит, моно, 8 кГц. MP3: `docker compose exec audio-tools python convert_to_mp3.py --once`.
voice-service: `POST /tts {"text", "voice": "male"|"female", "cache": true | "save_as": "имя"}`,
`POST /stt` (WAV или `{"path"}`), `GET /health` (список голосов).

---

## 5. Подключение Frontend

Минимальный код (браузер, без библиотек):
```js
const TEL = "http://localhost:8092";          // в config.js
const WS = "ws01";                            // SIP-аккаунт этого рабочего места

// открыли карточку -> телефония знает контекст (набор 2XXX/3000 с телефона)
await fetch(`${TEL}/trainees/${WS}/context`, {method: "PUT", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({session_id, card})});

// кнопка звонка у службы в карточке
const call = await (await fetch(`${TEL}/calls`, {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({call_type: "dispatch", trainee: WS, service: "Служба 101 (МЧС)"})})).json();

// состояние звонка и реплики вживую
const es = new EventSource(`${TEL}/events?trainee=${WS}`);
es.addEventListener("call.dialing",   e => toast("Звонок: поднимите трубку"));
es.addEventListener("call.started",   e => toast("Соединено"));
es.addEventListener("call.utterance", e => showLine(JSON.parse(e.data)));   // role, text
es.addEventListener("call.ended",     e => toast("Разговор завершён"));     // recording_url, transcript
es.addEventListener("call.failed",    e => toast("Не дозвонились: " + JSON.parse(e.data).reason)); // unavailable = софтфон не зарегистрирован
```
Входящий доклад старшего (`report`) придёт тем же потоком (`call.dialing` с `call_type: "report"`).

## 6. Подключение настоящих ML и Backend

```env
COMPOSE_PROFILES=                  # без заглушек
ML_API_URL=http://ml:8000          # телефония добавит /dialogue/turn
BACKEND_URL=http://backend:8000    # телефония добавит /telephony/events; пусто — только журнал
```
Сервисы в одной Docker-сети (корневой `docker-compose.yml` подключает compose ролей через `include`).
Проверка: `GET /health` → новые адреса; `python telephony/demo/demo_calls.py dispatch`.
