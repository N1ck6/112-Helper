# Учебный тренажёр ДДС

Локальный учебный тренажёр для подготовки операторов ДДС с имитацией
АРМ-112, учебных сценариев и голосовых вызовов.

Проект не обрабатывает реальные экстренные вызовы и не является системой-112.

## Назначение

Обучающийся принимает учебный входящий звонок, ведёт диалог с
виртуальным абонентом (или с реальным softphone/IP-телефоном), а система
фиксирует сессию: голос, текст, сценарий и результат отработки.

Основные возможности:

- локальный SIP/VoIP-контур (Asterisk, PJSIP, RTP);
- программный softphone и подключение физического IP-телефона;
- виртуальный учебный абонент со сценариями;
- запись вызовов (WAV / MP3) и воспроизведение;
- общее управление с аккаунта преподавателя;
- STT/TTS как сменные модули;
- диалоговый цикл: SIP → аудио → STT → ML/LLM API → TTS → SIP;
- привязка звонка к `session_id` / `scenario_id` / `call_id`;
- полный локальный стенд на Docker Compose без внешнего интернета в runtime.

## Архитектура

| Модуль | Роль |
|--------|------|
| **telephony** | SIP-сервер, звонки, RTP, запись, virtual caller, voice-service |
| **backend** | пользователи и роли, занятия, карточки, оценки, отчёты; API для frontend/ML/telephony |
| **frontend** | учебный интерфейс оператора (имитация АРМ) |
| **ml** | классификатор, генерация сценариев, оценка, реплики собеседников, LLM (Ollama) |
| **deploy** | nginx единой точки входа, надстройка телефонии для полного стенда |

## Стек

- SIP/PBX: Asterisk (PJSIP)
- Voice-сервисы: Python
- STT: faster-whisper
- TTS: Piper
- API: REST/JSON
- БД: PostgreSQL
- Контейнеризация: Docker / Docker Compose
- Аудио: WAV, MP3; FFmpeg при конвертации
- Тесты: pytest, AMI (проверка Asterisk)

## С чего начать

Весь комплекс (frontend, backend + PostgreSQL, ML + локальная LLM, телефония) — одной командой
из корня репозитория:

```bash
docker compose --profile llm up -d --build
```

Без профиля `llm` стенд поднимается без Ollama: ML работает на классификаторе и правилах,
анализ текста через LLM (`/analyze`) недоступен.

| Адрес | Что это |
|---|---|
| http://localhost:8080 | АРМ (с другого ПК — `http://<IP>:8080`); через него же браузер ходит в `/api/`, `/telephony/`, `/ml/dialogue/` |
| http://localhost:8000/docs | API backend |
| http://localhost:8100/docs | API ML-сервиса |
| `<IP>:5063` UDP | SIP для софтфона рабочего места (`ws01`…`ws20`) |

Первый старт скачивает модели STT/TTS (~0.6 ГБ) и LLM `qwen3:4b` (~2.5 ГБ); интернет нужен
один раз, дальше стенд работает без сети. Учебные учётные записи (создаёт `backend/scripts/seed.py`):
`admin` / `Admin#2026`, `teacher` / `Teacher#2026`, `student` / `Student#2026`.
Обучающийся входит в роли «Оператор» или «Диспетчер», выбирая номер рабочего места.

Как связаны части (контракты — `telephony/API.md`, `backend/docs/INTEGRATION.md`):

```text
frontend ─/api/v1─> backend ──> PostgreSQL
    │                  ├─ генерация и оценка ──> ML   (что ML не умеет, 501 или сбой — правила backend)
    │                  └─ /api/v1/calls/originate ──> телефония (входящий 112 на рабочее место)
    └─/telephony/──> телефония ─/dialogue/turn─> ML ─(profile llm)─> Ollama
                         └─ события звонка ──> backend /api/v1/telephony/events (X-Telephony-Token)
```

Настройки — `.env` в корне (шаблон `.env.example`) и `telephony/.env` (шаблон
`telephony/.env.example`). Оба файла необязательны, но для эксплуатации нужно сменить
`SECRET_KEY`, `POSTGRES_PASSWORD`, `TELEPHONY_WEBHOOK_TOKEN` и пароли SIP/AMI.

Автотесты (нужен запущенный стенд; пароль AMI — из `telephony/.env`):

```bash
pip install -r tests/requirements.txt
```

```bash
pytest tests/ -v
```

## Структура репозитория

```text
telephony/      SIP/VoIP, запись, virtual caller, voice-service
backend/        API сессий, сценариев, статусов звонка
frontend/       UI учебного АРМ
ml/             LLM и сценарная логика
deploy/         nginx стенда, подключение телефонии к ML/Backend
tests/          pytest, AMI-клиент
data/           записи, логи сессий (локально)
.env.example    перечень переменных окружения
```

Подробности по модулям — в `README.md` соответствующих каталогов `frontend/`, `backend/`, `telephony/`, `ml/`.

## Переменные и порты

Базовые сущности интеграции: `session_id`, `scenario_id`, `call_id`,
события старта/завершения звонка, статусы и ошибки.

Типичные порты локального стенда (точные значения — в `.env` / compose):

- SIP (UDP/TCP)
- RTP (диапазон UDP)
- AMI (управление/мониторинг Asterisk)
- HTTP voice-service / API backend / frontend

## Лицензия

Исходный код проекта распространяется по лицензии Apache License 2.0.

Права на сторонние и предоставленные заказчиком материалы могут регулироваться отдельными условиями и не считаются автоматически частью лицензии на исходный код.