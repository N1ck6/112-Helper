"""Создать или дополнить .env стенда из .env.example (запускают start.bat / start.sh).

- .env нет — копия шаблона, все пустые пароли и ключи заполняются случайными значениями;
- .env есть — значения пользователя не трогаются, дописываются только новые переменные шаблона
  (и генерируются пароли, если они пустые);
- --media-ip — IP этого ПК в локальной сети для EXTERNAL_MEDIA_ADDRESS (только для нового .env).

Только стандартная библиотека: скрипт работает и в контейнере python:alpine, и на хосте.
"""

from __future__ import annotations

import argparse
import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"

# без похожих символов (0/O, 1/l/I): пароль читают с экрана и набирают руками
HUMAN_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TOKEN_ALPHABET = string.ascii_letters + string.digits


def human_password() -> str:
    """Kt7m-Qp4x-Wz9a: 12 знаков, есть и буквы, и цифры (правило backend)."""
    while True:
        raw = "".join(secrets.choice(HUMAN_ALPHABET) for _ in range(12))
        if any(c.isdigit() for c in raw) and any(c.isalpha() for c in raw):
            return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def token(length: int) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


GENERATORS = {
    "ADMIN_PASSWORD": human_password,
    "TEACHER_PASSWORD": human_password,
    "STUDENT_PASSWORD": human_password,
    "TRAINEE_PASSWORD": human_password,
    "SECRET_KEY": lambda: secrets.token_hex(32),
    "POSTGRES_PASSWORD": lambda: token(24),
    "TELEPHONY_WEBHOOK_TOKEN": lambda: secrets.token_hex(24),
    "AMI_PASSWORD": lambda: token(24),
    "SIP_ALICE_PASSWORD": lambda: token(16),
    "SIP_BOB_PASSWORD": lambda: token(16),
}


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media-ip", default="", help="IP этого ПК в локальной сети")
    args = parser.parse_args()

    existed = TARGET.exists()
    current = parse(TARGET)
    lines, generated, added = [], [], []
    seen = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            lines.append(line)
            continue
        key, default = (part.strip() for part in stripped.split("=", 1))
        seen.add(key)
        value = current.get(key, default)
        if key not in current:
            added.append(key)
            if key == "EXTERNAL_MEDIA_ADDRESS" and args.media_ip and not existed:
                value = args.media_ip
        if not value and key in GENERATORS:
            value = GENERATORS[key]()
            generated.append(key)
        lines.append(f"{key}={value}")

    # свои переменные пользователя, которых нет в шаблоне, сохраняются
    extra = [f"{k}={v}" for k, v in current.items() if k not in seen]
    if extra:
        lines += ["", "# -------- Прочие настройки (нет в .env.example) --------", *extra]

    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    if not existed:
        print(f".env создан, сгенерированы пароли и ключи: {len(generated)}")
    elif added or generated:
        print(f".env дополнен: новых настроек {len(added)}, сгенерировано паролей {len(generated)}")
    else:
        print(".env уже есть и полный — оставлен как есть")


if __name__ == "__main__":
    main()
