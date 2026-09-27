"""
Общие фикстуры тестов telephony.

Все этапы работают в одном стенде telephony/ (один docker-compose.yml),
поэтому интеграционные тесты этапов 1-6 ходят в один AMI (порт 5041).
Если стенд не поднят, тест не падает (это не баг кода), а SKIP с
подсказкой, какую команду запустить.

Пароль AMI — из переменной AMI_PASSWORD, по умолчанию тот же дефолт,
что в docker-compose.yml (changeme_ami_pass). Если в telephony/.env
задан свой пароль: AMI_PASSWORD=<пароль> pytest tests/ -v
"""

import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from ami_client import AMIClient, AMIError  # noqa: E402

AMI_HOST = os.environ.get("AMI_HOST", "localhost")
AMI_PORT = int(os.environ.get("AMI_PORT", "5041"))
AMI_PASSWORD = os.environ.get("AMI_PASSWORD", "changeme_ami_pass")
AMI_USER = "test-user"  # см. telephony/asterisk/conf/manager.conf

REPO_ROOT = Path(__file__).parent.parent
RECORDINGS_DIR = REPO_ROOT / "data" / "recordings"
SESSIONS_LOG = REPO_ROOT / "data" / "sessions" / "sessions.log"
START_HINT = "cd telephony && docker compose up --build -d"


@pytest.fixture
def ami():
    client = AMIClient(AMI_HOST, AMI_PORT, timeout=5.0)
    try:
        client.connect()
        client.login(AMI_USER, AMI_PASSWORD)
    except (ConnectionRefusedError, socket.timeout, socket.gaierror, OSError, AMIError) as exc:
        pytest.skip(f"AMI {AMI_HOST}:{AMI_PORT} недоступен ({exc}). Стенд не запущен? {START_HINT}")
    yield client
    client.logoff()
    client.close()
