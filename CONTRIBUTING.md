# Contributing Guide

## 1. Назначение

Этот документ описывает правила совместной разработки проекта учебного ПО для подготовки операторов ДДС.

Проект разрабатывается командой из четырёх человек:

| Роль | Основная директория | Основная ответственность |
|---|---|---|
| Frontend | `frontend/` | Пользовательский интерфейс и взаимодействие с пользователем |
| Backend | `backend/` | API, бизнес-логика, данные и взаимодействие с БД |
| Python / ML | `ml/` | ИИ, генерация, анализ и оценка |
| Telephony / Docker | `telephony/`, `deploy/` | SIP/VoIP, голосовые сценарии и инфраструктура |

Распределение по директориям предназначено в том числе для уменьшения количества merge-конфликтов.

---

# 2. Структура репозитория

Основные директории:

```text
project/
│
├── frontend/
├── backend/
├── ml/
├── telephony/
│
├── database/
├── deploy/
├── docs/
├── tests/
│
├── data/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── LICENSE
```

## Зоны ответственности

### Frontend

Основная рабочая область:

```text
frontend/
```

Frontend отвечает за:

- интерфейс пользователя;
- интерфейс АРМ-112;
- отображение карточек происшествий;
- интерфейс занятий;
- отображение результатов обучения;
- взаимодействие с Backend API.

### Backend

Основная рабочая область:

```text
backend/
database/
```

Backend отвечает за:

- API;
- бизнес-логику;
- пользователей и роли;
- занятия;
- сценарии;
- карточки происшествий;
- результаты обучения;
- взаимодействие с PostgreSQL;
- хранение данных;
- интеграцию Frontend, ML и Telephony.

### Python / ML

Основная рабочая область:

```text
ml/
```

ML отвечает за:

- генерацию учебных сценариев;
- анализ текста;
- оценку действий обучающегося;
- анализ речи;
- рекомендации;
- ML API.

### Telephony / Docker

Основная рабочая область:

```text
telephony/
deploy/
```

Ответственность:

- SIP;
- VoIP;
- входящие и исходящие учебные вызовы;
- аудио;
- телефонные сценарии;
- Docker-инфраструктура;
- запуск и взаимодействие сервисов.

---

# 3. Общий принцип работы

Каждый разработчик в первую очередь работает внутри своей зоны ответственности.

Например:

```text
Frontend Developer
    ↓
frontend/

Backend Developer
    ↓
backend/
database/

ML Developer
    ↓
ml/

Telephony / Docker Developer
    ↓
telephony/
deploy/
```

Не следует без необходимости изменять файлы другого компонента.

Если изменение затрагивает несколько компонентов, сначала необходимо согласовать интерфейс взаимодействия между ними.

Например:

```text
Frontend
    ↓
Backend API
    ↓
ML API
```

В таком случае сначала фиксируется API-контракт, после чего каждый разработчик реализует свою часть.

---

# 4. Общие файлы

К общим файлам относятся:

```text
README.md
CONTRIBUTING.md
.gitignore
.env.example
docker-compose.yml
LICENSE
```

Также общими являются:

```text
docs/
database/
tests/
```

Изменения в этих областях желательно предварительно обсуждать с командой.

Особенно это относится к:

```text
docker-compose.yml
```

и архитектурной документации.

Не следует одновременно переписывать один из этих файлов в нескольких ветках без предварительного согласования.

Локальные параметры конфигурации хранятся в .env. Файл .env.example содержит перечень необходимых переменных без секретных значений и используется как шаблон для локальной конфигурации. Так как файл env с секретными ключами не пушится в репозиторий.

---

# 5. Git workflow

Используется следующая схема:

```text
main
  │
  ├── feature/...
  ├── fix/...
  └── docs/...
       │
       ↓
   Pull Request
       │
       ↓
     main
```

Прямой `push` в `main` запрещён.

Все изменения должны попадать в `main` через Pull Request.

---

# 6. Ветка main

`main` содержит только:

- проверенный код;
- изменения, прошедшие review;
- рабочую версию проекта.

Запрещается использовать `main` как рабочую ветку.

Не следует делать:

```bash
git checkout main
git add .
git commit -m "fix"
git push
```

Вместо этого необходимо создать отдельную ветку.

---

# 7. Именование веток

Название ветки должно содержать:

```text
<тип>/<роль>-<краткое описание>
```

## Типы веток

### feature

Новая функциональность:

```text
feature/frontend-login
feature/backend-rbac
feature/ml-scenario-generator
feature/telephony-incoming-call
```

### fix

Исправление ошибки:

```text
fix/frontend-card-layout
fix/backend-session-error
fix/ml-evaluation-error
fix/telephony-audio-routing
```

### refactor

Изменение внутренней структуры без изменения поведения:

```text
refactor/backend-api
refactor/ml-pipeline
refactor/frontend-components
```

### docs

Изменение документации:

```text
docs/api
docs/architecture
docs/deployment
```

### test

Добавление или изменение тестов:

```text
test/backend-sessions
test/ml-evaluation
test/frontend-cards
```

---

# 8. Названия веток: правила

Используем:

- латиницу;
- lowercase;
- дефисы;
- короткие понятные названия.

Хорошо:

```text
feature/backend-auth
feature/frontend-incident-card
feature/ml-scenario-generation
fix/telephony-sip-connection
```

Плохо:

```text
my-branch
test
new
new2
fix
frontend123
очень-важная-ветка
final-version
final-final
```

Название должно позволять понять назначение ветки без просмотра кода.

---

# 9. Создание новой ветки

Перед началом работы необходимо получить актуальный `main`:

```bash
git checkout main
git pull origin main
```

После этого создать рабочую ветку:

```bash
git checkout -b feature/backend-rbac
```

Или современный вариант:

```bash
git switch main
git pull origin main
git switch -c feature/backend-rbac
```

---

# 10. Синхронизация рабочей ветки

Во время длительной работы `main` может измениться.

Перед созданием Pull Request необходимо синхронизировать свою ветку с актуальным `main`.

Рекомендуемый вариант:

```bash
git fetch origin
git rebase origin/main
```

После rebase, если ветка уже была опубликована:

```bash
git push --force-with-lease
```

Использовать:

```bash
git push --force
```

не следует.

Если команда пока не использует `rebase`, допускается:

```bash
git fetch origin
git merge origin/main
```

Главное правило — не переписывать историю чужих веток.

---

# 11. Коммиты

Один коммит должен представлять одно логическое изменение.

Хорошо:

```text
feat(frontend): add incident card
feat(backend): add user roles
feat(ml): add scenario evaluation
fix(telephony): fix audio routing
docs: update deployment guide
```

Плохо:

```text
fix
changes
update
work
test
asdf
final
```

---

# 12. Формат commit message

Используем формат:

```text
<type>(<scope>): <description>
```

Например:

```text
feat(frontend): add ARM-112 incident card
feat(backend): add session endpoint
feat(ml): implement answer evaluation
feat(telephony): add incoming call scenario
fix(backend): handle missing session
fix(frontend): fix card status rendering
docs: update API documentation
test(ml): add evaluation tests
refactor(backend): simplify session service
```

## Типы

Используем следующие основные типы:

```text
feat      новая функциональность
fix       исправление ошибки
refactor  изменение структуры кода
test      тесты
docs      документация
build     сборка и зависимости
ci        CI/CD
chore     технические изменения
```

Описание пишется кратко и по существу.

---

# 13. Размер коммитов

Не следует делать один огромный коммит:

```text
feat: implement entire backend
```

Если задача большая, историю лучше разделить:

```text
feat(backend): add session model
feat(backend): add session repository
feat(backend): add session service
feat(backend): add session API
test(backend): add session tests
```

Такой подход облегчает code review и поиск ошибок.

---

# 14. Что нельзя коммитить

Не добавлять в Git:

```text
.env
.env.*
node_modules/
__pycache__/
.venv/
logs/
*.log
*.wav
*.mp3
*.onnx
*.pt
*.pth
database/data/
docker-volumes/
```

И другие файлы, перечисленные в корневом `.gitignore`.

Особенно запрещено добавлять:

- пароли;
- API keys;
- токены;
- приватные ключи;
- реальные учетные данные;
- реальные конфиденциальные данные;
- реальные экстренные вызовы.

Для локальной конфигурации используется:

```text
.env.example
```

---

# 15. Pull Request

После завершения задачи создаётся Pull Request:

```text
feature/backend-rbac
        ↓
      main
```

PR должен быть достаточно небольшим, чтобы его можно было нормально проверить.

---

# 16. Название Pull Request

Используем:

```text
[Frontend] Add incident card
[Backend] Add RBAC
[ML] Add scenario evaluation
[Telephony] Add incoming call scenario
```

Для исправлений:

```text
[Backend] Fix session creation
[Frontend] Fix incident status rendering
```

---

# 17. Описание Pull Request

Каждый PR должен содержать:

```markdown
## Что сделано

- Добавлена ...
- Реализована ...
- Изменено ...

## Зачем

Краткое описание задачи и причины изменения.

## Как проверить

1. Запустить ...
2. Открыть ...
3. Выполнить ...
4. Проверить ...

## Тесты

- [ ] Unit tests
- [ ] Integration tests
- [ ] Manual testing

## Зависимости от других изменений

Нет.

или:

Зависит от PR #123.
```

---

# 18. Пример Pull Request

```markdown
# [Backend] Add session API

## Что сделано

- Добавлена модель учебной сессии.
- Добавлен endpoint создания сессии.
- Добавлен endpoint получения состояния сессии.
- Добавлена валидация входных данных.

## Зачем

Frontend должен иметь API для создания и получения текущей учебной сессии.

## Как проверить

1. Запустить Backend.
2. Отправить POST-запрос на `/api/sessions`.
3. Проверить создание записи в БД.
4. Получить сессию через GET `/api/sessions/{id}`.

## Тесты

- [x] Unit tests
- [ ] Integration tests
- [x] Manual testing

## Зависимости

Нет.
```

---

# 19. Code Review

Минимально необходим один reviewer перед merge в `main`.

Разработчик, который написал код, не должен самостоятельно подтверждать свой PR.

Reviewer проверяет:

- соответствует ли изменение задаче;
- нет ли очевидных ошибок;
- соблюдается ли архитектура;
- нет ли случайно добавленных секретов;
- есть ли необходимые тесты;
- не нарушены ли API-контракты;
- не изменяется ли без необходимости код другого компонента.

---

# 20. Review между ролями

Для изменений внутри одной зоны основной reviewer — разработчик соответствующей роли.

Пример:

```text
Frontend PR
    ↓
Backend / другой член команды → review
```

Но если PR меняет границу между компонентами, необходимо участие владельца затронутого компонента.

Например:

```text
Frontend + Backend API
```

должны посмотреть:

```text
Frontend developer
Backend developer
```

А изменение:

```text
Backend + ML API
```

проверяют соответственно Backend и ML.

---

# 21. API-контракты

Изменения интерфейсов между компонентами нельзя делать незаметно для других разработчиков.

Например, если Backend меняет:

```text
POST /api/session
```

и формат ответа:

```json
{
  "id": 123,
  "status": "active"
}
```

на другой формат, это необходимо заранее согласовать с Frontend.

API-документация должна обновляться вместе с изменением API.

Документацию размещать в:

```text
docs/architecture/
docs/api/
```

---

# 22. Изменения БД

Изменения структуры БД должны выполняться через миграции.

Не следует вручную изменять структуру локальной БД и рассчитывать, что остальные разработчики повторят изменения.

Изменение должно включать:

```text
migration
+
изменение Backend
+
тест
```

Например:

```text
database/migrations/
backend/src/...
backend/tests/...
```

---

# 23. Работа с общими файлами

Перед изменением:

```text
docker-compose.yml
database/*
docs/architecture/*
.env.example
README.md
.gitignore
```

желательно сообщить команде.

Если два разработчика одновременно работают с одним общим файлом, необходимо заранее договориться, кто отвечает за итоговую версию.

---

# 24. Merge

PR можно объединять в `main`, когда:

- code review завершён;
- замечания исправлены;
- тесты проходят;
- конфликтов нет;
- изменение не ломает другие компоненты.

После merge рабочую ветку можно удалить.

```bash
git branch -d feature/backend-rbac
git push origin --delete feature/backend-rbac
```

---

# 25. Конфликты

Если возник merge conflict, сначала необходимо определить, почему оба изменения затрагивают один и тот же код.

Не следует просто выбирать:

```text
Accept Current
```

или:

```text
Accept Incoming
```

без проверки.

После разрешения конфликта необходимо:

1. проверить итоговый код;
2. запустить тесты;
3. убедиться, что функциональность обеих сторон сохранена;
4. завершить merge/rebase.

Если конфликт касается архитектуры или API, его необходимо обсудить с владельцами соответствующих компонентов.

---

# 26. Hotfix

Критические исправления могут иметь отдельную ветку:

```text
fix/backend-critical-error
```

Даже критические исправления не следует напрямую коммитить в `main`.

---

# 27. Общие правила команды

1. `main` всегда должен оставаться в рабочем состоянии.
2. Один PR — одна логическая задача.
3. Один коммит — одно логическое изменение.
4. Не коммитить секреты и реальные конфиденциальные данные.
5. Не изменять код другого компонента без необходимости.
6. Изменения API согласовывать между владельцами компонентов.
7. Изменения БД оформлять миграциями.
8. Общие файлы изменять согласованно.
9. Перед PR проверять актуальность `main`.
10. Перед merge запускать необходимые тесты.
11. Не использовать `git push --force` для общих веток.
12. Не делать прямые push в `main`.

---

# 28. Быстрый workflow разработчика

Типичный цикл работы:

```bash
# 1. Получить актуальный main
git switch main
git pull origin main

# 2. Создать ветку
git switch -c feature/backend-rbac

# 3. Разработка
# ... изменения ...

# 4. Проверить изменения
git status
git diff

# 5. Сделать коммит
git add backend/
git commit -m "feat(backend): add RBAC"

# 6. Отправить ветку
git push -u origin feature/backend-rbac

# 7. Создать Pull Request
```

После review:

```bash
# Получить актуальное состояние main
git fetch origin

# Обновить свою ветку
git rebase origin/main

# Отправить обновлённую ветку
git push --force-with-lease
```

После merge:

```bash
git switch main
git pull origin main

git branch -d feature/backend-rbac
```

---

# 29. Правило для команды

Основной принцип проекта:

> **Изолируем разработку по компонентам, согласовываем границы между компонентами и объединяем изменения только через Pull Request.**

Это позволяет четырём разработчикам работать параллельно, минимизируя конфликты, но не создавая четыре независимых проекта внутри одного репозитория.