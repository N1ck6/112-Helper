# Как протестировать backend

Документ описывает три уровня проверки: автотесты, ручной прогон через Swagger и
проверку нефункциональных требований ТЗ (норматив 30 секунд, устойчивость к сбоям,
разграничение прав, метрики).

Всё, что ниже, работает на заглушках ML и телефонии — внешние сервисы не нужны.

---

## 0. Подготовка

Первый запуск — одной командой в терминале PyCharm (окружение `.venv` активно):

```powershell
python scripts/setup_local.py
```

Скрипт найдёт PostgreSQL, один раз спросит пароль суперпользователя (ввод скрыт,
никуда не сохраняется), создаст роль `dds112` и базы `dds112` / `dds112_test`,
запишет `.env` со случайным `SECRET_KEY`, накатит миграции, загрузит стартовые
данные и прогонит тесты. Повторный запуск безопасен.

Дальше, когда окружение уже настроено:

```powershell
alembic upgrade head          # 41 таблица, восемь миграций
python -m scripts.seed        # роли, пользователи, классификатор, 4 сценария
uvicorn app.main:app --reload
```

Учебные учётные записи: `teacher / Teacher#2026`, `student / Student#2026`,
`student2 / Student#2026`, `admin / Admin#2026`.

Swagger: <http://localhost:8000/docs>. Нажмите **Authorize** и вставьте `access_token`,
полученный из `POST /api/v1/auth/login` — дальше все запросы пойдут от этой роли.
Для проверки ролей держите два окна браузера (обычное и приватное) — в каждом свой токен.

---

## 1. Автотесты

```powershell
pytest -q                                  # все тесты
pytest -v                                  # с названиями проверок
pytest tests/test_response_statuses.py -v  # только статусы реагирования
pytest -k "audit or rbac" -v               # выборочно
```

Ожидаемый результат — **79 passed**. Нужна база `dds112_test` (создаётся один раз,
см. README) — схема в ней пересоздаётся на каждом прогоне.

Что покрыто:

| Файл | Проверяет |
|---|---|
| `test_auth.py` | вход, неверный пароль, refresh, состав прав в `/auth/me`, health |
| `test_rbac.py` | ограничения ролей из ТЗ: администратор не правит сценарии и оценки, обучающийся не управляет занятием |
| `test_training_flow.py` | сквозной цикл: занятие → карточка → действия → сдача → оценка → правка оценки → аудит → отчёт → сертификат |
| `test_response_statuses.py` | конечный автомат статусов АРМ-112, норматив 30 секунд, обязательные комментарии, список оповещения по ЕКП, особенности службы 103, отказ профильной службы |
| `test_attestation_and_formats.py` | аттестация и зачёт, протокол, сертификат только при сдаче, выгрузка XLSX и XML, обмен карточками (экспорт → импорт) |
| `test_integrations.py` | синхронизация с каталогом доступа, запрет локального пароля для его учётных записей, пакетный импорт материалов |
| `test_operations.py` | резервное копирование, сроки хранения журналов, статус «Не завершено» через 48 часов |
| `test_incident_classifier.py` | импорт классификатора (JSON и XLSX), категории, типы, признаки, влияние типа на список оповещения |
| `test_security_and_norms.py` | второй фактор при входе через каталог, учёт неудачных попыток входа, разделение норматива 30 с и времени отработки карточки, пересмотр отказа, «пробный» режим синхронизации |

Что **не** покрыто автотестами и проверяется руками: WebSocket-мониторинг,
поведение при недоступном ML-сервисе, метрики, вебхук телефонии.
Нагрузка проверяется отдельно — см. раздел 12.

---

## 2. Ручной прогон: режим «заполнение карточки»

Роль преподавателя:

1. `POST /api/v1/auth/login` → `{"username": "teacher", "password": "Teacher#2026"}` → скопировать `access_token` → **Authorize**.
2. `GET /api/v1/users?role=student` → скопировать `id` обучающегося.
3. `POST /api/v1/lessons`:

```json
{
  "title": "Проверка: заполнение карточек",
  "mode": "card_fill",
  "student_ids": ["<id обучающегося>"],
  "card_source": "generated",
  "time_limit_seconds": 30,
  "max_cards": 2
}
```

4. `POST /api/v1/lessons/{id}/start` → статус должен стать `running`.

Роль обучающегося (второе окно браузера, вход под `student`):

5. `POST /api/v1/training/lessons/{id}/join` → сохранить `resume_token`.
6. `POST /api/v1/training/lessons/{id}/next-card` → проверить: пришли `deadline_at`,
   `seconds_left`, `template_fields`, а `card.payload` пуст (эталон скрыт от обучающегося).
7. `POST /api/v1/training/attempts/{id}/actions` — три раза: `call_accepted`,
   `field_filled` (с `field_code: "address_street"`), `classified`.
8. `PUT /api/v1/training/attempts/{id}/draft` — сохранить черновик.
9. `POST /api/v1/training/resume` с `resume_token` → должен вернуться черновик и
   `within_grace_period: true`.
10. `POST /api/v1/training/attempts/{id}/submit` с заполненной карточкой → в ответе
    `score`, `errors`, `next_attempt`.

Что смотреть в ответе: `duration_ms`, `time_delta_seconds`, `is_overtime` —
сравнение фактического времени с нормативом (п.2.5 ТЗ).

---

## 3. Ручной прогон: режим «действия с карточками»

Это профильный режим для диспетчера ДДС по памятке «Работа на АРМ-112».

Преподаватель создаёт занятие с `"mode": "card_action"` и запускает его.
Обучающийся делает `join` и `next-card`, затем:

1. `GET /api/v1/training/attempts/{id}/response-options` → доступны только
   `accepted` и `not_accepted`, видно `response_seconds_left`, список оповещения
   (`notification_list`) и служба обучающегося (`service_code`). Для занятия по
   категории «Медицинская помощь» служба — `103`, и `not_accepted` в списке не будет.
2. Попробовать «перепрыгнуть»: `POST .../response-status` со `{"status": "arrived"}`
   → **422**, код `response_status_transition_denied`.
3. Попробовать отказ без комментария: `{"status": "not_accepted"}`
   → **422**, код `response_comment_required`.
4. Принять карточку: `{"status": "accepted", "work_order_no": "Н-1024"}` →
   в ответе `is_primary: true`, `is_late: false`, у попытки заполнен
   `first_response_seconds`.
5. Пройти цепочку: `response_started` → `arrived` → `work_in_progress` →
   `work_completed` с комментарием.
6. На последнем шаге: `card_closed: true`, `lifecycle_status: "completed"`,
   пришла оценка и следующая карточка.
7. Повторная попытка поставить статус на закрытой карточке → **422**.

---

## 4. Проверка норматива 30 секунд

Ждать 30 секунд неудобно, поэтому занятие создаётся с укороченным нормативом
(минимум по схеме — 5 секунд):

```json
{"title": "Проверка норматива", "mode": "card_action",
 "student_ids": ["<id>"], "time_limit_seconds": 5, "max_cards": 1}
```

**Сценарий А — просрочка первичного статуса.**
Получить карточку, подождать ~7 секунд, поставить `accepted`. Ожидается:
`is_late: true`, у попытки `is_response_late: true`,
`lifecycle_status: "not_notified"`, а в оценке — замечание `primary_status_late`.

**Сценарий Б — статус не поставлен вовсе.**
Получить карточку и ничего не делать ~20 секунд. Фоновая задача `expire-attempts`
(срабатывает каждые 10 секунд) сама закроет попытку. Затем
`GET /api/v1/training/attempts/{id}`: статус `expired`,
`lifecycle_status: "not_notified"`, в оценке — `primary_status_missing`
с критической важностью.

**Важно про два норматива.** 30 секунд — это срок только на первичный статус
(`response_deadline_at`). На полную отработку карточки в режиме «действия с карточками»
даётся отдельное время (`CARD_ACTION_WORK_LIMIT_SECONDS`, по умолчанию **3 минуты** —
норматив заказчика; переопределяется в занятии через `success_criteria.work_limit_seconds`).
Пропуск 30 секунд карточку **не закрывает**: она получает пометку «Не оповещено», но
остаётся в работе — по памятке служба обязана отработать её и с опозданием.

---

## 5. Разграничение прав (RBAC)

| Под какой ролью | Запрос | Ожидание |
|---|---|---|
| `student` | `GET /api/v1/users` | 403 `permission_denied` |
| `student` | `POST /api/v1/lessons` | 403 |
| `admin` | `POST /api/v1/scenarios` | 403 — администратор не правит учебный контент |
| `admin` | `GET /api/v1/auth/me` | в `permissions` **нет** `evaluations:override` |
| `teacher` | `GET /api/v1/admin/logs` | 403 — системные журналы только админу |
| без токена | любой защищённый маршрут | 401 |

Отдельно: под `student` попытаться открыть чужую карточку
(`PUT /training/attempts/{чужой id}/draft`) → 403.

---

## 6. Аудит и журналы

Под `admin`:

* `GET /api/v1/admin/audit?action=grade_override` — после правки оценки
  преподавателем здесь появится запись с `before`/`after` и `is_security: true`.
* `GET /api/v1/admin/audit?security_only=true` — вход, блокировки, смена конфигурации.
* `GET /api/v1/admin/logs?level=warning` — системный журнал.
* `GET /api/v1/admin/stats` — пользователи, активные занятия, размер БД, состояние компонентов.

---

## 7. Отчёты и сертификаты

Под `teacher`, после завершённого занятия:

```json
POST /api/v1/reports
{"type": "lesson", "format": "pdf", "lesson_id": "<id занятия>"}
```

Проверить `status: "ready"` и `generation_ms` (норматив ТЗ — до 30 000 мс),
затем `GET /api/v1/reports/{id}/download` — скачается PDF с кириллицей.

Аналогично `{"type": "progress", "format": "csv", "student_id": "<id>"}` — в CSV
русские заголовки открываются в Excel без «кракозябр» (файл пишется в UTF-8 с BOM).

Сертификат: `POST /api/v1/certificates` → `GET /api/v1/certificates/{id}/download`.

Аналитика: `GET /api/v1/analytics/summary?student_id=<id>` и
`GET /api/v1/analytics/forecast/<id>` — прогноз следующей оценки с коэффициентом доверия.

---

## 8. Устойчивость к отказу ML-сервиса (п.2.8 ТЗ)

Эффектная проверка для защиты — показывает, что работа обучающегося не теряется.

1. В `.env` поставить `ML_USE_STUB=false` и `ML_SERVICE_URL=http://localhost:9999`
   (там ничего не слушает). Перезапустить сервер.
2. Провести занятие и сдать карточку. Оценка придёт со `source: "system"` и
   `details.deferred: true` — работа сохранена, оценка отложена.
3. Проверить очередь: `GET /api/v1/admin/stats` → `outbox_pending: 1`.
4. Вернуть `ML_USE_STUB=true`, перезапустить сервер и подождать ~10 секунд.
   Фоновый воркер сам переоценит попытку: `GET /api/v1/evaluations/by-attempt/{id}`
   → `source: "ai"`, появились баллы и замечания.

---

## 9. Телефония (вебхук от участника 4)

```
POST /api/v1/telephony/events
Header: X-Telephony-Token: dev-telephony-token
{
  "sip_call_id": "test-1", "event": "answered",
  "latency_ms": 320, "lesson_id": "<id>", "student_id": "<id>"
}
```

* Без заголовка или с неверным токеном → 403.
* `latency_ms: 320` превышает норматив 150 мс → в `GET /api/v1/admin/logs`
  появится предупреждение о превышении задержки VoIP.
* `GET /api/v1/telephony/calls` — журнал учебных вызовов.

---

## 10. WebSocket-мониторинг

Во время идущего занятия (токен преподавателя):

```python
# scripts/ws_check.py — запустить в отдельном терминале
import asyncio, websockets, json

async def main(lesson_id: str, token: str) -> None:
    url = f"ws://localhost:8000/api/v1/ws/lessons/{lesson_id}?token={token}"
    async with websockets.connect(url) as ws:
        while True:
            print(json.loads(await ws.recv()))

asyncio.run(main("<id занятия>", "<access_token>"))
```

Нужен `pip install websockets`. Пока обучающийся работает, в консоль будут приходить
события `card_issued`, `response_status_set`, `card_submitted`, `lesson_finished`.

Альтернатива без кода: `GET /api/v1/lessons/{id}/monitor` — срез состояния
(кто онлайн, какая карточка открыта, сколько секунд осталось, средний балл).

---

## 11. Служебные проверки

```powershell
# схема БД накатывается и откатывается без ошибок
alembic downgrade -1 ; alembic upgrade head

# линтер
ruff check .

# метрики Prometheus
curl http://localhost:8000/metrics | Select-String "dds112_http_requests_total"

# готовность комплекса: база, ML, телефония
curl http://localhost:8000/health/ready
```

В `/metrics` обратите внимание на `dds112_http_requests_slow_total` — счётчик запросов
дольше 2 секунд (норматив п.2.8). В норме он равен нулю.

---

## 12. Нагрузочное тестирование (п.2.8)

Замеры выполнены, методика и результаты — в [`PERFORMANCE.md`](PERFORMANCE.md).
Повторить прогон:

```powershell
python -m scripts.load_setup --students 100 --cards 900
uvicorn app.main:app --workers 2
locust -f locustfile.py --headless -u 100 -r 10 -t 90s --host http://127.0.0.1:8000
```

Результат на стенде 2 vCPU / 8 ГБ (СУБД и генератор нагрузки на той же машине):
95-й процентиль отклика 1700 мс при нормативе 2000 мс, 203 операции записи в секунду
при нормативе 100, 100 одновременных сессий при нормативе 20, ошибок нет.

---

## 13. Аттестация, форматы и интеграции

**Аттестация.** Создать занятие с `"purpose": "attestation"` и `"passing_score": 60`,
провести карточку, завершить занятие → у участника появятся `final_score` и
`is_passed`. Затем `POST /api/v1/reports {"type":"attestation","format":"pdf"}` —
протокол; `POST /api/v1/certificates` без зачёта вернёт `attestation_not_passed`.

**Форматы.** `POST /api/v1/reports` с `"format": "xlsx"` (два листа: «Данные» и
«Сводка») и `"xml"` (для legacy-интеграций).

**Обмен карточками.** `GET /api/v1/cards/export?format=xml&with_expected=true` →
править номера → `POST /api/v1/cards/import` с этим файлом. Повторная загрузка того
же файла ничего не перезапишет: карточки с существующим номером попадут в `warnings`.

**Классификатор происшествий.** `POST /api/v1/incidents/import/xlsx` с таблицей
заказчика (параметр `limit=200` — загрузить для проверки только часть), затем
`GET /api/v1/incidents/categories`, `GET /api/v1/incidents/types?query=ДТП`,
`GET /api/v1/incidents/2021103/features`. Карточка с `incident_type_code` получает
службы из классификатора: `POST /api/v1/cards` → в ответе `notification_list`.

**Каталог доступа.** `POST /api/v1/users/sync-directory?dry_run=true` покажет, кого
создаст; без `dry_run` — создаст. Вход такой учётной записи с локальным паролем
невозможен (пароль проверяет каталог).

**Резервное копирование.** `POST /api/v1/admin/backups?kind=schema` → в ответе
`status: success`, размер файла и команда восстановления; `GET /api/v1/admin/backups` —
журнал копий. Файлы лежат в `var/backups`, старые удаляются по `BACKUP_KEEP`.

---

## 13.1 Поток карточек, рабочие места и отработки

Проверки того, что добавлено после уточнений заказчика.

**Рабочее место.** Войти в занятие с телом `{"workplace_number": "03"}` →
в ответе `workplace: "03"`. Под другой учётной записью занять то же место —
422 «уже занято». `GET /api/v1/workplaces/class-map` показывает занятые и
свободные места; в `GET /api/v1/lessons/{id}/monitor` у строки есть `workplace`.
После `POST /api/v1/lessons/{id}/finish` место освобождается — это важно
проверить, иначе следующая смена не войдёт.

**Поток карточек.** Занятие в режиме `card_action`, `max_cards: 3`. Один раз
запросить `next-card`, затем `GET /api/v1/training/lessons/{id}/incidents` —
в списке должно быть **несколько строк**, все с разными `card_no`, и у каждой
свои `response_seconds_left` (30 с) и `work_seconds_left` (3 мин). Повторные
запросы `next-card` не должны переполнять список.

Для режима 112 (`card_fill`) тот же запрос возвращает `stream_window: 1` и ровно
одну строку.

**Просрочка первичного статуса ничего не отбирает.** Создать занятие с
`time_limit_seconds: 5`, получить карточку и подождать ~15 секунд, ничего не
нажимая. Ожидается: карточка **осталась в работе** (`status` = `issued` или
`in_progress`), но получила `is_response_late: true` и
`lifecycle_status: "not_notified"`, и её по-прежнему можно принять. Полное
закрытие происходит только по истечении срока отработки.

**Отработки.** `GET /api/v1/training/attempts/{id}/contacts` — список с
телефонами служб и заявителя. Затем `POST .../processings` без `answered_by`
для `kind: "supervisor"` → 422; с указанием ФИО принявшего и сути сообщения →
201, в ответе заполнены `offset_ms` и `phone` (подставлен из справочника ДДС).

**Раздача заданий по местам.** Обучающийся входит с `{"workplace_number": "02"}`,
преподаватель делает `POST /api/v1/workplaces/assign` с
`{"lesson_id": "...", "assignments": {"02": "<id карточки>"}}` → следующая карточка
у обучающегося должна быть именно назначенная. Назначение на пустое место
возвращается в `skipped` с причиной, а не молча теряется.

**Карточки обучающихся.** Провести занятие в режиме 112 и сдать карточку по эталону
(`passed: true`) → `GET /api/v1/cards?origin=student` покажет её в пуле. Карточка с
критической ошибкой в пул попадать не должна.

**Маршрутизация.** `POST /api/v1/services/routing/preview`:

```json
{"category_id": "<id категории «Пожар в жилом помещении»>",
 "payload": {"address_area": "Щукино", "has_victims": true}}
```

В ответе должны быть 101, `dds_shchukino` (по району) и `dds_szao`
(по подчинённости управы), у каждой записи — причина попадания в список.
С районом «Матушкино» чужие ДДС появляться не должны.

**Ошибки в адресах.** Заполнить карточку по эталону, но в одной букве названия
улицы сделать опечатку → в замечаниях `address_mismatch` с
`severity: "critical"`, карточка не зачтена. Пропуск необязательного поля адреса
даёт `address_incomplete` — тоже с объяснением, а не молча.

**Веса и адаптивная сложность.** Занятие с
`"success_criteria": {"weights": {"correctness": 5, "время": 3}}` — в
`GET /api/v1/evaluations/by-attempt/{id}` поле `details.weights` в сумме даёт 1.0,
а неназванные критерии не обнуляются. Занятие с `"adaptive_difficulty": true` и
`"difficulty_weight": 4`: после карточки, сданной на 85+ баллов, у участника
`difficulty_weight` становится 5, а в `difficulty_log` появляется причина.

---

## 14. Если что-то не запускается

**«Не помню пароль суперпользователя PostgreSQL».** Он задавался один раз при
установке PostgreSQL. Три выхода, от простого к сложному:

1. *Обойти совсем* — поднять базу контейнером, там пароль известен:
   ```powershell
   docker compose up -d postgres
   copy .env.example .env
   alembic upgrade head
   python -m scripts.seed
   ```
   Тестовую базу создать один раз:
   ```powershell
   docker exec -it dds112-postgres psql -U dds112 -c "CREATE DATABASE dds112_test OWNER dds112;"
   ```
2. *Сбросить пароль.* Открыть `C:\Program Files\PostgreSQL\16\data\pg_hba.conf`,
   в строке для `host all all 127.0.0.1/32` заменить метод `scram-sha-256` на `trust`,
   перезапустить службу (`services.msc` → PostgreSQL → Restart), затем
   `psql -U postgres -c "ALTER USER postgres PASSWORD 'новый';"` и **вернуть
   `scram-sha-256` обратно** с перезапуском службы.
3. *Переустановить PostgreSQL*, записав пароль.

**`WinError 64: Указанное сетевое имя больше не доступно` при `seed` или `pytest`.**
Это несовместимость asyncpg с циклом событий Windows по умолчанию. Исправлено в
`app/core/runtime.py` — он вызывается при импорте `app/db/session.py`. Если ошибка
всё же появилась, значит запускается старая версия кода: проверьте, что файл
`app/core/runtime.py` существует, и перезапустите терминал.

**`password authentication failed for user "dds112"`.** Пароль в `.env` не совпадает
с паролем роли в базе. Либо привести `POSTGRES_PASSWORD` в `.env` к настоящему,
либо сменить пароль роли: `psql -U postgres -c "ALTER USER dds112 PASSWORD 'dds112';"`.

**`database "dds112_test" does not exist`.** Тестовая база создаётся отдельно:
`psql -U postgres -c "CREATE DATABASE dds112_test OWNER dds112;"`.

**`[Errno 10048] address already in use` на порту 8000.** Порт занят прошлым
запуском. Найти и снять: `netstat -ano | findstr :8000`, затем
`taskkill /PID <номер> /F`. Или запустить на другом порту: `uvicorn app.main:app --port 8001`.

**Кракозябры в выводе PowerShell.** `chcp 65001` перед запуском, либо использовать
Windows Terminal вместо старой консоли.

**`pg_dump: команда не найдена` при проверке резервного копирования.** Добавить
`C:\Program Files\PostgreSQL\16\bin` в `PATH` или указать полный путь в
`BACKUP_PG_DUMP` в `.env`.

**Тесты падают все сразу, в трассировке — подключение к базе.** Сначала проверьте
саму связь: `python -c "import asyncio,asyncpg;
asyncio.run(asyncpg.connect('postgresql://dds112:dds112@localhost:5432/dds112_test'))"`.
Если и это падает — проблема в окружении, а не в тестах.
