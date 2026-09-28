# Контракты интеграции backend с модулями команды

Документ фиксирует границу ответственности между участниками. Backend вызывает ML-сервис и модуль
телефонии, но не знает, как они устроены внутри; они, в свою очередь, не обращаются к БД напрямую.

Всё общение — REST/JSON внутри изолированного локального контура.

---

## 1. ML-сервис (участник 3, Python/ML)

Backend ожидает сервис по адресу `ML_SERVICE_URL` (по умолчанию `http://localhost:8100`).
Пока сервиса нет — работает `StubMLClient` (`ML_USE_STUB=true`), его ответы служат образцом формата.

Реализация клиента: `app/integrations/ml_client.py`, класс `HttpMLClient` (там же список путей).

| Метод backend | HTTP | Путь | Когда вызывается |
|---|---|---|---|
| `generate_scenarios` | POST | `/api/v1/generate/scenarios` | преподаватель нажал «сгенерировать сценарии» |
| `correct_scenario` | POST | `/api/v1/generate/correct` | преподаватель написал комментарий к сценарию |
| `evaluate_attempt` | POST | `/api/v1/evaluate/attempt` | обучающийся сдал карточку |
| `check_grammar` | POST | `/api/v1/analyze/grammar` | принудительная проверка грамматики |
| `analytics` | POST | `/api/v1/analytics/summary` | инсайты по группе (опционально) |
| `recommendations` | POST | `/api/v1/recommendations` | формирование рекомендаций |
| `index_material` | POST | `/api/v1/knowledge/index` | загружен методический материал |
| `health` | GET | `/health` | проверка состояния комплекса |

Все ответы могут содержать `model`, `version`, `latency_ms` — backend сохраняет их в `ml_results`
для воспроизводимости оценок.

### 1.1 Генерация сценариев

Запрос:

```json
{
  "count": 2,
  "difficulty": "basic",
  "category_code": "fire",
  "category_name": "Пожар",
  "prompt": "Ночное возгорание в многоквартирном доме",
  "required_fields": ["aon_phone", "applicant_name", "address_district", "address_street",
                      "address_house", "survey_signs", "incident_class", "description"]
}
```

Ответ:

```json
{
  "model": "your-model-name",
  "version": "1.0",
  "scenarios": [
    {
      "title": "Возгорание в жилом доме",
      "description": "Дым из квартиры на четвёртом этаже",
      "category_code": "fire",
      "difficulty": "basic",
      "briefing": {
        "caller": {"name": "Петрова Анна", "state": "паника", "phone": "+7 (9xx) xxx-xx-02"},
        "dialogue": [{"role": "caller", "text": "Горит квартира, сильный дым!"}],
        "address": "г. Москва, улица Профсоюзная, д. 12, кв. 47",
        "signs": ["дым", "запах гари", "квартира"]
      },
      "reference": {
        "expected_fields": {
          "aon_phone": "+7 (495) 000-00-12",
          "applicant_name": "Петрова Анна Владимировна",
          "applicant_role": "участник",
          "address_region": "г. Москва",
          "address_district": "ЮЗАО",
          "address_area": "Черёмушки",
          "address_street": "улица Профсоюзная",
          "address_house": "12",
          "address_flat": "47",
          "address_floor": "4",
          "survey_signs": ["дым", "запах гари", "квартира"],
          "incident_class": "Пожар в жилом помещении",
          "has_victims": false,
          "victims_count": 0,
          "description": "Дым из квартиры на четвёртом этаже, в подъезде запах горелого"
        },
        "expected_actions": ["call_accepted", "field_filled", "classified", "card_submitted"],
        "expected_text": {
          "keywords": ["принято", "направлена"],
          "forbidden": ["не знаю", "перезвоните"],
          "min_length": 20
        }
      },
      "questions": [
        {"text": "Какие службы привлекаются?", "options": ["Пожарная охрана", "Скорая"], "correct": ["Пожарная охрана"]}
      ]
    }
  ]
}
```

**Коды полей** — из состава карточки АРМ-112 (`app/core/arm112.py`, 34 поля в восьми блоках:
информация о карточке, телефоны, заявитель, формализованный адрес, что случилось, признаки
и метки, описание, отработка и оповещение). Актуальный перечень с наименованиями отдаёт
`GET /api/v1/card-templates`, блоки формы — `GET /api/v1/card-templates/field-groups`.
Значения могут быть строкой, числом, логическим или списком (`survey_signs`) — backend
приводит их к сравнимому виду сам.

Список оповещения служб backend формирует сам по ЕКП и признакам происшествия
(`notification_list` карточки), от ML-сервиса он не требуется.

`reference` — это **эталон**: с ним backend сравнивает действия обучающегося. Каждый сценарий
попадает в БД со статусом «на проверке», карточка — черновиком; в занятие они уходят только после
утверждения преподавателем (`POST /api/v1/scenarios/{id}/approve`).

### 1.2 Коррекция генерации

Запрос: `{"comment": "...", "scenario": {...}, "reference": {...}}`
Ответ: `{"scenario": {...}, "reference": {...}}` — исправленные версии.

### 1.3 Оценка попытки — главный метод

Запрос от backend:

```json
{
  "attempt_id": "uuid",
  "lesson_mode": "card_fill",
  "submitted_payload": {"address": "...", "incident_type": "ДТП", "description": "..."},
  "draft_payload": {"address": "..."},
  "expected_fields": {"address": "...", "incident_type": "ДТП"},
  "expected_actions": ["call_accepted", "field_filled", "classified", "card_submitted"],
  "expected_text": {"keywords": ["принято"], "forbidden": [], "min_length": 20},
  "required_fields": ["address", "incident_type", "description"],
  "actions": [
    {"action_type": "call_accepted", "field_code": null, "offset_ms": 1200, "value_length": 0},
    {"action_type": "field_filled", "field_code": "address", "offset_ms": 8400, "value_length": 34}
  ],
  "duration_seconds": 41.6,
  "norm_seconds": 30,
  "max_errors": 3,
  "min_score": 70.0
}
```

Ожидаемый ответ:

```json
{
  "model": "your-model-name",
  "version": "1.0",
  "score": 82.4,
  "max_score": 100.0,
  "passed": true,
  "timing_score": 76.8,
  "procedure_score": 100.0,
  "accuracy_score": 87.5,
  "grammar_score": 94.0,
  "errors": [
    {
      "category": "timing",
      "severity": "major",
      "code": "norm_exceeded",
      "message": "Превышен норматив: 41.6 с вместо 30 с",
      "field_code": null,
      "expected": "30",
      "actual": "41.6",
      "penalty": 10.0
    }
  ],
  "details": {"любые_поля": "сохраняются как есть и доступны преподавателю"}
}
```

Допустимые значения:

* `category`: `timing`, `procedure`, `data_accuracy`, `classification`, `completeness`, `grammar`, `syntax`
* `severity`: `minor`, `major`, `critical`

Неизвестные значения backend не отбрасывает, а приводит к безопасным значениям по умолчанию
(`procedure` / `minor`), поэтому обмен не ломается при расхождении версий.

**Если сервис недоступен:** backend создаёт отложенную оценку (`source = system`, `details.deferred = true`),
складывает задачу в `outbox_messages` и повторяет её с экспоненциальной задержкой. Работа
обучающегося не теряется — это требование п.2.8 ТЗ.

### 1.3.1 Режим «действия с карточками»

Если занятие идёт в режиме `card_action`, в том же запросе `evaluate_attempt` приходит блок
реагирования, и оценивать нужно именно его (заполнение полей в этом режиме не проверяется):

```json
{
  "lesson_mode": "card_action",
  "norm_seconds": 30,
  "response": {
    "statuses": [
      {"status": "added", "comment": null, "offset_ms": 0, "is_primary": false, "is_late": false, "set_by_system": true},
      {"status": "received", "comment": null, "offset_ms": 0, "is_primary": false, "is_late": false, "set_by_system": true},
      {"status": "accepted", "comment": null, "offset_ms": 12400, "is_primary": true, "is_late": false, "set_by_system": false, "service_code": "104"},
      {"status": "work_completed", "comment": "Работы завершены, утечка устранена", "offset_ms": 74000, "is_primary": false, "is_late": false, "set_by_system": false, "service_code": "104"}
    ],
    "first_status": "accepted",
    "first_seconds": 12.4,
    "is_late": false,
    "lifecycle_status": "completed",
    "service_code": "104",
    "is_primary_service": true,
    "notification_list": [
      {"code": "104", "name": "Аварийная газовая служба (104)", "is_primary": true, "reason": "ЕКП"},
      {"code": "101", "name": "Пожарно-спасательный гарнизон (101)", "is_primary": false, "reason": "ЕКП"}
    ]
  },
  "expected_response": {
    "primary_status": "accepted",
    "final_status": "work_completed",
    "require_progress": true,
    "min_comment_length": 15,
    "comment_rules": {"keywords": ["передана"], "forbidden": ["не знаю"]}
  }
}
```

Значения `status`: `added`, `received`, `accepted`, `not_accepted`, `response_started`,
`arrived`, `work_in_progress`, `work_completed`, `work_refused`.

`service_code` — служба, от имени которой работает обучающийся; `is_primary_service`
означает, что происшествие в её компетенции. Отказ профильной службы от реагирования —
нарушение из каталога памятки, его код замечания `primary_service_refused`.
Записи с `set_by_system: true` проставлены системой — это не работа обучающегося.

Ответ — той же структуры, что и в п.1.3. Рекомендуемые коды замечаний (они соответствуют
нарушениям, которые перечисляет памятка «Работа на АРМ-112»):

| Код | Категория | Что означает |
|---|---|---|
| `primary_status_missing` | timing | нет «Принята»/«Не принята» — карточка «Не оповещено» |
| `primary_status_late` | timing | первичный статус позже норматива 30 секунд |
| `wrong_primary_status` | procedure | решение не соответствует компетенции службы |
| `comment_missing` | completeness | нет комментария к отказу |
| `comment_incomplete` | completeness | не указано, куда передана информация |
| `progress_statuses_missing` | procedure | нет статусов хода работ |
| `final_status_mismatch` | procedure | итоговый статус не соответствует результату |

Эталон (`expected_response`) формирует преподаватель или генератор сценариев;
backend берёт его из `ScenarioReference.expected_text["response"]`.

### 1.4 Рекомендации

Запрос: `{"scope": "group:uuid", "top_errors": [{"code": "norm_exceeded", "category": "timing", "count": 12, "share": 0.34}]}`
Ответ: `{"recommendations": [{"title": "...", "text": "...", "priority": 1, "based_on": {...}}]}`

### 1.4.1 Классификатор происшествий: что backend отдаёт и что принимает

Классификатор заказчика (таблица XLSX) разбирается один раз и хранится в backend
нормализованным. ML использует его как **структурный источник**: комбинация
признаков и итоговый тип происшествия берутся отсюда, а модель генерирует поверх
них вариативный учебный контекст — придумывать классификацию самостоятельно она
не должна.

Чтение (для контекста генерации):

```
GET /api/v1/incidents/types?category=ДТП%20пострадавшие
GET /api/v1/incidents/2021103
GET /api/v1/incidents/2021103/features
```

```json
{
  "code": "2021103",
  "name": "ДТП с пострадавшими — наезд на светофор",
  "category_name": "ДТП пострадавшие",
  "category_id": "uuid учебной категории или null",
  "features": [
    {"type": "object", "value": "Наезд на препятствие"},
    {"type": "detail", "value": "Светофор"}
  ],
  "main_service": "Police",
  "services": [
    {"code": "102", "name": "Полиция (102)", "is_primary": true, "reason": "ЕКП"},
    {"code": "103", "name": "Скорая медицинская помощь (103)", "is_primary": false, "reason": "ЕКП"}
  ],
  "agency_classifiers": {"Классификатор МЧС": "ДТП легкового транспорта"},
  "raw": {"Код": "2021103", "…": "исходная строка таблицы"}
}
```

Запись (результат импортёра таблицы):

```
POST /api/v1/incidents/import
{
  "items": [
    {
      "code": "2021103",
      "name": "ДТП с пострадавшими — наезд на светофор",
      "category_name": "ДТП пострадавшие",
      "category_code": "traffic_injured",
      "features": [{"type": "object", "value": "Наезд на препятствие"}],
      "main_service": "Police",
      "services": ["Скорая"],
      "agency_classifiers": {"Классификатор МЧС": "ДТП легкового транспорта"},
      "raw": {"Код": "2021103"}
    }
  ],
  "update_existing": true
}
```

Если нормализованных данных ещё нет, таблицу можно загрузить как есть —
`POST /api/v1/incidents/import/xlsx` (с `limit`, чтобы сначала проверить разбор на
части строк). Названия служб приводятся к кодам списка оповещения автоматически;
неизвестная служба сохраняется как есть — классификатор заказчика шире нашего
справочника, и терять сведения нельзя.

При генерации сценария по типу происшествия указывайте его код в карточке
(`incident_type_code`): тогда список оповещения берётся из классификатора заказчика,
а не из нашей матрицы по умолчанию.

### 1.5 Индексация материалов

Запрос: `{"material_id": "uuid", "title": "...", "kind": "memo", "path": "var/uploads/<файл>"}`
Ответ: `{"indexed": true, "chunks": 42}`

Файл лежит в общем томе; при разнесении сервисов по машинам договориться о доступе к каталогу
`var/uploads` или добавить выдачу файла по URL.

---

## 2. Модуль телефонии (участник 4, SIP/VoIP/Docker)

### 2.1 Backend → телефония

`POST {TELEPHONY_SERVICE_URL}/api/v1/calls/originate`

```json
{
  "lesson_id": "uuid",
  "attempt_id": "uuid",
  "student_id": "uuid",
  "card_no": "У-000012",
  "caller_profile": {"name": "Иванов Сергей", "state": "взволнован", "phone": "+7 (9xx) xxx-xx-01"},
  "caller_number": "+7 (9xx) xxx-xx-01",
  "callee_number": "1001",
  "record": true
}
```

Ответ: `{"sip_call_id": "...", "status": "ringing", "caller_number": "...", "callee_number": "...", "latency_ms": 35}`

Также используется `POST /api/v1/calls/hangup` с `{"sip_call_id": "..."}` и `GET /health`.

Номер SIP-аккаунта обучающегося backend берёт из `users.preferences.sip_extension` — его можно
задать при создании пользователя.

### 2.2 Телефония → backend (вебхук)

`POST /api/v1/telephony/events`, заголовок `X-Telephony-Token: <TELEPHONY_WEBHOOK_TOKEN>`.

```json
{
  "sip_call_id": "1a2b3c",
  "event": "ended",
  "attempt_id": "uuid",
  "lesson_id": "uuid",
  "student_id": "uuid",
  "latency_ms": 120,
  "duration_ms": 41600,
  "audio_path": "var/audio/1a2b3c.wav",
  "audio_format": "wav",
  "meta": {"codec": "PCMU"}
}
```

`event`: `ringing` | `answered` | `missed` | `ended` | `failed`.

Что делает backend: обновляет запись вызова, привязывает аудиозапись к карточке, а если
`latency_ms` превышает норматив из настроек (150 мс) — пишет предупреждение в системный журнал,
которое видно администратору.

Параметры SIP (хост, порт, транспорт, кодек, формат записи, допустимая задержка) администратор
задаёт через `GET/PATCH /api/v1/telephony/config` — модулю телефонии удобно читать их оттуда,
чтобы настройки не дублировались в двух местах.

---

## 3. Frontend (участник 1)

* Контракт — `/openapi.json`, живая документация — `/docs`.
* Авторизация: `Authorization: Bearer <access_token>`; при 401 с кодом `token_expired` —
  `POST /api/v1/auth/refresh`.
* Видимость элементов интерфейса строить по `GET /api/v1/auth/me` → массив `permissions`
  (например, кнопка правки оценки — при наличии `evaluations:override`).
* Форму карточки строить по `GET /api/v1/card-templates` → `fields_schema`, а не по фиксированному
  списку полей; вкладки формы — по `GET /api/v1/card-templates/field-groups` (восемь блоков АРМ-112
  в правильном порядке). У поля есть `group`, `order`, `required`, `readonly`, `options`, `hint`.
* Режим «действия с карточками»: выпадающий список статусов строить по
  `GET /api/v1/training/attempts/{id}/response-options` (там же остаток времени до норматива
  30 секунд, признак обязательного комментария, список оповещения служб, служба обучающегося
  и типовые формулировки комментариев из памятки), отправлять —
  `POST /api/v1/training/attempts/{id}/response-status`. Ответ с `card_closed: true` означает,
  что карточка закрыта и пришла оценка. Список оповещения показывать как в ПОВ-112: службу
  можно добавить, но не удалить.
* Аттестация: занятие создаётся с `purpose` = `attestation` | `refresher` и `passing_score`.
  После завершения у участника приходят `final_score` и `is_passed` — это и есть решение
  о зачёте; протокол печатается через `POST /api/v1/reports` с `type: attestation`.
* Экспорт: `POST /api/v1/reports` принимает `format` = `json` | `csv` | `pdf` | `xlsx` | `xml`;
  файл забирается через `GET /api/v1/reports/{id}/download`.
* Мониторинг занятия: `GET /api/v1/lessons/{id}/monitor` для среза либо
  `WS /api/v1/ws/lessons/{id}?token=<access_token>` для событий
  (`card_issued`, `card_submitted`, `response_status_set`, `primary_status_overdue`,
  `participant_online`, `lesson_started`, `lesson_finished`). В строке мониторинга есть
  `workplace` (номер АРМ) и `active_cards` (сколько карточек сейчас в потоке).
* Восстановление после обрыва связи: сохранить `resume_token`, полученный при входе в занятие,
  и вызвать `POST /api/v1/training/resume`.
* Каждый ответ содержит `X-Request-ID` — указывайте его при разборе ошибок, по нему находится
  вся цепочка в журналах.

### 3.1 Поток карточек, рабочие места и отработки

Изменения после уточнений заказчика. Они затрагивают экраны обучающегося, поэтому
описаны отдельно.

**Вход с номером рабочего места.** `POST /training/lessons/{id}/join` принимает тело
`{"workplace_number": "03"}` (необязательное). Номер обучающийся называет при входе,
как на реальном АРМ-112. Ответ содержит `workplace`. Одно место — один обучающийся:
занятое место даёт 422. Свободные и занятые места — `GET /workplaces/class-map`
(экран раздачи заданий у преподавателя).

**«Список происшествий» вместо одной карточки.** Главный экран диспетчера ДДС —
`GET /training/lessons/{id}/incidents`. Возвращает **все** незакрытые карточки: в
режиме ДДС их несколько, и таймеры у них идут параллельно. В каждой строке два
обратных отсчёта:

| Поле | Что это |
|---|---|
| `response_seconds_left` | до норматива первичного статуса — **30 секунд** |
| `work_seconds_left` | до конца отработки карточки — **3 минуты** |

Отсчёты могут быть отрицательными: просрочка — рабочая информация, а не ошибка
отображения. Пропуск 30 секунд карточку **не закрывает**: она получает
`lifecycle_status: "not_notified"` и `is_response_late: true`, но остаётся в работе —
по памятке служба обязана отработать её и с опозданием. Первой в списке идёт самая
старая карточка: у неё раньше всех истекает норматив.

`POST /training/lessons/{id}/next-card` по-прежнему работает: он пополняет поток и
возвращает карточку, которая горит. В режиме оператора 112 поток всегда из одной
карточки — следующий вызов приходит после сохранения текущей (`stream_window: 1`).
Открытие строки отмечается через `POST /training/attempts/{id}/open` — на норматив
это не влияет, но преподаватель видит, сколько обучающийся думал перед открытием.

**Отработки (панель телефона).** Кому можно звонить по карточке —
`GET /training/attempts/{id}/contacts`: службы из списка оповещения с внутренними
номерами (3–4 цифры) и данными должностного лица, плюс заявитель по номеру из
карточки. Своя служба из списка исключена. Зафиксировать звонок —
`POST /training/attempts/{id}/processings`:

```json
{
  "kind": "supervisor",
  "service_code": "101",
  "answered_by": "Дежурный Соколов А.П.",
  "summary": "Передан адрес, есть заблокированные, направлены два расчёта"
}
```

`kind` — `service` | `supervisor` | `brigade` | `applicant` | `incoming_report`.
Суть сообщения обязательна всегда, ФИО принявшего — для звонков в службы. Backend
сам просит телефонию поднять вызов и привязывает запись разговора к карточке и
рабочему месту; если телефония недоступна, отработка всё равно сохраняется.

**Раздача заданий по рабочим местам.** `POST /workplaces/assign`:

```json
{"lesson_id": "<id занятия>", "assignments": {"02": "<id карточки>", "05": "<id карточки>"}}
```

Ключ — номер АРМ, значение — карточка. Назначенные карточки выдаются обучающемуся
раньше случайных, в порядке назначения. Места, за которыми никто не работает, и
несуществующие карточки возвращаются в `skipped` с причиной — раздача при этом не
отменяется целиком, поэтому интерфейсу нужно показать обе части ответа.

**Карточки, сформированные обучающимися.** Занятие с `card_source: "student"` берёт
карточки из работ обучающихся: карточка, заполненная в режиме 112 и **зачтённая**,
попадает в пул с `origin: "student"`. Незачтённые в пул не идут — иначе следующие
обучающиеся тренировались бы на чужих ошибках.

**Сложность заданий.** У занятия и карточки есть `difficulty_weight` — шкала 1–10,
которую просил заказчик. Уровень (`difficulty`) остаётся как производная для
фильтров. Флаг `adaptive_difficulty` включает подстройку под обучающегося: после
каждой карточки вес двигается на шаг, журнал решений — в `participants[].difficulty_log`.
В аттестации адаптивность принудительно выключена.

**Веса оценки.** Преподаватель задаёт их в занятии:
`success_criteria.weights = {"accuracy": 5, "timing": 3}`. Значения нормализуются,
неназванные критерии сохраняют свою долю. Ошибки в адресных полях приходят с
`severity: "critical"` и кодом `address_mismatch` — их нужно выделять в интерфейсе
отдельно от прочих.

---

## 4. Формат ошибок

```json
{
  "error": {"code": "business_rule_violated", "message": "Занятие не запущено преподавателем", "details": null},
  "request_id": "8a2fad9b78fb45a1a5d6493b321f0817"
}
```

| Код | HTTP | Значение |
|---|---|---|
| `unauthenticated`, `invalid_token`, `token_expired` | 401 | проблема с токеном |
| `permission_denied` | 403 | нет права по модели RBAC |
| `not_found` | 404 | объект не найден |
| `conflict`, `integrity_error` | 409 | нарушение уникальности или состояния |
| `business_rule_violated` | 422 | операция запрещена правилами учебного процесса |
| `validation_error` | 422 | некорректные данные запроса |
| `integration_unavailable` | 502 | недоступен ML-сервис или телефония |
| `database_unavailable` | 503 | проблема с БД |
