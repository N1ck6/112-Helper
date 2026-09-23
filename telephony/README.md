# Telephony — SIP, голос, запись

Контур телефонии учебного тренажёра: локальный SIP-сервер, виртуальный абонент,
который разговаривает с обучающимся голосом (STT → ML → TTS), запись звонков и
API для Backend. **Контракт для других ролей — [API.md](API.md).**

## Быстрый старт

```bash
cd telephony
cp .env.example .env                 # пароли; уже есть .env — дописать блоки «Этап 5» и «Этап 6-7»
docker compose build
docker compose run --rm voice-service python download_models.py   # однократно, ~0.5 ГБ, нужен интернет
docker compose up -d
docker compose ps                    # asterisk, voice-service, virtual-caller, mocks -> healthy
```

Без моделей: `STT_ENGINE=mock` и `TTS_ENGINE=mock` в `.env` (тон вместо речи, фиксированный текст вместо распознавания).

Позвонить обучающемуся (софтфон `alice` зарегистрирован на порту 5063):

```bash
curl -X POST http://localhost:8092/calls -H "Content-Type: application/json"      -d '{"scenario_id": "scenario_001", "trainee": "alice"}'
```

Или самому набрать с софтфона `700` / `701`. События разговора — http://localhost:8093/backend/telephony/events,
записи — http://localhost:8090/.

## Сервисы

| Сервис | Порт (хост) | Что делает |
|---|---|---|
| `asterisk` | SIP 5063, AMI 5041, RTP 10033-10043 | SIP/VoIP, dialplan, запись MixMonitor |
| `virtual-caller` | API 8092 (FastAGI 4573 внутри) | голосовой цикл звонка, API звонков, события в Backend |
| `voice-service` | 8091 | STT (faster-whisper) / TTS (Piper), сменные движки |
| `audio-tools` | 8090 | список и проигрывание записей, конвертация в MP3 |
| `mocks` (профиль `mocks`) | 8093 | заглушки ML (`/ml`) и Backend (`/backend`) до интеграции |

Данные на хосте: `data/recordings/` (WAV), `data/sessions/sessions.log` (события JSON Lines),
`data/tts/` (реплики абонента), `telephony/models/` (модели, в .gitignore).

Номера: `600` — эхо-тест, `601` — тон 1004 Гц, `1001`/`1002` — alice ↔ bob, `700`/`701` — учебные сценарии.

---

# Этап 6-7 — голосовой цикл и API звонков (`virtual_caller/`, `mocks/`)

```
POST /calls ─► AMI Originate PJSIP/<trainee> ─► ответ ─► [training-run]: MixMonitor + AGI
                                                              │
   ┌──────────────────────────────────────────────────────────┘
   ▼
 ML /dialogue/turn ─► TTS /tts (save_as) ─► STREAM FILE /tts/<call>_cNN
   ▲                                                   │
   │                        RECORD FILE до паузы (SILENCE_SEC) или '#'
   └── STT /stt {"path"} ◄── /recordings/<call>_opNN.wav
... пока ML не вернёт end_call или не сработает MAX_TURNS / MAX_CALL_SEC
```

## Структура

| Файл | Роль |
|---|---|
| `virtual_caller/caller/dialogue.py` | Цикл разговора, реакция на сбои (нет TTS → звук-заглушка, нет STT → «молчание», нет ML → конец звонка) |
| `virtual_caller/caller/agi.py` | Протокол FastAGI, распознавание отбоя (строка `HANGUP`, код 511) |
| `virtual_caller/caller/api.py` | HTTP API звонков (`/calls`, `/endpoints`, `/health`) |
| `virtual_caller/caller/ami.py` | AMI: Originate (с `ChannelId` = `call_id`), Hangup, PJSIPShowEndpoints |
| `virtual_caller/caller/events.py` | События: `sessions.log` + webhook в Backend с повторами |
| `virtual_caller/caller/clients.py` | HTTP-клиенты voice-service и ML |
| `virtual_caller/caller/calls.py` | Реестр звонков в памяти |
| `virtual_caller/caller/config.py` | Настройки из env |
| `mocks/mock_services.py` | Заглушки ML (ответ по ключевым словам сценария) и Backend (приём/просмотр событий) |
| `mocks/scenarios/*.json` | Сценарии для заглушки ML |
| `asterisk/conf/extensions.conf` | `[training]` 700/701 → `[training-run]`; `[autotest]` — имитация диспетчера для автотестов |

## Проверка

```bash
curl http://localhost:8092/health
curl http://localhost:8092/endpoints                       # alice registered: true?
curl -X POST http://localhost:8092/calls -H "Content-Type: application/json"      -d '{"scenario_id":"scenario_001","trainee":"alice"}'    # софтфон зазвонит
curl http://localhost:8092/calls/<call_id>                 # статус и расшифровка
curl "http://localhost:8093/backend/telephony/events?call_id=<call_id>"
```

Без софтфона — вместо `trainee` передать `"channel": "Local/operator@autotest"`: трубку «возьмёт»
dialplan и будет периодически проигрывать фразу.

Автотест: `pytest tests/test_stage6_dialogue.py -v` — 25 unit-тестов (без Docker) + интеграционный
звонок через API до `call.ended` с проверкой событий и записи.

## Ограничения

- Перебивать абонента нельзя: пока играет реплика, запись не идёт (AGI синхронный).
- Конец реплики оператора — `SILENCE_SEC` тишины. Тишина считается и с начала записи: не ответил за
  `SILENCE_SEC` — реплика пустая. Телефоны с подавлением тишины (VAD без comfort noise) не шлют RTP
  в паузах — запись тогда идёт до `MAX_UTTERANCE_SEC`; VAD на телефоне выключить.
- Пауза перед ответом абонента ≈ `SILENCE_SEC` + STT (~1.5 с, whisper small, CPU) + ML + TTS (~0.2 с).
- Аккаунты обучающихся пока два (`alice`, `bob`).

## Definition of Done

- [x] голосовой цикл SIP → STT → ML API → TTS → SIP; ML — внешний сервис по HTTP, не в SIP-коде
- [x] API запуска/статуса/завершения звонка, статусы и причины, события в Backend с буфером в `sessions.log`
- [x] `session_id` / `scenario_id` / `call_id` сквозные: API → Asterisk → AGI → события → имя записи
- [x] заглушки ML и Backend с теми же контрактами (`API.md`), переключение адресом в `.env`
- [x] автотесты: unit без Docker + E2E-звонок без человека

---

# Этап 4 — аудио (запись, WAV, MP3, воспроизведение)

- **Весь разговор**: `MixMonitor(${RECORD_FILE})` в `[training-run]` → `data/recordings/<call_id>.wav`.
  Раньше стояла опция `b` (писать только в мосте) — у AGI-звонка моста нет, файлы были пустые (44 байта).
- **Реплики оператора**: `RECORD FILE` в голосовом цикле → `data/recordings/<call_id>_opNN.wav`.
- **MP3 по требованию**: `docker compose exec audio-tools python convert_to_mp3.py --once` (или `--watch`).
- **Воспроизведение**: http://localhost:8090/ — список файлов, WAV/MP3 играют в браузере.
- **Список с привязкой к сценарию**: `docker compose exec audio-tools python list_recordings.py`.

Автотест: `tests/test_stage4_audio.py` — звонок через AMI, новый WAV с заголовком RIFF и непустыми данными.

## Известная проблема: обрыв звонка на ~32-й секунде (исправлено)

- Симптом: любой звонок рвался через ~32 с.
- Причина: в Contact/Via Asterisk указывал `127.0.0.1:5060` (порт внутри контейнера), а на хост проброшен `5063`. ACK от софтфона не доходил; Asterisk переотправлял `200 OK` и через 64×T1 = 32 с (RFC 3261, Timer H/B) завершал вызов.
- Фикс: `external_signaling_port = ${EXTERNAL_SIGNALING_PORT}` в `pjsip.conf`; та же переменная задаёт левую часть `ports` в `docker-compose.yml` (по умолчанию 5063).
- Проверка: `docker exec -it telephony-asterisk asterisk -rx "pjsip set logger on"`, позвонить на 700, в `docker logs` найти `200 OK` → в `Contact:` должен быть `:5063`, после него один `ACK`, без повторных `200 OK`.

---

# Этап 5 — STT/TTS-интерфейсы (`voice_service/`)

Отдельный сервис `voice-service` (порт 8091). Asterisk и virtual_caller о движках не знают: общаются только через HTTP.

```
Audio (WAV) -> POST /stt -> {"text": ...}          faster-whisper | mock
Text        -> POST /tts -> WAV 8 кГц PCM16 mono   Piper          | mock
```

## Структура

| Файл | Роль |
|---|---|
| `voice/stt/base.py`, `voice/tts/base.py` | Контракты `STTEngine.transcribe(wav) -> STTResult`, `TTSEngine.synthesize(text, rate) -> TTSResult` |
| `voice/stt/faster_whisper_engine.py` | faster-whisper, CPU int8, VAD, модель из `models/whisper/<WHISPER_MODEL>` |
| `voice/tts/piper_engine.py` | Piper, голос из `models/piper/<PIPER_VOICE>.onnx`, ресемплинг 22050→8000 (ffmpeg) |
| `voice/stt/mock.py`, `voice/tts/mock.py` | Заглушки без моделей: фиксированный текст / тон длиной ∝ тексту |
| `voice/stt/__init__.py`, `voice/tts/__init__.py` | Фабрики по `STT_ENGINE` / `TTS_ENGINE` |
| `voice/server.py` | HTTP API (stdlib) |
| `voice/cli.py` | Проверка движков без HTTP |
| `download_models.py` | Однократная загрузка моделей в `./models` |

Замена движка: новый класс-наследник `STTEngine`/`TTSEngine` + одна ветка в фабрике. Код вызывающих сервисов не меняется.

## API

| Метод | Запрос | Ответ |
|---|---|---|
| `GET /health` | — | `200 {"status":"ok","stt":{"engine","ready","error"},"tts":{...}}`; `503` + `"degraded"` и причина, если модель не загружена |
| `POST /stt` | тело WAV, `Content-Type: audio/wav`, `?language=ru` | `{"text","language","duration_sec","processing_sec","engine","segments":[{"start","end","text"}]}` |
| `POST /stt` | `application/json` `{"path":"response_<call_id>.wav","language":"ru"}` — файл из `/recordings` (без передачи байтов) | то же |
| `POST /tts` | `{"text":"...","sample_rate":8000}` | `audio/wav`; заголовки `X-Engine`, `X-Sample-Rate`, `X-Duration-Sec`, `X-Processing-Sec` |
| `POST /tts` | `{"text":"...","save_as":"<call_id>_p1"}` | `{"path":"/tts/<name>.wav","asterisk_sound":"/tts/<name>",...}` — файл сразу доступен Asterisk для `STREAM FILE /tts/<name>` |

Ошибки: `400` (не WAV, пустой/длинный текст >1000, неверный `sample_rate`/`save_as`, путь вне `/recordings`), `404` (файл не найден), `413` (тело >20 МБ), `503` (движок не готов), `500`. Формат: `{"error": "..."}`. Заголовок `X-Call-Id` пишется в лог.

## Запуск

```bash
cd telephony
docker compose build voice-service
# 1) однократно, нужен интернет (~0.5 ГБ: whisper small + голос Piper):
docker compose run --rm voice-service python download_models.py
# 2) дальше без интернета:
docker compose up -d
docker compose ps               # voice-service -> healthy
```

Без моделей: `STT_ENGINE=mock TTS_ENGINE=mock` в `.env` — сервис работает, контракт тот же.

## Проверка

```bash
curl http://localhost:8091/health

# TTS -> файл
curl -X POST http://localhost:8091/tts -H "Content-Type: application/json" \
     -d '{"text":"Помогите, пожар на улице Ленина"}' -o tts.wav

# STT этого файла (цикл Text -> Audio -> Text)
curl -X POST "http://localhost:8091/stt?language=ru" -H "Content-Type: audio/wav" --data-binary @tts.wav

# STT ответа диспетчера из реального звонка (этап 4)
curl -X POST http://localhost:8091/stt -H "Content-Type: application/json" \
     -d '{"path":"response_<call_id>.wav"}'

# Движки напрямую, без HTTP
docker compose exec voice-service python -m voice.cli tts "Дым в коридоре" -o /tts/test.wav
docker compose exec voice-service python -m voice.cli stt /tts/test.wav
```

Windows PowerShell: вместо `curl` использовать `curl.exe`, JSON в одинарных кавычках.

Автотест: `pytest tests/test_stage5_voice.py -v` — 17 unit-тестов (без Docker, mock-движки) + интеграционный тест TTS→STT к запущенному контейнеру (с реальными движками проверяет, что распознано слово «пожар»).

## Definition of Done

- [x] код в `telephony/voice_service/`, сервис в `telephony/docker-compose.yml`
- [x] STT и TTS — независимые сменные модули (фабрика + общий контракт), mock для разработки без моделей
- [x] локальные движки faster-whisper и Piper, рантайм без интернета (`HF_HUB_OFFLINE=1`, модели в томе)
- [x] health check (`/health`, Docker healthcheck), логи каждого запроса с длительностью и `call_id`
- [x] секретов нет; модели в `.gitignore`
- [x] этапы 1–4 не изменены (Asterisk получил только том `/tts:ro` для этапа 6)
- [x] проверено вживую: сборка, `download_models.py`, реальные faster-whisper и Piper (2026-09-23)
