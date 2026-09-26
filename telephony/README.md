# Telephony — IP-телефония, голос, Docker

Контур телефонии тренажёра диспетчера ДДС: локальный SIP-сервер, виртуальные
собеседники с голосом (STT → ML → TTS), запись звонков, API для Frontend/Backend.
**Контракты для других ролей — [API.md](API.md).** Работает без интернета
(после однократной загрузки моделей).

## Что умеет

| Звонок (`call_type`) | Кто кому | Как начинается |
|---|---|---|
| `dispatch` — **основной** | диспетчер ДДС → руководитель/дежурный службы | набор 2XXX с телефона или кнопка у службы в карточке (`POST /calls`) |
| `report` | старший группы → диспетчер ДДС (доклад: прибытие / работы / завершение) | `POST /calls` от Backend/преподавателя |
| `applicant` | диспетчер ДДС → заявитель из карточки | набор 3000 или `POST /calls` |
| `incident_112` | заявитель → оператор 112 (голосовые вводные) | набор 700/701 или `POST /calls` |

- Собеседник отвечает голосом по категории: мужской (Piper *dmitri*) или женский (*irina*).
  Реплики формирует ML-сервис по истории разговора и карточке. Пока ML нет —
  заглушка `mocks/` (правила или любая OpenAI-совместимая LLM по адресу из `.env`).
- Каждый звонок: запись WAV обоих голосов, расшифровка, события в Backend и в браузер (SSE),
  связь с рабочим местом, сессией и карточкой.
- Рабочие места `ws01…ws20` — SIP-аккаунты для софтфона/IP-телефона на каждом АРМ.
- Нагрузка: 10 одновременных звонков проверены автотестом; RTP-диапазон — до 30 разговоров.

## Запуск

```bash
cd telephony
cp .env.example .env                  # пароли; для существующего .env — дописать новые блоки
docker compose build
docker compose run --rm voice-service python download_models.py   # один раз, ~0.6 ГБ, нужен интернет
docker compose up -d                  # с COMPOSE_PROFILES=mocks из .env поднимутся и заглушки
docker compose ps                     # все сервисы healthy
```

Полный стенд с frontend — из корня репозитория: `COMPOSE_PROFILES=mocks docker compose up -d`
(frontend на http://localhost:8080). Не запускать одновременно со стендом из `telephony/`.
Без моделей: `STT_ENGINE=mock`, `TTS_ENGINE=mock`.

## Демонстрация и проверка

```bash
python telephony/demo/demo_calls.py                 # 5 тестовых звонков без человека, печатает расшифровки
python telephony/demo/demo_calls.py --parallel 10   # 10 звонков одновременно
python telephony/demo/demo_calls.py dispatch --trainee ws01   # позвонит на ваш софтфон ws01
pytest tests/ -v                                     # AMI_PASSWORD=<из .env>; без стенда — только unit
```

Реплики «диспетчера» в демо и тестах заранее синтезируются голосом Irina (`data/tts/operator_9XXX.wav`)
и проигрываются имитацией рабочего места `Local/9XXX@autotest`.

Софтфон вручную (MicroSIP/Zoiper/Linphone): сервер `<IP машины>:5063`, UDP, логин `ws01`,
пароль `TRAINEE_PASSWORD`. Отключить VAD/подавление тишины. Набрать `2101` — Служба 101 (МЧС),
`2103` — СМП, `3000` — заявитель открытой карточки, `600` — эхо-тест. Софтфон на другом ПК —
`EXTERNAL_MEDIA_ADDRESS` = LAN-IP этой машины.

Записи: http://localhost:8090/ · события: http://localhost:8093/backend/telephony/events ·
API: http://localhost:8092/health, `/directory`, `/calls`.

## Сервисы и порты

| Сервис | Порт хоста | Роль |
|---|---|---|
| `asterisk` | SIP 5063, AMI 5041, RTP 10000–10059 | SIP/VoIP, dialplan, запись (MixMonitor) |
| `virtual-caller` | 8092 (FastAGI 4573 внутри) | голосовой цикл, API звонков, события, справочник служб |
| `voice-service` | 8091 | STT faster-whisper / TTS Piper (2 голоса, кэш фраз), сменные движки |
| `audio-tools` | 8090 | записи: список, прослушивание, MP3 |
| `mocks` (профиль `mocks`) | 8093 | заглушки ML (`/ml`) и Backend (`/backend`) |

Данные хоста: `data/recordings/` (WAV), `data/sessions/sessions.log` (события), `data/tts/` (синтез),
`telephony/models/` (модели). Всё это в `.gitignore`.

## Структура

```
telephony/
├── API.md                  контракт: API звонков, события, ML, интеграция frontend
├── docker-compose.yml      все сервисы контура; .env.example — все настройки с пояснениями
├── asterisk/               Dockerfile, entrypoint (рендер конфигов, аккаунты ws01..), conf/ (pjsip, dialplan)
├── virtual_caller/
│   ├── directory.json      справочник служб: номер, должность, пол голоса, текст ответа
│   └── caller/             dialogue.py (цикл), api.py (HTTP + SSE), agi.py, ami.py, events.py, calls.py
├── voice_service/voice/    stt/, tts/ (контракты + движки), server.py, textnorm.py (сокращения адресов)
├── mocks/                  mock_services.py (HTTP), ml_dialogue.py (правила + LLM), scenarios/
├── audio_tools/            MP3, список и раздача записей
└── demo/demo_calls.py      тестовые звонки
```

Добавить службу — объект в `directory.json`. Добавить движок STT/TTS — класс + строка в фабрике.
Подключить LLM — `DIALOGUE_ENGINE=llm`, `LLM_API_URL`, `LLM_MODEL` в `.env`.

## Ограничения

- Перебить собеседника нельзя: пока он говорит, речь не записывается (AGI синхронный).
- Конец реплики — `SILENCE_SEC` тишины (или `#`); первая пустая запись повторяется один раз.
- Телефоны с подавлением тишины (VAD без comfort noise) не шлют RTP в паузах — реплика пишется до
  `MAX_UTTERANCE_SEC`; VAD отключить.
- Пауза перед ответом собеседника ≈ `SILENCE_SEC` + STT (~1.5–2 с, whisper small на CPU) + ML + TTS (~0.3 с).
- Звонок из браузера (WebRTC-софтфон в интерфейсе АРМ) не реализован: голос идёт через софтфон
  или IP-телефон рабочего места, браузер управляет звонком через API.
- Файлы синтеза `data/tts/cache_*.wav` не удаляются автоматически.

## Проблемы и решения

- **Обрыв на 32-й секунде** — порт в Contact/Via ≠ порт хоста: `EXTERNAL_SIGNALING_PORT` = левая часть `ports`.
- **Нет звука** — `EXTERNAL_MEDIA_ADDRESS` или диапазон `rtp.conf` ≠ проброс RTP в compose.
- **Пустая запись (44 байта)** — у MixMonitor не должно быть опции `b` (AGI-звонок не в мосте).
- **`unhealthy` на Windows** — CRLF в `*.sh`; `.gitattributes` держит LF, Dockerfile срезает `\r`.
- **Собеседник молчит / звонок сразу кончается** — `curl localhost:8092/health`,
  `docker compose logs virtual-caller` (события `call.error` со `stage`: ml / tts / stt).
