"""
Общие фикстуры для тестов этапов 1-4.

Все тесты — интеграционные: они подключаются к УЖЕ ЗАПУЩЕННОМУ
docker-compose стенду соответствующего этапа. Если стенд не поднят,
тест не падает с ошибкой (это была бы ложная тревога, не баг в коде),
а аккуратно skip'ается с понятной подсказкой — какую команду запустить.

Пароль AMI берётся из переменной окружения AMI_PASSWORD, если она не
задана — используется тот же дефолт, что и в docker-compose.yml каждого
этапа (changeme_ami_pass), чтобы тесты работали "из коробки" сразу после
`docker compose up` без дополнительной настройки .env.
"""

import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from ami_client import AMIClient, AMIError  # noqa: E402

AMI_HOST = os.environ.get("AMI_HOST", "localhost")
AMI_PASSWORD = os.environ.get("AMI_PASSWORD", "changeme_ami_pass")
AMI_USER = "test-user"  # см. manager.conf в каждом этапе

REPO_ROOT = Path(__file__).parent.parent


def _connect(port: int, stage_dir: str) -> AMIClient:
    client = AMIClient(AMI_HOST, port, timeout=5.0)
    try:
        client.connect()
        client.login(AMI_USER, AMI_PASSWORD)
    except (ConnectionRefusedError, socket.timeout, socket.gaierror, OSError, AMIError) as exc:
        pytest.skip(
            f"Не удалось подключиться к AMI на {AMI_HOST}:{port} ({exc}).\n"
            f"Похоже, стенд не запущен. Запустите:\n"
            f"  docker compose -f telephony/{stage_dir}/docker-compose.yml up --build -d"
        )
    return client


@pytest.fixture
def ami_stage1():
    client = _connect(5038, "stage1_sip_server")
    yield client
    client.logoff()
    client.close()


@pytest.fixture
def ami_stage2():
    client = _connect(5039, "stage2_sip_call")
    yield client
    client.logoff()
    client.close()


@pytest.fixture
def ami_stage3():
    client = _connect(5040, "stage3_virtual_caller")
    yield client
    client.logoff()
    client.close()


@pytest.fixture
def ami_stage4():
    client = _connect(5041, "stage4_audio")
    yield client
    client.logoff()
    client.close()
