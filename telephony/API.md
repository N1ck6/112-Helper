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

Телефония работает в составе полного стенда (корневой `docker-compose.yml`) с сервисами команды:
ML — `http://ml:8000` (`/dialogue/turn`), Backend — `http://api:8000/api/v1` (события в его формате, п. 2.1),
а Backend поднимает звонки по своему контракту (п. 7). Браузер ходит через nginx: `/telephony/…`.

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

### `GET /numbers` — телефонная книга рабочего места
Службы (`call_type: dispatch`) + служебные номера:
```json
[{"number": "2101", "call_type": "dispatch", "title": "Служба 101 (МЧС)", "name": "Петров Андрей", …},
 {"number": "3000", "call_type": "applicant", "title": "Заявитель открытой карточки"},
 {"number": "700", "call_type": "incident_112", "scenario_id": "scenario_001", "title": "Учебный вызов 112: пожар в квартире"},
 {"number": "701", …}, {"number": "600", "call_type": "echo", "title": "Эхо-тест: проверка микрофона и звука"}]
```

### `PUT /trainees/{trainee}/status` — статус оператора в АРМ
`{"available": false}` — «недоступен»: вызовы **от системы** (`report`, `incident_112` без
`"initiated_by": "trainee"`) получают `409`. Звонки, которые обучающийся запускает сам, идут всегда.
`GET` — текущий статус (по умолчанию `true`). Статус виден и в `GET /endpoints` (`available`).

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
| `initiated_by` | необяз. | `"trainee"` — обучающийся нажал кнопку сам (статус «недоступен» не мешает) |
| `dial` | набор номера | вместо `call_type`: `"2101"` — см. ниже |
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

**Набор номера с панели** (`{"dial": "2101", "trainee": "ws01"}`): телефон рабочего места звонит
(«Набор 2101»), обучающийся снимает трубку — Asterisk набирает номер, дальше всё как при наборе
с трубки (гудки, собеседник по dialplan). Объект звонка: `dialed`, `call_type` по номеру
(`dispatch` / `applicant` / `incident_112` / `echo`), `persona` для служб. Номер — 2–6 цифр.

### `GET /calls/{call_id}`, `GET /calls?trainee=&session_id=`

| `status` | |
|---|---|
| `dialing` | звонит телефон рабочего места |
| `in_progress` | разговор идёт |
| `ended` | `reason`: `completed`, `operator_hangup`, `max_turns`, `max_duration`, `ml_error` (собеседник сказал о неполадке), `unknown_number`, `internal_error` |
| `failed` | `reason`: `no_answer`, `busy`, `rejected`, `unavailable` (телефон не зарегистрирован), `congestion`, `timeout`, `ami_error` |

`transcript`: `{"turn": 0, "role": "caller" | "operator", "text": "...", "audio": "/tts/….wav" | "/recordings/….wav"}`
(`caller` — собеседник, `operator` — обучающийся; пустой `text` у operator — молчал / не распознано).

### `POST /calls/{call_id}/hangup` — завершить (`202`; `409` — уже завершён)

### `GET /endpoints` — телефоны рабочих мест
```json
[{"endpoint": "ws01", "state": "Not in use", "registered": true, "active_channels": "", "available": true}, …]
```

### `GET /events?trainee=ws01` — поток событий в браузер (Server-Sent Events)

Фильтры: `trainee`, `session_id`, `call_id`. Формат — `event: <тип>` + `data: <JSON события>` (п. 2),
каждые 15 с комментарий-пинг. Реплика собеседника приходит в момент, когда начинает звучать.

### `GET /health`
```json
{"status": "ok", "ami": true, "voice_service": true, "ml": true, "backend": true,
 "ml_api_url": "http://ml:8000", "backend_url": "http://api:8000/api/v1",
 "directory_contacts": 12, "active_calls": 0}
```
`status: degraded` — нет ML или voice-service (`ml: false` — собеседники не ответят). `503` — нет Asterisk.

---

## 2. События звонка → Backend (webhook) и SSE

`POST {BACKEND_URL}/telephony/events` на каждое событие; ответ `2xx`. Повторы через 0.5, 1, 2, 5 с,
иначе событие остаётся в `data/sessions/sessions.log` (JSON Lines, те же объекты). Порядок сохраняется.

Общие поля: `event`, `timestamp` (ISO 8601 UTC), `call_id`, `session_id`, `scenario_id`, `call_type`, `trainee`.

| `event` | Когда | Доп. поля |
|---|---|---|
| `call.dialing` | принят `POST /calls` | `channel`, `persona` (service, name, position, number), `dialed` (набор) |
| `call.failed` | не дозвонились | `reason` |
| `call.started` | разговор начался | `direction`, `channel`, `caller_id`, `persona`, `card_id` |
| `call.utterance` | реплика | `turn`, `role`, `text`, `audio`, `latency` (`ml_sec`, `tts_sec` / `stt_sec`) |
| `call.error` | сбой сервиса | `stage` (`ml`/`tts`/`stt`/`internal`), `error` |
| `call.ended` | конец | `reason`, `duration_sec`, `recording_url`, `persona`, `card_id`, `transcript` |
| `operator.status` | статус в АРМ | `trainee`, `available` (без `call_id`) |

Для Backend: `call.ended` — готовая «отработка» карточки (служба = `persona.service`, кто принял =
`persona.name`, суть = `transcript`, время, запись). Для оценки ML — `transcript` доклада диспетчера.

### 2.1 Формат Backend (`BACKEND_EVENTS_FORMAT=backend`, полный стенд)

Backend принимает только смену статуса вызова (`backend/docs/INTEGRATION.md` §2.2), поэтому в полном
стенде события переводятся в его контракт и уходят с заголовком `X-Telephony-Token: <TELEPHONY_WEBHOOK_TOKEN>`:

| Событие телефонии | `event` для Backend |
|---|---|
| `call.dialing` | `ringing` |
| `call.started` | `answered` |
| `call.ended` | `ended` |
| `call.failed` | `missed` (`no_answer`, `busy`, `timeout`) или `failed` |
| `call.utterance`, `call.error`, `operator.status` | не отправляются (есть в SSE и `sessions.log`) |

```json
{"sip_call_id": "4f0c…", "event": "ended", "lesson_id": "…", "attempt_id": "…", "student_id": "…",
 "caller_number": "112", "callee_number": "ws05", "duration_ms": 41600,
 "audio_path": "http://localhost:8090/4f0c….wav", "audio_format": "wav",
 "meta": {"telephony_event": "call.ended", "session_id": "…", "call_type": "incident_112",
          "trainee": "ws05", "reason": "completed", "persona": {…}, "transcript": […]}}
```
`lesson_id` / `attempt_id` / `student_id` есть, только если звонок поднял Backend (п. 7): он передал их
в запросе, телефония возвращает их в каждом событии. `sip_call_id` = `call_id` телефонии.
`BACKEND_EVENTS_FORMAT=raw` — события в исходном виде (для отладки).

---

## 3. ML: реплика собеседника

`POST {ML_API_URL}/dialogue/turn` на каждом шаге. Реализация — ML-сервис (`ml/integration/dialogue.py`).
API **без состояния**: вся история в запросе.

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
  `end_call: true` — собеседник кладёт трубку после реплики. Необязательное `"voice": "male" | "female"`
  меняет голос (пол заявителя из сценария 112). Лишние поля игнорируются.
- Нужен быстрый ответ (цель < 2 с; таймаут 30 с). Ошибка → собеседник говорит «на линии техническая
  неполадка», звонок завершается (`ml_error`).
- Сокращения адресов («ул.», «д.») раскрываются перед синтезом — ML может отдавать адрес как в карточке.

Движки: правила по `call_type` (приветствие, переспрос адреса, если его нет в докладе; «информация
принята») и режим **LLM**. Вызов 112 без готового сценария (`scenario_id` не найден) строится из
`context.card`: заявитель называет суть, адрес и пострадавших из карточки.

В ML-сервисе полного стенда (корневой `.env`):
```env
DIALOGUE_ENGINE=llm
DIALOGUE_LLM_MODEL=qwen3:4b-instruct   # Ollama стенда (профиль llm): docker exec trainer-ollama ollama pull qwen3:4b-instruct
LLM_TIMEOUT_SEC=20
```
Нужна instruct-модель: `qwen3:4b` рассуждает вслух (ответ 10+ с, без готовой реплики). Любой другой
OpenAI-совместимый сервер — `LLM_API_URL=http://…/v1`, `LLM_API_KEY`. При недоступности LLM ответ
по правилам (`engine: rules-fallback`), звонок не срывается.

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

**Подключено.** Корневой `docker compose up -d`: nginx на `:8080` отдаёт frontend и на том же адресе
проксирует телефонию — `/telephony/*` → API `:8092` (с SSE), `/recordings/*` → записи
([deploy/nginx/default.conf](../deploy/nginx/default.conf)). Один origin: нет CORS и смешанного
контента, работает с других ПК по LAN. Адрес API — `APP_CONFIG.TELEPHONY_API_URL` (`frontend/js/config.js`):
`"telephony"` на стенде, `"http://localhost:8092"` для страницы с GitHub Pages / файла.

Звонки в интерфейсе — [frontend/js/telephony.js](../frontend/js/telephony.js):

| Где | Что | Запрос |
|---|---|---|
| низ справа | панель «Телефон»: аккаунт, телефон подключён, ML доступен, звонок, реплики, «Завершить», запись | `/endpoints`, `/health`, `/events`, `hangup` |
| панель | номеронабиратель (мышь/клавиатура) + справочник | `{"dial"}`, `/numbers` |
| панель, диспетчер | «Доклад старшего группы» — входящий доклад службы карточки (этапы по очереди) | `report` |
| панель | отработки по открытой карточке: служба, номер, кто принял, суть, время, запись | — |
| карточка оператора и диспетчера | ☎ у каждой службы | `dispatch` |
| карточка оператора, шапка | «☎ Вызов голосом» — учебный заявитель 112 звонит на телефон | `incident_112` |
| карточка диспетчера | «Перезвонить и уточнить» | `applicant` |
| открытие/правка карточки | карточка → контекст рабочего места (набор 2XXX / 3000 с трубки) | `PUT context` |
| шапка: доступен / недоступен | статус оператора | `PUT status` |

Связь с `app.js` — события `dds:card-open`, `dds:card-close`, `dds:review-open`, `dds:review-close`,
`dds:callback`, `dds:operator-status` и `window.DDS.addCallLog(id, entry)` — отработка сохраняется
в карточке (`incident.calls[]`). Рабочее место: `session.workstation` (когда появится во входе),
`?ws=ws02` в адресе (запоминается) или `ws01`.

Минимальный код для своей реализации (браузер, без библиотек):
```js
const TEL = "telephony";                      // через nginx стенда; напрямую — "http://localhost:8092"
const WS = "ws01";                            // SIP-аккаунт этого рабочего места

// открыли карточку -> телефония знает контекст (набор 2XXX/3000 с телефона)
await fetch(`${TEL}/trainees/${WS}/context`, {method: "PUT", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({session_id, card})});

// кнопка звонка у службы в карточке / набор номера
await fetch(`${TEL}/calls`, {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({call_type: "dispatch", trainee: WS, service: "Служба 101 (МЧС)", initiated_by: "trainee"})});
await fetch(`${TEL}/calls`, {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({dial: "2101", trainee: WS})});

// состояние звонка и реплики вживую
const es = new EventSource(`${TEL}/events?trainee=${WS}`);
es.addEventListener("call.dialing",   e => toast("Звонок: поднимите трубку"));
es.addEventListener("call.started",   e => toast("Соединено"));
es.addEventListener("call.utterance", e => showLine(JSON.parse(e.data)));   // role, text
es.addEventListener("call.ended",     e => toast("Разговор завершён"));     // recording_url, transcript
es.addEventListener("call.failed",    e => toast("Не дозвонились: " + JSON.parse(e.data).reason)); // unavailable = телефон не зарегистрирован
```
Входящий доклад старшего (`report`) придёт тем же потоком (`call.dialing` с `call_type: "report"`).

## 6. Связь с ML и Backend

Значения по умолчанию в `telephony/docker-compose.yml` (корневой compose подключает его через include):
```env
ML_API_URL=http://ml:8000                  # телефония добавит /dialogue/turn
BACKEND_URL=http://api:8000/api/v1         # телефония добавит /telephony/events
BACKEND_EVENTS_FORMAT=backend              # контракт Backend (п. 2.1)
TELEPHONY_WEBHOOK_TOKEN=…                  # тот же, что у Backend
```
Проверка: `GET /telephony/health` → `"ml": true, "backend": true`;
`pytest tests/test_stage9_integration.py`.

## 7. Контракт Backend: звонки занятия

Backend вызывает телефонию по своему контракту (`backend/docs/INTEGRATION.md` §2.1,
`TELEPHONY_SERVICE_URL=http://virtual-caller:8092`).

### `POST /api/v1/calls/originate`
```json
{"lesson_id": "…", "attempt_id": "…", "student_id": "…", "card_no": "У-000012",
 "caller_profile": {…}, "caller_number": "+7 …", "callee_number": "05", "record": true}
```
- Без `direction` — входящий вызов 112 обучающемуся: `callee_number` — SIP-аккаунт (`ws05`) или номер
  рабочего места (`05` → `ws05`), иначе `DEFAULT_TRAINEE`. Сценарий — `scenario_id` или `DEFAULT_112_SCENARIO`.
- `direction: "outbound"` — отработка: обучающийся (`caller_number`) звонит в службу (`callee_name` /
  `callee_number` по справочнику, «101» → 2101) или заявителю (`kind: "applicant"`); номер не из
  справочника набирается как есть.
- Ответ `200`: `{"sip_call_id": "…", "status": "ringing", "caller_number": "…", "callee_number": "ws05",
  "trainee": "ws05", "latency_ms": null}`. `409` — оператор в статусе «недоступен».

### `POST /api/v1/calls/hangup`
`{"sip_call_id": "…"}` → `{"status": "ending"}`; уже завершённый звонок — его статус, не ошибка.
