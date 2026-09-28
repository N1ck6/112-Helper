from __future__ import annotations

import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DB_USER = "dds112"
DB_PASSWORD = "dds112"
DB_NAME = "dds112"
TEST_DB_NAME = "dds112_test"


# --------------------------------------------------------------------- вывод
def step(text: str) -> None:
    print(f"\n=== {text} ===")


def ok(text: str) -> None:
    print(f"  [+] {text}")


def warn(text: str) -> None:
    print(f"  [!] {text}")


def fail(text: str) -> None:
    print(f"\n[ОШИБКА] {text}")
    sys.exit(1)


# ------------------------------------------------------------------ поиск СУБД
def find_psql() -> Path:
    """Ищет psql в PATH, затем в стандартных каталогах установки."""
    from shutil import which

    found = which("psql")
    if found:
        return Path(found)

    candidates: list[Path] = []
    if sys.platform == "win32":
        for base in (Path("C:/Program Files/PostgreSQL"), Path("C:/Program Files (x86)/PostgreSQL")):
            if base.exists():
                candidates += sorted(base.glob("*/bin/psql.exe"), reverse=True)
    else:
        candidates += [Path("/usr/bin/psql"), Path("/usr/local/bin/psql")]
        candidates += sorted(Path("/usr/lib/postgresql").glob("*/bin/psql"), reverse=True)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    fail(
        "PostgreSQL не найден.\n"
        "  Установите его: winget install -e --id PostgreSQL.PostgreSQL.16\n"
        "  либо скачайте с https://www.enterprisedb.com/downloads/postgres-postgresql-downloads"
    )
    raise SystemExit  # недостижимо, нужно для анализатора


def decode_output(raw: bytes) -> str:
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def run_sql(psql: Path, superuser: str, password: str, database: str, sql: str) -> tuple[int, str]:
    """Выполняет SQL от имени суперпользователя. Пароль передаётся через окружение."""
    env = {**os.environ, "PGPASSWORD": password, "PGCLIENTENCODING": "UTF8"}
    process = subprocess.run(
        [str(psql), "-U", superuser, "-h", "localhost", "-d", database, "-tAc", sql],
        capture_output=True,
        env=env,
    )
    return process.returncode, decode_output((process.stdout or b"") + (process.stderr or b""))


def connection_hint(output: str, superuser: str) -> str:
    """Подсказка по тексту ошибки psql — сообщения бывают и русские, и английские."""
    lowered = output.lower()
    if "authentication failed" in lowered or "проверку подлинности" in lowered:
        return (
            f"\n  PostgreSQL не принял пару «{superuser} + пароль». Возможны две причины:\n"
            f"    1) такого пользователя в PostgreSQL нет. Суперпользователь по умолчанию —\n"
            "       postgres; учётная запись Windows здесь ни при чём. Нажмите Enter на вопросе\n"
            "       об имени, чтобы взять postgres;\n"
            "    2) пароль не тот. Нужен пароль, заданный в мастере установки PostgreSQL\n"
            "       (на шаге «Password»), а не пароль от Windows."
        )
    if "does not exist" in lowered or "не существует" in lowered:
        return f"\n  Пользователя {superuser} в PostgreSQL нет. Попробуйте postgres."
    if "could not connect" in lowered or "connection refused" in lowered or "не удалось" in lowered:
        return (
            "\n  Похоже, служба PostgreSQL не запущена. Win+R → services.msc →\n"
            "  postgresql-x64-16 → «Запустить»."
        )
    return ""


# ------------------------------------------------------------------ шаги
def setup_database(psql: Path) -> None:
    superuser = os.environ.get("PGUSER") or ""
    password = os.environ.get("PGPASSWORD") or ""

    if not superuser:
        print("  Нужен суперпользователь PostgreSQL. Обычно это postgres —")
        print("  учётная запись Windows тут не подходит. Просто нажмите Enter.")

    for attempt in range(1, 4):
        try:
            if not superuser:
                superuser = input("  Имя суперпользователя PostgreSQL [postgres]: ").strip() or "postgres"
            if not password:
                password = getpass.getpass(f"  Пароль пользователя {superuser} (ввод скрыт): ")
        except EOFError:
            fail(
                "Скрипт запущен без интерактивного ввода.\n"
                "  Запустите его в терминале либо передайте данные через окружение:\n"
                "    $env:PGUSER='postgres'; $env:PGPASSWORD='<пароль>'; python scripts/setup_local.py"
            )
        if not password:
            fail("Пароль не введён.")

        code, output = run_sql(psql, superuser, password, "postgres", "SELECT version();")
        if code == 0:
            break

        print(f"\n  [!] Подключиться не удалось:\n      {output.strip()}")
        print(connection_hint(output, superuser).rstrip())
        if attempt == 3:
            fail("Три неудачные попытки подключения к PostgreSQL.")
        print(f"\n  Попытка {attempt + 1} из 3.")
        superuser = ""
        password = ""

    ok(f"PostgreSQL доступен: {output.strip().splitlines()[0][:60]}…")

    code, output = run_sql(
        psql, superuser, password, "postgres",
        f"SELECT 1 FROM pg_roles WHERE rolname='{DB_USER}';",
    )
    if output.strip() == "1":
        ok(f"Роль {DB_USER} уже существует")
    else:
        code, output = run_sql(
            psql, superuser, password, "postgres",
            f"CREATE ROLE {DB_USER} WITH LOGIN CREATEDB PASSWORD '{DB_PASSWORD}';",
        )
        if code != 0:
            fail(f"Не удалось создать роль {DB_USER}:\n{output.strip()}")
        ok(f"Создана роль {DB_USER}")

    for name in (DB_NAME, TEST_DB_NAME):
        code, output = run_sql(
            psql, superuser, password, "postgres",
            f"SELECT 1 FROM pg_database WHERE datname='{name}';",
        )
        if output.strip() == "1":
            ok(f"База {name} уже существует")
            continue
        code, output = run_sql(
            psql, superuser, password, "postgres",
            f'CREATE DATABASE "{name}" OWNER {DB_USER};',
        )
        if code != 0:
            fail(f"Не удалось создать базу {name}:\n{output.strip()}")
        ok(f"Создана база {name}")


def write_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        ok(".env уже есть — оставляю как есть (удалите файл, чтобы пересоздать)")
        return

    content = f"""# Сгенерировано scripts/setup_local.py
APP_ENV=local
DEBUG=true
ENABLE_DOCS=true

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER={DB_USER}
POSTGRES_PASSWORD={DB_PASSWORD}
POSTGRES_DB={DB_NAME}
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_ECHO=false

TEST_DATABASE_URL=postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@localhost:5432/{TEST_DB_NAME}

# Ключ подписи JWT сгенерирован случайно при установке
SECRET_KEY={secrets.token_hex(32)}
ACCESS_TOKEN_TTL_MINUTES=30
REFRESH_TOKEN_TTL_DAYS=7
MFA_REQUIRED_ROLES=[]
MAX_FAILED_LOGINS=5
LOCKOUT_MINUTES=15
SECURITY_LOG_RETENTION_DAYS=200

DEFAULT_CARD_TIME_LIMIT_SECONDS=30
SESSION_RECOVERY_GRACE_SECONDS=30
MAX_CONCURRENT_SESSIONS=20

ML_SERVICE_URL=http://localhost:8100
ML_USE_STUB=true
ML_TIMEOUT_SECONDS=20
TELEPHONY_SERVICE_URL=http://localhost:8200
TELEPHONY_USE_STUB=true
TELEPHONY_WEBHOOK_TOKEN=dev-telephony-token
MONITORING_ENABLED=true

STORAGE_DIR=var
MAX_UPLOAD_MB=50

CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]
"""
    env_path.write_text(content, encoding="utf-8")
    ok(".env создан, SECRET_KEY сгенерирован случайно")


def run_command(title: str, args: list[str], required: bool = True) -> bool:
    print(f"  → {title}")
    process = subprocess.run(args, cwd=ROOT)
    if process.returncode != 0:
        if required:
            fail(f"Шаг «{title}» завершился с ошибкой. Вывод выше.")
        warn(f"Шаг «{title}» завершился с ошибкой — можно разобраться позже")
        return False
    return True


def main() -> None:
    print("Настройка локального окружения тренажёра ДДС-112")
    print(f"Проект: {ROOT}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")

    if sys.version_info < (3, 11):  # noqa: UP036 — скрипт могут запустить старым интерпретатором
        fail(f"Нужен Python 3.11 или новее, запущен {sys.version.split()[0]}")

    try:
        import fastapi  # noqa: F401
        import sqlalchemy  # noqa: F401
    except ImportError:
        fail("Не установлены зависимости. Выполните: pip install -r requirements-dev.txt")

    step("1/5 Поиск PostgreSQL")
    psql = find_psql()
    ok(f"psql: {psql}")

    step("2/5 Роль и базы данных")
    setup_database(psql)

    step("3/5 Файл настроек .env")
    write_env()

    step("4/5 Схема БД и стартовые данные")
    run_command("миграции (alembic upgrade head)", [sys.executable, "-m", "alembic", "upgrade", "head"])
    run_command("стартовые данные (scripts.seed)", [sys.executable, "-m", "scripts.seed"])

    step("5/5 Тесты")
    tests_ok = run_command("pytest", [sys.executable, "-m", "pytest", "-q"], required=False)

    print("\n" + "=" * 70)
    if tests_ok:
        print("Готово. Все проверки пройдены.")
    else:
        print("Настройка завершена, но тесты не прошли — посмотрите вывод выше.")
    print("\nЗапуск сервера:")
    print("    uvicorn app.main:app --reload")
    print("\nДокументация API:  http://localhost:8000/docs")
    print("\nУчётные записи (только для локального контура):")
    print("    admin    / Admin#2026     — администратор")
    print("    teacher  / Teacher#2026   — преподаватель")
    print("    student  / Student#2026   — обучающийся")
    print("=" * 70)


if __name__ == "__main__":
    main()
