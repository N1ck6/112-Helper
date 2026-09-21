"""
Тест этапа 1 — SIP-сервер жив и отвечает на мониторинг (AMI).

Запуск:
    docker compose -f telephony/docker-compose.yml up --build -d
    pytest tests/test_stage1_sip_server.py -v
"""


def test_ami_ping(ami_stage1):
    """AMI Ping — простейшая проверка "сервер жив и понимает протокол".

    Это дополняет healthcheck.sh (который проверяет только процесс
    изнутри контейнера) — здесь мы стучимся СНАРУЖИ, как это будет
    делать реальный компонент мониторинга.
    """
    resp = ami_stage1.ping()
    assert resp.get("Response") == "Pong", f"Ожидали Pong от AMI, получили: {resp}"


def test_ami_reports_core_version(ami_stage1):
    """Дополнительная проверка через CoreSettings — что Asterisk
    действительно инициализировался (а не просто открыл TCP-порт)."""
    resp = ami_stage1.send_action("CoreSettings")
    assert resp.get("Response") == "Success", f"CoreSettings не ответил успехом: {resp}"
