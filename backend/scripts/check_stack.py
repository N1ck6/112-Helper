from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_API = "http://localhost:8000"
TIMEOUT = 10.0

OK = "  [ OK ]"
FAIL = "  [ НЕТ ]"
WARN = "  [  ?  ]"


def check_backend(api: str) -> bool:
    """Живость процесса и готовность к работе вместе с компонентами комплекса."""
    try:
        live = httpx.get(f"{api}/health/live", timeout=TIMEOUT)
        live.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"{FAIL} backend {api} не отвечает: {exc}")
        print("         запустите: uvicorn app.main:app --reload")
        return False
    print(f"{OK} backend {api}")

    try:
        ready = httpx.get(f"{api}/health/ready", timeout=TIMEOUT).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"{FAIL} /health/ready не отвечает: {exc}")
        return False

    database = ready.get("database")
    print(f"{OK if database == 'ok' else FAIL} PostgreSQL: {database}")

    healthy = database == "ok"
    for name, state in (ready.get("components") or {}).items():
        status = state.get("status") if isinstance(state, dict) else state
        mode = state.get("mode") if isinstance(state, dict) else None
        note = f" (режим: {mode})" if mode else ""
        if status == "ok" and mode == "stub":
            print(f"{WARN} {name}: заглушка{note} — реальный сервис не подключён")
        elif status == "ok":
            print(f"{OK} {name}: подключён{note}")
        else:
            print(f"{FAIL} {name}: {state}")
            healthy = False
    return healthy


def check_service(title: str, url: str, required: bool) -> bool:
    """Компонент соседней части команды: ML, телефония, frontend."""
    try:
        response = httpx.get(url, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        marker = FAIL if required else WARN
        print(f"{marker} {title} {url}: {exc.__class__.__name__}")
        return not required
    print(f"{OK} {title} {url}")
    return True


def check_training_flow(api: str, username: str, password: str) -> bool:
    """Сквозная проверка: вход, назначенные занятия, состав карточки АРМ-112."""
    try:
        login = httpx.post(
            f"{api}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        print(f"{FAIL} вход в систему: {exc}")
        return False

    if login.status_code != 200:
        print(f"{FAIL} вход под «{username}» отклонён: {login.text[:200]}")
        print("         загрузите стартовые данные: python -m scripts.seed")
        return False

    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    print(f"{OK} вход под «{username}»")

    try:
        groups = httpx.get(
            f"{api}/api/v1/card-templates/field-groups", headers=headers, timeout=TIMEOUT
        ).json()
        templates = httpx.get(
            f"{api}/api/v1/card-templates", headers=headers, timeout=TIMEOUT
        ).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"{FAIL} шаблон карточки недоступен: {exc}")
        return False

    fields = sum(len(item.get("fields_schema") or []) for item in templates)
    if not groups or not fields:
        print(f"{FAIL} шаблон карточки пуст: разделов {len(groups)}, полей {fields}")
        return False
    print(f"{OK} карточка АРМ-112: {len(groups)} разделов, {fields} полей")

    try:
        types = httpx.get(
            f"{api}/api/v1/incidents/types", headers=headers, params={"size": 1}, timeout=TIMEOUT
        ).json()
        total = types.get("total", 0)
    except (httpx.HTTPError, ValueError):
        total = 0
    if total:
        print(f"{OK} классификатор происшествий: {total} типов")
    else:
        print(f"{WARN} классификатор происшествий пуст — загрузите таблицу заказчика")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка готовности учебного комплекса")
    parser.add_argument("--api", default=DEFAULT_API, help="Адрес backend")
    parser.add_argument("--ml", default="http://localhost:8100/health", help="Проверка ML-сервиса")
    parser.add_argument("--sip", default="http://localhost:8200/health", help="Проверка телефонии")
    parser.add_argument("--frontend", default="http://localhost:5173", help="Проверка веб-интерфейса")
    parser.add_argument("--full", action="store_true", help="Требовать все компоненты комплекса")
    parser.add_argument("--user", default="teacher", help="Учётная запись для сквозной проверки")
    parser.add_argument("--password", default="Teacher#2026")
    args = parser.parse_args()

    print("Проверка учебного комплекса ДДС-112\n")

    print("Backend и данные:")
    results = [check_backend(args.api)]

    print("\nКомпоненты команды:")
    results.append(check_service("ML-сервис", args.ml, required=args.full))
    results.append(check_service("Телефония", args.sip, required=args.full))
    results.append(check_service("Веб-интерфейс", args.frontend, required=args.full))

    print("\nСквозная проверка:")
    results.append(check_training_flow(args.api, args.user, args.password))

    print("\n" + "=" * 62)
    if all(results):
        print("Комплекс готов к работе.")
    else:
        print("Комплекс собран не полностью — см. отметки выше.")
        sys.exit(1)


if __name__ == "__main__":
    main()
